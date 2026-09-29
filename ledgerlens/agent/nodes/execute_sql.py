"""Run the validated query as agent_ro, capped at row_cap rows."""

from typing import Any

import psycopg

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.state import AgentState, SqlAttempt
from ledgerlens.sql.executor import error_message, run_query


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    try:
        with deps.pool.connection() as conn:
            result = run_query(conn, state["sql"], deps.settings.row_cap)
    except psycopg.Error as exc:  # runtime errors EXPLAIN can't catch, e.g. a timeout
        error = error_message(exc)
        attempt = SqlAttempt(
            attempt=state["sql_attempts"], stage="execute", sql=state["sql"], errors=[error]
        )
        return {"sql_errors": [error], "attempt_log": [attempt]}
    return {"result": result, "sql_errors": []}
