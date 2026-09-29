"""Deterministic sanity checks on a query result. They add warnings; they never hide a result."""

import sqlglot
from pydantic import BaseModel
from sqlglot import exp
from sqlglot.errors import ParseError

from ledgerlens.sql.executor import QueryResult

# Fact tables and their grain key. A sum over a fact is only right at that grain.
FACT_KEYS = {"payment": "payment_id", "rental": "rental_id"}


class ResultWarning(BaseModel):
    code: str
    message: str


class FanoutProbe(BaseModel):
    fact: str
    sql: str  # returns (joined_rows, fact_rows) for the original FROM/JOIN/WHERE


def result_warnings(result: QueryResult) -> list[ResultWarning]:
    if result.row_count == 0:
        return [
            _warn(
                "empty_result",
                "The query returned no rows; the date range may fall outside the data.",
            )
        ]
    warnings = []
    if result.truncated:
        warnings.append(_warn("truncated", f"Showing the first {result.row_count} rows only."))

    measures = result.measure_indexes()
    for i in measures:
        name, values = result.columns[i], [row[i] for row in result.rows]
        if any(v is None for v in values):
            warnings.append(
                _warn("null_values", f"{name} is empty for some rows (no matching data).")
            )
        if any(v is not None and v < 0 for v in values):
            warnings.append(_warn("negative_values", f"{name} has negative values."))

    labels = [i for i in range(len(result.columns)) if i not in measures]
    if labels and measures:
        keys = [tuple(row[i] for i in labels) for row in result.rows]
        if len(keys) != len(set(keys)):
            warnings.append(
                _warn("duplicate_groups", "Some groups appear more than once; the grain is off.")
            )
    return warnings


def fanout_probe(sql: str) -> FanoutProbe | None:
    """For an aggregate over joins: a query comparing joined rows with distinct fact rows.

    If a join multiplies payments (or rentals), every sum over them is inflated. Returns None
    when the check does not apply (no joins, subqueries in FROM, nothing aggregated from a fact).
    """
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except ParseError:
        return None
    if not isinstance(tree, exp.Select) or not tree.args.get("joins"):
        return None
    sources = [tree.args["from_"].this] + [join.this for join in tree.args["joins"]]
    ctes = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    if not all(isinstance(s, exp.Table) and s.name not in ctes for s in sources):
        return None

    aliases = {s.alias_or_name: s.name for s in sources}
    fact = _aggregated_fact(tree, aliases)
    if fact is None:
        return None
    alias = next(a for a, table in aliases.items() if table == fact)

    probe = tree.copy()
    for arg in ("group", "having", "order", "limit", "offset", "distinct"):
        probe.set(arg, None)
    key = exp.column(FACT_KEYS[fact], table=alias)
    probe.set(
        "expressions",
        [
            exp.alias_(exp.Count(this=exp.Star()), "joined_rows"),
            exp.alias_(exp.Count(this=exp.Distinct(expressions=[key])), "fact_rows"),
        ],
    )
    return FanoutProbe(fact=fact, sql=probe.sql(dialect="postgres"))


def fanout_warning(probe: FanoutProbe, joined_rows: int, fact_rows: int) -> ResultWarning | None:
    if joined_rows <= fact_rows:
        return None
    ratio = joined_rows / fact_rows if fact_rows else float("inf")
    return _warn(
        "fanout",
        f"Join fan-out: {fact_rows:,} {probe.fact} rows became {joined_rows:,} joined rows "
        f"({ratio:.1f}x), so totals over {probe.fact} are inflated.",
    )


def _aggregated_fact(tree: exp.Select, aliases: dict[str, str]) -> str | None:
    """The fact table being summed or counted. COUNT(DISTINCT ...) is immune to fan-out."""
    for agg in tree.find_all(exp.AggFunc):
        if agg.find(exp.Distinct):
            continue
        for column in agg.find_all(exp.Column):
            if aliases.get(column.table) in FACT_KEYS:
                return aliases[column.table]
        if isinstance(agg, exp.Count) and agg.find(exp.Star):
            base = aliases.get(tree.args["from_"].this.alias_or_name)
            if base in FACT_KEYS:
                return base
    return None


def _warn(code: str, message: str) -> ResultWarning:
    return ResultWarning(code=code, message=message)


def query_limit(sql: str) -> int | None:
    """The literal LIMIT on the outer query, if any: tells the answer step a list is a top-N."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except ParseError:
        return None
    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) else None
    return int(value.this) if isinstance(value, exp.Literal) and value.is_int else None
