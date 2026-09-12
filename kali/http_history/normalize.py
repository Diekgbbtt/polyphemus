"""Turn a completed mitmproxy flow into an immutable ``http-artifact/v1``.

The normalizer is duck-typed over mitmproxy's object shape so the unit tier can
exercise it with fakes and the addon can run it in mitmproxy's own Python 3.13
environment without importing the test helpers. It never raises on a partially
populated flow: a missing piece becomes an explicit null/omitted field.
"""
from __future__ import annotations

import hashlib
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl, urlsplit

from kali.http_history.ids import new_artifact_id
from kali.http_history.models import (
    SCHEMA_VERSION,
    BodyRecord,
    CaptureContext,
    ConnectionRecord,
    HttpArtifact,
    HttpError,
    NameValue,
    RequestRecord,
    ResponseRecord,
    TimingsRecord,
)

DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024


def normalize_flow(
    flow,
    *,
    project_id: str,
    capture_context: CaptureContext | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    artifact_id: str | None = None,
    derived_from: str | None = None,
    replay_kind: str | None = None,
    now: float | None = None,
) -> tuple[HttpArtifact, dict[str, bytes]]:
    """Return ``(artifact, bodies)`` for a completed flow."""
    import time

    context = capture_context or CaptureContext()
    request = getattr(flow, "request", None)
    response = getattr(flow, "response", None)
    error = getattr(flow, "error", None)

    request_record, request_bodies = _request_record(request, max_body_bytes)
    response_record, response_bodies = (
        _response_record(response, max_body_bytes) if response is not None else (None, {})
    )

    total_ms = _total_ms(request, response, now if now is not None else time.time())
    artifact = HttpArtifact(
        schema_version=SCHEMA_VERSION,
        artifact_id=artifact_id or new_artifact_id(),
        project_id=project_id,
        capture_context=context,
        request=request_record,
        response=response_record,
        connection=_connection_record(flow),
        timings=TimingsRecord(total_ms=total_ms),
        error=_error_record(error),
        derived_from=derived_from or context.derived_from,
        replay_kind=replay_kind or context.replay_kind,
        created_at=now if now is not None else time.time(),
    )
    bodies: dict[str, bytes] = {}
    bodies.update(request_bodies)
    bodies.update(response_bodies)
    return artifact, bodies


# --- messages -----------------------------------------------------------------


def _header_pairs(headers) -> list[tuple[str, str]]:
    if headers is None:
        return []
    items = getattr(headers, "items", None)
    if callable(items):
        try:
            return [(str(k), str(v)) for k, v in items(multi=True)]
        except TypeError:
            try:
                return [(str(k), str(v)) for k, v in items()]
            except Exception:  # noqa: BLE001
                return []
    if isinstance(headers, dict):
        return [(str(k), str(v)) for k, v in headers.items()]
    try:
        return [(str(k), str(v)) for k, v in headers]
    except Exception:  # noqa: BLE001
        return []


def _content_of(message) -> bytes:
    for attr in ("raw_content", "content"):
        try:
            value = getattr(message, attr)
        except Exception:  # noqa: BLE001 - mitmproxy's .content can raise
            continue
        if value is None:
            continue
        try:
            return bytes(value)
        except Exception:  # noqa: BLE001
            continue
    return b""


def _body_record(content: bytes, max_body_bytes: int) -> tuple[BodyRecord, dict[str, bytes]]:
    size = len(content)
    if size == 0:
        return BodyRecord(body_size=0, capture_state="empty"), {}
    digest = hashlib.sha256(content).hexdigest()
    if size > max_body_bytes:
        return (
            BodyRecord(
                body_ref=None,
                body_size=size,
                body_hash=digest,
                capture_state="omitted",
                capture_reason=(
                    f"body exceeds capture limit ({size} > {max_body_bytes} bytes)"
                ),
            ),
            {},
        )
    encoding = _encoding(content)
    ref = f"sha256:{digest}"
    return (
        BodyRecord(
            body_ref=ref,
            body_size=size,
            body_hash=digest,
            body_encoding=encoding,
            capture_state="captured",
        ),
        {ref: content},
    )


def _encoding(content: bytes) -> str:
    try:
        content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "binary"


