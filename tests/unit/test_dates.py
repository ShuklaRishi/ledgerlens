from datetime import date

import pytest

from ledgerlens.sql.dates import DateContext, pick_anchor_column, resolve_relative_dates

ANCHOR = date(2022, 7, 27)  # the latest payment in Pagila, a Wednesday


@pytest.mark.parametrize(
    ("question", "start", "end"),
    [
        ("revenue last month", date(2022, 6, 1), date(2022, 7, 1)),
        ("revenue in the last 30 days", date(2022, 6, 28), date(2022, 7, 28)),
        ("rentals this month", date(2022, 7, 1), date(2022, 7, 28)),
        ("payments last week", date(2022, 7, 18), date(2022, 7, 25)),
        ("revenue last quarter", date(2022, 4, 1), date(2022, 7, 1)),
        ("revenue over the last 3 months", date(2022, 4, 1), date(2022, 7, 1)),
        ("revenue year to date", date(2022, 1, 1), date(2022, 7, 28)),
    ],
)
def test_relative_phrases_resolve_against_the_data_anchor(
    question: str, start: date, end: date
) -> None:
    (resolved,) = resolve_relative_dates(question, ANCHOR)
    assert (resolved.start, resolved.end) == (start, end)


def test_absolute_dates_are_left_to_the_model() -> None:
    assert resolve_relative_dates("revenue by category in June 2022", ANCHOR) == []


def test_anchor_column_prefers_the_metric_then_the_wording() -> None:
    assert pick_anchor_column("anything", "rental.rental_date") == "rental.rental_date"
    assert pick_anchor_column("How many rentals last month?", None) == "rental.rental_date"
    assert pick_anchor_column("What was revenue last month?", None) == "payment.payment_date"


def test_context_states_the_exact_filter_and_the_anchor() -> None:
    context = DateContext(
        anchor_column="payment.payment_date",
        anchor=ANCHOR,
        coverage={"payment.payment_date": (date(2022, 1, 23), ANCHOR)},
        ranges=resolve_relative_dates("last month", ANCHOR),
    )
    assert (
        "payment.payment_date >= '2022-06-01' AND payment.payment_date < '2022-07-01'"
        in context.for_prompt()
    )
    assert (
        context.for_humans() == "last month = 1 Jun 2022 to 30 Jun 2022 (latest data: 27 Jul 2022)"
    )
