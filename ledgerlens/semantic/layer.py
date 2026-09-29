"""The semantic layer: curated metric definitions and schema docs, loaded from YAML."""

from collections import deque
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

SEMANTIC_DIR = Path(__file__).parent


class Metric(BaseModel):
    name: str
    label: str
    description: str
    grain: str
    time_column: str | None
    tables: list[str]
    sql: str
    gotchas: list[str] = []

    def summary(self) -> str:
        return f"{self.name}: {self.label}. {self.description}"

    def describe(self) -> str:
        lines = [
            f"Metric {self.name} ({self.label}): {self.description}",
            f"Grain: {self.grain}. Time column: {self.time_column or 'none'}.",
            "Canonical SQL:",
            self.sql.strip(),
        ]
        lines += [f"Gotcha: {g}" for g in self.gotchas]
        return "\n".join(lines)


class Table(BaseModel):
    name: str
    description: str
    columns: dict[str, str]

    def describe(self) -> str:
        columns = ", ".join(f"{name} ({doc})" for name, doc in self.columns.items())
        return f"{self.name}: {self.description}\n  columns: {columns}"


class Join(BaseModel):
    many: str  # "payment.rental_id"
    one: str  # "rental.rental_id"

    @property
    def tables(self) -> tuple[str, str]:
        return self.many.split(".")[0], self.one.split(".")[0]


class SemanticLayer(BaseModel):
    metrics: dict[str, Metric]
    tables: dict[str, Table]
    joins: list[Join]

    def describe_metrics(self, names: list[str]) -> str:
        found = [self.metrics[n].describe() for n in names if n in self.metrics]
        return "\n\n".join(found) or "No defined metric applies."

    def describe_tables(self, names: list[str]) -> str:
        wanted = [n for n in names if n in self.tables]
        joins = [j for j in self.joins if set(j.tables) <= set(wanted)]
        lines = [self.tables[n].describe() for n in wanted]
        if joins:
            lines.append("Joins (each left row matches at most one right row):")
            lines += [f"  {j.many} = {j.one}" for j in joins]
        return "\n".join(lines)

    def bridge_tables(self, wanted: list[str]) -> list[str]:
        """Tables needed to join the wanted tables together (shortest paths in the join graph)."""
        known = [t for t in dict.fromkeys(wanted) if t in self.tables]
        if len(known) < 2:
            return []
        neighbours: dict[str, set[str]] = {t: set() for t in self.tables}
        for join in self.joins:
            a, b = join.tables
            neighbours[a].add(b)
            neighbours[b].add(a)

        connected, bridges = {known[0]}, set()
        for target in known[1:]:
            path = _shortest_path(neighbours, connected, target)
            connected |= set(path)
            bridges |= set(path) - set(known)
        return sorted(bridges)


def _shortest_path(neighbours: dict[str, set[str]], sources: set[str], target: str) -> list[str]:
    previous: dict[str, str | None] = dict.fromkeys(sources)
    queue = deque(sources)
    while queue:
        node = queue.popleft()
        if node == target:
            path = []
            while node is not None:
                path.append(node)
                node = previous[node]
            return path
        for nxt in sorted(neighbours[node]):
            if nxt not in previous:
                previous[nxt] = node
                queue.append(nxt)
    return []


@lru_cache
def load_layer() -> SemanticLayer:
    metrics = yaml.safe_load((SEMANTIC_DIR / "metrics.yaml").read_text())["metrics"]
    schema = yaml.safe_load((SEMANTIC_DIR / "schema.yaml").read_text())
    return SemanticLayer(
        metrics={m["name"]: Metric(**m) for m in metrics},
        tables={name: Table(name=name, **t) for name, t in schema["tables"].items()},
        joins=[Join(many=m, one=o) for m, o in (j.split(" -> ") for j in schema["joins"])],
    )
