"""Redact JavaScript intake URLs for the model-visible reader."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_SEGMENTS = {
    "auth",
    "key",
    "password",
    "secret",
    "session",
    "token",
}
_TOKENISH = re.compile(
    r"(?:[A-Fa-f0-9]{16,}|[A-Za-z0-9_-]{24,}|[^@\s]+@[^@\s]+\.[^@\s]+)"
)


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[REDACTED_URL]"

    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"

    redact_next = False
    path_segments: list[str] = []
    for segment in parts.path.split("/"):
        if not segment:
            path_segments.append(segment)
            continue
        if redact_next or _TOKENISH.fullmatch(segment):
            path_segments.append("[REDACTED]")
            redact_next = False
            continue
        path_segments.append(segment)
        redact_next = segment.lower() in _SENSITIVE_SEGMENTS
    path = "/".join(path_segments)

    query = urlencode(
        [(key, "[REDACTED]") for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    )
    fragment = "[REDACTED]" if parts.fragment else ""
    return urlunsplit((parts.scheme, netloc, path, query, fragment))
