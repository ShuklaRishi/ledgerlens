"""The state that flows through the graph. Each node returns only the keys it sets."""

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from ledgerlens.semantic.retrieval import RetrievedContext
from ledgerlens.sql.checks import ResultWarning
from ledgerlens.sql.dates import DateContext
from ledgerlens.sql.executor import QueryResult
from ledgerlens.viz.charts import OutputType

Route = Literal["metric_lookup", "custom_sql", "clarify", "out_of_scope"]


class RouteDecision(BaseModel):
    """The router's structured output."""

    route: Route
    reason: str = Field(description="One short sentence explaining the choice.")
    metric: str | None = Field(default=None, description="For metric_lookup: the metric's name.")
    clarifying_question: str | None = Field(
        default=None, description="For clarify: one short question offering 2-3 concrete options."
    )


class SqlAttempt(BaseModel):
    attempt: int
    stage: Literal["validate", "execute", "check"]  # check: sent back by the fan-out check
    sql: str
    errors: list[str]


class Chart(BaseModel):
    output_type: OutputType
    path: str | None = None  # a PNG for line and bar charts


class Answer(BaseModel):
    status: Literal["answered", "clarify", "out_of_scope", "failed"]
    headline: str
    interpretation: str | None = None
    definition: str | None = None  # the metric definition used, when one applied
    timeframe: str | None = None  # how relative dates were resolved
    warnings: list[str] = []


class AgentState(TypedDict, total=False):
    # input
    run_id: str
    question: str
    user_role: str
    chart_file: str  # where render_chart may write the PNG
    # set by the nodes, in graph order
    context: RetrievedContext
    route: RouteDecision
    dates: DateContext
    plan: str
    sql: str
    sql_attempts: int
    sql_errors: list[str]
    attempt_log: Annotated[list[SqlAttempt], operator.add]
    result: QueryResult
    warnings: list[ResultWarning]
    chart: Chart
    answer: Answer
    chart_requested: bool  # only in v1 (skipped_visualisation): the model's say on charting
