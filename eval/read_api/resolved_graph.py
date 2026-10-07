"""Resolved L0/L1 graph resolution (unified workspace).

The resolved graph prefers the immutable schema-v2 capture a Trial wrote beside
its manifest and otherwise queries the configured agent for the matching
instance's *current* project graph. A schema-v1 Trial from another instance
never reaches this server's agent merely because a project id matches.

Captured bytes that fail their recorded digest are never served: the resolver
keeps the strict failure code as a safe ``fallback_reason`` and, when eligible,
returns the current graph instead. Every transport, HTTP, decode, and
normalization failure becomes a stable, path-free reason; no agent response
body or exception string is ever forwarded. Import performs no I/O.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from orchestrator.project_graph import ProjectGraphError, normalize_project_graph

from . import project_graph as historical
from .project_graph import HistoricalProjectGraphError
from .resolved import TrialContext

TRIAL_SNAPSHOT = "trial_snapshot"
PROJECT_STORAGE = "project_storage"

REASON_UNAVAILABLE = "project_graph_unavailable"
REASON_INVALID = "project_graph_invalid"
REASON_EMPTY = "project_graph_empty"
REASON_NO_PROJECT = "project_id_unavailable"
REASON_NOT_ELIGIBLE = "instance_not_eligible"
# Distinct, path-free reasons for a current-graph read that failed, so the
# operator can tell a timeout from a missing project, an HTTP error, a transport
# error or a malformed payload - never one generic "unavailable".
REASON_TIMEOUT = "project_graph_timeout"
REASON_NOT_FOUND = "project_graph_not_found"
REASON_HTTP_ERROR = "project_graph_http_error"
REASON_TRANSPORT = "project_graph_transport_error"

# The current-graph read is bounded by a configurable, finite timeout. The
# default (20 s) comfortably covers the ~4 s these large graphs take; the range
# keeps a typo from becoming an infinite wait or a hair-trigger cut.
DEFAULT_TIMEOUT_SECONDS = 20.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 30.0

_KNOWN_CLIENT_REASONS = frozenset(
    {REASON_TIMEOUT, REASON_NOT_FOUND, REASON_HTTP_ERROR, REASON_TRANSPORT, REASON_INVALID}
)

MAX_GRAPH_BYTES = 32 * 1024 * 1024


def resolve_graph_timeout(raw: object) -> float:
    """The configured read timeout in seconds, or the safe default.

    A missing, empty, non-numeric, non-finite (NaN/Inf), or out-of-range value
    (< 1 s or > 30 s) falls back to `DEFAULT_TIMEOUT_SECONDS`, so a bad
    environment variable can never produce an infinite wait or a hair-trigger
    cut.
    """
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    text = str(raw).strip()
    if not text:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(text)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    if not math.isfinite(value) or not (MIN_TIMEOUT_SECONDS <= value <= MAX_TIMEOUT_SECONDS):
        return DEFAULT_TIMEOUT_SECONDS
    return value


def _client_reason(code: str) -> str:
    """Map a client failure code to a stable resolver reason."""
    if code == "invalid":  # the historical client code for a bad payload
        return REASON_INVALID
    if code in _KNOWN_CLIENT_REASONS:
        return code
    return REASON_TRANSPORT


def _http_reason(status: object) -> str:
    return REASON_NOT_FOUND if status == 404 else REASON_HTTP_ERROR


def _network_reason(exc: URLError) -> str:
    """A timeout wrapped in `URLError` is still a timeout, not a transport error."""
    return REASON_TIMEOUT if isinstance(exc.reason, TimeoutError) else REASON_TRANSPORT


class ProjectGraphClientError(RuntimeError):
    """A path-free transport/decode failure; `reason` is a stable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@runtime_checkable
class ProjectGraphClient(Protocol):
    """The injected network seam: current graph bytes for one project id."""

    def get_graph(self, project_id: str) -> Mapping[str, object]:
        """The decoded, unnormalized project graph payload."""


@dataclass(frozen=True)
class ResolvedGraph:
    """One resolved graph source; the graph body is present only when available."""

    status: str
    source: str
    project_id: str | None
    captured_at: str | None
    sha256: str | None
    graph: dict[str, Any] | None = field(default=None, repr=False)
    reason: str | None = None
    fallback_reason: str | None = None


def resolve_graph(
    store: str | Path | None,
    context: TrialContext,
    *,
    client: ProjectGraphClient | None,
) -> ResolvedGraph:
    """Prefer the captured schema-v2 graph, else the eligible current graph."""
    fallback_reason: str | None = None
    if store:
        try:
            captured = historical.read_project_graph(
                store, context.target_id, context.target_run_id, context.trial_id
            )
        except HistoricalProjectGraphError as exc:
            fallback_reason = exc.code
        else:
            return ResolvedGraph(
                status="available",
                source=TRIAL_SNAPSHOT,
                project_id=context.project_id,
                captured_at=captured.get("captured_at"),
                sha256=captured.get("sha256"),
                graph=captured["graph"],
                fallback_reason=None,
            )

    return _current_graph(context, client, fallback_reason)


