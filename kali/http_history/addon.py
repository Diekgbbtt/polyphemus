"""The Polyphemus mitmproxy addon: ``response``/``error`` -> durable artifact.

Deliberately passive: it reads the flow, never mutates it, and never raises
into mitmproxy. A store failure increments a counter and records the reason so
``proxy_status()`` can disclose a degraded capture plane without breaking the
proxied traffic.

Since #238 the same addon also carries the EGRESS GOVERNOR: an async ``request``
hook that spends the run's per-target token before the request leaves. The two
planes are separate switches - ``enabled`` gates capture, ``governor_enabled``
gates governance - because capture-off must not disarm an armed policy. The
hooks stay independent: capture is conditional on ``enabled``, governance on a
VALIDATED policy, and a governor failure is disclosed rather than silently
releasing traffic.

Correlation is by client source address through an injected resolver (the
shared namespace registry). A flow that cannot be correlated is still recorded,
under the reserved ``unscoped`` project, which project-scoped queries refuse to
read.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from kali.http_history.governor import (
    GovernorPermit,
    TrafficContext,
    validate_traffic_policy,
)
from kali.http_history.normalize import DEFAULT_MAX_BODY_BYTES, normalize_flow
from kali.http_history.store import HttpHistoryStore

UNSCOPED_PROJECT = "unscoped"


def source_ip_of(flow) -> str | None:
    client = getattr(flow, "client_conn", None)
    peername = getattr(client, "peername", None)
    if isinstance(peername, (tuple, list)) and peername:
        return str(peername[0])
    if isinstance(peername, str) and peername:
        return peername
    return None


def request_host_of(flow) -> str | None:
    """The hostname of a flow's request, or None when it cannot be named.

    mitmproxy's own `request.host` is authoritative when present; the URL is the
    fallback (and the only source the unit-tier fakes carry).
    """
    request = getattr(flow, "request", None)
    if request is None:
        return None
    host = getattr(request, "host", None)
    if isinstance(host, str) and host:
        return host
    url = getattr(request, "pretty_url", None) or getattr(request, "url", None)
    if isinstance(url, str) and url:
        return urlsplit(url).hostname
    return None


def _is_websocket(flow) -> bool:
    return getattr(flow, "websocket", None) is not None


def _is_http3(flow) -> bool:
    version = str(getattr(getattr(flow, "request", None), "http_version", "") or "")
    return version.startswith("HTTP/3") or version.startswith("h3")


PERMIT_METADATA_KEY = "polyphemus_governor_permit"


@dataclass
class _LocalRefusal:
    """A mitmproxy-free stand-in for the local refusal response, so the unit tier
    never imports mitmproxy."""

    status_code: int
    headers: dict = field(default_factory=dict)
    content: bytes = b""


def default_refuse_flow(flow, *, reason_code: str, detail: str) -> None:
    """The local-refusal adapter: give the flow a 503 response, so the request
    never reaches the target.

    The mitmproxy import is LAZY: importing this module (the unit tier, the
    service) must not pull mitmproxy in. In production `addon_entry` injects the
    eager adapter instead; this is the safe default.
    """
    headers = {"X-Polymerhus-Traffic-Refusal": reason_code}
    try:
        from mitmproxy import http  # noqa: PLC0415

        response = http.Response.make(
            503, b"traffic refused by the polyphemus governor",
            {**headers, "Content-Type": "text/plain"},
        )
    except Exception:  # noqa: BLE001 - no mitmproxy (unit tier): duck-typed stub
        response = _LocalRefusal(
            status_code=503, headers=dict(headers),
            content=b"traffic refused by the polyphemus governor",
        )
    flow.response = response


class HttpHistoryAddon:
    def __init__(
        self,
        *,
        root,
        resolver=None,
        enabled: bool = True,
        governor_enabled: bool = True,
        governor=None,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        store_factory=None,
        refuse_flow=None,
    ):
        self.root = root
        self.resolver = resolver
        self.enabled = enabled
        self.governor_enabled = governor_enabled
        self.governor = governor
        self.max_body_bytes = max_body_bytes
        self.refuse_flow = refuse_flow or default_refuse_flow
        self._store_factory = store_factory or (lambda project: HttpHistoryStore(root, project))
        self._stores: dict[str, HttpHistoryStore] = {}
        self._lock = threading.Lock()
        self._status = {
            "recorded": 0,
            "failed": 0,
            "unscoped": 0,
            "excluded_websocket": 0,
            "excluded_http3": 0,
            "governed": 0,
            "governor_failed": 0,
            "governor_refusals": 0,
            "last_error": None,
            "governor_last_error": None,
            "last_refusal": None,
        }

    # --- mitmproxy hooks ------------------------------------------------------

    async def request(self, flow) -> None:
        """Governance hook: reserve a concurrency permit and spend this target's
        token before the flow egresses.

        Fail-CLOSED for an ARMED flow (one whose lease carries a policy): an
        unenforceable policy, a missing governor, or any governor exception
        refuses the flow LOCALLY - a 503 with no upstream request - and is
        disclosed in `status()`. Capture is irrelevant here: the two switches are
        independent, so `enabled=False` never disarms governance. An UNARMED flow
        (a capture-only or legacy lease) is never delayed.
        """
        if not self.governor_enabled:
            return
        try:
            registration = self._resolve_registration(flow)
        except Exception as exc:  # noqa: BLE001 - the proxy must never break
            self._refuse(flow, "governor_error", type(exc).__name__)
            return
        if registration is None or not registration.traffic_policy:
            return
        if self.governor is None:
            self._refuse(flow, "governor_unavailable", "no governor attached")
            return
        try:
            policy = validate_traffic_policy(registration.traffic_policy)
            if policy is None:
                self._refuse(
                    flow, "policy_unenforceable",
                    "the registered traffic policy could not be validated",
                )
                return
            decision = await self.governor.acquire(
                registration.project_id,
                traffic_policy=policy,
                context=TrafficContext(
                    source_ip=source_ip_of(flow),
                    request_host=request_host_of(flow),
                ),
            )
        except Exception as exc:  # noqa: BLE001 - the proxy must never break
            self._refuse(flow, "governor_error", type(exc).__name__)
            return
        if decision.governed and decision.permit is not None:
            self._attach_permit(flow, decision.permit)
            with self._lock:
                self._status["governed"] += 1

    async def response(self, flow) -> None:
        await self._release_permit(flow)
        self._capture(flow)

    async def error(self, flow) -> None:
        await self._release_permit(flow)
        self._capture(flow)

    def done(self) -> None:
        with self._lock:
            for store in self._stores.values():
                try:
                    store.close()
                except Exception:  # noqa: BLE001
                    pass
            self._stores.clear()

    # --- internals ------------------------------------------------------------

    def _refuse(self, flow, reason_code: str, detail: str) -> None:
        """Disclose and refuse LOCALLY. `detail` must stay secret-safe - it is an
        exception TYPE or a fixed string, never a message that could carry a URL
        query, a header value, or a body."""
        with self._lock:
            self._status["governor_refusals"] += 1
            self._status["governor_failed"] += 1
            self._status["last_refusal"] = reason_code
            self._status["governor_last_error"] = detail
        try:
            self.refuse_flow(flow, reason_code=reason_code, detail=detail)
        except Exception:  # noqa: BLE001 - refusal must never raise into mitmproxy
            pass

    def _attach_permit(self, flow, permit: GovernorPermit) -> None:
        metadata = getattr(flow, "metadata", None)
        if isinstance(metadata, dict):
            metadata[PERMIT_METADATA_KEY] = {
                "key": list(permit.key),
                "permit_id": permit.permit_id,
            }

    async def _release_permit(self, flow) -> None:
        if self.governor is None:
            return
        metadata = getattr(flow, "metadata", None)
        if not isinstance(metadata, dict):
            return
        raw = metadata.pop(PERMIT_METADATA_KEY, None)
        if not isinstance(raw, dict):
            return
        try:
            permit = GovernorPermit(
                key=tuple(raw.get("key") or ()), permit_id=str(raw.get("permit_id") or "")
            )
            await self.governor.release(permit)
        except Exception:  # noqa: BLE001 - release must never break the proxy
            with self._lock:
                self._status["governor_failed"] += 1
                self._status["governor_last_error"] = "release_error"

    def _capture(self, flow) -> None:
        if not self.enabled:
            return
        if _is_websocket(flow):
            self._bump("excluded_websocket")
            return
        if _is_http3(flow):
            self._bump("excluded_http3")
            return
        try:
            project, context = self._resolve(flow)
            artifact, bodies = normalize_flow(
                flow,
                project_id=project,
                capture_context=context,
                max_body_bytes=self.max_body_bytes,
            )
            self._store_for(project).record(artifact, bodies)
        except Exception as exc:  # noqa: BLE001 - the proxy must never break
            with self._lock:
                self._status["failed"] += 1
                self._status["last_error"] = f"{type(exc).__name__}: {exc}"
            return
        with self._lock:
            self._status["recorded"] += 1
            if project == UNSCOPED_PROJECT:
                self._status["unscoped"] += 1

    def _resolve(self, flow):
        from kali.http_history.models import CaptureContext

        ip = source_ip_of(flow)
        if ip and self.resolver is not None:
            hit = self.resolver.lookup(ip)
            if hit is not None:
                project, context = hit
                if context is None:
                    context = CaptureContext()
                context = context.model_copy(update={"source_ip": ip})
                return project, context
        return UNSCOPED_PROJECT, CaptureContext(source_ip=ip)

    def _resolve_registration(self, flow):
        """The policy-aware lookup, when the injected resolver offers one.

        A resolver that only implements the legacy `lookup` is capture-only: the
        governance plane simply does not apply to it.
        """
        lookup = getattr(self.resolver, "lookup_registration", None)
        if lookup is None:
            return None
        ip = source_ip_of(flow)
        if not ip:
            return None
        return lookup(ip)

    def _store_for(self, project: str) -> HttpHistoryStore:
        with self._lock:
            store = self._stores.get(project)
            if store is None:
                store = self._store_factory(project)
                self._stores[project] = store
            return store

    def _bump(self, key: str) -> None:
        with self._lock:
            self._status[key] += 1

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self.enabled,
                "governor_enabled": self.governor_enabled and self.governor is not None,
                **self._status,
            }
