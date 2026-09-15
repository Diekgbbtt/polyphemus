"""Unit tier: the streamed session-turn core for #206 (#213, T1).

The pure mechanics that make streamed generation the default session mode and give
the blackloop cut something to ride on: extracting `reasoning_content` / `content`
from a streamed chunk, segmenting captured reasoning into window-fitting spans
(the multi-span shape #210's progressive fold consumes, seam S2), and the blackloop
predicate (reasoning accumulated past a bound with no content emitted -> cut).

The unit tier touches no live model and no live gateway (CODING_STANDARD sections
6, 10): every function here is pure over messages/strings, driven by a mocked
chat-stream, never a real provider.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk

from polymerhus.app.llm.streaming import (
    extract_content,
    extract_reasoning,
    segment_reasoning,
    should_cut_stream,
)


def test_extract_reasoning_from_ai_message_and_chunk():
    """The reasoning surface on both a settled AIMessage and a streamed AIMessageChunk
    is read from `additional_kwargs.reasoning_content` (and the `provider_specific_fields`
    fallback), tolerant of shape variance."""
    msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "think think"},
    )
    assert extract_reasoning(msg) == "think think"

    chunk = AIMessageChunk(
        content="",
        additional_kwargs={"reasoning_content": "more"},
    )
    assert extract_reasoning(chunk) == "more"

    empty = AIMessage(content="answer only", additional_kwargs={})
    assert extract_reasoning(empty) is None


def test_extract_content_from_ai_message_and_chunk():
    """The generated-text surface is read from `.content`, the incremental answer a
    blackloop's absence of is measured against."""
    chunk = AIMessageChunk(content="the answer")
    assert extract_content(chunk) == "the answer"

    empty = AIMessageChunk(content="")
    assert extract_content(empty) == ""


def test_segment_reasoning_splits_a_giant_reasoning_into_window_fitting_spans():
    """A 131k-token reasoning (the blackloop) is never ONE un-foldable span: it is
    segmented into ordered, bounded, window-fitting spans whose concatenation
    reconstructs the original (never a mid-token split, never a dropped tail)."""
    original = "Need maybe mention the admin routes. " * 2000
    spans = segment_reasoning(original, max_span_chars=400)
    assert len(spans) > 1
    assert all(0 < len(s) <= 400 for s in spans)
    assert "".join(spans) == original  # order + content preserved exactly


def test_segment_reasoning_short_passes_through_unchanged():
    """A window-fitting reasoning is a single span, unchanged."""
    original = "a short reasoning"
    assert segment_reasoning(original, max_span_chars=400) == [original]


def test_segment_reasoning_never_returns_empty_spans():
    """A degenerate input (empty/whitespace) yields no spans; a boundary-length input
    yields exactly one span - never an empty fragment."""
    assert segment_reasoning("", max_span_chars=400) == []
    assert segment_reasoning("x" * 400, max_span_chars=400) == ["x" * 400]


def test_should_cut_stream_cuts_on_reasoning_without_content():
    """The blackloop signature: accumulated reasoning passed the detection bound with
    no content emitted -> the stream should be cut and routed to the recovery turn."""
    assert should_cut_stream(
        accumulated_reasoning_chars=6000, accumulated_content="",
        reasoning_budget_chars=4000,
    ) is True


def test_should_cut_stream_does_not_cut_with_content():
    """Once ANY content is emitted, the model is producing its answer - not a blackloop -
    regardless of how much reasoning preceded it."""
    assert should_cut_stream(
        accumulated_reasoning_chars=6000, accumulated_content="the answer",
        reasoning_budget_chars=4000,
    ) is False


def test_should_cut_stream_does_not_cut_below_budget():
    """Reasoning under the detection bound is normal deliberation - never cut."""
    assert should_cut_stream(
        accumulated_reasoning_chars=1000, accumulated_content="",
        reasoning_budget_chars=4000,
    ) is False
