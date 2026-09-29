from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Rating = Literal["up", "down"]


class FeedbackRequest(BaseModel):
    rating: Rating
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackRecord(BaseModel):
    """Saved as runs/<run_id>/feedback.json (latest wins) and returned by the API."""

    run_id: str
    rating: Rating
    comment: str | None
    created_at: datetime
    trace_id: str | None
    attached_to_trace: bool  # False when tracing is off or Phoenix was unreachable
    trace_url: str | None
