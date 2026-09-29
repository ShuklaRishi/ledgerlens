from fastapi import APIRouter

from ledgerlens.api.deps import AgentServiceDep
from ledgerlens.schemas.ask import AskRequest
from ledgerlens.schemas.run import RunRecord

router = APIRouter(prefix="/v1", tags=["agent"])


@router.post("/ask", response_model=RunRecord)
def ask(request: AskRequest, service: AgentServiceDep) -> RunRecord:
    """Answer a business question. Blocking; three model calls, typically a few seconds."""
    return service.ask(request)
