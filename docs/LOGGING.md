# What ledgerlens logs, and why

Every question produces two records: a **trace** (OpenTelemetry spans in
[OpenInference](https://github.com/Arize-ai/openinference) conventions, viewed in a local
Arize Phoenix) and a **run record** (`runs/<run_id>/run.json`). The trace is for finding out
*where* a run went wrong; the run record is the answer the user saw, kept so any run can be
reopened, re-scored or shared (`http://localhost:8501/?run=<run_id>`) without a tracing
backend.

The goal behind every choice below: a developer who opens one trace should be able to say
why the answer was wrong without re-running anything.

## The shape of a trace

One trace per question. Turns of a conversation share a `session.id`; an eval run is one
session, and every trace in it carries its `eval_case_id`.

```
ask                     AGENT      question in, answer out, session, run metadata
├─ retrieve_context     RETRIEVER  metrics + tables found, with similarity scores
├─ route_question       CHAIN      the route and the model's reason
│  └─ llm RouteDecision LLM        exact prompt, raw response, token counts
├─ resolve_dates        CHAIN      the anchor date, where it came from, resolved ranges
├─ plan_sql             CHAIN      plan + SQL (on a retry: the previous SQL and its errors)
│  └─ llm SqlDraft      LLM
├─ validate_sql         GUARDRAIL  errors; the span is marked ERROR when SQL is rejected
├─ execute_sql          TOOL       row count + a 5-row sample, never the full result
├─ check_result         GUARDRAIL  warning codes (fanout, null_values, empty_result, ...)
├─ render_chart         CHAIN      chosen output type (stat / line / bar / table)
└─ write_answer         CHAIN      the answer object
   └─ llm AnswerText    LLM
```

Span kinds are chosen for what a reader needs: validation and sanity checks are
`GUARDRAIL`s (they pass or trip), running SQL is a `TOOL` call, retrieval is a `RETRIEVER` so
Phoenix renders the documents and scores.

## What each span records

Each node span's **input** is only the state keys that node reads, and its **output** is
exactly the keys it sets (the node registry is in `ledgerlens/agent/tracing.py`, and a test
keeps it in sync with the graph). That makes a node span a small, readable diff of the run's
state instead of a copy of everything.

| Span | Input | Output and extra attributes |
|---|---|---|
| `ask` | the question | answer headline + interpretation; `session.id`; `metadata`; `tag.tags` |
| `retrieve_context` | question | retrieved metrics, tables, join-path tables; `retrieval.documents.*` (id, score) |
| `route_question` | question | `route`, `reason`, `metric`, `clarifying_question` |
| `resolve_dates` | question, route | `anchor`, `anchor_source`, date coverage, resolved `ranges` |
| `plan_sql` | question, previous SQL + errors | `plan`, `sql`, attempt number |
| `validate_sql` | SQL | `sql_errors`; status ERROR with the first error when rejected |
| `execute_sql` | SQL | columns, `row_count`, `truncated`, 5 sample rows; `tool.name` |
| `check_result` | SQL, result summary | warnings; `ledgerlens.warnings` (codes) |
| `render_chart` | result summary | `output_type`, chart path |
| `write_answer` | question, route, warnings | the answer: headline, interpretation, definition, timeframe |
| `llm <Schema>` | the exact prompt | raw model output; `llm.model_name`, `llm.provider`, `llm.token_count.*` |

**Trace metadata** on the root span, set at the start: `run_id`, `agent_version`, `model`,
`failure_mode`, `user_role`, `eval_case_id`. At the end the outcome is added, so traces can
be filtered by it: `status`, `route`, `output_type`, `sql_attempts`, `warnings`, `llm_calls`,
`latency_ms`. Tags repeat the three labels people filter by most: `agent_version:v2`,
`failure_mode:none`, `user_role:am`.

**Failures are visible, not smoothed over.** A rejected SQL attempt turns its span red and
the next `plan_sql` span shows the error it was given. A crash records the exception on the
failing node. A provider error (Gemini's 503 "high demand") retried by the graph shows up as
one span per attempt, so a slow run explains itself.

## User feedback

A 👍/👎 in the chat UI (or `POST /v1/runs/{run_id}/feedback`) becomes a `user_feedback`
annotation on the run's root span: `annotator_kind: HUMAN`, label `thumbs_up`/`thumbs_down`,
score 1/0, the comment as the explanation, and the run id, user role and session in its
metadata. It is also saved as `runs/<run_id>/feedback.json`, so it survives even if the
tracing backend is down.

## What is not logged, and why

| Not logged | Why |
|---|---|
| Full query results | Privacy and cost. Results can hold customer data, and a trace is shipped to a third party and kept for a long time. Row count + 5 rows is enough to see if the shape was right. |
| Embedding vectors | Large and unreadable; the retrieved names and scores carry the signal. |
| Secrets | API keys never enter spans; settings hold them as `SecretStr`. |
| Staff password hashes | Not even readable: the agent's database role has no privilege on those columns. |

**One deliberate exception:** LLM spans record the exact prompt, and the answer prompt
contains up to 20 result rows. You cannot debug a model call without seeing what the model
saw. If that became a concern, the place to redact is `llm_span` in `agent/tracing.py`.

The run record (`run.json`) keeps up to 200 result rows, because it is the answer shown to
the user and it stays on the machine that produced it.

## Why hand-written spans instead of auto-instrumentation

Auto-instrumenting LangChain/LangGraph traces every node, but it records each node's input as
the whole graph state, including every result row, and nests extra chain spans around each
structured-output call. Writing the spans explicitly (about 150 lines in
`ledgerlens/agent/tracing.py`) gives a deliberate schema: every attribute is there because
someone debugging needs it. The cost is keeping the node registry up to date, which a test
enforces.

## Where it lives

| File | Role |
|---|---|
| `ledgerlens/core/tracing.py` | OpenTelemetry setup: Phoenix over OTLP/HTTP, optional Neatlogs over OTLP/gRPC. No backend configured means no provider, so every span is a no-op. |
| `ledgerlens/agent/tracing.py` | What gets recorded: root span, node spans, LLM spans, and the result-set trimming. |
| `ledgerlens/services/agent_service.py` | Opens the root span per question, writes the run record. |
| `ledgerlens/services/feedback_service.py` | Attaches feedback to the root span. |
| `ledgerlens/core/logging.py` | Plain logs, with the run id on every line. |
