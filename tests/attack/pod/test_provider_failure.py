"""Unit tier (#329): a provider failure in the test-executor pod is classified
distinctly from a target infeasibility.

The pod used to wrap its whole run and fabricate `verdict=unsuccessful`,
`terminal_reason=technical-infeasibility` on ANY raise (`pod/pod.py:114-118`),
so a provider 429 was written as a domain verdict. #329 forbids that: a
provider failure propagates as the typed `ProviderUnavailableError` (no
PodExport at all), while a genuine internal error keeps the IA-4 fail-open
degrade.
"""
from __future__ import annotations

import asyncio

import httpx
import openai
import pytest

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.app.llm.provider_failure import ProviderUnavailableError

from tests.attack.pod.test_graph import SPEC_ID, VALID_SPEC, _exec, _no_trace


def _rate_limit() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    response = httpx.Response(
        429, request=request, headers={"retry-after": "30"},
        text="Rate limit of 15 requests per minute exceeded")
    return openai.RateLimitError(
        "Rate limit of 15 requests per minute exceeded", response=response, body=None)


def test_provider_throttle_is_not_recorded_as_technical_infeasibility():
    """The red loop: a runner seam that raises a 429 must NOT return a
    fabricated `technical-infeasibility` domain verdict - it propagates the
    typed provider error with a backoff hint instead."""
    async def throttled_runner(spec, messages, tool_calls):
        raise _rate_limit()

    with pytest.raises(ProviderUnavailableError) as exc:
        asyncio.run(arun_pod(
            VALID_SPEC, exec_fn=_exec(""), runner_step_fn=throttled_runner,
            triager_fn=None, trace_fn=_no_trace))
    assert exc.value.status_code == 429
    assert exc.value.retry_after_s == 30.0


def test_provider_throttle_in_the_triager_seam_also_propagates():
    from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn

    def throttled_triager(spec, obs, messages, log):
        raise _rate_limit()

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(arun_pod(
            VALID_SPEC, exec_fn=_exec("not found\n__POD_HTTP_STATUS__:404\n"
                                      "__POD_HTTP_TIME__:0.02"),
            runner_step_fn=symbolic_runner_step_fn,
            triager_fn=throttled_triager, trace_fn=_no_trace))


def test_a_genuine_internal_error_still_degrades_fail_open():
    """IA-4 is preserved for NON-provider errors: the pod never raises a domain
    path into the parent, and the degrade records honest `technical-infeasibility`
    only for a real internal failure."""
    def broken_runner(spec, messages, tool_calls):
        raise RuntimeError("a genuine internal defect")

    env = asyncio.run(arun_pod(
        VALID_SPEC, exec_fn=_exec(""), runner_step_fn=broken_runner,
        triager_fn=None, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
