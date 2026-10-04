"""Parsing-error recovery at the session seam (#280).

One malformed model tool call (unparseable JSON arguments) is normalised by the
provider stack into an `AIMessage` whose `tool_calls` is EMPTY and whose
`invalid_tool_calls` carries the parse failure. The pinned `create_agent` routing
only inspects `tool_calls`, so the agent loop exits without answering; the wire
serializer (`langchain_openai.chat_models.base._convert_message_to_dict`) still
emits the invalid call as a `tool_calls` entry, so every later turn replays an
unanswered assistant tool call and the upstream rejects the request with HTTP
400 forever.

The fix is structural prevention, not request-scoped filtering: the ESTABLISHED
langchain algorithm (`AgentExecutor.handle_parsing_errors`, never ported to
`create_agent` - langchain #33504) answers each unanswered invalid call with an
error `ToolMessage` and routes back to the model, so the checkpoint trail is
CONTRACT-VALID and the next request pairs every wired tool call.

- `after_model` / `aafter_model` answer the invalid calls of the TAIL REQUEST - the
  last assistant tool-call request whose only trailing messages are its own `tool`
  answers. Walking back over trailing `ToolMessage`s is what makes the seam robust to
  the structured-output path (F13): `create_agent._handle_model_output` appends an
  answer `ToolMessage` for the structured call INSIDE the model node, so a sibling
  malformed ordinary call (the observed `graph_view` case) would otherwise sit one
  message behind the literal tail and stay unanswered. The answer is still appended at
  the tail; a `HumanMessage` (or a later assistant message) is a stop boundary and is
  never crossed, so a stale answer against a pre-boundary call is not written - the
  orphan answer the upstream rejects with HTTP 400 (#280 follow-up: the old whole-trail
  scan crossed a stop boundary and did exactly that).
  The jump back to the model for the BOUNDED in-turn retry is suppressed when the turn
  is already resolving (a trailing `tool` answer) or a VALID `tool_calls` entry is
  still unanswered (ToolNode must run it) - jumping in either case would bypass the
  tools routing and leave that valid call unanswered, a fresh poison. The invalid call
  is still answered in both cases, so the wire stays paired. Valid `tool_calls` are
  never touched (ToolNode owns those and runs after `after_model`).
- `before_model` / `abefore_model` reconcile a RESUMED turn positionally: only when
  the session seam saw pending `next` nodes before invoking (#280) does it insert
  each missing answer immediately after its assistant call, because the upstream
  requires the tool answer to directly follow the call. A completed turn carries no
  signal and is left untouched, so pre-existing completed-turn poison is not
  auto-repaired.
- Fail-open: any surprise calls the model unchanged and is logged, never raised.

The middleware is wired FIRST in `session._build_agent` (the one shared
construction point) so it is the after_model loop-exit node: every other
after_model hook (compaction ledger) runs before it, and its `jump_to="model"` is
honoured by `create_agent`'s model-to-tools routing. Importing this module
performs no I/O and needs no env var (CODING_STANDARD section 6); the langchain
middleware base class is imported lazily inside the factory.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage, ToolMessage

logger = logging.getLogger(__name__)

# Mirrors langchain's STRUCTURED_OUTPUT_ERROR_TEMPLATE ("Error: {error}. Please
# fix your mistakes.") so the model sees one consistent parse-failure voice.
PARSING_ERROR_TEMPLATE = "Error: {error}. Please fix your mistakes."

# The answer for a VALID tool call whose run stopped before ToolNode could execute
# it (an interrupted/resumed turn): the call must still be paired on the wire.
INTERRUPTED_TOOL_TEMPLATE = (
    "Error: the tool call was interrupted before it could be executed. "
    "Re-issue it if it is still needed."
)

# The bound on jump-retries for ONE turn: a model that poisons every attempt is
# bounced back at most this many times, then the final answer is appended without
# a jump so the turn ends on a valid trail. Env-overridable, fail-open.
_DEFAULT_MAX_ANSWERS = 3


def parsing_recovery_max_answers() -> int:
    """The per-turn bound on jump-retries (env `LLM_PARSING_RECOVERY_MAX_ANSWERS`).
    A negative or unparseable value falls back to the default (fail-open)."""
    try:
        value = int(os.environ.get("LLM_PARSING_RECOVERY_MAX_ANSWERS", "") or "")
        if value >= 0:
            return value
    except (TypeError, ValueError):
        pass
    return _DEFAULT_MAX_ANSWERS


def _call_field(call: Any, name: str) -> Any:
    """Read a field from an invalid tool call, which is a dict in the pinned
    langchain (a typed object would expose the same attribute)."""
    if isinstance(call, dict):
        return call.get(name)
    return getattr(call, name, None)


def _answered_ids(messages: Sequence[BaseMessage]) -> set[str]:
    return {m.tool_call_id for m in messages
            if isinstance(m, ToolMessage) and m.tool_call_id}


def _tail_request(messages: Sequence[BaseMessage]) -> AIMessage | None:
    """The last assistant tool-call request that is still the active tail.

    Walk back over any TRAILING `ToolMessage`s: a `tool` answer may only follow the
    assistant call it answers, so trailing answers are part of the request's own
    window. This matters because the framework's structured-output handling
    (`create_agent._handle_model_output`) appends an answer `ToolMessage` for the
    structured call INSIDE the model node - a sibling malformed call on that same
    assistant message would otherwise sit one message behind the literal tail and be
    invisible to the recovery (#280 follow-up residual, F13).

    The walk stops at the first non-tool message. That message is a request only when
    it is an `AIMessage`; a `HumanMessage` (or a later `AIMessage`) is a stop boundary
    and is never crossed, so a stale pre-boundary call is still left alone."""
    idx = len(messages) - 1
    while idx >= 0 and isinstance(messages[idx], ToolMessage):
        idx -= 1
    if idx < 0:
        return None
    candidate = messages[idx]
    if not isinstance(candidate, AIMessage):
        return None
    return candidate


def _has_unanswered_valid_tool_calls(
    messages: Sequence[BaseMessage], request: AIMessage
) -> bool:
    """Whether the tail request still carries a VALID `tool_calls` entry that no
    `ToolMessage` answers - i.e. ToolNode still has work to do for it. The recovery
    must not `jump_to="model"` in that case, because the jump bypasses the tools
    routing and would leave the valid call unanswered (a fresh poison)."""
    answered = _answered_ids(messages)
    for call in getattr(request, "tool_calls", None) or ():
        call_id = _call_field(call, "id")
        if call_id and call_id not in answered:
            return True
    return False


def unanswered_invalid_tool_calls(messages: Sequence[BaseMessage]) -> list[dict]:
    """The unanswered invalid tool calls of the TAIL REQUEST - the last assistant
    tool-call request that has no stop boundary after it.

    The answer is APPENDED at the tail, so it may only be written for a request whose
    trailing messages are its own `tool` answers (or nothing). Answering a call whose
    message sits before a stop boundary (a later `HumanMessage` or `AIMessage`) appends
    a `tool` message with no adjacent call - an orphan answer, which the upstream
    rejects with HTTP 400 ("Messages with role 'tool' must be a response to a preceding
    message with 'tool_calls'"). That post-turn-stop orphan is the #280 follow-up: the
    old whole-trail scan crossed a stop boundary and answered a call that was no longer
    the tail. Trailing `tool` answers are allowed because the structured-output path
    appends one for its own call before `after_model` runs; only `invalid_tool_calls`
    are considered (valid `tool_calls` belong to ToolNode, which runs after
    `after_model`); a call with no id cannot be answered and is skipped."""
    if not messages:
        return []
    last = _tail_request(messages)
    if last is None:
        return []
    answered = _answered_ids(messages)
    pending: list[dict] = []
    seen: set[str] = set()
    for call in getattr(last, "invalid_tool_calls", None) or ():
        call_id = _call_field(call, "id")
        if not call_id or call_id in answered or call_id in seen:
            continue
        seen.add(call_id)
        pending.append({
            "id": call_id,
            "name": _call_field(call, "name") or "",
            "error": _call_field(call, "error") or "the tool call arguments "
                                                    "could not be parsed",
        })
    return pending


def build_parsing_error_answers(messages: Sequence[BaseMessage]) -> list[ToolMessage]:
    """The error `ToolMessage`s that repair the LAST message's unanswered invalid
    calls - the model's just-produced (tail) request, and only it. Empty when the last
    message is not a tool-call request, or the trail is clean or already answered
    (idempotent); an answer is never appended against a non-tail request (the orphan
    answer the upstream rejects)."""
    return [
        ToolMessage(
            content=PARSING_ERROR_TEMPLATE.format(error=call["error"]),
            tool_call_id=call["id"],
            name=call["name"],
            status="error",
        )
        for call in unanswered_invalid_tool_calls(messages)
    ]


def reconcile_pending_tool_calls(
    messages: Sequence[BaseMessage],
) -> list[BaseMessage] | None:
    """The positionally repaired trail for a RESUMED turn, or None if no change.

    For every `AIMessage` carrying a tool call - VALID (`tool_calls`, interrupted
    before ToolNode ran) or INVALID (`invalid_tool_calls`) - whose id has no
    answering `ToolMessage` anywhere in the trail, an error `ToolMessage` is
    inserted IMMEDIATELY after that assistant message. Positional adjacency is the
    upstream contract: a `tool` answer must directly follow the assistant call it
    answers, so appending at the tail (after a later user message) is rejected.
    Idempotent: an id already answered is never answered twice. The trail order of
    every original message is preserved. Valid calls are only touched here because
    the gate ("the run was interrupted") guarantees ToolNode never got to them;
    `after_model` never touches them."""
    answered = _answered_ids(messages)
    seen: set[str] = set()
    repaired: list[BaseMessage] = []
    changed = False
    for message in messages:
        repaired.append(message)
        if not isinstance(message, AIMessage):
            continue
        answers: list[ToolMessage] = []
        for call in getattr(message, "invalid_tool_calls", None) or ():
            call_id = _call_field(call, "id")
            if not call_id or call_id in answered or call_id in seen:
                continue
            seen.add(call_id)
            changed = True
            answers.append(ToolMessage(
                content=PARSING_ERROR_TEMPLATE.format(
                    error=_call_field(call, "error") or "the tool call arguments "
                                                       "could not be parsed"),
                tool_call_id=call_id,
                name=_call_field(call, "name") or "",
                status="error"))
        for call in getattr(message, "tool_calls", None) or ():
            call_id = _call_field(call, "id")
            if not call_id or call_id in answered or call_id in seen:
                continue
            seen.add(call_id)
            changed = True
            answers.append(ToolMessage(
                content=INTERRUPTED_TOOL_TEMPLATE,
                tool_call_id=call_id,
                name=_call_field(call, "name") or "",
                status="error"))
        repaired.extend(answers)
    return repaired if changed else None


def parsing_recovery_middleware():
    """Build the recovery `AgentMiddleware`.

    `after_model` answers new invalid calls and jumps back to the model for a
    bounded retry; once the bound is reached it still answers (keeping the trail
    valid) but stops jumping so the turn ends. `before_model` reconciles a RESUMED
    turn positionally, only when the seam passed the pending-`next` signal.
    """
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import hook_config

    max_answers = parsing_recovery_max_answers()

    class ParsingRecoveryMiddleware(AgentMiddleware):
        """Answer invalid (unparseable) tool calls so the trail stays paired."""

        def __init__(self) -> None:
            self._answers_this_turn = 0

        def _detect(self, state):
            messages = state.get("messages") if isinstance(state, dict) else None
            if not isinstance(messages, list):
                return None
            return build_parsing_error_answers(messages)

        @hook_config(can_jump_to=["model"])
        def after_model(self, state, runtime=None):
            """Answer the TAIL REQUEST's new invalid calls and jump back to the model
            for a bounded retry; once the bound is reached, answer without jumping so
            the turn ends on a valid trail.

            The jump is suppressed when the answer is appended behind the framework's
            own processing: a trailing `ToolMessage` (the structured-output path
            answered its call first) means the turn is already resolving, and a
            still-unanswered VALID `tool_calls` entry means ToolNode has work to do -
            jumping would bypass the tools routing and leave it unanswered. In both
            cases the invalid call is still answered, so the wire stays paired. A
            request that sits before a stop boundary is never answered."""
            try:
                answers = self._detect(state)
                if answers is None:
                    return None
                if not answers:
                    # a real decision (or a clean reply) resets the streak
                    self._answers_this_turn = 0
                    return None
                self._answers_this_turn += 1
                messages = state.get("messages") if isinstance(state, dict) else []
                request = _tail_request(messages)
                resolving = request is None or messages[-1] is not request
                pending_valid = (request is not None
                                 and _has_unanswered_valid_tool_calls(messages, request))
                jump = (self._answers_this_turn <= max_answers
                        and not resolving and not pending_valid)
                logger.warning(
                    "parsing-error recovery: answering %d unanswered invalid "
                    "tool call(s) %s%s", len(answers),
                    [a.tool_call_id for a in answers],
                    "" if jump else " (no in-turn retry: the turn is resolving or a "
                                    "valid call is still pending)")
                if jump:
                    return {"messages": answers, "jump_to": "model"}
                return {"messages": answers}
            except Exception:  # noqa: BLE001 - fail-open, never into the turn
                logger.warning("parsing-error recovery after_model failed; "
                               "calling the model unchanged", exc_info=True)
                return None

        @hook_config(can_jump_to=["model"])
        def before_model(self, state, runtime=None):
            """Gated positional reconciliation for a RESUMED turn (#280).

            Fires ONLY when the session seam marked this turn as resuming a thread
            whose prior run left pending `next` nodes (`session_pending_next` in the
            config metadata). A normal, completed turn carries no signal and is left
            untouched - so pre-existing completed-turn poison is deliberately NOT
            auto-repaired. Never jumps and never touches the in-turn retry counter."""
            try:
                from langgraph.config import get_config

                pending = (get_config().get("metadata") or {}).get(
                    "session_pending_next")
                if not pending:
                    return None
                messages = state.get("messages") if isinstance(state, dict) else None
                if not isinstance(messages, list):
                    return None
                repaired = reconcile_pending_tool_calls(messages)
                if repaired is None:
                    return None
                from langgraph.graph.message import REMOVE_ALL_MESSAGES

                logger.warning(
                    "parsing-error recovery (resumed turn): reconciling the trail "
                    "with %d positional answer(s) before the next request",
                    len(repaired) - len(messages))
                return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *repaired]}
            except Exception:  # noqa: BLE001 - fail-open, never into the turn
                logger.warning("parsing-error recovery before_model failed; "
                               "calling the model unchanged", exc_info=True)
                return None

        @hook_config(can_jump_to=["model"])
        async def aafter_model(self, state, runtime=None):
            return self.after_model(state, runtime)

        async def abefore_model(self, state, runtime=None):
            return self.before_model(state, runtime)

    return ParsingRecoveryMiddleware()
