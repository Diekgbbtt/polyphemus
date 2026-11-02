"""Client-side Steel session identity and live-view resolution (#395).

The Cedar session record is the source of truth for a browser session:
`id`, `name`, `status`, the viewer/debug URLs, the CDP websocket, and the
session clocks. The API returns the viewer URL as a resource attribute; it is
not a value a caller should reconstruct.

The self-hosted runtime and the cloud disagree on what that attribute means:

* a cloud viewer URL can name the session directly
  (`https://app.steel.dev/sessions/<id>`);
* the self-hosted runtime returns a shared base (`http://host:3000/`) that may
  not even serve a page, while the working player is the shared
  `/v1/sessions/debug` page and its cast WebSocket follows the active session.

This module keeps the session record and the view candidate together. It never
fabricates a `?sessionId=` chain, and it marks `addressable` only when the URL
actually carries the session id. A caller can therefore publish a live view
without claiming it names a specific session when it does not.

The module is pure value objects and a thread-safe registry. It performs no
I/O at import and never starts, stops, or releases a session. The lifecycle
owner calls `observe_start`, `observe_catalogue`, `observe_api`, and
`observe_stop`; the registry only tracks what the owner observed.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import parse_qsl, urlparse

VIEW_KINDS = ("viewer", "player", "debugger")


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _carries_session(url: str, session_id: str) -> bool:
    """Whether the URL actually names this session.

    A path segment or a query value equal to the id is evidence. A substring
    match is not: a base URL that merely contains the host or a similar id
    must not be published as addressable.
    """
    if not url or not session_id:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if any(part == session_id for part in parsed.path.split("/") if part):
        return True
    return any(value == session_id for _, value in parse_qsl(parsed.query))


@dataclass(frozen=True)
class SteelLiveView:
    """One view candidate for a session, with its addressability made explicit."""

    url: str
    kind: str
    session_id: str
    session_name: str | None = None
    addressable: bool = False
    healthy: bool | None = None
    observed_at: float = field(default_factory=time.time)

    def as_public(self) -> dict:
        return {
            "url": self.url,
            "kind": self.kind,
            "session_id": self.session_id,
            "session_name": self.session_name,
            "addressable": self.addressable,
            "healthy": self.healthy,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class SteelSession:
    """One observed Steel browser session.

    `name` is the tool/CLI session name; `session_id` is the runtime id. The
    two are the stable identity pair. A name can be reused after a release, so
    the id is the tiebreaker.
    """

    session_id: str
    name: str | None = None
    status: str = "unknown"
    viewer_url: str = ""
    debug_url: str = ""
    debugger_url: str = ""
    websocket_url: str = ""
    created_at: str | None = None
    remaining_ms: int | None = None
    inactivity_timeout_ms: int | None = None
    source: str = "unknown"
    observed_at: float = field(default_factory=time.time)

    @classmethod
    def from_cli_catalogue(cls, item: Mapping[str, Any]) -> "SteelSession":
        """Build from `steel browser sessions --json`."""
        return cls(
            session_id=str(item.get("id") or ""),
            name=_opt_str(item.get("name")),
            status=str(item.get("status") or "unknown"),
            viewer_url=str(item.get("viewerUrl") or ""),
            source="cli.catalogue",
        )

    @classmethod
    def from_cli_start(
        cls, name: str | None, data: Mapping[str, Any]
    ) -> "SteelSession":
        """Build from `steel browser start --json`."""
        return cls(
            session_id=str(data.get("id") or ""),
            name=_opt_str(name) or _opt_str(data.get("name")),
            status="live",
            viewer_url=str(data.get("liveUrl") or ""),
            websocket_url=str(data.get("connectUrl") or ""),
            remaining_ms=_opt_int(data.get("remainingMs")),
            inactivity_timeout_ms=_opt_int(data.get("inactivityTimeoutMs")),
            source="cli.start",
        )

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "SteelSession":
        """Build from the API session record (`sessions get` / `/v1/sessions`)."""
        return cls(
            session_id=str(data.get("id") or ""),
            name=_opt_str(data.get("name")),
            status=str(data.get("status") or "unknown"),
            viewer_url=str(data.get("sessionViewerUrl") or ""),
            debug_url=str(data.get("debugUrl") or ""),
            debugger_url=str(data.get("debuggerUrl") or ""),
            websocket_url=str(data.get("websocketUrl") or ""),
            created_at=_opt_str(data.get("createdAt")),
            source="api",
        )

    @classmethod
    def from_sdk(cls, session: Any) -> "SteelSession":
        """Build from the `steel-sdk` session resource.

        The SDK exposes snake_case attributes; a missing debug URL is normal.
        """
        return cls(
            session_id=str(getattr(session, "id", "") or ""),
            status=str(getattr(session, "status", "live") or "live"),
            viewer_url=str(getattr(session, "session_viewer_url", "") or ""),
            debug_url=str(getattr(session, "debug_url", "") or ""),
            debugger_url=str(getattr(session, "debugger_url", "") or ""),
            websocket_url=str(getattr(session, "websocket_url", "") or ""),
            created_at=_opt_str(getattr(session, "created_at", None)),
            source="sdk",
        )

    def merge(self, other: "SteelSession") -> "SteelSession":
        """Return this record with `other`'s non-empty observations applied.

        The newer observation wins for every explicit field. A missing field
        never erases an earlier one, so a catalogue read does not drop the
        debug URL or the websocket learned from a start or an API read.
        """
        if (
            self.session_id
            and other.session_id
            and self.session_id != other.session_id
        ):
            raise ValueError("cannot merge two different Steel sessions")

        def pick_str(current: str, incoming: str) -> str:
            return incoming if incoming else current

        status = other.status if other.status not in ("", "unknown") else self.status
        return replace(
            self,
            session_id=other.session_id or self.session_id,
            name=other.name or self.name,
            status=status,
            viewer_url=pick_str(self.viewer_url, other.viewer_url),
            debug_url=pick_str(self.debug_url, other.debug_url),
            debugger_url=pick_str(self.debugger_url, other.debugger_url),
            websocket_url=pick_str(self.websocket_url, other.websocket_url),
            created_at=other.created_at or self.created_at,
            remaining_ms=(
                other.remaining_ms
                if other.remaining_ms is not None else self.remaining_ms
            ),
            inactivity_timeout_ms=(
                other.inactivity_timeout_ms
                if other.inactivity_timeout_ms is not None
                else self.inactivity_timeout_ms
            ),
            source=other.source or self.source,
            observed_at=max(self.observed_at, other.observed_at),
        )

    @property
    def is_live(self) -> bool:
        return self.status == "live"

    @property
    def live_view(self) -> SteelLiveView | None:
        """The best view candidate, with addressability explicit.

        Priority:
        1. a URL that actually carries the session id (viewer, player, debugger);
        2. the shared debug player, which follows the active session;
        3. the shared viewer base;
        4. the debugger page.

        The shared player is preferred over the shared viewer base because the
        self-hosted runtime's viewer base is the API root, while the player is
        the page that actually streams the browser.
        """
        candidates = (
            ("viewer", self.viewer_url),
            ("player", self.debug_url),
            ("debugger", self.debugger_url),
        )
        for kind, url in candidates:
            if url and _carries_session(url, self.session_id):
                return SteelLiveView(
                    url=url, kind=kind, session_id=self.session_id,
                    session_name=self.name, addressable=True,
                )
        preferred = (
            ("player", self.debug_url),
            ("viewer", self.viewer_url),
            ("debugger", self.debugger_url),
        )
        for kind, url in preferred:
            if url:
                return SteelLiveView(
                    url=url, kind=kind, session_id=self.session_id,
                    session_name=self.name, addressable=False,
                )
        return None

    def public_view(self) -> dict:
        """The model/UI-safe view: identity, status, and the view candidate."""
        view = self.live_view
        return {
            "session_id": self.session_id,
            "name": self.name,
            "status": self.status,
            "is_live": self.is_live,
            "viewer_url": self.viewer_url,
            "debug_url": self.debug_url,
            "live_view": view.as_public() if view else None,
            "source": self.source,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class SessionTransition:
    """One registry-observed lifecycle change."""

    kind: str
    before: SteelSession | None
    after: SteelSession | None

    @property
    def name(self) -> str | None:
        return (self.after or self.before).name if (self.after or self.before) else None


class SteelSessionRegistry:
    """A client-side, name-keyed view of the sessions one caller owns.

    It performs no lifecycle actions. `observe_start` is called after a
    successful start, `observe_catalogue` after `steel browser sessions`,
    `observe_api` after a session record read, and `observe_stop` after a
    stop. A live name that disappears from the catalogue becomes `lost`; an
    explicit stop becomes `released`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, SteelSession] = {}

    def get(self, name: str) -> SteelSession | None:
        with self._lock:
            return self._by_name.get(name)

    def live(self) -> list[SteelSession]:
        with self._lock:
            return [
                session for session in self._by_name.values()
                if session.is_live
            ]

    def views(self) -> list[SteelLiveView]:
        """Live sessions' view candidates, addressable or explicitly shared."""
        return [
            view for session in self.live()
            if (view := session.live_view) is not None
        ]

    def observe_start(
        self, name: str, data: Mapping[str, Any]
    ) -> SteelSession:
        incoming = SteelSession.from_cli_start(name, data)
        with self._lock:
            existing = self._by_name.get(name)
            if existing is not None and existing.session_id == incoming.session_id:
                incoming = existing.merge(incoming)
            self._by_name[name] = incoming
            return incoming

    def observe_api(
        self, name: str, data: Mapping[str, Any]
    ) -> SteelSession:
        incoming = SteelSession.from_api(data)
        with self._lock:
            existing = self._by_name.get(name)
            if existing is not None and existing.session_id == incoming.session_id:
                incoming = existing.merge(incoming)
            elif incoming.name is None:
                incoming = replace(incoming, name=name)
            self._by_name[name] = incoming
            return incoming

    def observe_catalogue(
        self, items: Iterable[Mapping[str, Any]] | Mapping[str, Any]
    ) -> list[SessionTransition]:
        now = time.time()
        transitions: list[SessionTransition] = []
        incoming: dict[str, SteelSession] = {}
        if isinstance(items, Mapping):
            items = [items]
        for item in items:
            session = SteelSession.from_cli_catalogue(item)
            if not session.name or not session.session_id:
                continue
            incoming[session.name] = session
        with self._lock:
            for name, session in incoming.items():
                existing = self._by_name.get(name)
                if existing is not None and existing.session_id == session.session_id:
                    merged = existing.merge(session)
                else:
                    merged = session
                self._by_name[name] = merged
                if existing is None or existing.session_id != merged.session_id:
                    transitions.append(SessionTransition("appeared", existing, merged))
                elif existing != merged:
                    transitions.append(SessionTransition("updated", existing, merged))
            for name, existing in list(self._by_name.items()):
                if name in incoming or not existing.is_live:
                    continue
                lost = replace(
                    existing, status="lost", observed_at=now,
                    source="cli.catalogue",
                )
                self._by_name[name] = lost
                transitions.append(SessionTransition("vanished", existing, lost))
        return transitions

    def observe_stop(self, name: str) -> SessionTransition | None:
        now = time.time()
        with self._lock:
            existing = self._by_name.get(name)
            if existing is None:
                return None
            released = replace(
                existing, status="released", observed_at=now, source="cli.stop"
            )
            self._by_name[name] = released
            return SessionTransition("released", existing, released)


__all__ = [
    "SessionTransition",
    "SteelLiveView",
    "SteelSession",
    "SteelSessionRegistry",
]
