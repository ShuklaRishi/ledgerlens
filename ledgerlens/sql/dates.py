"""Resolve relative dates ("last month") against the data's latest date, not the machine clock.

Pagila's data ends in 2022, so "last month" relative to today would return nothing.
"""

import re
from collections.abc import Callable
from datetime import date, timedelta

from pydantic import BaseModel

DAY = timedelta(days=1)

_RENTAL_WORDS = re.compile(r"\b(rent\w*|return\w*|late|overdue|active customers?)\b", re.IGNORECASE)


class DateRange(BaseModel):
    phrase: str
    start: date
    end: date  # exclusive

    def sql_filter(self, column: str) -> str:
        return f"{column} >= '{self.start}' AND {column} < '{self.end}'"

    def human(self) -> str:
        return f"{self.phrase} = {_fmt(self.start)} to {_fmt(self.end - DAY)}"


class DateContext(BaseModel):
    anchor_column: str  # relative ranges filter on this column
    anchor: date
    anchor_source: str = "the latest date in the data"
    coverage: dict[str, tuple[date, date]]
    ranges: list[DateRange]

    def for_prompt(self) -> str:
        lines = [
            f"{column} covers {first} to {last}." for column, (first, last) in self.coverage.items()
        ]
        lines.append(f"Relative dates are anchored to {self.anchor} ({self.anchor_source}).")
        if not self.ranges:
            lines.append("The question contains no relative dates.")
        lines += [f'"{r.phrase}": {r.sql_filter(self.anchor_column)}' for r in self.ranges]
        return "\n".join(lines)

    def for_humans(self) -> str | None:
        if not self.ranges:
            return None
        return "; ".join(r.human() for r in self.ranges) + f" (latest data: {_fmt(self.anchor)})"


def pick_anchor_column(question: str, metric_time_column: str | None) -> str:
    if metric_time_column:
        return metric_time_column
    return "rental.rental_date" if _RENTAL_WORDS.search(question) else "payment.payment_date"


def resolve_relative_dates(question: str, anchor: date) -> list[DateRange]:
    ranges = []
    for pattern, span in _RULES:
        for match in re.finditer(pattern, question, flags=re.IGNORECASE):
            start, end = span(anchor, match)
            ranges.append(DateRange(phrase=match[0].lower(), start=start, end=end))
    return ranges


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _shift_months(d: date, months: int) -> date:
    """First day of the month `months` away from d's month."""
    index = d.year * 12 + d.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _week_start(d: date) -> date:
    return d - d.weekday() * DAY


def _fmt(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


_Span = Callable[[date, re.Match[str]], tuple[date, date]]

# Each rule maps a phrase to a half-open [start, end) range. "Last N months" means N full
# months before the anchor's month, the usual reporting convention.
_RULES: list[tuple[str, _Span]] = [
    (r"\btoday\b", lambda a, m: (a, a + DAY)),
    (r"\byesterday\b", lambda a, m: (a - DAY, a)),
    (r"\b(?:last|past|previous) (\d+) days?\b", lambda a, m: (a - (int(m[1]) - 1) * DAY, a + DAY)),
    (
        r"\b(?:last|past|previous) (\d+) weeks?\b",
        lambda a, m: (a - (7 * int(m[1]) - 1) * DAY, a + DAY),
    ),
    (
        r"\b(?:last|past|previous) (\d+) months?\b",
        lambda a, m: (_shift_months(a, -int(m[1])), _month_start(a)),
    ),
    (r"\bthis week\b", lambda a, m: (_week_start(a), a + DAY)),
    (r"\b(?:last|previous) week\b", lambda a, m: (_week_start(a) - 7 * DAY, _week_start(a))),
    (r"\b(?:this month|month to date|mtd)\b", lambda a, m: (_month_start(a), a + DAY)),
    (r"\b(?:last|previous) month\b", lambda a, m: (_shift_months(a, -1), _month_start(a))),
    (r"\bthis quarter\b", lambda a, m: (_quarter_start(a), a + DAY)),
    (
        r"\b(?:last|previous) quarter\b",
        lambda a, m: (_shift_months(_quarter_start(a), -3), _quarter_start(a)),
    ),
    (r"\b(?:this year|year to date|ytd)\b", lambda a, m: (date(a.year, 1, 1), a + DAY)),
    (r"\b(?:last|previous) year\b", lambda a, m: (date(a.year - 1, 1, 1), date(a.year, 1, 1))),
]
