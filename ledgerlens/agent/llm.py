"""The one place a chat model is built, and per-run accounting of calls and tokens."""

import logging
from typing import Any, TypeVar

import httpx
from google.genai import errors as genai_errors
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import LLMResult
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from ledgerlens.agent.tracing import llm_span, record_llm_response
from ledgerlens.core.config import Settings

T = TypeVar("T", bound=BaseModel)

# google-genai warns about "automatic function calling" on every structured call.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)


class MissingApiKeyError(RuntimeError):
    pass


def build_chat_model(settings: Settings) -> BaseChatModel:
    if settings.gemini_api_key is None:
        raise MissingApiKeyError("GEMINI_API_KEY is not set; see .env.example")
    # The limiter keeps us under the free tier's requests-per-minute cap; one per process.
    limiter = InMemoryRateLimiter(
        requests_per_second=settings.llm_requests_per_minute / 60,
        check_every_n_seconds=0.1,
        max_bucket_size=1,
    )
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        api_key=settings.gemini_api_key,
        thinking_level=settings.llm_thinking_level,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,  # the graph's RetryPolicy owns backoff (see graph.py)
        rate_limiter=limiter,
    )


def daily_quota_exhausted(error: object) -> bool:
    """The free tier's requests-per-day cap is spent; it resets at midnight Pacific."""
    return "PerDay" in str(error)  # Google's quotaId, e.g. GenerateRequestsPerDay...FreeTier


TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def is_transient(exc: Exception) -> bool:
    """Provider hiccups worth retrying: overload, per-minute limits, timeouts.

    Never bad requests, and never an exhausted daily quota: every retry is a request against
    that same daily cap and cannot succeed before it resets.
    """
    for error in (exc, exc.__cause__):
        if daily_quota_exhausted(error):
            return False
        if isinstance(error, genai_errors.APIError) and error.code in TRANSIENT_STATUS_CODES:
            return True
        if isinstance(error, httpx.TimeoutException):
            return True
    return False


def ask_structured(llm: BaseChatModel, schema: type[T], prompt: str) -> T:
    """One structured model call, traced as an LLM span (prompt, raw response, tokens)."""
    with llm_span(getattr(llm, "model", type(llm).__name__), schema.__name__, prompt) as span:
        out = llm.with_structured_output(schema, include_raw=True).invoke(prompt)
        record_llm_response(span, out["raw"])
        if out["parsed"] is None:
            cause = out["parsing_error"]
            raise ValueError(f"model output did not match {schema.__name__}") from cause
        return out["parsed"]


class UsageTracker(BaseCallbackHandler):
    """Counts model calls and tokens for one run. Passed as a callback to graph.invoke."""

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self.calls += 1
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                self.input_tokens += usage.get("input_tokens", 0)
                self.output_tokens += usage.get("output_tokens", 0)
