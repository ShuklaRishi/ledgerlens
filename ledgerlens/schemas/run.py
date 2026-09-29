"""A finished agent run: what POST /v1/ask returns and what runs/<run_id>/run.json stores."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from ledgerlens.agent.state import Answer, RouteDecision, SqlAttempt
from ledgerlens.semantic.retrieval import RetrievedContext
from ledgerlens.sql.checks import ResultWarning
from ledgerlens.sql.dates import DateContext
from ledgerlens.sql.executor import QueryResult
from ledgerlens.viz.charts import OutputType


class Usage(BaseModel):
    llm_calls: int
    input_tokens: int
    output_tokens: int


class RunRecord(BaseModel):
    run_id: str
    trace_id: str | None = None  # the OpenTelemetry trace; None when tracing is off
    span_id: str | None = None  # the root "ask" span, which feedback annotates
    trace_url: str | None = None  # opens the trace in Phoenix
    created_at: datetime
    question: str
    user_role: str
    session_id: str | None
    eval_case_id: str | None = None
    agent_version: str
    failure_mode: str
    model: str
    latency_ms: int
    usage: Usage
    status: Literal["answered", "clarify", "out_of_scope", "failed", "error"]
    answer: Answer | None = None
    route: RouteDecision | None = None
    retrieved: RetrievedContext | None = None
    dates: DateContext | None = None
    plan: str | None = None
    sql: str | None = None
    attempts: list[SqlAttempt] = []
    warnings: list[ResultWarning] = []
    result: QueryResult | None = None
    output_type: OutputType | None = None
    chart_path: str | None = None
    error: str | None = None  # set when the agent crashed; the fields above hold how far it got
