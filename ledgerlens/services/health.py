"""Checks behind GET /health."""

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from ledgerlens.core.config import Settings
from ledgerlens.schemas.health import CheckResult, HealthReport


def check_health(pool: ConnectionPool, settings: Settings) -> HealthReport:
    try:
        with pool.connection(timeout=2) as conn:
            checks = [
                CheckResult(name="database", ok=True, critical=True, detail="agent_ro connected"),
                _check_pgvector(conn),
                _check_semantic_layer(conn),
            ]
    except (psycopg.OperationalError, PoolTimeout) as exc:
        checks = [CheckResult(name="database", ok=False, critical=True, detail=str(exc))]

    checks.append(
        CheckResult(
            name="tracing",
            ok=True,  # off is a valid configuration, not a fault
            critical=False,
            detail=", ".join(settings.tracing_backends) or "off (PHOENIX_URL not set)",
        )
    )
    return HealthReport.from_checks(checks)


def _check_pgvector(conn: psycopg.Connection) -> CheckResult:
    row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    return CheckResult(
        name="pgvector",
        ok=row is not None,
        critical=True,
        detail=f"v{row[0]}" if row else "extension missing",
    )


def _check_semantic_layer(conn: psycopg.Connection) -> CheckResult:
    seeded = conn.execute("SELECT to_regclass('semantic.docs') IS NOT NULL").fetchone()[0]
    if not seeded:
        return CheckResult(
            name="semantic_layer", ok=False, critical=False, detail="not seeded: run `make seed`"
        )
    count = conn.execute("SELECT count(*) FROM semantic.docs").fetchone()[0]
    return CheckResult(
        name="semantic_layer", ok=count > 0, critical=False, detail=f"{count} documents"
    )
