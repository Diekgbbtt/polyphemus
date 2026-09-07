"""The streamed session-turn core for #206 (#213, T1).

The pure mechanics that make streamed generation the DEFAULT session mode and give
the blackloop cut something to ride on, decoupled from the graph-wiring that lives
in `session.py`:

1. **EXTRACT** (`extract_reasoning` / `extract_content`): read the two output
   surfaces off a settled `AIMessage` OR a streamed `AIMessageChunk` - the
   `reasoning_content` (and `provider_specific_fields` fallback) and the generated
   `content`. This is UNCONDITIONAL (unlike `reasoning.extract_reasoning`, which is
   capability-profile-gated): the recovery turn must capture whatever reasoning the
   provider emitted even when the profile is unknown, so the extractor reads the
   raw surface tolerantly, never raising.

2. **SEGMENT** (`segment_reasoning`): a giant captured reasoning (the blackloop's
   131k-token stream) is NEVER one un-foldable span. It is segmented into ordered,
   bounded, window-fitting spans whose concatenation reconstructs the original
   exactly - the multi-span shape #210's progressive fold consumes (seam S2:
   span-granular, never a mid-span split, never a dropped tail). Span size is a
   character budget (deterministic, byte-exact under reconstruction).

3. **CUT** (`should_cut_stream`): the blackloop predicate - accumulated reasoning
   passed the detection bound with NO content emitted yet -> the session turn must
   stop streaming and route to the recovery turn. Once ANY content is present the
   model is answering, not looping, and no cut fires regardless of reasoning volume.

These functions are pure (no I/O, no env, no gateway); importing the module performs
no side effects (CODING_STANDARD section 6).
"""
from __future__ import annotations

from typing import Any

from polymerhus.app.llm.reasoning import (
    PROVIDER_SPECIFIC_FIELDS,
    SURFACE_REASONING_CONTENT,
    SURFACE_REASONING_DETAILS,
)


def extract_reasoning(message: Any) -> str | None:
    """Read the reasoning surface off an `AIMessage` / `AIMessageChunk`, tolerant of
    shape variance. Returns the reasoning string or None (absent)."""
    kwargs = getattr(message, "additional_kwargs", None) or {}
    value = kwargs.get(SURFACE_REASONING_CONTENT)
    parsed = _as_text(value)
    if parsed is not None:
        return parsed
    provider = kwargs.get(PROVIDER_SPECIFIC_FIELDS) or {}
    for surface in (SURFACE_REASONING_CONTENT, SURFACE_REASONING_DETAILS):
        parsed = _as_text(provider.get(surface))
        if parsed is not None:
            return parsed
    return None


def extract_content(message: Any) -> str:
    """Read the generated-text surface off a message/chunk to a plain string ("" when
    none) - the incremental answer a blackloop's absence of is measured against."""
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        else:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def segment_reasoning(text: str, *, max_span_chars: int) -> list[str]:
    """Segment a (possibly giant) reasoning string into ordered, bounded, window-fitting
    spans. Concatenation of the spans reconstructs the original exactly; a short input
    is a single unchanged span; a degenerate input yields no spans."""
    if not text or not text.strip():
        return []
    if len(text) <= max_span_chars:
        return [text]
    spans: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_span_chars, len(text))
        spans.append(text[start:end])
        start = end
    return spans


def should_cut_stream(
    *,
    accumulated_reasoning_chars: int | None,
    accumulated_content: str,
    reasoning_budget_chars: int,
) -> bool:
    """The blackloop predicate: accumulated reasoning passed the detection bound with
    no content emitted -> cut. Content present or reasoning under budget -> no cut."""
    reasoning = accumulated_reasoning_chars or 0
    return not accumulated_content and reasoning >= reasoning_budget_chars


def _as_text(value: Any) -> str | None:
    """Coerce a reasoning value to a non-empty string, tolerating the list-of-blocks
    shape some SDKs carry; None when absent/empty."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        joined = "".join(parts)
        return joined if joined else None
    return None
