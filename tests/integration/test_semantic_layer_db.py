"""The curated layer must match the live database: every query runs, every column exists."""

import psycopg
import pytest

from ledgerlens.semantic.layer import load_layer
from ledgerlens.sql.catalog import load_catalog
from ledgerlens.sql.checks import fanout_probe
from ledgerlens.sql.executor import explain, run_query
from ledgerlens.sql.validator import validate_sql

pytestmark = pytest.mark.integration
LAYER = load_layer()


def concrete(sql: str) -> str:
    return sql.replace(":start", "'2022-06-01'").replace(":end", "'2022-07-01'")


@pytest.mark.parametrize("name", sorted(LAYER.metrics))
def test_canonical_metric_sql_validates_and_returns_rows(
    agent_conn: psycopg.Connection, name: str
) -> None:
    sql = concrete(LAYER.metrics[name].sql)
    assert validate_sql(sql, load_catalog(agent_conn)).errors == []
    assert explain(agent_conn, sql) is None
    assert run_query(agent_conn, sql, row_cap=50).row_count > 0


def test_documented_columns_exist_and_secrets_are_hidden(agent_conn: psycopg.Connection) -> None:
    catalog = load_catalog(agent_conn)
    missing = [
        f"{t.name}.{c}"
        for t in LAYER.tables.values()
        for c in t.columns
        if c not in catalog.get(t.name, set())
    ]
    assert missing == []
    assert "password" not in catalog["staff"]


def test_fanout_probe_catches_a_join_through_every_copy_of_a_film(
    agent_conn: psycopg.Connection,
) -> None:
    bad = (
        "SELECT c.name AS category, SUM(p.amount) AS revenue FROM payment p "
        "JOIN rental r ON r.rental_id = p.rental_id "
        "JOIN inventory i ON i.inventory_id = r.inventory_id "
        "JOIN inventory i2 ON i2.film_id = i.film_id "  # every copy of the film, not the rented one
        "JOIN film_category fc ON fc.film_id = i2.film_id "
        "JOIN category c ON c.category_id = fc.category_id GROUP BY c.name"
    )
    good = concrete(LAYER.metrics["revenue_by_category"].sql)

    bad_joined, bad_distinct = agent_conn.execute(fanout_probe(bad).sql).fetchone()
    good_joined, good_distinct = agent_conn.execute(fanout_probe(good).sql).fetchone()
    assert bad_joined > bad_distinct
    assert good_joined == good_distinct
