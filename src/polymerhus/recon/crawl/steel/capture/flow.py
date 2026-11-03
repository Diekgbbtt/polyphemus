"""The capture flow record and the digest-keyed body store.

Spec: `docs/design/steel-crawl-spec.md` sections 2.5, 9.2, 9.5, and 12.

`Flow` is one request/response lifecycle observed on the page target. It is
frozen: the sidecar replaces a record as events arrive, so a flow a caller
holds never changes under it. The attribution is read from the sidecar's
context when the request starts and is never rewritten afterwards (spec 9.5).

`BodyStore` is the one owner of captured response bodies. A body is keyed by
the sha256 of the bytes the store retains, so the digest always names the
stored content and the same body observed twice costs the run cap once
(spec 10.1: body hashes are over decoded bytes). A capped body keeps a prefix;
the stored record carries the full decoded size and the reason, so a reader
never mistakes a truncation for a short body.

Nothing here performs I/O or reads a clock.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The correlation a flow carries (spec 9.5). `page` names a page visit with no
# action, `action` names the CLI action within the visit, and `unknown` is a
# flow observed outside any page/action context.
Attribution = Literal["page", "action", "unknown"]

# The closed truncation vocabulary (spec 9.2): which cap kept only a prefix.
TRUNCATION_RESPONSE_CAP = "response_cap"
TRUNCATION_RUN_CAP = "run_cap"

# The default caps: one response body is bounded at 1 MiB, and one run at
# 64 MiB. The spec requires a cap, not a number; both are injectable so a run
# can tune them without changing the record shape.
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_MAX_RUN_BYTES = 64 * 1024 * 1024

# A request URL is evidence, but an analytics beacon can carry a payload as a
# path segment or query value. The cap keeps one flow's URL and every graph
# record derived from it bounded; the first 2 KiB keep the route and the start
# of the data.
MAX_URL_CHARS = 2048


def cap_url(url: str) -> tuple[str, bool, int]:
    """The URL, whether it was truncated, and its original length."""
    if len(url) <= MAX_URL_CHARS:
        return url, False, len(url)
    return url[:MAX_URL_CHARS], True, len(url)


class Flow(BaseModel):
    """One captured HTTP lifecycle, complete or failed.

    The request fields are read when `Network.requestWillBeSent` arrives; the
    response fields follow on `Network.responseReceived`; the body and
    `finished` follow on `Network.loadingFinished`. A `Network.loadingFailed`
    sets `error` and `finished` without a body fetch.

    `received_at` is the request's CDP wall time (epoch seconds), the only
    absolute clock CDP exposes; `None` when the event carries none.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str
    page_id: str | None = None
    action_id: str | None = None
    attribution: Attribution = "unknown"
    method: str = ""
    url: str = ""
    url_truncated: bool = False
    url_original_length: int = 0
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: str | None = None
    resource_type: str = ""
    initiator: dict[str, Any] = Field(default_factory=dict)
    frame_id: str | None = None
    status: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    mime_type: str | None = None
    connection: str | None = None
    timing: dict[str, Any] = Field(default_factory=dict)
    encoded_data_length: int | None = None
    response_body: bytes | None = None
    response_body_sha256: str | None = None
    body_truncated: bool = False
    body_original_size: int | None = None
    body_truncation_reason: str | None = None
    error: str | None = None
    http_version: str | None = None
    received_at: float | None = None
    finished: bool = False


@dataclass(frozen=True)
class StoredBody:
    """One captured body and the cap outcome that kept it.

    `sha256` is the digest of `data`, never of a discarded full body, so the
    store's key and its content agree. `original_size` is the full decoded
    size; a truncated record's `data` is a prefix of that body.
    """

    sha256: str
    data: bytes
    truncated: bool
    original_size: int
    truncation_reason: str | None


class BodyStore:
    """A sha256-keyed body store with per-response and per-run byte caps.

    The caps keep a prefix and never fail the flow. The reason names the last
    limit that removed bytes: `response_cap` when one response alone was too
    large, `run_cap` when the run's budget ran out.
    """

    def __init__(
        self,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_run_bytes: int = DEFAULT_MAX_RUN_BYTES,
    ) -> None:
        if max_response_bytes < 0 or max_run_bytes < 0:
            raise ValueError("a body cap must not be negative")
        self._max_response_bytes = max_response_bytes
        self._max_run_bytes = max_run_bytes
        self._bodies: dict[str, StoredBody] = {}
        self._retained_bytes = 0

    @property
    def retained_bytes(self) -> int:
        """The bytes the store retains, counted once per distinct body."""
        return self._retained_bytes

    def get(self, sha256: str) -> StoredBody | None:
        """The stored body for a digest, or `None` when it was never captured."""
        return self._bodies.get(sha256)

    def capture(self, body: bytes) -> StoredBody:
        """Store a decoded body and return its record and cap outcome."""
        original_size = len(body)
        kept = body
        truncated = False
        reason: str | None = None
        if len(kept) > self._max_response_bytes:
            kept = kept[: self._max_response_bytes]
            truncated = True
            reason = TRUNCATION_RESPONSE_CAP
        existing = self._bodies.get(hashlib.sha256(kept).hexdigest())
        if existing is not None:
            return existing
        remaining = self._max_run_bytes - self._retained_bytes
        if len(kept) > remaining:
            kept = kept[: max(remaining, 0)]
            truncated = True
            reason = TRUNCATION_RUN_CAP
            existing = self._bodies.get(hashlib.sha256(kept).hexdigest())
            if existing is not None:
                return existing
        digest = hashlib.sha256(kept).hexdigest()
        stored = StoredBody(
            sha256=digest,
            data=kept,
            truncated=truncated,
            original_size=original_size,
            truncation_reason=reason,
        )
        self._bodies[digest] = stored
        self._retained_bytes += len(kept)
        return stored


__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_MAX_RUN_BYTES",
    "MAX_URL_CHARS",
    "cap_url",
    "TRUNCATION_RESPONSE_CAP",
    "TRUNCATION_RUN_CAP",
    "Attribution",
    "BodyStore",
    "Flow",
    "StoredBody",
]
