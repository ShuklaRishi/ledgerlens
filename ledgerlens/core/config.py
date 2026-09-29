"""All configuration comes from here (environment, then .env). Nothing else reads os.environ."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_ignore_empty=True,  # `KEY=` in .env means "unset", not ""
        extra="ignore",  # .env also carries docker-compose variables
    )

    # Database. The agent only ever uses agent_database_url; admin is for `ledgerlens seed`.
    agent_database_url: str = "postgresql://agent_ro:agent_ro@localhost:5433/pagila"
    admin_database_url: str = "postgresql://postgres:postgres@localhost:5433/pagila"
    statement_timeout_ms: int = 15_000

    # LLM: Gemini free tier. gemini-3.1-flash-lite allows 15 requests/min and 500/day, and
    # answered in ~10 s where gemini-3.5-flash-lite took 25-80 s (measured Sep 2026).
    gemini_api_key: SecretStr | None = None
    llm_model: str = "gemini-3.1-flash-lite"
    llm_thinking_level: Literal["minimal", "low", "medium", "high"] = "low"
    llm_requests_per_minute: float = 12
    llm_timeout_seconds: float = 60  # fail a stuck call instead of hanging the request

    # Retrieval runs locally: no API calls, no quota
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    cache_dir: Path = PROJECT_ROOT / ".cache"

    # Agent
    agent_version: str = "v2"
    failure_mode: str = "none"
    max_sql_attempts: int = 3  # the first try plus two retries
    row_cap: int = 200

    # Tracing: OpenTelemetry spans in OpenInference conventions. No backend set = no-op.
    phoenix_url: str | None = None  # the local Arize Phoenix from docker-compose
    trace_project: str = "ledgerlens"
    neatlogs_api_key: SecretStr | None = None  # optional second exporter; untested (no account)

    log_level: str = "INFO"
    runs_dir: Path = PROJECT_ROOT / "runs"

    @property
    def tracing_backends(self) -> list[str]:
        backends = {"phoenix": self.phoenix_url, "neatlogs": self.neatlogs_api_key}
        return [name for name, configured in backends.items() if configured]


@lru_cache
def get_settings() -> Settings:
    return Settings()
