"""`http-artifact/v1` normalization and the HTTP-history batch client.

Spec: `docs/design/steel-crawl-spec.md` sections 10.1, 10.2, 10.3, and 12.

The normalizer turns one captured CDP `Flow` into the canonical artifact shape
without importing the Kali service: the crawler ships the same JSON contract,
and the edge validates it with its own model. The content id is deterministic
over the request and response truth, so a replay keeps the caller-provided id
and a first capture is reproducible.

The client batches at most 100 artifacts or 8 MiB, posts with the bearer token,
and retries from its cursor. It is injected with the HTTP callable, so the unit
tier never needs a live edge.

Nothing here performs I/O at import; `http_fn` is the only network seam.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.crawl.steel.capture.flow import Flow
from polymerhus.recon.crawl.steel.state import normalize_url

SCHEMA_VERSION = "http-artifact/v1"
MAX_ARTIFACTS = 100
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024

CaptureState = Literal["none", "captured", "empty", "omitted", "truncated"]
ReplayKind = Literal["baseline", "mutated"]

# Headers that carry a clock, a per-edge identity, or a trace id. They are
# evidence, but they are not the request's or response's content identity.
VOLATILE_HEADERS = frozenset(
    {
        "age",
        "cf-ray",
        "date",
        "etag",
        "expires",
        "last-modified",
        "server",
        "traceparent",
        "tracestate",
        "x-amz-cf-id",
        "x-request-id",
        "x-trace-id",
    }
)

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class NameValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: str


class BodyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    model_config = ConfigDict(frozen=True)

    client_address: str | None = None
    server_address: str | None = None
    tls: bool = False
    sni: str | None = None
    alpn: str | None = None
    protocol: str = "http"
    quic: bool = False
    websocket: bool = False


class TimingsRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_ms: float = 0.0


class CaptureContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = ""
    run_id: str = ""
    spec_id: str = ""
    variant_ref: str = ""
    exec_id: str = ""
    source_ip: str | None = None
    derived_from: str | None = None
    replay_kind: str | None = None


class HttpError(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str = ""
    message: str = ""


class HttpArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

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


def _canonical_headers(
    headers: Mapping[str, str] | Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Lower-cased, sorted, volatile-free header pairs for the content identity."""
    if isinstance(headers, Mapping):
        pairs = [(str(name), str(value)) for name, value in headers.items()]
    else:
        pairs = [(str(name), str(value)) for name, value in headers]
    return sorted(
        (name.lower(), value)
        for name, value in pairs
        if name.lower() not in VOLATILE_HEADERS
    )


