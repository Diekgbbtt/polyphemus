"""Unit tier: the conversation scope (D12) - the ambient per-conversation identity
provider request primitives bind at model construction (opencode-go's
`x-opencode-session`). Pure: no network, no client construction."""
from __future__ import annotations

from polymerhus.app.llm.conversation import (
    conversation_scope,
    current_conversation_id,
)


def test_the_fallback_is_stable_within_the_process():
    first = current_conversation_id()
    second = current_conversation_id()
    assert first, "the fallback id must never be empty"
    assert first == second, "the fallback must be stable across calls"


def test_the_scope_binds_and_restores():
    fallback = current_conversation_id()
    with conversation_scope("run-1:crawler"):
        assert current_conversation_id() == "run-1:crawler"
        with conversation_scope("run-1:triager"):
            assert current_conversation_id() == "run-1:triager"
        assert current_conversation_id() == "run-1:crawler"
    assert current_conversation_id() == fallback


def test_a_blank_scope_binds_the_fallback_not_an_empty_id():
    with conversation_scope(""):
        assert current_conversation_id(), "a blank scope degrades to the fallback"
