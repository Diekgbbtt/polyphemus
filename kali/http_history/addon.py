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
from urllib.parse import urlsplit

from kali.http_history.governor import validate_traffic_policy
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
    ):
        self.root = root
        self.resolver = resolver
        self.enabled = enabled
        self.governor_enabled = governor_enabled
        self.governor = governor
        self.max_body_bytes = max_body_bytes
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
            "last_error": None,
            "governor_last_error": None,
        }

    # --- mitmproxy hooks ------------------------------------------------------

    async def request(self, flow) -> None:
        """Governance hook: spend this target's token before the flow egresses.

        Conditional on BOTH the governor switch and a validated policy for the
        flow's leased source address, so a capture-only flow (or a legacy
        registration) is never delayed. A failing governor is counted and
        disclosed: the proxy must not break a request whose command was already
        admitted by the exec seam's own fail-closed check.
        """
        if not self.governor_enabled or self.governor is None:
            return
        try:
            registration = self._resolve_registration(flow)
            if registration is None or not registration.traffic_policy:
                return
            policy = validate_traffic_policy(registration.traffic_policy)
            if policy is None:
                return
            decision = await self.governor.acquire(
                registration.project_id, policy, request_host_of(flow)
            )
        except Exception as exc:  # noqa: BLE001 - the proxy must never break
            with self._lock:
                self._status["governor_failed"] += 1
                self._status["governor_last_error"] = f"{type(exc).__name__}: {exc}"
            return
        if decision.governed:
            with self._lock:
                self._status["governed"] += 1

    def response(self, flow) -> None:
        self._capture(flow)

    def error(self, flow) -> None:
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
