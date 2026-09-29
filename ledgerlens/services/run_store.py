"""Every run is saved as runs/<run_id>/run.json (plus chart.png), so any answer can be debugged
after the fact, with or without a tracing backend."""

import re
import secrets
from datetime import UTC, datetime
from pathlib import Path

from ledgerlens.schemas.feedback import FeedbackRecord
from ledgerlens.schemas.run import RunRecord

_RUN_ID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")


class RunNotFoundError(LookupError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id!r} not found")
        self.run_id = run_id


class RunStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def new_run_id() -> str:
        """Sortable by time, safe in paths and URLs."""
        return f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"

    def chart_file(self, run_id: str) -> Path:
        return self._dir(run_id) / "chart.png"

    def save(self, record: RunRecord) -> Path:
        path = self._dir(record.run_id) / "run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2))
        return path

    def load(self, run_id: str) -> RunRecord:
        path = self._dir(run_id) / "run.json"
        if not path.is_file():
            raise RunNotFoundError(run_id)
        return RunRecord.model_validate_json(path.read_text())

    def save_feedback(self, feedback: FeedbackRecord) -> Path:
        path = self._dir(feedback.run_id) / "feedback.json"
        path.write_text(feedback.model_dump_json(indent=2))
        return path

    def chart(self, run_id: str) -> Path:
        path = self.chart_file(run_id)
        if not path.is_file():
            raise RunNotFoundError(run_id)
        return path

    def _dir(self, run_id: str) -> Path:
        if not _RUN_ID.match(run_id):  # also rules out path traversal from the URL
            raise RunNotFoundError(run_id)
        return self._root / run_id
