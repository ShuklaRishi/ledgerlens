"""Feedback is always saved with the run, and attached to its trace when Phoenix is there."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ledgerlens.api.deps import get_feedback_service
from ledgerlens.core.config import Settings
from ledgerlens.main import create_app
from ledgerlens.schemas.feedback import FeedbackRequest
from ledgerlens.schemas.run import RunRecord, Usage
from ledgerlens.services.feedback_service import FeedbackService
from ledgerlens.services.run_store import RunNotFoundError, RunStore

RUN_ID = "20260928T120000-abcdef"


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    store = RunStore(tmp_path)
    store.save(
        RunRecord(
            run_id=RUN_ID,
            trace_id="a" * 32,
            span_id="b" * 16,
            created_at=datetime.now(UTC),
            question="What was revenue last month?",
            user_role="leadership",
            session_id="s1",
            agent_version="v1",
            failure_mode="all",
            model="test",
            latency_ms=1,
            usage=Usage(llm_calls=3, input_tokens=1, output_tokens=1),
            status="answered",
        )
    )
    return store


def service(
    store: RunStore, handler: httpx.MockTransport | None, phoenix: str | None
) -> FeedbackService:
    client = httpx.Client(transport=handler) if handler else None
    return FeedbackService(Settings(phoenix_url=phoenix), store, client)


def test_thumbs_down_is_attached_to_the_root_span_and_saved(
    store: RunStore, tmp_path: Path
) -> None:
    sent: list[httpx.Request] = []

    def phoenix(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"data": [{"id": "1"}]})

    feedback = service(store, httpx.MockTransport(phoenix), "http://phoenix:6006").submit(
        RUN_ID, FeedbackRequest(rating="down", comment="Says no revenue; June had $10,923")
    )

    assert feedback.attached_to_trace
    (request,) = sent
    assert str(request.url) == "http://phoenix:6006/v1/span_annotations"
    (annotation,) = json.loads(request.content)["data"]
    assert annotation["span_id"] == "b" * 16
    assert annotation["annotator_kind"] == "HUMAN"
    assert annotation["result"] == {
        "label": "thumbs_down",
        "score": 0.0,
        "explanation": "Says no revenue; June had $10,923",
    }
    saved = json.loads((tmp_path / RUN_ID / "feedback.json").read_text())
    assert (saved["rating"], saved["attached_to_trace"]) == ("down", True)


def test_feedback_is_kept_when_phoenix_is_down(store: RunStore, tmp_path: Path) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    svc = service(store, httpx.MockTransport(unreachable), "http://phoenix:6006")
    feedback = svc.submit(RUN_ID, FeedbackRequest(rating="up"))

    assert not feedback.attached_to_trace
    assert (tmp_path / RUN_ID / "feedback.json").is_file()


def test_without_tracing_feedback_is_only_saved(store: RunStore) -> None:
    feedback = service(store, None, None).submit(RUN_ID, FeedbackRequest(rating="up"))
    assert not feedback.attached_to_trace


def test_feedback_on_an_unknown_run_is_rejected(store: RunStore) -> None:
    with pytest.raises(RunNotFoundError):
        service(store, None, None).submit("20260928T120000-ffffff", FeedbackRequest(rating="up"))


def test_the_api_route_returns_the_saved_feedback_and_404s_unknown_runs(store: RunStore) -> None:
    app = create_app()
    app.dependency_overrides[get_feedback_service] = lambda: service(store, None, None)
    client = TestClient(app)

    ok = client.post(
        f"/v1/runs/{RUN_ID}/feedback", json={"rating": "down", "comment": "wrong month"}
    )
    missing = client.post("/v1/runs/20260928T120000-ffffff/feedback", json={"rating": "up"})

    assert ok.status_code == 200
    assert (ok.json()["rating"], ok.json()["comment"]) == ("down", "wrong month")
    assert missing.status_code == 404
