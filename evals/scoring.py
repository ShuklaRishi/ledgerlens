"""Deterministic scoring of one agent run against a golden case. No model grades anything."""

import math
import statistics
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, computed_field

from evals.cases import DATA_ROUTES, GoldenCase
from ledgerlens.agent.llm import TRANSIENT_STATUS_CODES
from ledgerlens.schemas.run import RunRecord
from ledgerlens.sql.catalog import Catalog
from ledgerlens.sql.executor import is_number
from ledgerlens.sql.validator import validate_sql

# Matched against the saved error text: the retried status codes, plus timeouts.
_PROVIDER_ERRORS = (*map(str, TRANSIENT_STATUS_CODES), "DEADLINE_EXCEEDED", "Timeout")


class CaseResult(BaseModel):
    case_id: str
    question: str
    targets: str | None
    status: str  # answered / clarify / out_of_scope / failed / error
    expected_route: str
    actual_route: str | None
    route_ok: bool
    expected_output_type: list[str]
    actual_output_type: str
    output_type_ok: bool
    answer_ok: bool | None  # None when the case isn't answered with data
    answer_detail: str
    sql_safe: bool | None  # None when no SQL ran
    retries: int
    llm_calls: int
    tokens: int
    latency_ms: int
    run_id: str
    trace_url: str | None
    error: str | None = None  # why the run crashed, if it did

    @computed_field
    @property
    def provider_error(self) -> bool:
        """The model API failed (overload, rate limit, timeout): not the agent's fault."""
        return self.error is not None and any(code in self.error for code in _PROVIDER_ERRORS)

    @computed_field
    @property
    def passed(self) -> bool:
        return self.route_ok and self.output_type_ok and self.answer_ok is not False


def score(
    case: GoldenCase, expected: list[list[Any]] | None, record: RunRecord, catalog: Catalog
) -> CaseResult:
    actual_route = record.route.route if record.route else None
    actual_type = _output_type(record)
    answer_ok, detail = None, ""
    if case.answers_with_data:
        if record.result is None:
            reason = record.error or (record.answer.headline if record.answer else "no answer")
            answer_ok, detail = False, f"no result ({record.status}): {reason}"
        else:
            answer_ok, detail = rows_match(expected or [], record.result.rows, case.tolerance)
    return CaseResult(
        case_id=case.id,
        question=case.question,
        targets=case.targets,
        status=record.status,
        expected_route=case.expected_route,
        actual_route=actual_route,
        route_ok=route_matches(case.expected_route, actual_route),
        expected_output_type=case.expected_output_type,
        actual_output_type=actual_type,
        output_type_ok=actual_type in case.expected_output_type,
        answer_ok=answer_ok,
        answer_detail=detail,
        sql_safe=validate_sql(record.sql, catalog).ok if record.sql else None,
        retries=max(len({a.attempt for a in record.attempts}) - 1, 0),
        llm_calls=record.usage.llm_calls,
        tokens=record.usage.input_tokens + record.usage.output_tokens,
        latency_ms=record.latency_ms,
        run_id=record.run_id,
        trace_url=record.trace_url,
        error=record.error,
    )


def route_matches(expected: str, actual: str | None) -> bool:
    """Either data route is fine when data is expected: both go on to write SQL."""
    if expected in DATA_ROUTES:
        return actual in DATA_ROUTES
    return actual == expected


def rows_match(
    expected: list[list[Any]], actual: list[list[Any]], tolerance: float
) -> tuple[bool, str]:
    """Same number of rows, and every expected row's values appear in a distinct returned row.

    Order-insensitive, and tolerant of column names, column order and extra columns: the agent
    may call it total_revenue and add a store name, and still be right.
    """
    if len(actual) != len(expected):
        return False, f"expected {len(expected)} rows, got {len(actual)}"
    unused = list(actual)
    for row in expected:
        match = next(
            (a for a in unused if all(any(_same(e, v, tolerance) for v in a) for e in row)), None
        )
        if match is None:
            return False, f"no returned row matches {row}"
        unused.remove(match)
    return True, f"all {len(expected)} rows match"


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    data = [r for r in results if r.answer_ok is not None]
    with_sql = [r for r in results if r.sql_safe is not None]
    latencies = sorted(r.latency_ms for r in results)
    return {
        "cases": len(results),
        "passed": sum(r.passed for r in results),
        "answer_accuracy": _share(r.answer_ok for r in data),
        "route_accuracy": _share(r.route_ok for r in results),
        "output_type_accuracy": _share(r.output_type_ok for r in results),
        "sql_safety": _share(r.sql_safe for r in with_sql),
        "retries": sum(r.retries for r in results),
        "errors": sum(r.status == "error" for r in results),
        "provider_errors": sum(r.provider_error for r in results),
        "llm_calls": sum(r.llm_calls for r in results),
        "tokens": sum(r.tokens for r in results),
        "latency_p50_ms": round(statistics.median(latencies)) if latencies else 0,
        "latency_p95_ms": latencies[max(math.ceil(0.95 * len(latencies)) - 1, 0)]
        if latencies
        else 0,
    }


def by_target(results: list[CaseResult]) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = {}
    for result in results:
        group = groups.setdefault(result.targets or "baseline", {"cases": 0, "passed": 0})
        group["cases"] += 1
        group["passed"] += result.passed
    return groups


def report_sections(results: list[CaseResult]) -> dict[str, Any]:
    """Everything in a report but its meta; evals.run writes it, evals.rescore rewrites it."""
    return {
        "summary": summarize(results),
        "by_target": by_target(results),
        "results": [result.model_dump() for result in results],
    }


def _output_type(record: RunRecord) -> str:
    if record.status == "clarify":
        return "clarify"
    if record.status == "answered" and record.output_type:
        return record.output_type
    return "none"


def _same(expected: Any, actual: Any, tolerance: float) -> bool:
    if isinstance(expected, date) or isinstance(actual, date):
        return _day(expected) == _day(actual)
    if is_number(expected) and is_number(actual):
        if isinstance(expected, int) and isinstance(actual, int):
            return expected == actual  # counts must be exact
        close = [
            math.isclose(a, float(expected), rel_tol=tolerance, abs_tol=0.011)
            for a in (actual, actual / 100)
        ]
        return any(close)  # a rate may come back as a percentage
    return str(expected).strip().casefold() == str(actual).strip().casefold()


def _day(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _share(flags: Any) -> float | None:
    values = list(flags)
    return round(sum(values) / len(values), 3) if values else None
