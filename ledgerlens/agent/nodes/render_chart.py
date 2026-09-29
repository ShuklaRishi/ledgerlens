"""Choose stat / line / bar / table from the result's shape and draw the chart. No model call."""

from pathlib import Path
from typing import Any

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.state import AgentState, Chart
from ledgerlens.viz.charts import choose_output_type, render_chart


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    result = state["result"]
    output_type = choose_output_type(result)
    if state.get("chart_requested") is False and output_type in ("line", "bar"):
        output_type = "table"  # v1: the answer step decided a chart wasn't needed
    path = None
    if output_type in ("line", "bar"):
        path = str(render_chart(result, output_type, state["question"], Path(state["chart_file"])))
    return {"chart": Chart(output_type=output_type, path=path)}
