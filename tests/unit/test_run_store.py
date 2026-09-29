from datetime import UTC, datetime
from pathlib import Path

import pytest

from ledgerlens.agent.state import Answer
from ledgerlens.schemas.run import RunRecord, Usage
from ledgerlens.services.run_store import RunNotFoundError, RunStore


def test_a_saved_run_loads_back_unchanged(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    record = RunRecord(
        run_id=store.new_run_id(),
        created_at=datetime.now(UTC),
        question="How are we doing?",
        user_role="leadership",
        session_id=None,
        agent_version="v2",
        failure_mode="none",
        model="test",
        latency_ms=12,
        usage=Usage(llm_calls=1, input_tokens=10, output_tokens=5),
        status="clarify",
        answer=Answer(status="clarify", headline="Revenue or rentals, and over which period?"),
    )
    store.save(record)
    assert store.load(record.run_id) == record


@pytest.mark.parametrize("run_id", ["../../etc/passwd", "20260928T081530-a1b2c3/../x", "nope"])
def test_unknown_or_malformed_run_ids_are_not_found(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(RunNotFoundError):
        RunStore(tmp_path).load(run_id)
