"""A business user's 👍/👎 on an answer: saved with the run and attached to its trace.

The annotation lands on the run's root span in Phoenix, so a developer who opens the trace
sees the rating and comment next to the exact prompts, SQL and results that produced it.
"""

import logging
from datetime import UTC, datetime

import httpx

from ledgerlens.core.config import Settings
from ledgerlens.schemas.feedback import FeedbackRecord, FeedbackRequest
from ledgerlens.schemas.run import RunRecord
from ledgerlens.services.run_store import RunStore

log = logging.getLogger(__name__)

ANNOTATION_NAME = "user_feedback"


class FeedbackService:
    def __init__(
        self, settings: Settings, store: RunStore, client: httpx.Client | None = None
    ) -> None:
        self._settings = settings
        self._store = store
        self._client = client or httpx.Client(timeout=5)

    def submit(self, run_id: str, request: FeedbackRequest) -> FeedbackRecord:
        run = self._store.load(run_id)  # RunNotFoundError -> 404
        feedback = FeedbackRecord(
            run_id=run.run_id,
            rating=request.rating,
            comment=request.comment,
            created_at=datetime.now(UTC),
            trace_id=run.trace_id,
            attached_to_trace=self._annotate_trace(run, request),
            trace_url=run.trace_url,
        )
        self._store.save_feedback(feedback)  # kept even when the trace can't be annotated
        log.info(
            "feedback %s on run %s (trace attached: %s)",
            request.rating,
            run_id,
            feedback.attached_to_trace,
        )
        return feedback

    def close(self) -> None:
        self._client.close()

    def _annotate_trace(self, run: RunRecord, request: FeedbackRequest) -> bool:
        if not (self._settings.phoenix_url and run.span_id):
            return False
        up = request.rating == "up"
        annotation = {
            "span_id": run.span_id,  # the root "ask" span of the run's trace
            "name": ANNOTATION_NAME,
            "annotator_kind": "HUMAN",
            "result": {
                "label": "thumbs_up" if up else "thumbs_down",
                "score": 1.0 if up else 0.0,
                "explanation": request.comment,
            },
            "metadata": {
                "run_id": run.run_id,
                "user_role": run.user_role,
                "session_id": run.session_id,
            },
        }
        url = f"{self._settings.phoenix_url.rstrip('/')}/v1/span_annotations"
        try:
            self._client.post(url, json={"data": [annotation]}).raise_for_status()
        except httpx.HTTPError:  # feedback is still saved with the run; the trace just lacks it
            log.warning("could not attach feedback to trace %s", run.trace_id, exc_info=True)
            return False
        return True
