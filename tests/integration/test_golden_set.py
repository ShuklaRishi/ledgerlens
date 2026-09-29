"""Every ground-truth query must pass the agent's own validator and return real rows."""

import psycopg
import pytest

from evals.cases import GoldenCase, expected_rows, load_cases
from ledgerlens.sql.catalog import load_catalog
from ledgerlens.sql.validator import validate_sql

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("case", [c for c in load_cases() if c.sql], ids=lambda c: c.id)
def test_ground_truth_is_valid_and_returns_rows(
    agent_conn: psycopg.Connection, case: GoldenCase
) -> None:
    assert validate_sql(case.sql, load_catalog(agent_conn)).errors == []
    rows = expected_rows(agent_conn, case)
    assert rows
    assert all(value is not None for row in rows for value in row)
