"""POST /v1/ask request body."""

from pydantic import BaseModel, Field

from ledgerlens.agent.state import UserRole


class AskRequest(BaseModel):
    question: str = Field(
        min_length=3, max_length=500, examples=["What was revenue by store last month?"]
    )
    user_role: UserRole = "dev"
    session_id: str | None = Field(default=None, max_length=64)
