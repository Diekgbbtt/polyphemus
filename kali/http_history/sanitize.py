"""Model-facing views of an artifact: no bodies, and redacted secrets.

Raw material (authorization headers, cookies, query/form values, body content)
stays in the store so a deterministic runtime can replay it. Anything an LLM or
a Langfuse span can see goes through here first.

The ONE exception is the search summary (`sanitize_summary`): its `url` and its
selected request and response headers are rendered VERBATIM, by operator
decision (2026-10-23 / 2026-10-25). A row shows the real `Authorization`,
`Cookie`, and `Set-Cookie` values and the raw URL, including userinfo and
sensitive query values, because the row must be the string the filter matched
on. The full view (`sanitize_artifact`) keeps redacting.
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

# The triage headers a candidate row carries, per side. A header outside these
# sets (`vary`, `date`, `user-agent`, `content-length`) is not rendered: the
# sizes already carry the length, and the rest is noise on every row.
SUMMARY_REQUEST_HEADERS = frozenset({
    "authorization", "content-type", "cookie", "origin", "referer",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "x-forwarded-protocol", "x-real-ip",
})
SUMMARY_RESPONSE_HEADERS = frozenset({
    "access-control-allow-credentials", "access-control-allow-headers",
    "access-control-allow-methods", "access-control-allow-origin",
    "access-control-expose-headers", "access-control-max-age",
    "content-security-policy", "content-security-policy-report-only",
    "content-type", "location", "server", "set-cookie",
    "www-authenticate", "x-cache", "x-cache-lookup", "x-frame-options",
    "x-powered-by",
})
SUMMARY_HEADER_VALUE_MAX = 256


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


_EXPOSED_CONTEXT_FIELDS = (
    "session_id", "run_id", "spec_id", "variant_ref", "exec_id",
    "derived_from", "replay_kind",
)


def _context_view(artifact: HttpArtifact) -> dict:
    """Explicit projection: anything not listed here never crosses the
    boundary (`source_ip` is the internal namespace address and stays out)."""
    return {name: getattr(artifact.capture_context, name)
            for name in _EXPOSED_CONTEXT_FIELDS}


def sanitize_artifact(artifact: HttpArtifact) -> dict:
    """A full sanitized record (no body content, no body reference)."""
    return {
        "schema_version": artifact.schema_version,
        "artifact_id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "capture_context": _context_view(artifact),
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


def _summary_headers(headers, selected: frozenset[str]) -> dict[str, list[str]]:
    """Only the selected keys, lowercased, every value kept, value capped.

    The search row is a menu: it shows the triage headers so the model can
    choose a candidate without fetching it. Duplicates stay in recorded order;
    a value over `SUMMARY_HEADER_VALUE_MAX` is truncated, never dropped.
    """
    out: dict[str, list[str]] = {}
    for name, value in headers or []:
        key = str(name).strip().lower()
        if key not in selected:
            continue
        text = str(value)
        if len(text) > SUMMARY_HEADER_VALUE_MAX:
            text = text[:SUMMARY_HEADER_VALUE_MAX - 3] + "..."
        out.setdefault(key, []).append(text)
    return out


def sanitize_summary(artifact: HttpArtifact) -> dict:
    """The candidate-row projection: identity, triage scalars, and lineage.

    The search row is a menu, not a record. The full view is
    `sanitize_artifact`, which carries `capture_state`, timings, and the
    connection record. Do not add a field here unless the search decision
    needs it on every row. `request_headers` and `response_headers` carry only
    the triage keys, and their values are verbatim. `url` is the recorded
    string, not `sanitize_url` output: a predicate matched the raw URL, so the
    row must display the same string.
    """
    response = artifact.response
    status = response.status if response is not None else None
    summary = {
        "artifact_id": artifact.artifact_id,
        "method": artifact.request.method,
        "url": artifact.request.url,
        "status": status,
    }
    if artifact.request.body_size:
        summary["request_size"] = artifact.request.body_size
    if response is not None and response.body_size:
        summary["response_size"] = response.body_size
    request_headers = _summary_headers(
        artifact.request.headers, SUMMARY_REQUEST_HEADERS)
    if request_headers:
        summary["request_headers"] = request_headers
    if response is not None:
        response_headers = _summary_headers(
            response.headers, SUMMARY_RESPONSE_HEADERS)
        if response_headers:
            summary["response_headers"] = response_headers
    if artifact.derived_from:
        summary["derived_from"] = artifact.derived_from
    if artifact.replay_kind:
        summary["replay_kind"] = artifact.replay_kind
    if artifact.error is not None:
        summary["error"] = artifact.error.type
    return summary
