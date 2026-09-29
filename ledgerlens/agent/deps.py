"""Everything a node needs besides the state. Built once per process and shared by all runs."""

from dataclasses import dataclass
from functools import cached_property

from langchain_core.language_models import BaseChatModel
from psycopg_pool import ConnectionPool

from ledgerlens.agent.failure_modes import FailureMode, prompt_version
from ledgerlens.core.config import Settings
from ledgerlens.semantic.embedder import Embedder
from ledgerlens.semantic.layer import SemanticLayer
from ledgerlens.sql.catalog import Catalog, Coverage, load_catalog, load_coverage


@dataclass
class AgentDeps:
    settings: Settings
    pool: ConnectionPool
    llm: BaseChatModel
    embedder: Embedder
    layer: SemanticLayer
    failures: frozenset[FailureMode]  # empty for v2; see agent/failure_modes.py

    def prompt_version(self, prompt: str) -> str:
        return prompt_version(prompt, self.failures)

    @cached_property
    def catalog(self) -> Catalog:
        with self.pool.connection() as conn:
            return load_catalog(conn)

    @cached_property
    def coverage(self) -> Coverage:
        with self.pool.connection() as conn:
            return load_coverage(conn)
