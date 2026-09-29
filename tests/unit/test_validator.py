import pytest

from ledgerlens.sql.validator import validate_sql

CATALOG = {
    "payment": {"payment_id", "customer_id", "rental_id", "amount", "payment_date"},
    "customer": {"customer_id", "first_name", "last_name", "address_id"},
    "address": {"address_id", "city_id"},
}


def test_valid_aggregate_passes() -> None:
    sql = (
        "SELECT c.first_name, SUM(p.amount) AS revenue FROM payment p "
        "JOIN customer c ON c.customer_id = p.customer_id "
        "GROUP BY c.first_name ORDER BY revenue DESC LIMIT 5"
    )
    assert validate_sql(sql, CATALOG).ok


def test_cte_names_are_not_mistaken_for_tables() -> None:
    sql = (
        "WITH t AS (SELECT p.customer_id, SUM(p.amount) AS total FROM payment p GROUP BY 1) "
        "SELECT t.customer_id, t.total FROM t ORDER BY t.total DESC LIMIT 3"
    )
    assert validate_sql(sql, CATALOG).ok


def test_joining_aggregated_ctes_counts_as_bounded() -> None:
    # The two-fact pattern the planner is told to use: each fact aggregated on its own.
    sql = (
        "WITH paid AS (SELECT p.customer_id, SUM(p.amount) AS revenue FROM payment p GROUP BY 1), "
        "cnt AS (SELECT p.customer_id, COUNT(*) AS payments FROM payment p GROUP BY 1) "
        "SELECT paid.customer_id, paid.revenue, cnt.payments FROM paid JOIN cnt USING (customer_id)"
    )
    assert validate_sql(sql, CATALOG).ok
    raw = (
        "WITH c AS (SELECT * FROM customer) "
        "SELECT c.first_name FROM c JOIN payment p USING (customer_id)"
    )
    assert "Unbounded" in validate_sql(raw, CATALOG).errors[0]


def test_a_join_on_a_column_with_itself_is_rejected() -> None:
    # The first v2 eval run produced this; it matched every payment to every customer.
    sql = (
        "SELECT c.first_name, ROUND(SUM(p.amount), 2) AS lifetime_value FROM payment p "
        "JOIN customer c ON c.customer_id = c.customer_id "
        "GROUP BY c.customer_id, c.first_name ORDER BY lifetime_value DESC LIMIT 5"
    )
    errors = validate_sql(sql, CATALOG).errors
    assert any("compares a column with itself" in e for e in errors), errors
    assert validate_sql(sql, CATALOG, check_joins=False).ok  # v1 let it through


def test_hallucinated_column_is_rejected() -> None:
    sql = (
        "SELECT c.country, SUM(p.amount) FROM payment p "
        "JOIN customer c ON c.customer_id = p.customer_id GROUP BY 1"
    )
    errors = validate_sql(sql, CATALOG).errors
    assert any("country" in e for e in errors), errors


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("DELETE FROM payment", "Only SELECT"),
        ("SELECT 1; DROP TABLE payment", "exactly one statement"),
        ("WITH d AS (DELETE FROM payment RETURNING *) SELECT count(*) FROM d", "Read-only"),
        ("SELECT * INTO backup FROM payment", "Read-only"),
        ("SELECT pg_sleep(10)", "pg_sleep"),
        ("SELECT d.name FROM semantic.docs d LIMIT 1", "Schema 'semantic'"),
        ("SELECT s.password FROM staff_secrets s LIMIT 1", "Unknown table"),
        ("SELECT p.amount FROM payment p", "Unbounded"),
        ("SELECT (p.amount FROM payment p", "does not parse"),
    ],
)
def test_unsafe_or_invalid_sql_is_rejected(sql: str, expected: str) -> None:
    errors = validate_sql(sql, CATALOG).errors
    assert any(expected in e for e in errors), errors
