"""The pod failure classifier: one decision for a raised pod execution failure.

The classifier separates three outcomes:

- a typed infrastructure terminal (`node-timeout`, `graph-limit`,
  `context-window-exceeded`, `tool-timeout`) that the pod graph writes as a
  `PodExport`;
- a provider failure (`429`, `5xx`, transport timeout, quota) that returns
  `None` so the surfer retries or pauses the run and no domain verdict is
  fabricated;
- a generic domain degrade (`None`) that the existing `arun_pod` fail-open path
  turns into `technical-infeasibility`.

The module imports the LangGraph error types because it classifies their
failures; it performs no I/O.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from langgraph.errors import GraphRecursionError, NodeTimeoutError

from polymerhus.app.llm.context_window import classify_terminal
from polymerhus.app.llm.provider_failure import as_provider_error
from polymerhus.attack.hunting.pod.types import (
    CONTEXT_WINDOW_EXCEEDED,
    GRAPH_LIMIT,
    NODE_TIMEOUT,
    TOOL_TIMEOUT,
)


@dataclass(frozen=True)
class PodFailure:
    """One typed pod failure and the operator-readable detail for the export."""

    reason: str
    detail: str


def classify_pod_failure(exc: BaseException, *, node: str = "") -> PodFailure | None:
    """Classify a pod execution raise, or return `None`.

    `None` means the caller keeps its existing policy: a provider failure is
    re-raised for the surfer's retry/backoff, and any other error degrades to
    the pod's generic domain terminal.
    """
    if node == "tool_exec" and isinstance(exc, NodeTimeoutError):
        kind = getattr(exc, "kind", "run")
        return PodFailure(
            reason=TOOL_TIMEOUT,
            detail=f"tool exec {kind} timeout: {exc}",
        )
    if isinstance(exc, NodeTimeoutError):
        failed_node = getattr(exc, "node", "") or node or "unknown"
        kind = getattr(exc, "kind", "run")
        return PodFailure(
            reason=NODE_TIMEOUT,
            detail=f"node {failed_node} {kind} timeout: {exc}",
        )
    if isinstance(exc, (GraphRecursionError, RecursionError)):
        return PodFailure(
            reason=GRAPH_LIMIT,
            detail=f"graph recursion limit: {exc}",
        )
    # A tool timeout is local to the exec node. Check it before the shared
    # provider classifier, which treats every TimeoutError as provider
    # unavailability.
    if node == "tool_exec" and isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return PodFailure(
            reason=TOOL_TIMEOUT,
            detail=f"tool timeout: {exc}",
        )
    if as_provider_error(exc) is not None:
        return None
    if classify_terminal(exc):
        return PodFailure(
            reason=CONTEXT_WINDOW_EXCEEDED,
            detail=f"context window exceeded: {exc}",
        )
    return None


__all__ = ["PodFailure", "classify_pod_failure"]
