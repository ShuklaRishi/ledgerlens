"""`ledgerlens db-check`: is Pagila loaded, and is the agent role really read-only?"""

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg import errors, sql

from ledgerlens.core.config import Settings
from ledgerlens.db.connection import connect_agent

TABLES = ("store", "staff", "customer", "film", "category", "inventory", "rental", "payment")

# Each must fail with "permission denied" even after the session turns read-only mode
# off, which proves the grants block them, not just default_transaction_read_only.
PROBES: dict[str, str] = {
    "read staff.password": "SELECT password FROM public.staff LIMIT 1",
    "insert": (
        "INSERT INTO public.payment (customer_id, staff_id, rental_id, amount, payment_date) "
        "VALUES (1, 1, 1, 1.00, now())"
    ),
    "update": "UPDATE public.customer SET first_name = 'x' WHERE customer_id = 1",
    "delete": "DELETE FROM public.rental WHERE rental_id = 1",
    "truncate": "TRUNCATE public.payment",
    "create table": "CREATE TABLE public.probe (id int)",
    "create temp table": "CREATE TEMP TABLE probe (id int)",
    "write semantic schema": "CREATE TABLE semantic.probe (id int)",
    "security-definer fn": "SELECT * FROM public.rewards_report(1, 1)",
}


@dataclass(frozen=True)
class ProbeResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DbCheckReport:
    server_version: str
    pgvector_version: str | None
    row_counts: dict[str, int]
    date_ranges: dict[str, tuple[datetime, datetime]]
    probes: list[ProbeResult]

    @property
    def ok(self) -> bool:
        return (
            self.pgvector_version is not None
            and all(self.row_counts.values())
            and all(p.ok for p in self.probes)
        )


def probe_privileges(conn: psycopg.Connection) -> list[ProbeResult]:
    conn.autocommit = True
    conn.execute("SET default_transaction_read_only = off")
    results = []
    for name, statement in PROBES.items():
        try:
            conn.execute(statement)
        except errors.InsufficientPrivilege as exc:
            results.append(ProbeResult(name, ok=True, detail=exc.diag.message_primary or ""))
        except psycopg.Error as exc:
            reason = f"blocked, but not by grants: {type(exc).__name__}: {exc}"
            results.append(ProbeResult(name, ok=False, detail=reason))
        else:
            results.append(ProbeResult(name, ok=False, detail="SUCCEEDED: agent_ro was allowed"))
    return results


def run_checks(settings: Settings) -> DbCheckReport:
    """Raises psycopg.OperationalError if the database is unreachable."""
    with connect_agent(settings) as conn:
        server_version = conn.execute("SHOW server_version").fetchone()[0]
        vector = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        row_counts = {
            table: conn.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in TABLES
        }
        date_ranges = {
            "rental_date": conn.execute(
                "SELECT min(rental_date), max(rental_date) FROM public.rental"
            ).fetchone(),
            "payment_date": conn.execute(
                "SELECT min(payment_date), max(payment_date) FROM public.payment"
            ).fetchone(),
        }
        probes = probe_privileges(conn)
    return DbCheckReport(
        server_version=server_version,
        pgvector_version=vector[0] if vector else None,
        row_counts=row_counts,
        date_ranges=date_ranges,
        probes=probes,
    )
