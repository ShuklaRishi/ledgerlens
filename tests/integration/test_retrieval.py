import psycopg
import pytest

from ledgerlens.core.config import get_settings
from ledgerlens.semantic.embedder import Embedder
from ledgerlens.semantic.layer import load_layer
from ledgerlens.semantic.retrieval import retrieve

pytestmark = pytest.mark.integration


def test_a_country_question_retrieves_the_metric_and_its_join_path(
    agent_conn: psycopg.Connection,
) -> None:
    if not agent_conn.execute("SELECT to_regclass('semantic.docs')").fetchone()[0]:
        pytest.skip("semantic layer not seeded; run `make seed`")
    settings = get_settings()
    embedder = Embedder(settings.embedding_model, settings.cache_dir)

    context = retrieve(
        agent_conn, embedder, load_layer(), "Which countries bring in the most revenue?"
    )

    assert "revenue_by_country" in context.metric_names
    assert {"payment", "customer", "address", "city", "country"} <= set(context.table_names)
