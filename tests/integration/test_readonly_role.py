import psycopg
import pytest

from ledgerlens.db.check import PROBES, probe_privileges

pytestmark = pytest.mark.integration


def test_agent_role_can_read(agent_conn: psycopg.Connection) -> None:
    assert agent_conn.execute("SELECT count(*) FROM payment").fetchone()[0] > 0


def test_writes_and_sensitive_reads_are_blocked_by_grants(agent_conn: psycopg.Connection) -> None:
    results = probe_privileges(agent_conn)

    assert [r.name for r in results] == list(PROBES)
    assert [f"{r.name}: {r.detail}" for r in results if not r.ok] == []
