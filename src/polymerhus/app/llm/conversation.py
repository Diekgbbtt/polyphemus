"""The conversation scope (D12): the ambient per-conversation identity that
provider request primitives bind at model construction.

Some upstreams require the CLIENT to identify the conversation on every request
(opencode-go enforces `x-opencode-session`: a stable per-conversation value since
2026-09-05, forwarded by the gateway's scoped `forward_client_headers_to_llm_api`
stanza). The conversation is the session seam's thread id - the one collision-free
instance identity (`session_address.SessionAddress.thread_id`) - and it is already
known where the turn is run, so the seam binds it for the turn's duration
(`conversation_scope`) and `build_chat_model` reads it when it builds the client.

Outside a session (one-shot roles, and any construction that legitimately runs
with no conversation) the fallback is a PROCESS-STABLE id: the upstream's hard
requirement is stability, and a per-process value keeps affinity as close as is
honestly possible rather than forging a conversation that does not exist. A blank
binding degrades to the fallback, never to an empty header value.

The module is pure (the `authn_loop.py` precedent): no I/O, no env var, no
import-time side effect beyond the one process id.
"""
from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from typing import Iterator

_CONVERSATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm-conversation-id", default=None
)
"""The ambient conversation binding: set by `conversation_scope`, read by the
provider request primitives. None means "no conversation bound" (the fallback)."""

_PROCESS_CONVERSATION_ID = uuid.uuid4().hex
"""The process-stable fallback id: stable across the process's calls (the
upstream's hard requirement) and distinct per process (affinity stays as close to
per-conversation as a conversation-less caller can honestly claim)."""


@contextmanager
def conversation_scope(conversation_id: str | None) -> Iterator[None]:
    """Bind `conversation_id` for the enclosed constructions, restoring the
    PREVIOUS binding on exit (nested scopes restore nesting, never the default).
    A None/blank id binds the fallback. Fail-safe by construction: the context
    manager always restores, so one turn's binding can never leak into the next."""
    token = _CONVERSATION_ID.set(conversation_id or None)
    try:
        yield
    finally:
        _CONVERSATION_ID.reset(token)


def current_conversation_id() -> str:
    """The ambient conversation id, or the process-stable fallback when none is
    bound. Never empty."""
    return _CONVERSATION_ID.get() or _PROCESS_CONVERSATION_ID


__all__ = ["conversation_scope", "current_conversation_id"]
