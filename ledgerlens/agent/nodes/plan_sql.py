"""Write a short plan and one SQL query. On a retry, the previous errors are part of the prompt."""

from typing import Any

from pydantic import BaseModel, Field

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.llm import ask_structured
from ledgerlens.agent.prompts import render_prompt
from ledgerlens.agent.state import AgentState


class SqlDraft(BaseModel):
    plan: str = Field(description="Two to four short lines: tables, joins, grain, filters, dates.")
    sql: str = Field(description="One PostgreSQL SELECT statement.")


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    context, route = state["context"], state["route"]
    metric_names = [route.metric] if route.metric else context.metric_names
    prompt = render_prompt(
        deps.prompt_version("plan_sql"),  # v1's prompt has no grain rule
        "plan_sql",
        metrics=deps.layer.describe_metrics(metric_names),
        schema=deps.layer.describe_tables(context.table_names),
        dates=state["dates"].for_prompt(),
        feedback=_retry_feedback(state),
        question=state["question"],
    )
    draft = ask_structured(deps.llm, SqlDraft, prompt)
    return {
        "plan": draft.plan,
        "sql": _clean(draft.sql),
        "sql_attempts": state.get("sql_attempts", 0) + 1,
    }


def _retry_feedback(state: AgentState) -> str:
    errors = state.get("sql_errors")
    if not errors:
        return ""
    lines = ["", "Your previous query failed. Fix these problems:", *[f"- {e}" for e in errors]]
    lines += ["Previous query:", state["sql"], ""]
    return "\n".join(lines)


def _clean(sql: str) -> str:
    return sql.strip().removeprefix("```sql").removesuffix("```").strip().rstrip(";").strip()
