"""The passive raw-CDP capture sidecar.

Spec: `docs/design/steel-crawl-spec.md` sections 2.5, 9.1, 9.2, 9.5, and 12.

The sidecar observes the same browser session the CLI drives, over one raw CDP
page target. It is passive by construction: `attach` enables the domains and
the event pump answers only `Network.getResponseBody`, so the sidecar never
sends a navigation, an input, or a DOM-mutating method (spec 9.1).

The transport is injected. The fake in the test pack replays a checked-in event
stream and records every sent command, so the passivity is provable on the wire
without a browser.

`pump` consumes the transport's event stream and records one `Flow` per
request id. The correlation context is read when `Network.requestWillBeSent`
arrives, so a later `set_context` or `clear_context` never rewrites a flow that
already started (spec 9.5).
"""
from __future__ import annotations

import base64
from collections.abc import Iterator, Mapping
from typing import Any, Protocol

from polymerhus.recon.crawl.steel.capture.flow import (
    DEFAULT_MAX_RESPONSE_BYTES,
    DEFAULT_MAX_RUN_BYTES,
    Attribution,
    BodyStore,
    Flow,
)

# The five enable commands, in the order spec 9.1 lists them. Nothing here
# drives the browser; the cache disable is the one behavioural command, and it
# only makes capture see every request.
ENABLE_METHODS: tuple[str, ...] = (
    "Page.enable",
    "Network.enable",
    "Network.setCacheDisabled",
    "Runtime.enable",
    "Debugger.enable",
)

# The one read the pump sends after a load completes.
BODY_METHOD = "Network.getResponseBody"

# The resource types whose bodies the crawl captures (spec 9.2). An empty type
# is fetched defensively: an unlabelled document must not lose its body.
BODY_RESOURCE_TYPES = frozenset({"Document", "XHR", "Fetch", "Script"})


class CdpEvent(Protocol):
    """One inbound CDP event: its method and its params object."""

    method: str
    params: Mapping[str, Any]


