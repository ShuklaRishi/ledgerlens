"""Local sentence embeddings (fastembed / ONNX). No API calls, so retrieval costs no LLM quota."""

from pathlib import Path

from fastembed import TextEmbedding


class Embedder:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir / "fastembed"))

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(texts)]


def to_vector_literal(vector: list[float]) -> str:
    """pgvector's text input format; cast with ::semantic.vector in SQL."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
