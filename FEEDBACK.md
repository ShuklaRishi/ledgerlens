# Feedback on Neatlogs, from building ledgerlens

Context: I couldn't create a Neatlogs account (see below), so ledgerlens is traced with
OpenTelemetry spans in OpenInference conventions and viewed in a local Arize Phoenix. Before
that decision I evaluated the Python SDK offline: `neatlogs` **1.4.23** (latest on PyPI on
28 Sep 2026), its docs, and the `neatlogs/skills` repo. Every item under "Where I got stuck"
was reproduced locally with no API key.

## What worked immediately

<!-- TODO(me): fill in after using the dashboard with a real account. -->

## Where I got stuck

1. **Signup needs a work email.** As an individual developer I couldn't create an account,
   so I couldn't send a single trace. ledgerlens includes an OTLP/gRPC exporter configured the
   way the docs describe (`ingest.neatlogs.com:443`, `x-api-key` header), but it is untested.

2. **`instrumentations=["langgraph"]` silently does nothing.** There is a `neatlogs[langgraph]`
   extra, but the key is skipped at init. The only signal is a debug-level log line,
   `langgraph: no instrumentor available (skipped)`. The LangChain skill says to use
   `neatlogs.langchain_handler()` at the graph invocation instead; the SDK could say so at
   init, or reject the key.

3. **The sessions docs are ahead of the SDK.** The LangChain skill's sessions reference
   shows `neatlogs.identify(..., parent_session_id=..., session_custom_fields=...)` and says it
   needs `neatlogs>=1.4.2`. On 1.4.23 both arguments raise
   `TypeError: identify() got an unexpected keyword argument`.

4. **No way to attach end-user feedback to a trace from code.** The public API has nothing
   for feedback or scores, and the skills repo's contract lists "feedback/scoring" as excluded
   from the SDK launch. The loop I most wanted to show (a business user flags an answer, a
   developer opens that exact trace) has to go through the dashboard. In ledgerlens it goes
   through Phoenix's `POST /v1/span_annotations`.

5. **Span kinds are a closed list you discover by trying.** `@neatlogs.span(kind="LLM")` and
   `kind="RERANKER"` raise `ValueError`; the accepted kinds are `WORKFLOW, AGENT, CHAIN, TOOL,
   RETRIEVER, EMBEDDING, GUARDRAIL, EVALUATOR, MEMORY, MCP_TOOL`.

6. **An unexplained dependency.** The package declares a dependency on `agnost` (a
   third-party analytics SDK), but nothing in the package imports it. Worth removing or
   explaining, since people installing an observability SDK tend to check what else it pulls
   in.

## What a business user would struggle with

<!-- TODO(me) -->

## Features I wished for

<!-- TODO(me): for each, name the specific run that made you want it. -->
