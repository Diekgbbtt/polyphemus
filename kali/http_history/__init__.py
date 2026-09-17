"""Durable, per-project HTTP/HTTPS request/response history for Kali.

See docs/design/http-proxy-history-design.md (design) and
docs/design/http-proxy-history-test-evidence.md (runs and limits).
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