def _current_graph(
    context: TrialContext,
    client: ProjectGraphClient | None,
    fallback_reason: str | None,
) -> ResolvedGraph:
    project_id = context.project_id
    if project_id is None:
        return _unavailable(None, REASON_NO_PROJECT, fallback_reason)
    if not context.fallback_eligible:
        return _unavailable(project_id, REASON_NOT_ELIGIBLE, fallback_reason)
    if client is None:
        return _unavailable(project_id, REASON_UNAVAILABLE, fallback_reason)

    try:
        payload = client.get_graph(project_id)
    except ProjectGraphClientError as exc:
        return _unavailable(project_id, _client_reason(exc.reason), fallback_reason)

    if not isinstance(payload, Mapping):
        return _unavailable(project_id, REASON_INVALID, fallback_reason)
    try:
        graph = normalize_project_graph(payload, project_id=project_id)
    except (ProjectGraphError, TypeError, ValueError):
        return _unavailable(project_id, REASON_INVALID, fallback_reason)
    if not graph["nodes"] and not graph["links"]:
        return _unavailable(project_id, REASON_EMPTY, fallback_reason)
    return ResolvedGraph(
        status="available",
        source=PROJECT_STORAGE,
        project_id=project_id,
        captured_at=None,
        sha256=None,
        graph=graph,
        fallback_reason=fallback_reason,
    )


def _unavailable(
    project_id: str | None, reason: str, fallback_reason: str | None
) -> ResolvedGraph:
    return ResolvedGraph(
        status="unavailable",
        source=PROJECT_STORAGE,
        project_id=project_id,
        captured_at=None,
        sha256=None,
        graph=None,
        reason=reason,
        fallback_reason=fallback_reason,
    )


def graph_response(resolved: ResolvedGraph) -> dict[str, Any]:
    """The resolved graph wire body (never carries a trusted root)."""
    body: dict[str, Any] = {
        "status": resolved.status,
        "source": resolved.source,
        "project_id": resolved.project_id,
        "captured_at": resolved.captured_at,
        "fallback_reason": resolved.fallback_reason,
    }
    if resolved.status == "available":
        body["sha256"] = resolved.sha256
        body["graph"] = resolved.graph
    else:
        body["reason"] = resolved.reason
    return body


class HttpProjectGraphClient:
    """A bounded, path-free client for `GET /projects/<id>/graph`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        opener: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._opener = opener or urlopen

    @property
    def timeout(self) -> float:
        """The configured read timeout in seconds (for wiring assertions)."""
        return self._timeout

    def get_graph(self, project_id: str) -> Mapping[str, object]:
        url = "{}/projects/{}/graph".format(
            self._base_url, quote(project_id, safe="")
        )
        request = Request(url, method="GET")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise ProjectGraphClientError(_http_reason(status))
                raw = response.read(MAX_GRAPH_BYTES + 1)
        except ProjectGraphClientError:
            raise
        except HTTPError as exc:
            raise ProjectGraphClientError(_http_reason(getattr(exc, "code", None))) from None
        except URLError as exc:
            raise ProjectGraphClientError(_network_reason(exc)) from None
        except TimeoutError:
            raise ProjectGraphClientError(REASON_TIMEOUT) from None
        except OSError:
            raise ProjectGraphClientError(REASON_TRANSPORT) from None
        if len(raw) > MAX_GRAPH_BYTES:
            raise ProjectGraphClientError(REASON_INVALID)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ProjectGraphClientError(REASON_INVALID) from None
        if not isinstance(payload, Mapping):
            raise ProjectGraphClientError(REASON_INVALID)
        return payload


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "HttpProjectGraphClient",
    "MAX_TIMEOUT_SECONDS",
    "MIN_TIMEOUT_SECONDS",
    "PROJECT_STORAGE",
    "ProjectGraphClient",
    "ProjectGraphClientError",
    "REASON_EMPTY",
    "REASON_HTTP_ERROR",
    "REASON_INVALID",
    "REASON_NOT_ELIGIBLE",
    "REASON_NOT_FOUND",
    "REASON_NO_PROJECT",
    "REASON_TIMEOUT",
    "REASON_TRANSPORT",
    "REASON_UNAVAILABLE",
    "ResolvedGraph",
    "TRIAL_SNAPSHOT",
    "graph_response",
    "resolve_graph_timeout",
    "resolve_graph",
]
