"""Turn relative dates in the question into concrete ranges, anchored to the data's latest date."""

from datetime import date
from typing import Any

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.state import AgentState
from ledgerlens.sql.dates import DateContext, pick_anchor_column, resolve_relative_dates


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    metric = deps.layer.metrics.get(state["route"].metric or "")
    column = pick_anchor_column(state["question"], metric.time_column if metric else None)
    if FailureMode.DATE_BOUNDARY in deps.failures:
        # v1: "last month" meant last month on the server's clock; the data ends in 2022
        anchor, source, coverage = date.today(), "today's date", {}
    else:
        anchor, source, coverage = deps.coverage[column][1], f"the latest {column}", deps.coverage
    dates = DateContext(
        anchor_column=column,
        anchor=anchor,
        anchor_source=source,
        coverage=coverage,
        ranges=resolve_relative_dates(state["question"], anchor),
    )
    return {"dates": dates}
