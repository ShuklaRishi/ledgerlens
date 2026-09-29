"""The golden set: questions, expected behaviour, and ground-truth SQL (evals/golden.yaml)."""

from pathlib import Path
from typing import Any, Literal

import psycopg
import yaml
from pydantic import BaseModel, field_validator, model_validator

from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.state import Route
from ledgerlens.schemas.ask import UserRole
from ledgerlens.sql.executor import run_query

GOLDEN = Path(__file__).parent / "golden.yaml"
DATA_ROUTES = ("metric_lookup", "custom_sql")
OutputType = Literal["stat", "line", "bar", "table", "clarify", "none"]


class GoldenCase(BaseModel):
    id: str
    question: str
    user_role: UserRole
    expected_route: Route
    expected_output_type: list[OutputType]  # one type, or several acceptable ones
    targets: FailureMode | None = None
    sql: str | None = None  # ground truth, for cases answered with data
    tolerance: float = 0.001  # relative tolerance for non-integer numbers

    @field_validator("expected_output_type", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value

    @model_validator(mode="after")
    def _data_cases_have_ground_truth(self) -> "GoldenCase":
        if self.answers_with_data != (self.sql is not None):
            raise ValueError(
                f"{self.id}: give ground-truth sql exactly when the route answers with data"
            )
        return self

    @property
    def answers_with_data(self) -> bool:
        return self.expected_route in DATA_ROUTES


def load_cases(only: list[str] | None = None) -> list[GoldenCase]:
    cases = [GoldenCase(**raw) for raw in yaml.safe_load(GOLDEN.read_text())["cases"]]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("golden case ids must be unique")
    if only:
        if unknown := set(only) - set(ids):
            raise ValueError(f"unknown case ids: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in only]
    return cases


def expected_rows(conn: psycopg.Connection, case: GoldenCase) -> list[list[Any]] | None:
    """Run the ground-truth SQL. Expected values always come from the data, never the YAML."""
    if case.sql is None:
        return None
    return run_query(conn, case.sql, row_cap=1000).rows
