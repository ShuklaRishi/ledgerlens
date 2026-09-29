"""`ledgerlens seed`: embed the semantic layer and (re)write semantic.docs. Idempotent."""

from psycopg import sql

from ledgerlens.core.config import Settings
from ledgerlens.db.connection import connect_admin
from ledgerlens.semantic.embedder import Embedder, to_vector_literal
from ledgerlens.semantic.layer import SemanticLayer, load_layer


def build_documents(layer: SemanticLayer) -> list[tuple[str, str, str]]:
    """(kind, name, text to embed) for every metric and table."""
    docs = [
        ("metric", m.name, f"{m.label}. {m.description} Grain: {m.grain}. " + " ".join(m.gotchas))
        for m in layer.metrics.values()
    ]
    docs += [
        ("table", t.name, f"Table {t.name}: {t.description} Columns: " + ", ".join(t.columns))
        for t in layer.tables.values()
    ]
    return docs


def seed(settings: Settings, embedder: Embedder) -> int:
    docs = build_documents(load_layer())
    vectors = embedder.embed_documents([text for _, _, text in docs])
    create = sql.SQL(
        "CREATE TABLE semantic.docs ("
        " kind text NOT NULL, name text NOT NULL, content text NOT NULL,"
        " embedding semantic.vector({dim}) NOT NULL, PRIMARY KEY (kind, name))"
    ).format(dim=sql.Literal(len(vectors[0])))

    # Owner connection: agent_ro can read semantic.docs (default privileges), never write it.
    with connect_admin(settings) as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS semantic.docs")
        cur.execute(create)
        cur.executemany(
            "INSERT INTO semantic.docs VALUES (%s, %s, %s, %s::semantic.vector)",
            [
                (kind, name, text, to_vector_literal(v))
                for (kind, name, text), v in zip(docs, vectors, strict=True)
            ],
        )
    return len(docs)
