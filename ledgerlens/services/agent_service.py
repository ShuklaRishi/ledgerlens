"""Runs one question through the agent, traces it, and records the run.

The API, the CLI and the eval runner all call AgentService.ask, so they exercise the same path.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from psycopg_pool import ConnectionPool

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.failure_modes import active_failure_modes, label
from ledgerlens.agent.graph import build_graph
from ledgerlens.agent.llm import UsageTracker, build_chat_model
from ledgerlens.agent.state import AgentState
from ledgerlens.agent.tracing import finish_run_span, run_span, trace_ids
from ledgerlens.core.config import Settings
from ledgerlens.core.logging import run_id_var
from ledgerlens.core.tracing import trace_url
from ledgerlens.schemas.ask import AskRequest
from ledgerlens.schemas.run import RunRecord, Usage
from ledgerlens.semantic.embedder import Embedder
from ledgerlens.semantic.layer import load_layer
from ledgerlens.services.run_store import RunStore

log = logging.getLogger(__name__)


class AgentRunError(RuntimeError):
    """The agent crashed. The run record, with the error and partial state, is saved."""

    def __init__(self, run_id: str, message: str) -> None:
        super().__init__(message)
        self.run_id = run_id


class AgentService:
    def __init__(self, settings: Settings, pool: ConnectionPool, store: RunStore) -> None:
        self._settings = settings
        self._store = store
        # validated here, so a typo in AGENT_VERSION / FAILURE_MODE fails at startup
        self._failures = active_failure_modes(settings.agent_version, settings.failure_mode)
        deps = AgentDeps(
            settings=settings,
            pool=pool,
            llm=build_chat_model(settings),
            embedder=Embedder(settings.embedding_model, settings.cache_dir),
            layer=load_layer(),
            failures=self._failures,
        )
        self._graph = build_graph(deps)

    def ask(self, request: AskRequest, eval_case_id: str | None = None) -> RunRecord:
        run_id = self._store.new_run_id()
        token = run_id_var.set(run_id)  # every log line of this run carries its id
        try:
            return self._run(run_id, request, eval_case_id)
        finally:
            run_id_var.reset(token)

    def _run(self, run_id: str, request: AskRequest, eval_case_id: str | None) -> RunRecord:
        started_at, started = datetime.now(UTC), time.perf_counter()
        labels = {
            "run_id": run_id,
            "agent_version": self._settings.agent_version,
            "model": self._settings.llm_model,
            "failure_mode": label(self._failures),
            "user_role": request.user_role,
            "eval_case_id": eval_case_id,
        }
        tags = [f"{key}:{labels[key]}" for key in ("agent_version", "failure_mode", "user_role")]
        log.info("question: %s", request.question)

        with run_span(request.question, request.session_id, labels, tags) as span:
            usage = UsageTracker()
            state, error = self._invoke(run_id, request, usage)
            trace_id, span_id = trace_ids(span)
            answer, chart = state.get("answer"), state.get("chart")
            record = RunRecord(
                run_id=run_id,
                trace_id=trace_id,
                span_id=span_id,
                trace_url=trace_url(self._settings, trace_id),
                created_at=started_at,
                question=request.question,
                user_role=request.user_role,
                session_id=request.session_id,
                eval_case_id=eval_case_id,
                agent_version=self._settings.agent_version,
                failure_mode=label(self._failures),
                model=self._settings.llm_model,
                latency_ms=round((time.perf_counter() - started) * 1000),
                usage=Usage(
                    llm_calls=usage.calls,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                ),
                status=answer.status if answer and not error else "error",
                answer=answer,
                route=state.get("route"),
                retrieved=state.get("context"),
                dates=state.get("dates"),
                plan=state.get("plan"),
                sql=state.get("sql"),
                attempts=state.get("attempt_log", []),
                warnings=state.get("warnings", []),
                result=state.get("result"),
                output_type=chart.output_type if chart else None,
                chart_path=chart.path if chart else None,
                error=f"{type(error).__name__}: {error}" if error else None,
            )
            finish_run_span(span, _answer_text(record), {**labels, **_outcome(record)}, error)

        self._store.save(record)
        log.info(
            "done: status=%s llm_calls=%d tokens=%d latency_ms=%d trace_id=%s",
            record.status,
            record.usage.llm_calls,
            record.usage.input_tokens + record.usage.output_tokens,
            record.latency_ms,
            record.trace_id,
        )
        if record.error:
            raise AgentRunError(run_id, record.error)
        return record

    def _invoke(
        self, run_id: str, request: AskRequest, usage: UsageTracker
    ) -> tuple[AgentState, Exception | None]:
        """Run the graph. On a crash, return the state up to the failing node with the error."""
        initial: AgentState = {
            "run_id": run_id,
            "question": request.question,
            "user_role": request.user_role,
            "chart_file": str(self._store.chart_file(run_id)),
        }
        state = initial
        try:
            # stream() rather than invoke(), so a crash still leaves the latest state
            for snapshot in self._graph.stream(
                initial, config={"callbacks": [usage]}, stream_mode="values"
            ):
                state = snapshot
        except Exception as exc:  # any failure is recorded; the run file and trace show where
            log.exception("run failed")
            return state, exc
        return state, None


def _answer_text(record: RunRecord) -> str | None:
    if record.answer is None:
        return None
    return "\n".join(filter(None, [record.answer.headline, record.answer.interpretation]))


def _outcome(record: RunRecord) -> dict[str, Any]:
    """Added to the root span's metadata at the end, so traces can be filtered by result."""
    return {
        "status": record.status,
        "route": record.route.route if record.route else None,
        "output_type": record.output_type,
        "sql_attempts": len({a.attempt for a in record.attempts}),
        "warnings": [w.code for w in record.warnings],
        "llm_calls": record.usage.llm_calls,
        "latency_ms": record.latency_ms,
    }
