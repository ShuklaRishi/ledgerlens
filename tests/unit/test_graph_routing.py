from functools import partial

import pytest

from ledgerlens.agent.graph import after_route, after_sql_step
from ledgerlens.agent.state import Route, RouteDecision


@pytest.mark.parametrize(
    ("route", "next_node"),
    [
        ("metric_lookup", "resolve_dates"),
        ("custom_sql", "resolve_dates"),
        ("clarify", "write_answer"),
        ("out_of_scope", "write_answer"),
    ],
)
def test_only_answerable_routes_go_to_sql(route: Route, next_node: str) -> None:
    assert after_route({"route": RouteDecision(route=route, reason="test")}) == next_node


def test_sql_errors_retry_until_the_attempt_budget_is_spent() -> None:
    step = partial(after_sql_step, on_success="execute_sql", max_attempts=3)
    assert step({"sql_errors": [], "sql_attempts": 1}) == "execute_sql"
    assert step({"sql_errors": ["unknown column"], "sql_attempts": 1}) == "plan_sql"
    assert step({"sql_errors": ["unknown column"], "sql_attempts": 3}) == "write_answer"
