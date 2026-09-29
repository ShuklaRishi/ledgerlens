"""FastAPI app factory. Run with `uvicorn ledgerlens.main:app` (or `make api`)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ledgerlens import __version__
from ledgerlens.api.errors import register_exception_handlers
from ledgerlens.api.routes import ask, health, runs
from ledgerlens.core.config import get_settings
from ledgerlens.core.logging import setup_logging
from ledgerlens.core.tracing import setup_tracing, shutdown_tracing
from ledgerlens.db.connection import create_agent_pool
from ledgerlens.services.agent_service import AgentService
from ledgerlens.services.feedback_service import FeedbackService
from ledgerlens.services.run_store import RunStore

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    tracer_provider = setup_tracing(settings)  # once per process, before any request
    pool = create_agent_pool(settings)
    pool.open(wait=False)  # don't block startup on the DB; /health reports it
    store = RunStore(settings.runs_dir)
    app.state.agent_pool = pool
    app.state.run_store = store
    app.state.agent_service = AgentService(settings, pool, store)
    app.state.feedback_service = FeedbackService(settings, store)
    log.info(
        "ledgerlens %s up: model=%s agent_version=%s failure_mode=%s tracing=%s",
        __version__,
        settings.llm_model,
        settings.agent_version,
        settings.failure_mode,
        settings.tracing_backends or "off",
    )
    try:
        yield
    finally:
        app.state.feedback_service.close()
        pool.close()
        shutdown_tracing(tracer_provider)  # flush spans still buffered


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ledgerlens",
        version=__version__,
        summary="Ask business questions of the Pagila DVD-rental database.",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(ask.router)
    app.include_router(runs.router)
    return app


app = create_app()
