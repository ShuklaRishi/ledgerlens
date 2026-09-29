from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from fastapi.testclient import TestClient

from ledgerlens.api.deps import get_agent_pool
from ledgerlens.main import create_app
from ledgerlens.schemas.health import CheckResult, HealthReport


class _UnreachablePool:
    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[psycopg.Connection]:
        raise psycopg.OperationalError("connection refused")
        yield  # pragma: no cover


def test_health_is_503_when_database_is_unreachable() -> None:
    app = create_app()
    app.dependency_overrides[get_agent_pool] = _UnreachablePool

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert body["checks"][0] == {
        "name": "database",
        "ok": False,
        "critical": True,
        "detail": "connection refused",
    }


def test_non_critical_failure_is_degraded_not_down() -> None:
    report = HealthReport.from_checks(
        [
            CheckResult(name="database", ok=True, critical=True, detail=""),
            CheckResult(name="semantic_layer", ok=False, critical=False, detail=""),
        ]
    )
    assert report.status == "degraded"
