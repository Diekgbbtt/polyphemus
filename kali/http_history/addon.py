"""The Polyphemus mitmproxy addon: ``response``/``error`` -> durable artifact.

Deliberately passive: it reads the flow, never mutates it, and never raises
into mitmproxy. A store failure increments a counter and records the reason so
``proxy_status()`` can disclose a degraded capture plane without breaking the
proxied traffic.

Correlation is by client source address through an injected resolver (the
shared namespace registry). A flow that cannot be correlated is still recorded,
under the reserved ``unscoped`` project, which project-scoped queries refuse to
read.
"""
from __future__ import annotations

import threading

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
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        store_factory=None,
    ):
        self.root = root
        self.resolver = resolver
        self.enabled = enabled
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
            "last_error": None,
        }

    # --- mitmproxy hooks ------------------------------------------------------

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
            return {"enabled": self.enabled, **self._status}
