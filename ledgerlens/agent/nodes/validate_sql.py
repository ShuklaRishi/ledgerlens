"""Deterministic checks (read-only, known tables/columns, bounded), then Postgres EXPLAIN."""

from typing import Any

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.state import AgentState, SqlAttempt
from ledgerlens.sql.executor import explain
from ledgerlens.sql.validator import validate_sql


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    sql = state["sql"]
    # v1 checked tables but not columns against the catalog, and not join conditions
    errors = validate_sql(
        sql,
        deps.catalog,
        check_columns=FailureMode.HALLUCINATED_COLUMN not in deps.failures,
        check_joins=FailureMode.FANOUT_JOIN not in deps.failures,
    ).errors
    if not errors:
        with deps.pool.connection() as conn:
            problem = explain(conn, sql)
        errors = [problem] if problem else []
    attempt = SqlAttempt(attempt=state["sql_attempts"], stage="validate", sql=sql, errors=errors)
    return {"sql_errors": errors, "attempt_log": [attempt]}
