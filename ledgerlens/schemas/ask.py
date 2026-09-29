from typing import Literal

from pydantic import BaseModel, Field

UserRole = Literal["am", "sales", "leadership", "dev"]


class AskRequest(BaseModel):
    question: str = Field(
        min_length=3, max_length=500, examples=["What was revenue by store last month?"]
    )
    user_role: UserRole = "dev"
    session_id: str | None = Field(default=None, max_length=64)
