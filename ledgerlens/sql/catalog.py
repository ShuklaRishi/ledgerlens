"""What the agent may reference, and how far the data goes. Read through the agent_ro role."""

from datetime import date

import psycopg
from psycopg import sql

Catalog = dict[str, set[str]]  # table -> columns agent_ro can read
Coverage = dict[str, tuple[date, date]]  # "table.column" -> (first date, last date)

TIME_COLUMNS = ("payment.payment_date", "rental.rental_date")


def load_catalog(conn: psycopg.Connection) -> Catalog:
    """Public tables and views, limited to columns agent_ro has privileges on."""
    catalog: Catalog = {}
    rows = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public'"
    ).fetchall()
    for table, column in rows:
        catalog.setdefault(table, set()).add(column)
    return catalog


def load_coverage(conn: psycopg.Connection) -> Coverage:
    coverage: Coverage = {}
    for qualified in TIME_COLUMNS:
        table, column = qualified.split(".")
        query = sql.SQL("SELECT min({c})::date, max({c})::date FROM {t}").format(
            c=sql.Identifier(column), t=sql.Identifier(table)
        )
        coverage[qualified] = conn.execute(query).fetchone()
    return coverage
