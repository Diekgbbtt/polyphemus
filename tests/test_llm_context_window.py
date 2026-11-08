"""Unit tier: the shared context-window classifier.

One classifier is the source of truth for the summary compaction path and the
pod failure taxonomy. A provider 400 that names a context-length overflow is a
deterministic input failure, not a transient provider outage and not a target
infeasibility.
"""
from __future__ import annotations

from polymerhus.app.llm import summary
from polymerhus.app.llm.context_window import classify_terminal


class FakeBadRequest(Exception):
    code = "context_length_exceeded"
    body = {
        "error": {
            "message": "This model's maximum context length is 128000 tokens.",
            "code": "context_length_exceeded",
        }
    }


def test_the_openai_context_length_shape_is_recognised():
    assert classify_terminal(FakeBadRequest("request too large")) is True


def test_the_message_markers_are_recognised_case_insensitively():
    assert classify_terminal(Exception("maximum CONTEXT LENGTH exceeded")) is True
    assert classify_terminal(Exception("context length 150000")) is True


def test_unrelated_provider_errors_are_not_context_errors():
    assert classify_terminal(Exception("429 rate limit")) is False
    assert classify_terminal(Exception("500 internal server error")) is False
    assert classify_terminal(None) is False


def test_the_summary_module_uses_the_same_classifier():
    assert summary.classify_terminal is classify_terminal
