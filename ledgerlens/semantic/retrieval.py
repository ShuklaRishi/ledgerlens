"""Find the metric definitions and tables relevant to a question (pgvector cosine search)."""

import psycopg
from pydantic import BaseModel

from ledgerlens.semantic.embedder import Embedder, to_vector_literal
from ledgerlens.semantic.layer import SemanticLayer

_SEARCH = """
    SELECT name, 1 - (embedding OPERATOR(semantic.<=>) %(v)s::semantic.vector) AS score
    FROM semantic.docs
    WHERE kind = %(kind)s
    ORDER BY embedding OPERATOR(semantic.<=>) %(v)s::semantic.vector
    LIMIT %(k)s
"""


class Hit(BaseModel):
    name: str
    score: float


class RetrievedContext(BaseModel):
    metrics: list[Hit]
    tables: list[Hit]
    metric_tables: list[str]  # tables the retrieved metrics' canonical SQL uses
    bridge_tables: list[str]  # added so every table above can be joined

    @property
    def metric_names(self) -> list[str]:
        return [h.name for h in self.metrics]

    @property
    def table_names(self) -> list[str]:
        names = [h.name for h in self.tables] + self.metric_tables + self.bridge_tables
        return list(dict.fromkeys(names))


def retrieve(
    conn: psycopg.Connection,
    embedder: Embedder,
    layer: SemanticLayer,
    question: str,
    k_metrics: int = 3,
    k_tables: int = 5,
    complete_join_paths: bool = True,
) -> RetrievedContext:
    """complete_join_paths adds the metrics' tables and the bridge tables needed to join
    everything retrieved; without it the model sees only the top-k tables."""
    vector = to_vector_literal(embedder.embed_query(question))
    metrics = _search(conn, vector, "metric", k_metrics)
    tables = _search(conn, vector, "table", k_tables)
    if not complete_join_paths:
        return RetrievedContext(metrics=metrics, tables=tables, metric_tables=[], bridge_tables=[])
    metric_tables = list(
        dict.fromkeys(
            t for h in metrics if h.name in layer.metrics for t in layer.metrics[h.name].tables
        )
    )
    wanted = [h.name for h in tables] + metric_tables
    return RetrievedContext(
        metrics=metrics,
        tables=tables,
        metric_tables=metric_tables,
        bridge_tables=layer.bridge_tables(wanted),
    )


def _search(conn: psycopg.Connection, vector: str, kind: str, k: int) -> list[Hit]:
    rows = conn.execute(_SEARCH, {"v": vector, "kind": kind, "k": k}).fetchall()
    return [Hit(name=name, score=round(float(score), 4)) for name, score in rows]
