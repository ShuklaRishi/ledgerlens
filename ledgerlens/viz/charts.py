"""Pick the output type from the shape of the result, and draw charts in one house style.

The choice is deterministic on purpose: whether a trend gets a chart is not up to the model.
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")  # charts are files, never windows

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.ticker import FuncFormatter

from ledgerlens.sql.executor import QueryResult, is_number

OutputType = Literal["stat", "line", "bar", "table"]

MAX_BARS = 25
MAX_SERIES = 6
INK, MUTED, GRID = "#1f2933", "#616e7c", "#e4e7eb"
PALETTE = ["#2f6fdf", "#e8833a", "#3aa76d", "#c94a4a", "#8e6bd6", "#6b7a8f"]
_MONEY_WORDS = ("revenue", "amount", "value", "sales", "payment", "spend", "cost", "price")
_RATE_SUFFIXES = ("_rate", "_share", "_pct", "_ratio")


def choose_output_type(result: QueryResult) -> OutputType:
    measures, temporal, labels = _shape(result)
    if result.row_count == 1 and len(measures) == 1 and len(labels) + len(temporal) <= 1:
        return "stat"
    if len(temporal) == 1 and len(measures) == 1 and len(labels) <= 1 and result.row_count >= 2:
        series = {row[labels[0]] for row in result.rows} if labels else {None}
        return "line" if len(series) <= MAX_SERIES else "table"
    if (
        len(labels) == 1
        and len(measures) == 1
        and not temporal
        and 2 <= result.row_count <= MAX_BARS
    ):
        return "bar"
    return "table"


def _shape(result: QueryResult) -> tuple[list[int], list[int], list[int]]:
    """Measure columns, the time axis, and label columns.

    A date that never changes (the month of a one-month answer) is a constant, not a time
    axis, and is left out: "rentals per store last month" is a bar chart, not two one-point
    lines, whether or not the query kept its month column.
    """
    measures, dates = result.measure_indexes(), result.temporal_indexes()
    axis = [i for i in dates if len({row[i] for row in result.rows}) > 1]
    labels = [i for i in range(len(result.columns)) if i not in measures and i not in dates]
    return measures, axis, labels


def render_chart(result: QueryResult, output_type: OutputType, title: str, path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    try:
        _style(ax, title)
        if output_type == "bar":
            _draw_bar(ax, result)
        elif output_type == "line":
            _draw_line(ax, result)
        else:
            raise ValueError(f"no chart for output type {output_type!r}")
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, facecolor="white")
    finally:
        plt.close(fig)
    return path


def format_table(result: QueryResult, limit: int = 20) -> str:
    """The first rows as a plain-text table, for prompts and the CLI."""
    lines = [" | ".join(result.columns)]
    for row in result.rows[:limit]:
        lines.append(
            " | ".join(format_value(c, v) for c, v in zip(result.columns, row, strict=True))
        )
    return "\n".join(lines)


def format_value(column: str, value: Any) -> str:
    """How a value in this column should read in an answer or on a chart."""
    if value is None:
        return "n/a"
    if isinstance(value, datetime):
        return (
            f"{value:%Y-%m-%d}"
            if (value.hour, value.minute) == (0, 0)
            else f"{value:%Y-%m-%d %H:%M}"
        )
    if isinstance(value, date):
        return value.isoformat()
    if column.endswith("_id") or not is_number(value):
        return str(value)
    name = column.lower()
    if name.endswith(_RATE_SUFFIXES) and name != "rental_rate" and abs(value) <= 1:
        return f"{value:.1%}"
    whole = float(value).is_integer()
    if any(word in name for word in _MONEY_WORDS) or name == "rental_rate":
        return f"${value:,.0f}" if whole or abs(value) >= 1000 else f"${value:,.2f}"
    return f"{value:,.0f}" if whole or abs(value) >= 100 else f"{value:,.2f}"


def label_value(column: str, value: Any) -> str:
    """Category labels: identifiers read better with their noun ("Store 2", not "2")."""
    if column.endswith("_id"):
        return f"{column[:-3].replace('_', ' ').title()} {value}"
    return str(value)


def pretty(column: str) -> str:
    return column.replace("_", " ").capitalize()


def _style(ax: Axes, title: str) -> None:
    ax.set_title(
        title if len(title) <= 80 else title[:77] + "...",
        loc="left",
        fontsize=12,
        color=INK,
        pad=12,
    )
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#cbd2d9")
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _draw_bar(ax: Axes, result: QueryResult) -> None:
    measures, _, labels = _shape(result)
    (m,), (label,) = measures, labels
    measure = result.columns[m]
    names = [label_value(result.columns[label], row[label]) for row in result.rows]
    values = [row[m] or 0 for row in result.rows]
    ticks = FuncFormatter(lambda v, _: format_value(measure, v))

    if len(names) > 8:  # long category lists read better as horizontal bars, largest on top
        bars = ax.barh(names[::-1], values[::-1], color=PALETTE[0])
        ax.xaxis.set_major_formatter(ticks)
        ax.grid(axis="y", visible=False)
        ax.bar_label(
            bars,
            labels=[format_value(measure, v) for v in values[::-1]],
            padding=3,
            fontsize=8,
            color=INK,
        )
        ax.set_xlabel(pretty(measure), color=MUTED)
    else:
        bars = ax.bar(names, values, color=PALETTE[0], width=0.6)
        ax.yaxis.set_major_formatter(ticks)
        ax.grid(axis="x", visible=False)
        ax.bar_label(
            bars,
            labels=[format_value(measure, v) for v in values],
            padding=3,
            fontsize=9,
            color=INK,
        )
        ax.set_ylabel(pretty(measure), color=MUTED)


def _draw_line(ax: Axes, result: QueryResult) -> None:
    measures, axis, labels = _shape(result)
    (m,), (t,) = measures, axis
    measure = result.columns[m]

    series: dict[str, list[tuple[Any, Any]]] = {}
    for row in result.rows:
        name = label_value(result.columns[labels[0]], row[labels[0]]) if labels else measure
        series.setdefault(name, []).append((row[t], row[m]))

    for colour, (name, points) in zip(PALETTE, series.items(), strict=False):
        xs, ys = zip(*sorted(points, key=lambda p: p[0]), strict=True)
        ax.plot(xs, ys, marker="o", markersize=4, linewidth=2, color=colour, label=name)
        if len(series) == 1 and len(xs) <= 12:
            for x, y in zip(xs, ys, strict=True):
                label = format_value(measure, y)
                ax.annotate(label, (x, y), textcoords="offset points", xytext=(0, 7), ha="center",
                            fontsize=8, color=INK)  # fmt: skip

    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: format_value(measure, v)))
    ax.set_ylabel(pretty(measure), color=MUTED)
    ax.grid(axis="x", visible=False)
    if all(isinstance(x, datetime) and x.day == 1 for x, _ in next(iter(series.values()))):
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=9)
