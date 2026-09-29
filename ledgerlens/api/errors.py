"""Domain exceptions -> HTTP responses, in one place. Every error body carries the run_id."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ledgerlens.services.agent_service import AgentRunError
from ledgerlens.services.run_store import RunNotFoundError


async def _run_not_found(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RunNotFoundError)
    return JSONResponse(status_code=404, content={"detail": str(exc), "run_id": exc.run_id})


async def _agent_failed(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AgentRunError)
    return JSONResponse(status_code=500, content={"detail": str(exc), "run_id": exc.run_id})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RunNotFoundError, _run_not_found)
    app.add_exception_handler(AgentRunError, _agent_failed)