def _cookies_from_header(pairs: list[tuple[str, str]], name: str) -> list[NameValue]:
    values: list[NameValue] = []
    for header, value in pairs:
        if header.lower() != name:
            continue
        jar = SimpleCookie()
        try:
            jar.load(value)
        except Exception:  # noqa: BLE001 - malformed cookie header: keep the raw header
            continue
        for key, morsel in jar.items():
            values.append(NameValue(name=key, value=morsel.value))
    return values


def _query_of(url: str) -> list[NameValue]:
    try:
        query = urlsplit(url).query
    except ValueError:
        return []
    return [NameValue(name=k, value=v) for k, v in parse_qsl(query, keep_blank_values=True)]


def _form_of(pairs: list[tuple[str, str]], content: bytes) -> list[NameValue]:
    content_type = ""
    for header, value in pairs:
        if header.lower() == "content-type":
            content_type = value.lower()
    if "application/x-www-form-urlencoded" not in content_type:
        return []
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return [NameValue(name=k, value=v) for k, v in parse_qsl(text, keep_blank_values=True)]


def _request_record(message, max_body_bytes: int) -> tuple[RequestRecord, dict[str, bytes]]:
    if message is None:
        return RequestRecord(), {}
    pairs = _header_pairs(getattr(message, "headers", None))
    content = _content_of(message)
    body, bodies = _body_record(content, max_body_bytes)
    url = getattr(message, "pretty_url", None) or getattr(message, "url", "") or ""
    record = RequestRecord(
        method=str(getattr(message, "method", "") or ""),
        url=str(url),
        http_version=str(getattr(message, "http_version", "") or ""),
        headers=pairs,
        cookies=_cookies_from_header(pairs, "cookie"),
        query=_query_of(str(url)),
        form=_form_of(pairs, content),
        timestamp_start=float(getattr(message, "timestamp_start", 0.0) or 0.0),
        timestamp_end=float(getattr(message, "timestamp_end", 0.0) or 0.0),
        **body.model_dump(),
    )
    return record, bodies


def _response_record(message, max_body_bytes: int) -> tuple[ResponseRecord, dict[str, bytes]]:
    pairs = _header_pairs(getattr(message, "headers", None))
    content = _content_of(message)
    body, bodies = _body_record(content, max_body_bytes)
    status = getattr(message, "status_code", None)
    if status is None:
        status = getattr(message, "status", None)
    record = ResponseRecord(
        status=int(status) if status is not None else None,
        reason=str(getattr(message, "reason", "") or ""),
        http_version=str(getattr(message, "http_version", "") or ""),
        headers=pairs,
        cookies=_cookies_from_header(pairs, "set-cookie"),
        timestamp_start=float(getattr(message, "timestamp_start", 0.0) or 0.0),
        timestamp_end=float(getattr(message, "timestamp_end", 0.0) or 0.0),
        **body.model_dump(),
    )
    return record, bodies


# --- connection / timing / error ----------------------------------------------


def _address(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and value:
        return f"{value[0]}:{value[1]}" if len(value) > 1 else str(value[0])
    return str(value)


def _connection_record(flow) -> ConnectionRecord:
    client = getattr(flow, "client_conn", None)
    server = getattr(flow, "server_conn", None)
    tls = bool(getattr(server, "tls_established", False)) if server is not None else False
    return ConnectionRecord(
        client_address=_address(getattr(client, "peername", None)),
        server_address=_address(getattr(server, "address", None)),
        tls=tls,
        sni=_str_or_none(getattr(server, "sni", None)),
        alpn=_str_or_none(getattr(server, "alpn", None)),
        protocol="https" if tls else "http",
    )


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _total_ms(request, response, now: float) -> float:
    start = _float_or_none(getattr(request, "timestamp_start", None))
    if start is None:
        return 0.0
    end = _float_or_none(getattr(response, "timestamp_end", None)) if response is not None else None
    if end is None:
        end = _float_or_none(getattr(response, "timestamp_start", None)) if response is not None else None
    if end is None:
        end = now
    return max(0.0, round((end - start) * 1000.0, 3))


def _float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error_record(error) -> HttpError | None:
    if error is None:
        return None
    message = getattr(error, "msg", None)
    if message is None and isinstance(error, BaseException):
        message = str(error)
    return HttpError(type=type(error).__name__, message=str(message or ""))
