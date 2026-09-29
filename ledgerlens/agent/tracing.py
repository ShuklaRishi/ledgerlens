"""What the agent records in each trace (OpenInference conventions). See docs/LOGGING.md.

One trace per question:
  ask (AGENT)                  question, answer, session, run metadata (version, model, ...)
    <one span per node>        the state keys the node read, and the keys it set
      llm <Schema> (LLM)       exact prompt, raw response, token counts
Query results are never recorded in full: only columns, row count and a 5-row sample.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from langchain_core.messages import AIMessage
from openinference.semconv.trace import DocumentAttributes, MessageAttributes
from openinference.semconv.trace import OpenInferenceSpanKindValues as Kind
from openinference.semconv.trace import SpanAttributes as A
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, format_span_id, format_trace_id
from pydantic import BaseModel

from ledgerlens.agent.state import AgentState
from ledgerlens.sql.executor import QueryResult

tracer = trace.get_tracer("ledgerlens.agent")

SAMPLE_ROWS = 5
JSON = "application/json"

# Each node's span kind, and the state keys it reads (recorded as the span's input).
NODES: dict[str, tuple[Kind, tuple[str, ...]]] = {
    "retrieve_context": (Kind.RETRIEVER, ("question",)),
    "route_question": (Kind.CHAIN, ("question",)),
    "resolve_dates": (Kind.CHAIN, ("question", "route")),
    "plan_sql": (Kind.CHAIN, ("question", "sql", "sql_errors")),
    "validate_sql": (Kind.GUARDRAIL, ("sql",)),
    "execute_sql": (Kind.TOOL, ("sql",)),
    "check_result": (Kind.GUARDRAIL, ("sql", "result")),
    "render_chart": (Kind.CHAIN, ("result", "chart_requested")),
    "write_answer": (Kind.CHAIN, ("question", "route", "warnings")),
}

NodeFn = Callable[[AgentState], dict[str, Any]]


@contextmanager
def run_span(
    question: str, session_id: str | None, metadata: dict[str, Any], tags: list[str]
) -> Iterator[Span]:
    """The root span of one question. Everything the graph does nests under it."""
    attributes: dict[str, Any] = {
        A.OPENINFERENCE_SPAN_KIND: Kind.AGENT.value,
        A.INPUT_VALUE: question,
        A.METADATA: _json(metadata),
        A.TAG_TAGS: tags,
    }
    if session_id:
        attributes[A.SESSION_ID] = session_id
    # Failures are recorded explicitly by finish_run_span, so the service can still save the run.
    with tracer.start_as_current_span(
        "ask", attributes=attributes, record_exception=False, set_status_on_exception=False
    ) as span:
        yield span


def finish_run_span(
    span: Span, output: str | None, metadata: dict[str, Any], error: Exception | None
) -> None:
    if output:
        span.set_attribute(A.OUTPUT_VALUE, output)
    span.set_attribute(A.METADATA, _json(metadata))  # now including the outcome, for filtering
    if error is not None:
        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, f"{type(error).__name__}: {error}"))


def trace_ids(span: Span) -> tuple[str | None, str | None]:
    """(trace_id, span_id) as hex, or (None, None) when tracing is off."""
    context = span.get_span_context()
    if not context.is_valid:
        return None, None
    return format_trace_id(context.trace_id), format_span_id(context.span_id)


def traced_node(name: str, node: NodeFn) -> NodeFn:
    """Wrap a graph node in a span. A retried node gets one span per attempt."""
    kind, reads = NODES[name]

    def run(state: AgentState) -> dict[str, Any]:
        with tracer.start_as_current_span(
            name, attributes={A.OPENINFERENCE_SPAN_KIND: kind.value}
        ) as span:
            _set_io(
                span, A.INPUT_VALUE, A.INPUT_MIME_TYPE, {k: state[k] for k in reads if k in state}
            )
            update = node(state)
            _set_io(span, A.OUTPUT_VALUE, A.OUTPUT_MIME_TYPE, update)
            _describe(span, name, update)
            return update

    return run


@contextmanager
def llm_span(model: str, schema: str, prompt: str) -> Iterator[Span]:
    message = f"{A.LLM_INPUT_MESSAGES}.0."
    attributes = {
        A.OPENINFERENCE_SPAN_KIND: Kind.LLM.value,
        A.LLM_PROVIDER: "google",
        A.LLM_MODEL_NAME: model,
        A.LLM_INVOCATION_PARAMETERS: _json({"response_schema": schema}),
        A.INPUT_VALUE: prompt,
        message + MessageAttributes.MESSAGE_ROLE: "user",
        message + MessageAttributes.MESSAGE_CONTENT: prompt,
    }
    with tracer.start_as_current_span(f"llm {schema}", attributes=attributes) as span:
        yield span


def record_llm_response(span: Span, response: AIMessage) -> None:
    content = response.content if isinstance(response.content, str) else _json(response.content)
    message = f"{A.LLM_OUTPUT_MESSAGES}.0."
    span.set_attribute(message + MessageAttributes.MESSAGE_ROLE, "assistant")
    span.set_attribute(message + MessageAttributes.MESSAGE_CONTENT, content)
    span.set_attribute(A.OUTPUT_VALUE, content)
    usage = response.usage_metadata or {}
    span.set_attribute(A.LLM_TOKEN_COUNT_PROMPT, usage.get("input_tokens", 0))
    span.set_attribute(A.LLM_TOKEN_COUNT_COMPLETION, usage.get("output_tokens", 0))
    span.set_attribute(A.LLM_TOKEN_COUNT_TOTAL, usage.get("total_tokens", 0))


def _describe(span: Span, name: str, update: dict[str, Any]) -> None:
    """Node-specific attributes that make a trace readable at a glance."""
    if context := update.get("context"):  # retrieved docs with their similarity scores
        hits = [("metric", h) for h in context.metrics] + [("table", h) for h in context.tables]
        for i, (kind, hit) in enumerate(hits):
            prefix = f"{A.RETRIEVAL_DOCUMENTS}.{i}."
            span.set_attribute(prefix + DocumentAttributes.DOCUMENT_ID, f"{kind}:{hit.name}")
            span.set_attribute(prefix + DocumentAttributes.DOCUMENT_CONTENT, f"{kind} {hit.name}")
            span.set_attribute(prefix + DocumentAttributes.DOCUMENT_SCORE, hit.score)
    if name == "execute_sql":
        span.set_attribute(A.TOOL_NAME, "postgres (read-only role agent_ro)")
    if errors := update.get("sql_errors"):  # a rejected or failed SQL attempt shows up red
        span.set_status(Status(StatusCode.ERROR, errors[0]))
    if warnings := update.get("warnings"):
        span.set_attribute("ledgerlens.warnings", [w.code for w in warnings])


def _set_io(span: Span, value_key: str, mime_key: str, value: Any) -> None:
    span.set_attribute(value_key, _json(value))
    span.set_attribute(mime_key, JSON)


def _json(value: Any) -> str:
    return json.dumps(_loggable(value), default=str)


def _loggable(value: Any) -> Any:
    """Plain data for a span, with query results cut down to a sample."""
    if isinstance(value, QueryResult):
        return {
            "columns": value.columns,
            "row_count": value.row_count,
            "truncated": value.truncated,
            "sample": value.rows[:SAMPLE_ROWS],
        }
    if isinstance(value, BaseModel):
        return _loggable(dict(value))
    if isinstance(value, dict):
        return {key: _loggable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_loggable(item) for item in value]
    return value
