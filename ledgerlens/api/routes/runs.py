from fastapi import APIRouter
from fastapi.responses import FileResponse

from ledgerlens.api.deps import FeedbackServiceDep, RunStoreDep
from ledgerlens.schemas.feedback import FeedbackRecord, FeedbackRequest
from ledgerlens.schemas.run import RunRecord

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunRecord)
def get_run(run_id: str, store: RunStoreDep) -> RunRecord:
    return store.load(run_id)


@router.get("/{run_id}/chart.png", response_class=FileResponse)
def get_chart(run_id: str, store: RunStoreDep) -> FileResponse:
    return FileResponse(store.chart(run_id), media_type="image/png")


@router.post("/{run_id}/feedback", response_model=FeedbackRecord)
def submit_feedback(
    run_id: str, request: FeedbackRequest, service: FeedbackServiceDep
) -> FeedbackRecord:
    """A business user's 👍/👎 on an answer: saved with the run and attached to its trace."""
    return service.submit(run_id, request)
