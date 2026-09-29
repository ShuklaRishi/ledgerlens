"""FastAPI dependencies. Routes get what they need from here, never from module globals."""

from typing import Annotated

from fastapi import Depends, Request
from psycopg_pool import ConnectionPool

from ledgerlens.core.config import Settings, get_settings
from ledgerlens.services.agent_service import AgentService
from ledgerlens.services.feedback_service import FeedbackService
from ledgerlens.services.run_store import RunStore


def get_agent_pool(request: Request) -> ConnectionPool:
    return request.app.state.agent_pool


def get_agent_service(request: Request) -> AgentService:
    return request.app.state.agent_service


def get_run_store(request: Request) -> RunStore:
    return request.app.state.run_store


def get_feedback_service(request: Request) -> FeedbackService:
    return request.app.state.feedback_service


SettingsDep = Annotated[Settings, Depends(get_settings)]
AgentPoolDep = Annotated[ConnectionPool, Depends(get_agent_pool)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
RunStoreDep = Annotated[RunStore, Depends(get_run_store)]
FeedbackServiceDep = Annotated[FeedbackService, Depends(get_feedback_service)]
