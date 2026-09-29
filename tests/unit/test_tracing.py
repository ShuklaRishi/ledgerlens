"""One trace per question, curated span content, and never a full result set."""

import json

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from ledgerlens.agent import graph as agent_graph
from ledgerlens.agent import tracing
from ledgerlens.agent.state import AgentState
from ledgerlens.core.config import Settings
from ledgerlens.core.tracing import setup_tracing, trace_url
from ledgerlens.sql.executor import QueryResult

EXPORTER = InMemorySpanExporter()


@pytest.fixture
def spans() -> InMemorySpanExporter:
    # The global provider can only be set once per process; only these tests set it.
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
        trace.set_tracer_provider(provider)
    EXPORTER.clear()
    return EXPORTER


def test_no_backend_means_no_provider_and_no_op_spans() -> None:
    assert setup_tracing(Settings(phoenix_url=None, neatlogs_api_key=None)) is None


def test_every_graph_node_has_a_span_kind() -> None:
    assert set(tracing.NODES) == set(agent_graph.NODES)


def test_one_trace_per_question_with_a_child_span_per_node(spans: InMemorySpanExporter) -> None:
    result = QueryResult(
        columns=["store_id", "revenue"], rows=[[i, 1.0] for i in range(50)], truncated=False
    )
    graph = StateGraph(AgentState)
    graph.add_node(
        "validate_sql", tracing.traced_node("validate_sql", lambda s: {"sql_errors": []})
    )
    graph.add_node("execute_sql", tracing.traced_node("execute_sql", lambda s: {"result": result}))
    graph.add_edge(START, "validate_sql")
    graph.add_edge("validate_sql", "execute_sql")
    graph.add_edge("execute_sql", END)

    with tracing.run_span("q?", "session-1", {"agent_version": "v2"}, ["agent_version:v2"]):
        graph.compile().invoke({"question": "q?", "sql": "SELECT 1"})

    by_name = {span.name: span for span in spans.get_finished_spans()}
    root, execute = by_name["ask"], by_name["execute_sql"]
    assert set(by_name) == {"ask", "validate_sql", "execute_sql"}
    assert {span.context.trace_id for span in by_name.values()} == {root.context.trace_id}
    assert execute.parent is not None and execute.parent.span_id == root.context.span_id
    assert root.attributes["session.id"] == "session-1"
    assert json.loads(root.attributes["metadata"]) == {"agent_version": "v2"}
    assert execute.attributes["openinference.span.kind"] == "TOOL"
    logged = json.loads(execute.attributes["output.value"])["result"]
    assert logged["row_count"] == 50
    assert len(logged["sample"]) == tracing.SAMPLE_ROWS  # never the full result set


def test_a_rejected_sql_attempt_marks_its_span_as_an_error(spans: InMemorySpanExporter) -> None:
    node = tracing.traced_node(
        "validate_sql", lambda s: {"sql_errors": ["Unknown column: country"]}
    )
    node({"sql": "SELECT c.country FROM customer c"})

    (span,) = spans.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "Unknown column: country"
    assert json.loads(span.attributes["input.value"]) == {"sql": "SELECT c.country FROM customer c"}


def test_a_crashing_node_records_the_exception(spans: InMemorySpanExporter) -> None:
    def overloaded(state: AgentState) -> dict:
        raise RuntimeError("503 UNAVAILABLE")

    with pytest.raises(RuntimeError):
        tracing.traced_node("write_answer", overloaded)({"question": "q"})

    (span,) = spans.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert [event.name for event in span.events] == ["exception"]


def test_llm_span_records_prompt_response_and_tokens(spans: InMemorySpanExporter) -> None:
    response = AIMessage(
        content='{"route": "clarify"}',
        usage_metadata={"input_tokens": 30, "output_tokens": 18, "total_tokens": 48},
    )
    with tracing.llm_span("gemini-test", "RouteDecision", "Route this question") as span:
        tracing.record_llm_response(span, response)

    (span,) = spans.get_finished_spans()
    attributes = span.attributes
    assert attributes["openinference.span.kind"] == "LLM"
    assert attributes["llm.model_name"] == "gemini-test"
    assert attributes["llm.input_messages.0.message.content"] == "Route this question"
    assert attributes["llm.output_messages.0.message.content"] == '{"route": "clarify"}'
    assert (attributes["llm.token_count.prompt"], attributes["llm.token_count.completion"]) == (
        30,
        18,
    )


def test_finishing_a_run_records_the_outcome_and_any_error(spans: InMemorySpanExporter) -> None:
    with tracing.run_span("q?", None, {"run_id": "r1"}, []) as span:
        trace_id, span_id = tracing.trace_ids(span)
        tracing.finish_run_span(
            span, "Revenue was $5.", {"run_id": "r1", "status": "error"}, ValueError("boom")
        )

    (root,) = spans.get_finished_spans()
    assert len(trace_id) == 32 and len(span_id) == 16
    assert "session.id" not in root.attributes
    assert root.attributes["output.value"] == "Revenue was $5."
    assert json.loads(root.attributes["metadata"])["status"] == "error"
    assert root.status.status_code is StatusCode.ERROR


def test_trace_url_points_at_the_phoenix_redirect_only_when_phoenix_is_configured() -> None:
    settings = Settings(phoenix_url="http://localhost:6006/", neatlogs_api_key=None)
    assert trace_url(settings, "abc123") == "http://localhost:6006/redirects/traces/abc123"
    assert trace_url(settings, None) is None
    assert trace_url(Settings(phoenix_url=None, neatlogs_api_key=None), "abc123") is None
