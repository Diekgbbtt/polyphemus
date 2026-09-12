"""Model-facing views of an artifact: no raw secrets, cookies, or bodies.

Raw material (authorization headers, cookies, query/form values, body content)
stays in the store so a deterministic runtime can replay it. Anything an LLM or
a Langfuse span can see goes through here first.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from kali.http_history.models import HttpArtifact

REDACTED = "[redacted]"

_SENSITIVE_KEY_RE = re.compile(
    r"(auth|token|secret|passw|api[-_]?key|apikey|session|sid|cookie|csrf|jwt|"
    r"bearer|credential|signature|otp)",
    re.IGNORECASE,
)
_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-amz-security-token",
    "x-session-token",
}


def _redact_if_sensitive(name: str, value: str) -> str:
    if (name or "").lower() in _SENSITIVE_HEADERS or _SENSITIVE_KEY_RE.search(name or ""):
        return REDACTED
    return value


def sanitize_url(url: str) -> str:
    """Drop userinfo and redact sensitive query values."""
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    netloc = parts.netloc.rsplit("@", 1)[-1] if "@" in parts.netloc else parts.netloc
    if parts.query:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        query = "&".join(
            f"{name}={_redact_if_sensitive(name, value)}" for name, value in pairs
        )
    else:
        query = ""
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _body_view(message) -> dict:
    if message is None:
        return {}
    return {
        "size": message.body_size,
        "encoding": message.body_encoding,
        "capture_state": message.capture_state,
        "capture_reason": message.capture_reason,
    }


def _message_view(message, *, request: bool) -> dict:
    view: dict = {
        "http_version": message.http_version,
        "headers": [[n, _redact_if_sensitive(n, v)] for n, v in message.headers],
        "cookies": [{"name": c.name, "value": REDACTED} for c in message.cookies],
        "body": _body_view(message),
        "timestamp_start": message.timestamp_start,
        "timestamp_end": message.timestamp_end,
    }
    if request:
        view["method"] = message.method
        view["url"] = sanitize_url(message.url)
        view["query"] = [
            {"name": q.name, "value": _redact_if_sensitive(q.name, q.value)}
            for q in message.query
        ]
        view["form"] = [
            {"name": f.name, "value": _redact_if_sensitive(f.name, f.value)}
            for f in message.form
        ]
    else:
        view["status"] = message.status
        view["reason"] = message.reason
    return view


def sanitize_artifact(artifact: HttpArtifact) -> dict:
    """A full sanitized record (no body content, no body reference)."""
    return {
        "schema_version": artifact.schema_version,
        "artifact_id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "capture_context": artifact.capture_context.model_dump(),
        "request": _message_view(artifact.request, request=True),
        "response": None
        if artifact.response is None
        else _message_view(artifact.response, request=False),
        "connection": artifact.connection.model_dump(),
        "timings": artifact.timings.model_dump(),
        "error": None if artifact.error is None else artifact.error.model_dump(),
        "derived_from": artifact.derived_from,
        "replay_kind": artifact.replay_kind,
        "created_at": artifact.created_at,
    }


def sanitize_summary(artifact: HttpArtifact) -> dict:
    """The compact search-row projection: identity + safe scalars only."""
    try:
        host = urlsplit(artifact.request.url).hostname or ""
    except ValueError:
        host = ""
    response = artifact.response
    status = response.status if response is not None else None
    return {
        "artifact_id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "created_at": artifact.created_at,
        "method": artifact.request.method,
        "url": sanitize_url(artifact.request.url),
        "host": host,
        "status": status,
        "status_class": f"{status // 100}xx" if isinstance(status, int) else None,
        "http_version": artifact.request.http_version,
        "request_size": artifact.request.body_size,
        "response_size": response.body_size if response is not None else 0,
        "timing_ms": artifact.timings.total_ms,
        "tls": artifact.connection.tls,
        "error_type": artifact.error.type if artifact.error is not None else None,
        "derived_from": artifact.derived_from,
        "replay_kind": artifact.replay_kind,
    }
