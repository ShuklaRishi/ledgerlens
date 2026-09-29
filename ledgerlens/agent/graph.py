"""The analytics agent as a LangGraph state machine.

    retrieve_context -> route_question -> resolve_dates -> plan_sql -> validate_sql
        -> execute_sql -> check_result -> render_chart -> write_answer

Clarify / out-of-scope routes go straight to write_answer. A SQL error at validate or
execute loops back to plan_sql (with the error) until max_sql_attempts is reached.
Only route_question, plan_sql and write_answer call the model; every other step is code.
"""

from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.llm import is_transient
from ledgerlens.agent.nodes import (
    check_result,
    execute_sql,
    plan_sql,
    render_chart,
    resolve_dates,
    retrieve_context,
    route_question,
    validate_sql,
    write_answer,
)
from ledgerlens.agent.state import AgentState
from ledgerlens.agent.tracing import traced_node

NODES = {
    "retrieve_context": retrieve_context.run,
    "route_question": route_question.run,
    "resolve_dates": resolve_dates.run,
    "plan_sql": plan_sql.run,
    "validate_sql": validate_sql.run,
    "execute_sql": execute_sql.run,
    "check_result": check_result.run,
    "render_chart": render_chart.run,
    "write_answer": write_answer.run,
}


# The free tier answers 429/503 under load, sometimes for minutes. Model-calling nodes retry
# a few times with long waits (10s, 20s, 40s): every attempt counts against the daily request
# cap, so waiting longer beats trying more often. Other errors fail the run at once.
MODEL_NODES = {"route_question", "plan_sql", "write_answer"}
MODEL_RETRY = RetryPolicy(
    initial_interval=10.0, max_interval=60.0, max_attempts=4, retry_on=is_transient
)


def build_graph(deps: AgentDeps) -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    for name, node in NODES.items():
        retry = MODEL_RETRY if name in MODEL_NODES else None
        graph.add_node(name, traced_node(name, partial(node, deps=deps)), retry_policy=retry)

    retry = partial(after_sql_step, max_attempts=deps.settings.max_sql_attempts)
    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "route_question")
    graph.add_conditional_edges("route_question", after_route, ["resolve_dates", "write_answer"])
    graph.add_edge("resolve_dates", "plan_sql")
    graph.add_edge("plan_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        partial(retry, on_success="execute_sql"),
        ["execute_sql", "plan_sql", "write_answer"],
    )
    graph.add_conditional_edges(
        "execute_sql",
        partial(retry, on_success="check_result"),
        ["check_result", "plan_sql", "write_answer"],
    )
    if FailureMode.SKIPPED_VISUALISATION in deps.failures:
        # v1: the answer step (told to be concise) decided whether a chart was worth drawing
        after_check = partial(retry, on_success="write_answer")
        graph.add_conditional_edges("check_result", after_check, ["write_answer", "plan_sql"])
        graph.add_conditional_edges("write_answer", after_answer, ["render_chart", END])
        graph.add_edge("render_chart", END)
    else:
        # v2: the chart follows from the data's shape, before the answer is written
        after_check = partial(retry, on_success="render_chart")
        graph.add_conditional_edges(
            "check_result", after_check, ["render_chart", "plan_sql", "write_answer"]
        )
        graph.add_edge("render_chart", "write_answer")
        graph.add_edge("write_answer", END)
    return graph.compile()


def after_route(state: AgentState) -> str:
    return (
        "resolve_dates"
        if state["route"].route in ("metric_lookup", "custom_sql")
        else "write_answer"
    )


def after_sql_step(state: AgentState, *, on_success: str, max_attempts: int) -> str:
    if not state.get("sql_errors"):
        return on_success
    return "plan_sql" if state["sql_attempts"] < max_attempts else "write_answer"


def after_answer(state: AgentState) -> str:
    """v1 only: chart a successful result after answering; clarify/failed runs just end."""
    return "render_chart" if "result" in state and not state.get("sql_errors") else END
