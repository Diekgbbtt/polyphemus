"""The canonical ``http-artifact/v1`` record.

HAR-shaped without being HAR: header order and duplicates survive as ordered
pairs, cookies/query/form are additive projections (raw headers are kept),
bodies are content-addressed references, and a missing response is represented
explicitly rather than dropped.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "http-artifact/v1"

# How much of a body we actually hold. A body is never silently truncated:
# every non-``captured`` state carries the original size and a reason.
CaptureState = Literal["none", "captured", "empty", "omitted", "truncated"]
ReplayKind = Literal["baseline", "mutated"]


class NameValue(BaseModel):
    name: str
    value: str


class BodyRecord(BaseModel):
    body_ref: str | None = None
    body_size: int = 0
    body_hash: str | None = None
    body_encoding: str | None = None
    capture_state: CaptureState = "none"
    capture_reason: str | None = None


class RequestRecord(BodyRecord):
    method: str = ""
    url: str = ""
    http_version: str = ""
    headers: list[tuple[str, str]] = Field(default_factory=list)
    cookies: list[NameValue] = Field(default_factory=list)
    query: list[NameValue] = Field(default_factory=list)
    form: list[NameValue] = Field(default_factory=list)
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0


class ResponseRecord(BodyRecord):
    status: int | None = None
    reason: str = ""
    http_version: str = ""
    headers: list[tuple[str, str]] = Field(default_factory=list)
    cookies: list[NameValue] = Field(default_factory=list)
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0


class ConnectionRecord(BaseModel):
    client_address: str | None = None
    server_address: str | None = None
    tls: bool = False
    sni: str | None = None
    alpn: str | None = None
    protocol: str = "http"
    quic: bool = False
    websocket: bool = False


class TimingsRecord(BaseModel):
    total_ms: float = 0.0


class CaptureContext(BaseModel):
    """Runtime correlation metadata (never a hunter-spec validation schema)."""

    session_id: str = ""
    run_id: str = ""
    spec_id: str = ""
    variant_ref: str = ""
    exec_id: str = ""
    source_ip: str | None = None
    # Replay lineage is captured with the flow so the addon can stamp the new
    # immutable artifact without a second write ever mutating the baseline.
    derived_from: str | None = None
    replay_kind: str | None = None


class HttpError(BaseModel):
    type: str = ""
    message: str = ""


class HttpArtifact(BaseModel):
    schema_version: str = SCHEMA_VERSION
    artifact_id: str
    project_id: str
    capture_context: CaptureContext = Field(default_factory=CaptureContext)
    request: RequestRecord = Field(default_factory=RequestRecord)
    response: ResponseRecord | None = None
    connection: ConnectionRecord = Field(default_factory=ConnectionRecord)
    timings: TimingsRecord = Field(default_factory=TimingsRecord)
    error: HttpError | None = None
    derived_from: str | None = None
    replay_kind: ReplayKind | None = None
    created_at: float = 0.0
