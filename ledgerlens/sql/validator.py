"""Deterministic checks on generated SQL, before it reaches the database.

Errors are phrased for the model: they are fed back to plan_sql on a retry.
"""

import logging
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from ledgerlens.sql.catalog import Catalog

log = logging.getLogger(__name__)

_WRITES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Command, exp.Into, exp.Copy, exp.Grant, exp.Set,
)  # fmt: skip
_BLOCKED_FUNCTIONS = (
    "pg_sleep",
    "pg_read",
    "pg_ls_",
    "pg_terminate",
    "pg_cancel",
    "set_config",
    "lo_",
    "dblink",
)


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_sql(
    sql: str, catalog: Catalog, check_columns: bool = True, check_joins: bool = True
) -> ValidationResult:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        return ValidationResult([f"SQL does not parse: {str(exc).splitlines()[0][:200]}"])
    if len(statements) != 1:
        return ValidationResult([f"Expected exactly one statement, got {len(statements)}."])
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        return ValidationResult([f"Only SELECT queries are allowed, got {tree.key.upper()}."])
    writes = sorted({node.key.upper() for node in tree.find_all(*_WRITES)})
    if writes:
        return ValidationResult([f"Read-only: {', '.join(writes)} is not allowed."])

    errors = _check_functions(tree)
    if check_joins:
        errors += _check_joins(tree)
    table_errors = _check_tables(tree, catalog)
    errors += table_errors
    if check_columns and not table_errors:  # resolving columns needs every table to exist
        errors += _check_columns(tree, catalog)
    if not _is_bounded(tree):
        errors.append("Unbounded result: add a LIMIT (at most 100) or aggregate the rows.")
    return ValidationResult(errors)


def _check_joins(tree: exp.Expression) -> list[str]:
    """A join condition comparing a column with itself matches every row: a cross join."""
    errors = []
    for join in tree.find_all(exp.Join):
        condition = join.args.get("on")
        for eq in condition.find_all(exp.EQ) if condition else []:
            if isinstance(eq.left, exp.Column) and eq.left == eq.right:
                errors.append(
                    f"Join condition {eq.sql(dialect='postgres')} compares a column with itself, "
                    "so every row matches. Join on the key of the other table."
                )
    return errors


def _check_functions(tree: exp.Expression) -> list[str]:
    names = {f.name.lower() for f in tree.find_all(exp.Anonymous)}
    return [
        f"Function {n}() is not allowed." for n in sorted(names) if n.startswith(_BLOCKED_FUNCTIONS)
    ]


def _check_tables(tree: exp.Expression, catalog: Catalog) -> list[str]:
    ctes = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    errors = set()
    for table in tree.find_all(exp.Table):
        if not table.name or (table.name in ctes and not table.db):
            continue
        if table.db and table.db != "public":
            errors.add(f"Schema {table.db!r} is not allowed; use public tables only.")
        elif table.name not in catalog:
            errors.add(f"Unknown table {table.name!r}.")
    return sorted(errors)


def _check_columns(tree: exp.Expression, catalog: Catalog) -> list[str]:
    schema = {"public": {t: dict.fromkeys(cols, "TEXT") for t, cols in catalog.items()}}
    try:
        qualify(
            tree.copy(),
            schema=schema,
            db="public",
            dialect="postgres",
            validate_qualify_columns=True,
            quote_identifiers=False,
        )
    except OptimizeError as exc:
        return [f"{exc}. Use only columns listed in the schema."]
    except Exception:  # sqlglot can't analyse every construct; EXPLAIN is still the backstop
        log.debug("column check skipped", exc_info=True)
    return []


def _is_bounded(tree: exp.Query) -> bool:
    """LIMITed, aggregated, or reading only from aggregated CTEs / subqueries."""
    if tree.args.get("limit"):
        return True
    if not isinstance(tree, exp.Select):
        return False
    if tree.args.get("group") or any(
        agg.find_ancestor(exp.Window) is None
        for projection in tree.expressions
        for agg in projection.find_all(exp.AggFunc)
    ):
        return True
    # e.g. revenue and rentals aggregated in separate CTEs, then joined (the two-fact pattern)
    ctes = {cte.alias_or_name: cte.this for cte in tree.find_all(exp.CTE)}
    from_ = tree.args.get("from_")
    sources = ([from_.this] if from_ else []) + [join.this for join in tree.args.get("joins") or []]
    return bool(sources) and all(_source_is_bounded(source, ctes) for source in sources)


def _source_is_bounded(source: exp.Expression, ctes: dict[str, exp.Expression]) -> bool:
    if isinstance(source, exp.Table) and not source.db and source.name in ctes:
        return _is_bounded(ctes[source.name])
    if isinstance(source, exp.Subquery):
        return _is_bounded(source.this)
    return False
