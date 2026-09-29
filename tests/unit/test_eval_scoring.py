from datetime import UTC, datetime
from typing import Any

import pytest

from evals.cases import load_cases
from evals.scoring import route_matches, rows_match, score, summarize
from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.state import Answer, RouteDecision
from ledgerlens.schemas.run import RunRecord, Usage
from ledgerlens.sql.executor import QueryResult

CASES = {case.id: case for case in load_cases()}


def record(**overrides: Any) -> RunRecord:
    fields: dict[str, Any] = {
        "run_id": "20260928T000000-abcdef",
        "created_at": datetime.now(UTC),
        "question": "q",
        "user_role": "am",
        "session_id": None,
        "agent_version": "v2",
        "failure_mode": "none",
        "model": "test",
        "latency_ms": 1000,
        "usage": Usage(llm_calls=3, input_tokens=100, output_tokens=20),
        "status": "answered",
    }
    return RunRecord(**{**fields, **overrides})


def test_the_golden_set_covers_every_failure_mode() -> None:
    assert 15 <= len(CASES) <= 20
    assert {case.targets for case in CASES.values() if case.targets} == set(FailureMode)


@pytest.mark.parametrize(
    ("expected", "actual", "ok"),
    [
        ([[1, 5550.95]], [[5550.95, 1]], True),
        ([[1, 5550.95], [2, 5372.5]], [[2, "Store 2", 5372.5], [1, "Store 1", 5550.95]], True),
        ([["Sports", 0.5791]], [["sports", 57.91]], True),
        ([[10923.45]], [[10923.44]], True),
        ([[datetime(2022, 6, 1, tzinfo=UTC), 10923.45]], [["2022-06-01", 10923.45]], True),
        ([[598]], [[599]], False),
        ([[10923.45]], [[None]], False),
        ([[1, 2270]], [[1, 2270], [2, 2311]], False),
    ],
    ids=[
        "column-order",
        "row-order-and-extra-column",
        "case-and-percentage",
        "rounding",
        "timestamp-vs-date",
        "counts-are-exact",
        "null-total",
        "row-count",
    ],
)
def test_rows_match_is_strict_on_values_and_loose_on_shape(
    expected: list[list[Any]], actual: list[list[Any]], ok: bool
) -> None:
    assert rows_match(expected, actual, tolerance=0.001)[0] is ok


def test_either_data_route_counts_when_data_is_expected() -> None:
    assert route_matches("metric_lookup", "custom_sql")
    assert not route_matches("clarify", "metric_lookup")
    assert not route_matches("clarify", None)


def test_a_correct_answer_passes() -> None:
    result = QueryResult(columns=["revenue"], rows=[[10923.45]], truncated=False)
    run = record(
        route=RouteDecision(route="metric_lookup", reason=""), result=result, output_type="stat"
    )
    scored = score(CASES["revenue_june"], [[10923.45]], run, catalog={})
    assert scored.passed
    assert scored.answer_detail == "all 1 rows match"


def test_answering_a_vague_question_fails_on_route_and_output() -> None:
    result = QueryResult(columns=["revenue"], rows=[[10923.45]], truncated=False)
    run = record(
        route=RouteDecision(route="metric_lookup", reason=""), result=result, output_type="stat"
    )
    scored = score(CASES["vague_how_did_we_do"], None, run, catalog={})
    assert not scored.passed
    assert (scored.route_ok, scored.output_type_ok, scored.answer_ok) == (False, False, None)


def test_a_crashed_run_is_scored_not_skipped() -> None:
    run = record(status="error", error="GoogleAPIError: 503 UNAVAILABLE")
    scored = score(CASES["revenue_june"], [[10923.45]], run, catalog={})
    assert not scored.passed
    assert scored.actual_output_type == "none"
    assert "503" in scored.answer_detail


def test_clarifying_a_vague_question_passes() -> None:
    run = record(
        status="clarify",
        route=RouteDecision(route="clarify", reason="vague"),
        answer=Answer(status="clarify", headline="Revenue or rentals?"),
    )
    assert score(CASES["vague_business_update"], None, run, catalog={}).passed


def test_summary_counts_passes_and_percentiles() -> None:
    result = QueryResult(columns=["revenue"], rows=[[10923.45]], truncated=False)
    good = record(
        route=RouteDecision(route="metric_lookup", reason=""), result=result, output_type="stat"
    )
    bad = record(status="error", latency_ms=9000)
    scored = [score(CASES["revenue_june"], [[10923.45]], r, catalog={}) for r in (good, bad)]
    summary = summarize(scored)
    assert (summary["passed"], summary["errors"], summary["answer_accuracy"]) == (1, 1, 0.5)
    assert summary["latency_p95_ms"] == 9000
