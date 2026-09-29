from collections.abc import Iterator

import psycopg
import pytest

from ledgerlens.core.config import get_settings
from ledgerlens.db.connection import connect_agent


@pytest.fixture
def agent_conn() -> Iterator[psycopg.Connection]:
    try:
        conn = connect_agent(get_settings())
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable; run `make up`")
    with conn:
        yield conn
