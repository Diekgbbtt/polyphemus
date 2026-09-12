"""Durable, per-project HTTP/HTTPS request/response history for Kali.

See docs/superpowers/specs/2026-09-12-http-proxy-history-196-design.md.
The package is stdlib-only at its core so it can be imported by the MCP
process, by the mitmproxy addon (separate Python environment), and by the
host test suite without side effects.
"""
from kali.http_history.ids import new_artifact_id, new_ulid
from kali.http_history.models import (
    SCHEMA_VERSION,
    CaptureContext,
    HttpArtifact,
)

__all__ = [
    "SCHEMA_VERSION",
    "CaptureContext",
    "HttpArtifact",
    "new_artifact_id",
    "new_ulid",
]
