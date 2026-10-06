"""Unit tier (#329): the shared provider-failure classifier.

A provider throttle/quota is an INFRASTRUCTURE failure, classified distinctly
from a domain error so the app layer can back off and pause instead of failing
a run, and the pod can refuse to fabricate a `technical-infeasibility` verdict.
"""
from __future__ import annotations

import httpx
import openai
import pytest

from polymerhus.app.llm.provider_failure import (
    ProviderUnavailableError,
    as_provider_error,
    is_provider_unavailable,
    retry_after_seconds,
)


def _rate_limit(message: str = "Rate limit of 15 requests per minute exceeded",
                headers: dict | None = None) -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    response = httpx.Response(429, request=request, headers=headers or {})
    return openai.RateLimitError(message, response=response, body=None)


def _server_error(status: int = 503) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return openai.APIStatusError("upstream exploded", response=response, body=None)


# --- the classification --------------------------------------------------------

def test_429_throttle_is_a_provider_failure():
    assert is_provider_unavailable(_rate_limit())


def test_5xx_is_a_provider_failure():
    assert is_provider_unavailable(_server_error(500))
    assert is_provider_unavailable(_server_error(503))


def test_timeout_and_transport_are_provider_failures():
    assert is_provider_unavailable(httpx.ConnectTimeout("timed out"))
    assert is_provider_unavailable(openai.APIConnectionError(
        request=httpx.Request("POST", "https://api.example.test")))


def test_go_usage_limit_message_is_a_provider_failure():
    """The live opencode-go signature: `429 GoUsageLimitError: Go usage limit
    exceeded` (`limitName: 5 hour`). A status-less provider wrapper still
    classifies via its type provenance + the throttle message."""
    class GoUsageLimitError(RuntimeError):
        pass

    assert is_provider_unavailable(
        GoUsageLimitError("429 GoUsageLimitError: Go usage limit exceeded"))


def test_a_domain_error_is_not_a_provider_failure():
    assert not is_provider_unavailable(ValueError("spec_id is required"))
    assert not is_provider_unavailable(RuntimeError("assumptions unverifiable"))


def test_a_domain_error_echoing_a_throttle_word_is_not_a_provider_failure():
    """The last-resort message scan is gated on provider TYPE provenance, so a
    plain application error that happens to mention `429`/`quota`/`rate limit`
    stays a domain error (IA-4 fail-open preserved)."""
    assert not is_provider_unavailable(
        RuntimeError("target returned 429 while rate limiting"))
    assert not is_provider_unavailable(ValueError("the quota field is required"))
    assert not is_provider_unavailable(
        RuntimeError("upstream said too many requests"))


def test_typed_error_is_recognised_idempotently():
    typed = ProviderUnavailableError("provider unavailable: boom")
    assert is_provider_unavailable(typed)


# --- the typed error + the retry hint -----------------------------------------

def test_as_provider_error_carries_status_and_quota():
    failure = as_provider_error(_rate_limit(
        "429 GoUsageLimitError: Go usage limit exceeded", headers={"retry-after": "45"}))
    assert failure is not None
    assert failure.status_code == 429
    assert failure.retry_after_s == 45.0
    assert failure.quota_exhausted is True
    assert failure.retryable is True


def test_as_provider_error_is_none_for_a_domain_error():
    assert as_provider_error(ValueError("nope")) is None


def test_retry_after_accepts_http_date():
    request = httpx.Request("POST", "https://api.example.test/v1")
    response = httpx.Response(
        429, request=request,
        headers={"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"})
    exc = openai.RateLimitError("throttled", response=response, body=None)
    # A past HTTP-date floors at 0 - never negative.
    assert retry_after_seconds(exc) == 0.0


def test_retry_after_absent_is_none():
    assert retry_after_seconds(_rate_limit()) is None
