import pytest
from google.genai import errors as genai_errors

from ledgerlens.agent.llm import is_transient


def api_error(code: int) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


@pytest.mark.parametrize("code", [429, 500, 503, 504])
def test_overload_and_rate_limits_are_retried(code: int) -> None:
    assert is_transient(api_error(code))


def test_wrapped_provider_errors_are_recognised() -> None:
    wrapper = RuntimeError("503 UNAVAILABLE")  # langchain re-raises with the SDK error as cause
    wrapper.__cause__ = api_error(503)
    assert is_transient(wrapper)


@pytest.mark.parametrize("error", [api_error(400), api_error(403), ValueError("bad prompt")])
def test_real_errors_fail_fast(error: Exception) -> None:
    assert not is_transient(error)


def test_an_exhausted_daily_quota_is_not_retried() -> None:
    # Retrying burns requests against the same cap and can't succeed before it resets.
    message = "Quota exceeded. quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    error = genai_errors.APIError(429, {"error": {"code": 429, "message": message, "status": "X"}})
    assert not is_transient(error)
