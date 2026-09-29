"""The reply for a business user. The model writes the two sentences; the facts come from code."""

from typing import Any

from pydantic import BaseModel, Field

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.llm import ask_structured
from ledgerlens.agent.prompts import render_prompt
from ledgerlens.agent.state import AgentState, Answer, UserRole
from ledgerlens.sql.checks import query_limit
from ledgerlens.sql.executor import QueryResult
from ledgerlens.viz.charts import format_table

AUDIENCE: dict[UserRole, str] = {
    "am": "an account manager",
    "sales": "a salesperson",
    "leadership": "a member of the leadership team",
    "dev": "a developer",
}
OUT_OF_SCOPE = (
    "I can only answer questions about the rental business's own data: stores, staff, "
    "customers, films, rentals and payments."
)


class AnswerText(BaseModel):
    headline: str = Field(description="One sentence answering the question with the key number(s).")
    interpretation: str = Field(description="One short sentence on what stands out.")


class AnswerTextWithChartChoice(AnswerText):
    """v1: the model also decided whether a chart was worth drawing."""

    include_chart: bool = Field(description="True only if a chart is essential.")


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    route = state["route"]
    if route.route == "clarify":
        question = (
            route.clarifying_question or "What would you like to measure, and over which period?"
        )
        return {"answer": Answer(status="clarify", headline=question)}
    if route.route == "out_of_scope":
        return {
            "answer": Answer(
                status="out_of_scope", headline=OUT_OF_SCOPE, interpretation=route.reason
            )
        }
    if state.get("sql_errors"):
        return {
            "answer": Answer(
                status="failed",
                headline="I couldn't build a valid query for this question.",
                interpretation=f"Last error: {state['sql_errors'][-1]}",
            )
        }

    result = state["result"]
    model_charts = FailureMode.SKIPPED_VISUALISATION in deps.failures
    # v1 never told the user how "last month" was resolved
    timeframe = None if FailureMode.DATE_BOUNDARY in deps.failures else state["dates"].for_humans()
    warnings = [w.message for w in state.get("warnings", [])]
    prompt = render_prompt(
        deps.prompt_version("answer"),  # v1's prompt: "be concise", and it chooses charts
        "answer",
        audience=AUDIENCE.get(state["user_role"], "a colleague"),
        question=state["question"],
        timeframe=timeframe or "as stated in the question",
        rows=_describe_rows(result, state["sql"]),
        table=format_table(result),
        warnings="; ".join(warnings) or "none",
    )
    text = ask_structured(
        deps.llm, AnswerTextWithChartChoice if model_charts else AnswerText, prompt
    )
    metric = deps.layer.metrics.get(route.metric or "")
    answer = Answer(
        status="answered",
        headline=text.headline,
        interpretation=text.interpretation,
        definition=f"{metric.label}: {metric.description}" if metric else None,
        timeframe=timeframe,
        warnings=warnings,
    )
    if isinstance(text, AnswerTextWithChartChoice):
        return {"answer": answer, "chart_requested": text.include_chart}
    return {"answer": answer}


def _describe_rows(result: QueryResult, sql: str) -> str:
    text = f"{result.row_count} rows"
    if result.truncated:
        text += ", truncated"
    limit = query_limit(sql)
    if limit is not None and result.row_count == limit:
        text += f"; the query's top {limit}, not every group"
    return text
