"""Find the metric definitions and tables relevant to the question (pgvector, local embeddings)."""

from typing import Any

from ledgerlens.agent.deps import AgentDeps
from ledgerlens.agent.failure_modes import FailureMode
from ledgerlens.agent.state import AgentState
from ledgerlens.semantic.retrieval import retrieve


def run(state: AgentState, deps: AgentDeps) -> dict[str, Any]:
    # v1 passed the model only the top 3 tables, without the tables needed to join them
    truncated = FailureMode.HALLUCINATED_COLUMN in deps.failures
    with deps.pool.connection() as conn:
        context = retrieve(
            conn,
            deps.embedder,
            deps.layer,
            state["question"],
            k_tables=3 if truncated else 5,
            complete_join_paths=not truncated,
        )
    return {"context": context}