class CdpTransport(Protocol):
    """The two seams the sidecar needs from a raw CDP connection."""

    def send(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        """Send one command and return its result object (empty for no result)."""
        ...

    def replay(self) -> Iterator[CdpEvent]:
        """Yield the inbound events in arrival order."""
        ...


class CaptureUnavailable(RuntimeError):
    """The sidecar cannot observe the target; the run must not continue.

    Spec 12 maps every attach failure to this one contract code. A caller
    fails the run rather than produce a capture-less success.
    """

    code = "capture_unavailable"
    default_message = "the capture sidecar could not attach to the CDP target"

    def __init__(self, message: str = "") -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class CaptureSidecar:
    """A passive observer of one page target's network lifecycle."""

    def __init__(
        self,
        transport: CdpTransport,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_run_bytes: int = DEFAULT_MAX_RUN_BYTES,
    ) -> None:
        self._transport = transport
        self._bodies = BodyStore(
            max_response_bytes=max_response_bytes,
            max_run_bytes=max_run_bytes,
        )
        self._flows: dict[str, Flow] = {}
        self._finished: list[str] = []
        self._page_id: str | None = None
        self._action_id: str | None = None
        self._attached = False

    @property
    def attached(self) -> bool:
        """Whether every enable command was acknowledged."""
        return self._attached

    @property
    def bodies(self) -> BodyStore:
        """The run's captured bodies, keyed by digest."""
        return self._bodies

    @property
    def flows(self) -> tuple[Flow, ...]:
        """Every completed flow, in the order it finished."""
        return tuple(self._flows[request_id] for request_id in self._finished)

    def attach(self) -> None:
        """Enable the capture domains; never send a browser action.

        Any transport failure is `capture_unavailable`, the spec 12 fail-closed
        code: a half-enabled sidecar must not be mistaken for a working one.
        """
        if self._attached:
            return
        try:
            for method in ENABLE_METHODS:
                self._transport.send(method)
        except Exception as exc:
            raise CaptureUnavailable(
                f"the capture sidecar could not attach: {exc}"
            ) from exc
        self._attached = True

    def set_context(self, page_id: str, action_id: str | None = None) -> None:
        """Set the page visit and action the next request is attributed to.

        The context is read when `Network.requestWillBeSent` arrives, so an
        in-flight flow keeps the context it started under (spec 9.5).
        """
        self._page_id = page_id or None
        self._action_id = action_id or None

    def clear_context(self) -> None:
        """Return to an unattributed context."""
        self._page_id = None
        self._action_id = None

    def pump(self) -> tuple[Flow, ...]:
        """Consume the inbound events and return the flows finished this pump."""
        if not self._attached:
            raise CaptureUnavailable("the capture sidecar is not attached")
        completed: list[Flow] = []
        for event in self._transport.replay():
            if event.method == "Network.requestWillBeSent":
                self._record_request(event.params)
            elif event.method == "Network.responseReceived":
                self._record_response(event.params)
            elif event.method == "Network.loadingFinished":
                flow = self._record_finished(event.params)
                if flow is not None:
                    completed.append(flow)
            elif event.method == "Network.loadingFailed":
                flow = self._record_failed(event.params)
                if flow is not None:
                    completed.append(flow)
        return tuple(completed)

    def _record_request(self, params: Mapping[str, Any]) -> None:
        request_id = _opt_str(params.get("requestId"))
        if request_id is None:
            return
        request = params.get("request")
        if not isinstance(request, Mapping):
            return
        self._flows[request_id] = Flow(
            request_id=request_id,
            page_id=self._page_id,
            action_id=self._action_id,
            attribution=_attribution(self._page_id, self._action_id),
            method=_opt_str(request.get("method")) or "",
            url=_opt_str(request.get("url")) or "",
            request_headers=_headers(request.get("headers")),
            request_body=_opt_str(request.get("postData")),
            resource_type=(
                _opt_str(request.get("resourceType"))
                or _opt_str(params.get("type"))
                or ""
            ),
            initiator=_mapping(params.get("initiator")),
            frame_id=_opt_str(params.get("frameId")),
            received_at=_opt_float(params.get("wallTime")),
        )

    def _record_response(self, params: Mapping[str, Any]) -> None:
        request_id = _opt_str(params.get("requestId"))
        flow = self._flows.get(request_id or "")
        if flow is None:
            return
        response = params.get("response")
        if not isinstance(response, Mapping):
            return
        self._flows[flow.request_id] = flow.model_copy(
            update={
                "status": _opt_int(response.get("status")),
                "response_headers": _headers(response.get("headers")),
                "mime_type": _opt_str(response.get("mimeType")),
                "connection": _opt_str(response.get("connection")),
                "timing": _mapping(response.get("timing")),
                "encoded_data_length": _opt_int(response.get("encodedDataLength")),
                "http_version": _opt_str(response.get("protocol")),
            }
        )

    def _record_finished(self, params: Mapping[str, Any]) -> Flow | None:
        request_id = _opt_str(params.get("requestId"))
        flow = self._flows.get(request_id or "")
        if flow is None:
            return None
        updates: dict[str, Any] = {"finished": True}
        encoded = _opt_int(params.get("encodedDataLength"))
        if encoded is not None:
            updates["encoded_data_length"] = encoded
        if not flow.resource_type or flow.resource_type in BODY_RESOURCE_TYPES:
            updates.update(self._fetch_body(flow.request_id))
        return self._finish(flow.model_copy(update=updates))

    def _record_failed(self, params: Mapping[str, Any]) -> Flow | None:
        """A failed load carries no body; the error text is the evidence."""
        request_id = _opt_str(params.get("requestId"))
        flow = self._flows.get(request_id or "")
        if flow is None:
            return None
        error = _opt_str(params.get("errorText")) or _opt_str(
            params.get("blockedReason")
        )
        return self._finish(
            flow.model_copy(update={"finished": True, "error": error or "loading failed"})
        )

    def _finish(self, flow: Flow) -> Flow:
        """Record a terminal flow once, in finish order."""
        self._flows[flow.request_id] = flow
        if flow.request_id not in self._finished:
            self._finished.append(flow.request_id)
        return flow

    def _fetch_body(self, request_id: str) -> dict[str, Any]:
        """Fetch and store the body; a failure becomes the flow's error.

        The body is one field of a flow, never the flow's reason to exist, so
        this one seam fails open: a transport error, a missing body, or an
        undecodable payload is recorded on the flow and never raised (spec 12
        reserves `capture_unavailable` for attach).
        """
        try:
            result = self._transport.send(BODY_METHOD, {"requestId": request_id})
            stored = self._bodies.capture(_decoded_body(result))
        except Exception as exc:
            return {"error": f"body fetch failed: {exc}"}
        return {
            "response_body": stored.data,
            "response_body_sha256": stored.sha256,
            "body_truncated": stored.truncated,
            "body_original_size": stored.original_size,
            "body_truncation_reason": stored.truncation_reason,
        }


def _attribution(page_id: str | None, action_id: str | None) -> Attribution:
    """The flow's attribution from the context active at request time."""
    if action_id is not None:
        return "action"
    if page_id is not None:
        return "page"
    return "unknown"


def _decoded_body(result: Mapping[str, Any]) -> bytes:
    """The response body as bytes; base64 bodies are decoded first."""
    text = result.get("body")
    if not isinstance(text, str):
        text = ""
    if result.get("base64Encoded"):
        try:
            return base64.b64decode(text)
        except (ValueError, TypeError):
            return b""
    return text.encode("utf-8")


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return dict(value)


def _headers(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(name): str(text) for name, text in value.items()}


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _opt_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _opt_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "BODY_METHOD",
    "ENABLE_METHODS",
    "CaptureSidecar",
    "CaptureUnavailable",
    "CdpEvent",
    "CdpTransport",
]
