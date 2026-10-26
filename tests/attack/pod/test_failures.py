"""Unit tier: the pod failure classifier.

The classifier is the one place that decides whether a raised pod failure is a
typed infrastructure terminal, a provider failure the surfer must retry, or a
generic degrade. It never turns a provider outage into a domain verdict.
"""
from __future__ import annotations

import asyncio

from langgraph.errors import GraphRecursionError, NodeTimeoutError

from polymerhus.app.llm.provider_failure import ProviderUnavailableError
from polymerhus.attack.hunting.pod.failures import (
    PodFailure,
    classify_pod_failure,
)
from polymerhus.attack.hunting.pod.types import (
    CONTEXT_WINDOW_EXCEEDED,
    GRAPH_LIMIT,
    NODE_TIMEOUT,
    TOOL_TIMEOUT,
)


def test_a_node_timeout_is_typed_with_the_node_and_kind():
    exc = NodeTimeoutError(
        "runner_agent", 12.5, kind="idle", idle_timeout=10, run_timeout=60)

    failure = classify_pod_failure(exc, node="runner_agent")

    assert failure == PodFailure(
        reason=NODE_TIMEOUT,
        detail=f"node runner_agent idle timeout: {exc}",
    )


def test_a_graph_recursion_error_is_typed_as_a_graph_limit():
    failure = classify_pod_failure(
        GraphRecursionError("Recursion limit of 25 reached"), node="runner_agent")

    assert failure is not None
    assert failure.reason == GRAPH_LIMIT
    assert "Recursion limit" in failure.detail


def test_a_context_window_error_is_typed():
    failure = classify_pod_failure(
        Exception("This model's maximum context length is 128000 tokens"),
        node="runner_agent",
    )

    assert failure is not None
    assert failure.reason == CONTEXT_WINDOW_EXCEEDED


def test_a_tool_timeout_is_typed():
    failure = classify_pod_failure(TimeoutError("exec timed out"), node="tool_exec")

    assert failure is not None
    assert failure.reason == TOOL_TIMEOUT


def test_a_tool_timeout_beats_the_provider_timeout_classification():
    failure = classify_pod_failure(asyncio.TimeoutError(), node="tool_exec")

    assert failure is not None
    assert failure.reason == TOOL_TIMEOUT


def test_a_provider_failure_is_left_for_the_surfer():
    assert classify_pod_failure(
        ProviderUnavailableError("429 too many requests"), node="runner_agent"
    ) is None


def test_a_provider_timeout_in_a_model_node_is_left_for_the_surfer():
    assert classify_pod_failure(asyncio.TimeoutError(), node="runner_agent") is None


def test_a_generic_error_is_left_for_the_domain_degrade():
    assert classify_pod_failure(RuntimeError("bad parsing"), node="runner_agent") is None
