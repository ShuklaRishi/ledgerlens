from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ledgerlens.sql.executor import QueryResult
from ledgerlens.viz.charts import OutputType, choose_output_type, format_value, render_chart


def result(columns: list[str], rows: list[list[Any]]) -> QueryResult:
    return QueryResult(columns=columns, rows=rows, truncated=False)


MONTHLY = result(
    ["month", "revenue"], [[datetime(2022, m, 1, tzinfo=UTC), 1000.0 * m] for m in range(1, 7)]
)
BY_STORE_MONTH = result(
    ["month", "store_id", "rentals"],
    [[datetime(2022, m, 1, tzinfo=UTC), s, 10 * m + s] for m in (5, 6, 7) for s in (1, 2)],
)
BY_CATEGORY = result(["category", "revenue"], [["Sports", 5.0], ["Drama", 4.0], ["Action", 3.0]])


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (result(["revenue"], [[10923.45]]), "stat"),
        (result(["store_id", "revenue"], [[2, 100.0]]), "stat"),
        (MONTHLY, "line"),
        (BY_STORE_MONTH, "line"),
        (BY_CATEGORY, "bar"),
        (result(["store_id", "revenue"], [[1, 5.0], [2, 4.0]]), "bar"),
        (result(["store_id", "copies", "titles"], [[1, 2270, 759], [2, 2311, 762]]), "table"),
        (result(["revenue"], []), "table"),
    ],
    ids=[
        "single-number",
        "single-row",
        "time-series",
        "multi-series",
        "categories",
        "id-labels",
        "wide",
        "empty",
    ],
)
def test_output_type_follows_the_shape_of_the_data(data: QueryResult, expected: OutputType) -> None:
    assert choose_output_type(data) == expected


@pytest.mark.parametrize(
    ("output_type", "data"), [("bar", BY_CATEGORY), ("line", MONTHLY), ("line", BY_STORE_MONTH)]
)
def test_render_writes_a_png(tmp_path: Path, output_type: OutputType, data: QueryResult) -> None:
    path = render_chart(data, output_type, "A chart", tmp_path / "chart.png")
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize(
    ("column", "value", "text"),
    [
        ("revenue", 10923.45, "$10,923"),
        ("avg_payment", 4.2, "$4.20"),
        ("late_return_rate", 0.184, "18.4%"),
        ("rental_rate", 2.99, "$2.99"),
        ("rentals", 2311, "2,311"),
        ("store_id", 2, "2"),
        ("revenue", None, "n/a"),
    ],
)
def test_values_are_formatted_for_people(column: str, value: Any, text: str) -> None:
    assert format_value(column, value) == text


def test_a_single_dated_row_is_a_stat() -> None:
    # "revenue last month" grouped by month: one row, one date, one number
    data = result(["month", "revenue"], [[datetime(2022, 6, 1, tzinfo=UTC), 10923.45]])
    assert choose_output_type(data) == "stat"


def test_a_constant_date_column_is_not_a_time_axis(tmp_path: Path) -> None:
    # "rentals per store last month" with the month kept in the query (second v2 eval run)
    july = datetime(2022, 7, 1, tzinfo=UTC)
    data = result(["month", "store_id", "rentals"], [[july, 1, 3352], [july, 2, 3387]])
    assert choose_output_type(data) == "bar"
    assert render_chart(data, "bar", "Rentals per store", tmp_path / "c.png").is_file()
