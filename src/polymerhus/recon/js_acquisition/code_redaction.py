"""Bounded redaction for source-code windows, computed before slicing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

REDACTION_POLICY_ID = "js-source-redaction-v1"
_MARKERS = {
    "secret": "[REDACTED:secret]",
    "credential": "[REDACTED:credential]",
    "url": "[REDACTED:url]",
}


class CodeRedactionError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RedactedWindow:
    display: str
    original_start: int
    original_end: int
    original_sha256: str
    policy_id: str
    redaction_count: int
    redaction_kinds: tuple[str, ...]


@dataclass(frozen=True)
class PreparedRedaction:
    """Content/policy state reused by multiple source windows."""

    source: bytes
    spans: tuple[tuple[int, int, str], ...]
    byte_size: int
    policy_id: str = REDACTION_POLICY_ID

    def window(self, start: int, end: int) -> RedactedWindow:
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
            or end > self.byte_size
        ):
            raise CodeRedactionError("invalid_window")
        try:
            raw = self.source[start:end]
            raw.decode("utf-8")
        except UnicodeDecodeError:
            raise CodeRedactionError("invalid_utf8_window_boundary") from None
        fragments: list[str] = []
        redacted_kinds: list[str] = []
        position = start
        for span_start, span_end, kind in self.spans:
            if span_end <= start or span_start >= end:
                continue
            clipped_start = max(start, span_start)
            clipped_end = min(end, span_end)
            try:
                fragments.append(
                    self.source[position:clipped_start].decode("utf-8")
                )
            except UnicodeDecodeError:
                raise CodeRedactionError(
                    "invalid_utf8_window_boundary"
                ) from None
            fragments.append(_MARKERS.get(kind, _MARKERS["credential"]))
            redacted_kinds.append(kind)
            position = clipped_end
        try:
            fragments.append(self.source[position:end].decode("utf-8"))
        except UnicodeDecodeError:
            raise CodeRedactionError("invalid_utf8_window_boundary") from None
        return RedactedWindow(
            display="".join(fragments),
            original_start=start,
            original_end=end,
            original_sha256=hashlib.sha256(raw).hexdigest(),
            policy_id=self.policy_id,
            redaction_count=len(redacted_kinds),
            redaction_kinds=tuple(redacted_kinds),
        )


def _byte_prefix(text: str) -> list[int]:
    offsets = [0]
    total = 0
    for char in text:
        total += len(char.encode("utf-8"))
        offsets.append(total)
    return offsets


def _add_span(
    spans: list[tuple[int, int, str]],
    match: re.Match[str],
    group: int,
    kind: str,
) -> None:
    start, end = match.span(group)
    if end > start:
        spans.append((start, end, kind))


def _redaction_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    # Query values remain structurally visible while their values are masked.
    for match in re.finditer(
        r"(?P<prefix>[?&][A-Za-z0-9_.~-]+=)(?P<value>[^&'\"\s<>]+)",
        text,
    ):
        _add_span(spans, match, "value", "secret")
    # Userinfo in an absolute URL is credential material, never source context.
    for match in re.finditer(r"https?://[^/@\s]+@", text, re.I):
        _add_span(spans, match, 0, "credential")
    # Bearer/basic values and common cookie assignments.
    for match in re.finditer(
        r"(?i)\b(?:authorization\s*:\s*)?(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}",
        text,
    ):
        _add_span(spans, match, 0, "credential")
    for match in re.finditer(
        r"(?i)\b(?:session|sessionid|auth|jwt)\s*=\s*[^'\"`;\s]+",
        text,
    ):
        value = re.search(r"=\s*", match.group(0))
        if value:
            start = match.start() + value.end()
            spans.append((start, match.end(), "secret"))
    # Assignment-like key/value literals. The key may itself contain a sensitive
    # word, e.g. longSecret; the getter call localStorage.getItem("token") does
    # not match because it has no assignment separator after the key.
    key_pattern = (
        r"(?i)\b[\w$]*(?:token|secret|password|passwd|api[_-]?key|"
        r"access[_-]?key|cookie|authorization)[\w$]*\b"
    )
    quoted = re.compile(
        key_pattern
        + r"\s*[:=]\s*(?P<quote>['\"`])(?P<value>.*?)(?P=quote)",
        re.S,
    )
    unquoted = re.compile(
        key_pattern + r"\s*[:=]\s*(?P<value>[^\s,;)}\]]+)",
        re.I,
    )
    for pattern in (quoted, unquoted):
        for match in pattern.finditer(text):
            _add_span(spans, match, "value", "secret")
    for match in re.finditer(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", text):
        _add_span(spans, match, 0, "credential")

    merged: list[tuple[int, int, str]] = []
    for start, end, kind in sorted(spans):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end, previous_kind = merged[-1]
            merged[-1] = (
                previous_start,
                max(previous_end, end),
                (
                    previous_kind
                    if previous_kind == kind
                    else "credential"
                ),
            )
        else:
            merged.append((start, end, kind))
    return merged


def prepare_redaction(source: bytes) -> PreparedRedaction:
    if not isinstance(source, bytes):
        raise CodeRedactionError("source_must_be_bytes")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        raise CodeRedactionError("unsupported_encoding") from None
    byte_offsets = _byte_prefix(text)
    spans = _redaction_spans(text)
    return PreparedRedaction(
        source=source,
        spans=tuple(
            (
                byte_offsets[span_start],
                byte_offsets[span_end],
                kind,
            )
            for span_start, span_end, kind in spans
        ),
        byte_size=len(source),
    )


def redact_window(source: bytes, start: int, end: int) -> RedactedWindow:
    """Compatibility interface; prepares once and renders one window."""
    return prepare_redaction(source).window(start, end)


__all__ = [
    "CodeRedactionError",
    "PreparedRedaction",
    "REDACTION_POLICY_ID",
    "RedactedWindow",
    "prepare_redaction",
    "redact_window",
]
