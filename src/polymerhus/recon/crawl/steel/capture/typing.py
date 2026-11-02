"""Typed capture records: scripts, realtime frames, frames, and dialogs.

Spec: `docs/design/steel-crawl-spec.md` sections 9.2, 9.3, 9.4, and 9.5.

These are the records the HTTP `Flow` does not carry. The WebSocket handshake is
an HTTP flow in `flow.py`; its frames are `RealtimeRecord`s. A parsed script is a
`ScriptAsset` with an absolute URL and a provenance, never a source map. A frame
navigation is a `FrameNavigation`. A JavaScript dialog is a `DialogRecord` that
names the auto-dismiss action the sidecar took.

Nothing here performs I/O. The provenance is a literal, so a script observed by
the debugger cannot claim another source.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScriptProvenance = Literal["debugger"]
RealtimeKind = Literal[
    "websocket_created",
    "handshake_request",
    "handshake_response",
    "frame_sent",
    "frame_received",
    "closed",
]
RealtimeDirection = Literal["sent", "received"]


class ScriptAsset(BaseModel):
    """One parsed script: an absolute URL, the CDP script id, and provenance."""

    model_config = ConfigDict(frozen=True)

    script_url: str
    script_id: str
    provenance: ScriptProvenance = "debugger"


class RealtimeRecord(BaseModel):
    """One WebSocket lifecycle record (spec 9.3).

    The handshake request and its `101` response are also an HTTP `Flow`; these
    records keep the created, request, response, frame, and close order for the
    realtime evidence.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str
    kind: RealtimeKind
    url: str | None = None
    direction: RealtimeDirection | None = None
    opcode: int | None = None
    payload: str | None = None
    status: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timestamp: float | None = None
    page_id: str | None = None
    action_id: str | None = None


class FrameNavigation(BaseModel):
    """One `Page.frameNavigated` record (spec 9.2)."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    url: str
    parent_frame_id: str | None = None
    page_id: str | None = None


class DialogRecord(BaseModel):
    """One JavaScript dialog and the auto-dismiss the sidecar attempted.

    `action` and `prompt_text` are the fixed dismiss contract (spec 9.2). An
    `error` means the dismiss command failed; the dialog is still recorded so the
    run can name what blocked it.
    """

    model_config = ConfigDict(frozen=True)

    message: str
    dialog_type: str
    url: str | None = None
    action: Literal["accept"] = "accept"
    prompt_text: str = "test"
    error: str | None = None


__all__ = [
    "DialogRecord",
    "FrameNavigation",
    "RealtimeDirection",
    "RealtimeKind",
    "RealtimeRecord",
    "ScriptAsset",
    "ScriptProvenance",
]
