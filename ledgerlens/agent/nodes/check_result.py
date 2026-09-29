"""Sanity-check the result: empty, NULL or negative totals, duplicate groups, join fan-out.

Most findings are warnings for the answer. A fan-out is something the model can fix, so while
SQL attempts remain it goes back to plan_sql like a validation error, instead of letting an
inflated total reach the user.
"""

import logging
from typing import Any

import psycopg

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.state import AgentState, SqlAttempt
from ledgerlens.sql.checks import ResultWarning, fanout_probe, fanout_warning, result_warnings

log = logging.getLogger(__name__)


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    warnings = result_warnings(state["result"])
    if FailureMode.FANOUT_JOIN in deps.failures:  # v1 had no fan-out check
        return {"warnings": warnings}

    fanout = _fanout_warnings(state["sql"], deps)
    if fanout and state["sql_attempts"] < deps.settings.max_sql_attempts:
        errors = [w.message for w in fanout]
        attempt = SqlAttempt(
            attempt=state["sql_attempts"], stage="check", sql=state["sql"], errors=errors
        )
        return {"warnings": warnings + fanout, "sql_errors": errors, "attempt_log": [attempt]}
    return {"warnings": warnings + fanout}  # out of attempts: answer, with the warning shown


def _fanout_warnings(sql: str, deps: AgentDeps) -> list[ResultWarning]:
    probe = fanout_probe(sql)
    if probe is None:
        return []
    try:
        with deps.pool.connection() as conn:
            joined_rows, fact_rows = conn.execute(probe.sql).fetchone()
    except psycopg.Error:  # the check is best-effort; never fail an answer because of it
        log.warning("fan-out probe failed", exc_info=True)
        return []
    warning = fanout_warning(probe, joined_rows, fact_rows)
    return [warning] if warning else []
