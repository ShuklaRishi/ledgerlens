"""A fan-out found after execution goes back to the planner while SQL attempts remain."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import pytest

from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.nodes import check_result
from ledgerlens.sql.executor import run_query

pytestmark = pytest.mark.integration

# From the first v2 eval run: a self-join condition that matches every customer.
CROSS_JOIN = (
    "SELECT cu.first_name || ' ' || cu.last_name AS customer, "
    "ROUND(SUM(p.amount), 2) AS lifetime_value "
    "FROM payment p JOIN customer cu ON cu.customer_id = cu.customer_id "
    "GROUP BY cu.customer_id, cu.first_name, cu.last_name ORDER BY lifetime_value DESC LIMIT 5"
)


def deps(conn: psycopg.Connection, failures: frozenset = frozenset()) -> SimpleNamespace:
    @contextmanager
    def connection() -> Iterator[psycopg.Connection]:
        yield conn

    return SimpleNamespace(
        pool=SimpleNamespace(connection=connection),
        failures=failures,
        settings=SimpleNamespace(max_sql_attempts=3),
    )


def state(conn: psycopg.Connection, attempts: int) -> dict:
    return {"sql": CROSS_JOIN, "result": run_query(conn, CROSS_JOIN, 50), "sql_attempts": attempts}


def test_fanout_is_sent_back_to_the_planner_while_attempts_remain(
    agent_conn: psycopg.Connection,
) -> None:
    update = check_result.run(state(agent_conn, attempts=1), deps(agent_conn))
    assert update["sql_errors"]
    assert "599.0x" in update["sql_errors"][0]
    assert update["attempt_log"][0].stage == "check"


def test_out_of_attempts_the_answer_carries_the_warning(agent_conn: psycopg.Connection) -> None:
    update = check_result.run(state(agent_conn, attempts=3), deps(agent_conn))
    assert "sql_errors" not in update
    assert [w.code for w in update["warnings"]] == ["fanout"]


def test_v1_has_no_fanout_check(agent_conn: psycopg.Connection) -> None:
    update = check_result.run(
        state(agent_conn, attempts=1), deps(agent_conn, frozenset({FailureMode.FANOUT_JOIN}))
    )
    assert update == {"warnings": []}
