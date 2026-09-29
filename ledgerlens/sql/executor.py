"""Run validated SQL through the read-only pool, and describe the result's shape."""

from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
from pydantic import BaseModel, computed_field


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool  # more rows existed than the row cap

    @computed_field
    @property
    def row_count(self) -> int:
        return len(self.rows)

    def measure_indexes(self) -> list[int]:
        """Numeric columns that are not identifiers: revenue is a measure, store_id is a label."""
        return [
            i
            for i, name in enumerate(self.columns)
            if not _is_identifier(name) and all(_is_number(v) for v in self._values(i))
        ]

    def temporal_indexes(self) -> list[int]:
        return [
            i
            for i in range(len(self.columns))
            if self._values(i) and all(isinstance(v, date) for v in self._values(i))
        ]

    def _values(self, index: int) -> list[Any]:
        return [row[index] for row in self.rows if row[index] is not None]


def explain(conn: psycopg.Connection, sql: str) -> str | None:
    """Postgres's own check (types, ambiguity) without running the query. Returns the error."""
    try:
        conn.execute(f"EXPLAIN {sql}")
    except psycopg.Error as exc:
        return error_message(exc)
    return None


def run_query(conn: psycopg.Connection, sql: str, row_cap: int) -> QueryResult:
    cursor = conn.execute(sql)
    columns = [d.name for d in cursor.description or []]
    rows = cursor.fetchmany(row_cap + 1)
    return QueryResult(
        columns=columns,
        rows=[[_plain(v) for v in row] for row in rows[:row_cap]],
        truncated=len(rows) > row_cap,
    )


def error_message(exc: psycopg.Error) -> str:
    return (exc.diag.message_primary or str(exc)).strip()


def _plain(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_identifier(name: str) -> bool:
    return name == "id" or name.endswith("_id")