def _crockford(data: bytes, length: int) -> str:
    value = int.from_bytes(data, "big")
    chars: list[str] = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def content_id(
    *,
    project: str,
    method: str,
    url: str,
    request_headers: Mapping[str, str] | Sequence[tuple[str, str]],
    request_body_sha256: str | None,
    status: int | None,
    response_headers: Mapping[str, str] | Sequence[tuple[str, str]],
    response_body_sha256: str | None,
) -> str:
    """The deterministic `http_` content id (spec 10.3).

    The canonical object carries the request and response truth only: the
    project, the uppercased method, the normalized URL, the canonical headers,
    the body digests, and the status. Volatile headers are removed, so a replay
    that differs only by a clock or an edge identity keeps the baseline id.
    """
    canonical = json.dumps(
        {
            "project": project,
            "method": method.upper(),
            "url": normalize_url(url),
            "request_headers": _canonical_headers(request_headers),
            "request_body_sha256": request_body_sha256,
            "status": status,
            "response_headers": _canonical_headers(response_headers),
            "response_body_sha256": response_body_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return "http_" + _crockford(digest, 26)


def _body_record(
    body: bytes | None,
    *,
    retained: bytes | None = None,
    truncated: bool = False,
    reason: str | None = None,
    original_size: int | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> tuple[BodyRecord, dict[str, bytes]]:
    """One body record, its digest-keyed content, and its capture state."""
    if body is None and retained is None:
        return BodyRecord(capture_state="none"), {}
    content = retained if retained is not None else (body or b"")
    size = original_size if original_size is not None else len(content)
    if not content and not truncated:
        return BodyRecord(body_size=size, capture_state="empty"), {}
    if len(content) > max_body_bytes:
        digest = hashlib.sha256(content).hexdigest()
        return (
            BodyRecord(
                body_size=size,
                body_hash=digest,
                capture_state="omitted",
                capture_reason=(
                    f"body exceeds capture limit ({len(content)} > {max_body_bytes} bytes)"
                ),
            ),
            {},
        )
    digest = hashlib.sha256(content).hexdigest()
    ref = f"sha256:{digest}"
    encoding = _encoding(content)
    state: CaptureState = "truncated" if truncated else "captured"
    return (
        BodyRecord(
            body_ref=ref,
            body_size=size,
            body_hash=digest,
            body_encoding=encoding,
            capture_state=state,
            capture_reason=reason,
        ),
        {ref: content},
    )


def _encoding(content: bytes) -> str:
    try:
        content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "binary"


def _cookies(pairs: Sequence[tuple[str, str]], name: str) -> list[NameValue]:
    values: list[NameValue] = []
    for header, value in pairs:
        if header.lower() != name:
            continue
        jar = SimpleCookie()
        try:
            jar.load(value)
        except Exception:  # noqa: BLE001 - a malformed cookie keeps the raw header
            continue
        for key, morsel in jar.items():
            values.append(NameValue(name=key, value=morsel.value))
    return values


def _query(url: str) -> list[NameValue]:
    try:
        query = urlsplit(url).query
    except ValueError:
        return []
    return [
        NameValue(name=name, value=value)
        for name, value in parse_qsl(query, keep_blank_values=True)
    ]


def _form(headers: Sequence[tuple[str, str]], body: str | None) -> list[NameValue]:
    if not body:
        return []
    content_type = ""
    for name, value in headers:
        if name.lower() == "content-type":
            content_type = value.lower()
            break
    if "application/x-www-form-urlencoded" not in content_type:
        return []
    return [
        NameValue(name=name, value=value)
        for name, value in parse_qsl(body, keep_blank_values=True)
    ]


def _header_list(headers: Mapping[str, str]) -> list[tuple[str, str]]:
    return [(str(name), str(value)) for name, value in headers.items()]


def normalize_cdp_flow(
    flow: Flow,
    *,
    project_id: str,
    capture_context: CaptureContext | None = None,
    artifact_id: str | None = None,
    derived_from: str | None = None,
    replay_kind: str | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    now: float | None = None,
) -> tuple[HttpArtifact, dict[str, bytes]]:
    """Map one captured CDP flow to `http-artifact/v1` (spec 10.1).

    The request body is the CDP `postData` string; the response body is the
    decoded bytes the sidecar retained. The artifact keeps the wire headers
    (order included), the additive cookie/query/form projections, the body
    references, the connection and timing facts, and the capture context.
    """
    context = capture_context or CaptureContext()
    request_headers = _header_list(flow.request_headers)
    response_headers = _header_list(flow.response_headers)
    request_body = (
        flow.request_body.encode("utf-8") if flow.request_body is not None else None
    )
    request_body_sha = (
        hashlib.sha256(request_body).hexdigest() if request_body else None
    )
    request_record, request_bodies = _body_record(
        request_body, max_body_bytes=max_body_bytes
    )
    response_record: ResponseRecord | None = None
    response_bodies: dict[str, bytes] = {}
    if flow.status is not None or flow.response_body is not None:
        body_record, response_bodies = _body_record(
            flow.response_body,
            truncated=flow.body_truncated,
            reason=flow.body_truncation_reason,
            original_size=flow.body_original_size,
            max_body_bytes=max_body_bytes,
        )
        response_record = ResponseRecord(
            **body_record.model_dump(),
            status=flow.status,
            reason="",
            http_version=flow.http_version or "",
            headers=response_headers,
            cookies=_cookies(response_headers, "set-cookie"),
            timestamp_start=flow.received_at or 0.0,
            timestamp_end=flow.received_at or 0.0,
        )
    created_at = now if now is not None else (flow.received_at or 0.0)
    response_body_sha = (
        flow.response_body_sha256
        if flow.response_body_sha256 is not None
        else (
            hashlib.sha256(flow.response_body).hexdigest()
            if flow.response_body
            else None
        )
    )
    identifier = artifact_id or content_id(
        project=project_id,
        method=flow.method,
        url=flow.url,
        request_headers=request_headers,
        request_body_sha256=request_body_sha,
        status=flow.status,
        response_headers=response_headers,
        response_body_sha256=response_body_sha,
    )
    scheme = urlsplit(flow.url).scheme.lower()
    artifact = HttpArtifact(
        artifact_id=identifier,
        project_id=project_id,
        capture_context=context,
        request=RequestRecord(
            **request_record.model_dump(),
            method=flow.method,
            url=flow.url,
            url_truncated=flow.url_truncated,
            url_original_length=flow.url_original_length,
            http_version=flow.http_version or "",
            headers=request_headers,
            cookies=_cookies(request_headers, "cookie"),
            query=_query(flow.url),
            form=_form(request_headers, flow.request_body),
            timestamp_start=flow.received_at or 0.0,
            timestamp_end=flow.received_at or 0.0,
        ),
        response=response_record,
        connection=ConnectionRecord(
            server_address=urlsplit(flow.url).netloc or None,
            tls=scheme in ("https", "wss"),
            sni=urlsplit(flow.url).hostname,
            alpn=flow.http_version if flow.http_version == "h3" else None,
            protocol="http",
            quic=flow.http_version == "h3",
            websocket=flow.resource_type == "WebSocket",
        ),
        timings=TimingsRecord(total_ms=0.0),
        error=HttpError(type="flow_error", message=flow.error) if flow.error else None,
        derived_from=derived_from or context.derived_from,
        replay_kind=replay_kind or context.replay_kind,
        created_at=created_at,
    )
    bodies: dict[str, bytes] = {}
    bodies.update(request_bodies)
    bodies.update(response_bodies)
    return artifact, bodies


# `http_fn(url, payload, headers) -> response mapping`: the one network seam.
HttpFn = Callable[[str, dict[str, Any], dict[str, str]], Mapping[str, Any]]


class HistoryIngestError(RuntimeError):
    """The edge could not accept a batch after the retry budget (spec 12)."""

    code = "http_history_flush_failed"

    def __init__(self, message: str, *, batch_index: int | None = None) -> None:
        self.batch_index = batch_index
        super().__init__(message)


@dataclass(frozen=True)
class IngestResult:
    created: int = 0
    duplicates: int = 0
    rejected: int = 0
    errors: tuple[dict[str, Any], ...] = ()
    retries: int = 0
    batches: int = 0


@dataclass(frozen=True)
class _Batch:
    artifacts: tuple[tuple[HttpArtifact, dict[str, bytes]], ...]
    size: int


class HistoryClient:
    """Batch the normalized artifacts to the HTTP-history edge (spec 10.2).

    The cursor is per client: a failed batch leaves `self.cursor` at that batch,
    so a caller that persists it (the run ledger) can retry without re-sending
    the accepted batches. The default transport is `httpx.post`; tests inject a
    fake callable.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        http_fn: HttpFn | None = None,
        max_artifacts: int = MAX_ARTIFACTS,
        max_bytes: int = MAX_PAYLOAD_BYTES,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http_fn = http_fn
        self._max_artifacts = max(1, max_artifacts)
        self._max_bytes = max(1, max_bytes)
        self._max_retries = max(0, max_retries)
        self.cursor = 0

    def ingest(
        self,
        project_id: str,
        run_id: str,
        artifacts: Sequence[tuple[HttpArtifact, Mapping[str, bytes]]],
    ) -> IngestResult:
        """Send every batch from the cursor, retrying the failed one."""
        batches = _batches(
            artifacts, self._max_artifacts, self._max_bytes
        )
        created = duplicates = rejected = retries = 0
        errors: list[dict[str, Any]] = []
        while self.cursor < len(batches):
            batch = batches[self.cursor]
            payload = _payload(project_id, run_id, batch)
            try:
                response = self._post(payload)
            except Exception as exc:
                if retries >= self._max_retries:
                    raise HistoryIngestError(
                        f"the HTTP-history edge rejected batch {self.cursor}: {exc}",
                        batch_index=self.cursor,
                    ) from exc
                retries += 1
                continue
            created += _count(response, "created")
            duplicates += _count(response, "duplicates")
            rejected += _count(response, "rejected")
            raw_errors = response.get("errors")
            if isinstance(raw_errors, list):
                errors.extend(
                    dict(error) for error in raw_errors if isinstance(error, Mapping)
                )
            self.cursor += 1
        return IngestResult(
            created=created,
            duplicates=duplicates,
            rejected=rejected,
            errors=tuple(errors),
            retries=retries,
            batches=len(batches),
        )

    def _post(self, payload: dict[str, Any]) -> Mapping[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if self._http_fn is not None:
            return self._http_fn(
                f"{self.base_url}/v1/ingest", payload, headers
            )
        import httpx

        response = httpx.post(
            f"{self.base_url}/v1/ingest",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise HistoryIngestError(
                f"the HTTP-history edge answered {response.status_code}"
            )
        data = response.json()
        if not isinstance(data, Mapping):
            raise HistoryIngestError("the HTTP-history edge returned no JSON object")
        return data


def _encoded_item_size(
    artifact: HttpArtifact, bodies: Mapping[str, bytes]
) -> int:
    """The wire size of one artifact item, including the base64 bodies.

    The edge caps the request's actual content length, so the client must count
    the encoded bytes, not the raw body bytes: base64 grows a body by 4/3 and
    the JSON envelope adds its own overhead.
    """
    encoded = json.dumps(
        artifact.model_dump(mode="json"), separators=(",", ":")
    )
    body_bytes = sum(
        len(base64.b64encode(body)) + 64 for body in bodies.values()
    )
    return len(encoded.encode("utf-8")) + body_bytes


def _batches(
    artifacts: Sequence[tuple[HttpArtifact, Mapping[str, bytes]]],
    max_artifacts: int,
    max_bytes: int,
) -> list[_Batch]:
    batches: list[_Batch] = []
    current: list[tuple[HttpArtifact, dict[str, bytes]]] = []
    size = 0
    for artifact, bodies in artifacts:
        item = (artifact, dict(bodies))
        item_size = _encoded_item_size(artifact, bodies)
        # 1 KiB of envelope (project/run ids, the two lists, and separators).
        if current and (
            len(current) >= max_artifacts
            or size + item_size + 1024 > max_bytes
        ):
            batches.append(_Batch(tuple(current), size))
            current, size = [], 0
        current.append(item)
        size += item_size
    if current:
        batches.append(_Batch(tuple(current), size))
    return batches


def _payload(
    project_id: str, run_id: str, batch: _Batch
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    bodies: list[dict[str, str]] = []
    for artifact, content in batch.artifacts:
        artifacts.append(artifact.model_dump(mode="json"))
        for ref, data in content.items():
            digest = ref.removeprefix("sha256:")
            bodies.append(
                {
                    "sha256": digest,
                    "encoding": "base64",
                    "data": base64.b64encode(data).decode("ascii"),
                }
            )
    return {
        "project_id": project_id,
        "run_id": run_id,
        "artifacts": artifacts,
        "bodies": bodies,
    }


def _count(response: Mapping[str, Any], key: str) -> int:
    try:
        return int(response.get(key, 0))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "CaptureContext",
    "DEFAULT_MAX_BODY_BYTES",
    "HistoryClient",
    "HistoryIngestError",
    "HttpArtifact",
    "IngestResult",
    "MAX_ARTIFACTS",
    "MAX_PAYLOAD_BYTES",
    "content_id",
    "normalize_cdp_flow",
]
