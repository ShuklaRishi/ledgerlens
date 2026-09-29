from typing import Any

import pytest

from ledgerlens.sql.checks import FanoutProbe, fanout_probe, fanout_warning, result_warnings
from ledgerlens.sql.executor import QueryResult

CATEGORY_REVENUE = (
    "SELECT c.name, SUM(p.amount) AS revenue FROM payment p "
    "JOIN rental r ON r.rental_id = p.rental_id "
    "JOIN inventory i ON i.inventory_id = r.inventory_id "
    "JOIN film_category fc ON fc.film_id = i.film_id "
    "JOIN category c ON c.category_id = fc.category_id "
    "WHERE p.payment_date >= '2022-06-01' GROUP BY c.name ORDER BY revenue DESC LIMIT 5"
)


def codes(columns: list[str], rows: list[list[Any]]) -> list[str]:
    result = QueryResult(columns=columns, rows=rows, truncated=False)
    return [w.code for w in result_warnings(result)]


def test_clean_result_has_no_warnings() -> None:
    assert codes(["store_id", "revenue"], [[1, 10.0], [2, 20.0]]) == []


@pytest.mark.parametrize(
    ("columns", "rows", "expected"),
    [
        (["revenue"], [], ["empty_result"]),
        (["revenue"], [[None]], ["null_values"]),  # SUM over no matching rows
        (["store_id", "revenue"], [[1, 10.0], [2, -5.0]], ["negative_values"]),
        (["category", "revenue"], [["Action", 1.0], ["Action", 2.0]], ["duplicate_groups"]),
    ],
)
def test_suspicious_results_are_flagged(
    columns: list[str], rows: list[list[Any]], expected: list[str]
) -> None:
    assert codes(columns, rows) == expected


def test_fanout_probe_counts_joined_rows_against_distinct_payments() -> None:
    probe = fanout_probe(CATEGORY_REVENUE)
    assert probe is not None
    assert probe.fact == "payment"
    assert "COUNT(DISTINCT p.payment_id)" in probe.sql
    assert "p.payment_date >= '2022-06-01'" in probe.sql  # same filters as the question
    assert "GROUP BY" not in probe.sql
    assert "LIMIT" not in probe.sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(p.amount) FROM payment p",
        "SELECT COUNT(DISTINCT r.customer_id) FROM rental r "
        "JOIN inventory i ON i.inventory_id = r.inventory_id",
        "SELECT c.name, COUNT(*) FROM category c "
        "JOIN film_category fc ON fc.category_id = c.category_id GROUP BY 1",
    ],
    ids=["no-join", "count-distinct", "no-fact-table"],
)
def test_fanout_probe_skips_queries_it_does_not_apply_to(sql: str) -> None:
    assert fanout_probe(sql) is None


def test_fanout_warning_only_when_rows_multiply() -> None:
    probe = FanoutProbe(fact="payment", sql="...")
    assert fanout_warning(probe, joined_rows=100, fact_rows=100) is None
    warning = fanout_warning(probe, joined_rows=500, fact_rows=100)
    assert warning is not None
    assert "5.0x" in warning.message
