"""The failure modes switch real causes on and off: prompts, checks, the date anchor, the graph."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.graph import END

from ledgerlens.agent.failure_modes import (
    PROMPT_FAILURE_MODES,
    FailureMode,
    active_failure_modes,
    label,
    prompt_version,
)
from ledgerlens.agent.graph import after_answer
from ledgerlens.agent.nodes import render_chart, resolve_dates
from ledgerlens.agent.prompts import render_prompt
from ledgerlens.agent.state import RouteDecision
from ledgerlens.semantic.layer import load_layer
from ledgerlens.sql.checks import query_limit
from ledgerlens.sql.executor import QueryResult
from ledgerlens.sql.validator import validate_sql

ALL = frozenset(FailureMode)
PROMPT_VALUES = {
    "route": {"metrics": "- m", "question": "q"},
    "plan_sql": {"metrics": "m", "schema": "s", "dates": "d", "feedback": "", "question": "q"},
    "answer": {
        "audience": "a",
        "question": "q",
        "timeframe": "t",
        "rows": "r",
        "table": "t",
        "warnings": "w",
    },
}


@pytest.mark.parametrize(
    ("version", "mode", "expected"),
    [
        ("v1", "none", ALL),
        ("v2", "none", frozenset()),
        ("v2", "all", ALL),
        ("v2", "date_boundary, wrong_route", {FailureMode.DATE_BOUNDARY, FailureMode.WRONG_ROUTE}),
    ],
)
def test_versions_and_modes_resolve_to_a_set_of_failures(
    version: str, mode: str, expected: set
) -> None:
    assert active_failure_modes(version, mode) == expected


@pytest.mark.parametrize(("version", "mode"), [("v2", "fan_out"), ("v3", "none")])
def test_typos_fail_loudly(version: str, mode: str) -> None:
    with pytest.raises(ValueError):
        active_failure_modes(version, mode)


def test_labels_are_stable_for_traces_and_reports() -> None:
    assert label(frozenset()) == "none"
    assert label(ALL) == ",".join(sorted(m.value for m in FailureMode))


@pytest.mark.parametrize("prompt", sorted(PROMPT_FAILURE_MODES))
def test_each_prompt_has_a_v1_and_v2_that_accept_the_same_values(prompt: str) -> None:
    assert prompt_version(prompt, ALL) == "v1"
    assert prompt_version(prompt, frozenset()) == "v2"
    for version in ("v1", "v2"):
        assert render_prompt(version, prompt, **PROMPT_VALUES[prompt])


def test_v1_validation_lets_an_invented_column_through() -> None:
    catalog = {"customer": {"customer_id", "address_id"}}
    sql = "SELECT c.country, COUNT(*) FROM customer c GROUP BY 1"
    assert not validate_sql(sql, catalog).ok
    assert validate_sql(sql, catalog, check_columns=False).ok  # left for EXPLAIN to find


@pytest.mark.parametrize(
    ("failures", "anchor"),
    [(frozenset(), date(2022, 7, 27)), (frozenset({FailureMode.DATE_BOUNDARY}), date.today())],
    ids=["v2-data-anchor", "v1-clock-anchor"],
)
def test_relative_dates_anchor_to_the_data_or_to_the_clock(
    failures: frozenset, anchor: date
) -> None:
    deps = SimpleNamespace(
        layer=load_layer(),
        failures=failures,
        coverage={
            "payment.payment_date": (date(2022, 1, 23), date(2022, 7, 27)),
            "rental.rental_date": (date(2022, 2, 14), date(2022, 8, 23)),
        },
    )
    state = {
        "question": "What was revenue last month?",
        "route": RouteDecision(route="custom_sql", reason=""),
    }
    dates = resolve_dates.run(state, deps)["dates"]
    assert dates.anchor == anchor
    assert dates.ranges[0].start.month == (anchor.month - 2) % 12 + 1


def test_v1_charts_only_when_the_model_asks(tmp_path: Path) -> None:
    months = [[datetime(2022, m, 1, tzinfo=UTC), 1000.0 * m] for m in range(1, 7)]
    state = {
        "question": "Monthly revenue?",
        "result": QueryResult(columns=["month", "revenue"], rows=months, truncated=False),
        "chart_file": str(tmp_path / "chart.png"),
    }
    assert render_chart.run(state, deps=None)["chart"].output_type == "line"  # v2: from the shape
    declined = render_chart.run({**state, "chart_requested": False}, deps=None)["chart"]
    assert (declined.output_type, declined.path) == ("table", None)


def test_v1_graph_only_charts_answered_results() -> None:
    assert after_answer({"result": object(), "sql_errors": []}) == "render_chart"
    assert after_answer({"sql_errors": ["boom"]}) == END


def test_query_limit_reads_the_outer_limit_only() -> None:
    assert query_limit("SELECT c.name FROM category c ORDER BY 1 LIMIT 10") == 10
    assert query_limit("WITH t AS (SELECT 1 AS x LIMIT 5) SELECT t.x FROM t") is None
