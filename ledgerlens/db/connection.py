"""Postgres connections for the agent.

The agent only ever connects as agent_ro. Read-only is guaranteed by the role's grants
(db/init/20_roles.sh); the session options here are a second layer, not the guarantee.
"""

import psycopg
from psycopg_pool import ConnectionPool

from ledgerlens.core.config import Settings


def _session_options(settings: Settings) -> str:
    return (
        f"-c default_transaction_read_only=on -c statement_timeout={settings.statement_timeout_ms}"
    )


def create_agent_pool(settings: Settings) -> ConnectionPool:
    """Returned closed: the app lifespan opens it, so importing never touches the network."""
    return ConnectionPool(
        conninfo=settings.agent_database_url,
        kwargs={"autocommit": True, "options": _session_options(settings)},
        min_size=1,
        max_size=5,
        open=False,
        name="agent_ro",
    )


def connect_agent(settings: Settings) -> psycopg.Connection:
    """A single agent_ro connection, for the CLI and scripts that don't need a pool."""
    return psycopg.connect(
        settings.agent_database_url,
        autocommit=True,
        connect_timeout=5,
        options=_session_options(settings),
    )


def connect_admin(settings: Settings) -> psycopg.Connection:
    """Owner connection. Only `ledgerlens seed` uses it, to write embeddings; never the agent."""
    return psycopg.connect(settings.admin_database_url, connect_timeout=5)
