"""The shared context-window failure classifier.

A provider context-length overflow is a deterministic input failure. It is not
a transient provider outage, not a retryable rate limit, and not a target
infeasibility. The summary compaction path and the pod failure taxonomy both
read this one classifier so they can never disagree.

The classifier is fail-open: an unrecognised exception is not a context error.
Import performs no I/O and imports no provider SDK.
"""
from __future__ import annotations

from typing import Any

# The window-cap markers, matched case-insensitively against the exception's
# name, message, `code`, and body. The set is a superset of the openai
# BadRequestError `code="context_length_exceeded"` and its message phrasing.
_TERMINAL_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "context length",
)


def classify_terminal(exc: Any) -> bool:
    """Detect a provider context-length or window-cap error.

    Inspects the exception type name, message, `code`, and body. The openai
    `BadRequestError` shape (`code` / `message` / `body["error"]`) is covered by
    each scan surface. Fail-open: anything unrecognised is not a context error.
    """
    try:
        if exc is None:
            return False
        haystack: list[str] = []
        type_name = type(exc).__name__
        if type_name:
            haystack.append(type_name)
        message = str(exc)
        if message:
            haystack.append(message)
        for attr in ("code", "message"):
            value = getattr(exc, attr, None)
            if isinstance(value, str):
                haystack.append(value)
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                for key in ("message", "code", "type"):
                    value = error.get(key)
                    if isinstance(value, str):
                        haystack.append(value)
        exploded = " ".join(haystack).lower()
        return any(marker in exploded for marker in _TERMINAL_MARKERS)
    except Exception:  # noqa: BLE001 - classification is fail-open by contract
        return False


__all__ = ["classify_terminal"]
