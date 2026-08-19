"""The session path: a resumable, tool-calling LLM agent (#94).

A `session`-mode role (agent_mode="session", `app/llm/providers.py`) runs as a
proper long-horizon agent via `langchain.agents.create_agent`: it binds its tools
through the **tool_calling** API (not the legacy one-shot `function_calling`
structured path, which stays only on the `invoke_role` one_shot seam), runs the
model<->tool loop, and persists its conversation across invocations through an
INJECTED checkpointer keyed by `thread_id` (short-term memory the next turn
resumes from). This is the counterpart to the stateless `invoke_role` path.

Two capabilities are NOT built here, they plug in through the seams this component
exposes:

- **Context-window compaction + memory** (#98/#99): `middleware` (langchain
  `AgentMiddleware`: `before_model`/`after_model`/`before_tool`/`after_tool`), which
  fire at the exact trigger points those tickets need (after an LLM turn and after tool
  output), plus the `store` seam (#85) for long-term/cross-thread memory. Inert
  (empty) by default.
- **The parent-to-child memory READ** lives here too: `read_session_memory` /
  `aread_session_memory` read a sub-agent's OWN persisted thread from the shared
  checkpointer - the primitive a "read my sub-agent's reasoning" TOOL calls, generic
  because every stateful child lives in the same store under its `SessionAddress`.
- **Dynamic inference-method / tool-capability configuration**: also supplied as
  `middleware`, so a provider whose model cannot call tools natively is caught
  early / degraded by that layer - this component never hardcodes the method or
  asserts a provider capability.

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6): the model and the checkpointer resolve on call, never at import.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# The collision-free session ADDRESSING lives in `session_address.py` (the typed,
# per-module `SessionAddress` value objects). This module consumes a thread id (or an
# address that yields one); it never hand-builds one.


def _as_thread_id(thread) -> str:
    """Accept either a raw `thread_id` string or a `SessionAddress` (any object exposing
    `.thread_id`), so a caller can pass the typed address directly."""
    return getattr(thread, "thread_id", thread)


@dataclass(frozen=True)
class SessionTurn:
    """One turn's result: the model's `content` (the last message's text, or the
    parsed object when a `response_format` schema is set), and the full post-turn
    `messages` trail - the persisted short-term memory - for a caller that wants
    to inspect it."""

    content: Any
    messages: list[BaseMessage]
    thread_id: str


# `model_factory(role_id) -> chat model`. Defaults to the session-path builder
# `chat_model_for`, so a real turn uses the role's configured model; tests inject
# a fake. `create_agent` binds the tools onto this model (tool_calling).
ModelFactory = Callable[[str], Any]


def _default_model_factory(role_id: str) -> Any:
    from polymerhus.app.llm.roles import chat_model_for

    return chat_model_for(role_id)


def _observe_config(config: dict, role_id: str, thread_id: str) -> dict:
    """Attach Langfuse callbacks + honest per-role_id/thread attribution (the #18
    recipe, mirrored from `analysis/supervisor._observability_config`). Empty
    callbacks (Langfuse unconfigured) are inert; fail-open."""
    from polymerhus.app.observability import get_langfuse_callbacks

    config = dict(config)
    config["callbacks"] = get_langfuse_callbacks()
    config["metadata"] = {
        "langfuse_session_id": thread_id,
        "langfuse_tags": ["session", role_id],
        "role_id": role_id,
    }
    return config


def _attach_readability_metadata(config: dict, values: dict | None) -> None:
    """T6 (D11 item 4): merge the dedicated `reasoning_readability` llm-response
    field into the config metadata from a pre-read thread state - "replayed"
    when the turn BEFORE the current one had its reasoning re-persisted by the
    replay pipeline, "absent" otherwise (same session trace:
    `langfuse_session_id`). The field rides the metadata the Langfuse
    CallbackHandler records onto the llm response of the REQUEST that carries
    the replayed prefix. Fail-open: no state (or an unreadable state) simply
    omits the field."""
    if values is None:
        return
    messages = values.get("messages")
    if not isinstance(messages, list):
        return
    from polymerhus.app.llm.reasoning import reasoning_readability_metadata

    config["metadata"].update(reasoning_readability_metadata(messages))


def _build_agent(
    role_id: str,
    *,
    tools: Sequence,
    response_format,
    system_prompt: str | None,
    middleware: Sequence,
    store,
    checkpointer,
    model_factory: ModelFactory | None,
):
    """Build the `create_agent` tool-calling agent shared by the sync/async turns.

    `store` (#85 long-term memory) and `middleware` (#95 compaction + the
    inference-method-config workstream) are passed straight through - inert when
    empty. This is the ONE place tool_calling is wired, so the two turn entry
    points can never drift."""
    from langchain.agents import create_agent

    model = (model_factory or _default_model_factory)(role_id)
    kwargs: dict = {"tools": list(tools), "checkpointer": checkpointer}
    if system_prompt is not None:
        kwargs["system_prompt"] = system_prompt
    if response_format is not None:
        kwargs["response_format"] = response_format
    if middleware:
        kwargs["middleware"] = list(middleware)
    if store is not None:
        kwargs["store"] = store
    return create_agent(model, **kwargs)


def _turn_config(role_id: str, thread_id: str, observe: bool) -> dict:
    config: dict = {"configurable": {"thread_id": thread_id}}
    return _observe_config(config, role_id, thread_id) if observe else config


def _to_turn(result: dict, response_format, thread_id: str) -> SessionTurn:
    messages = result.get("messages", [])
    if response_format is not None:
        content = result.get("structured_response")
    else:
        content = messages[-1].content if messages else None
    return SessionTurn(content=content, messages=list(messages), thread_id=thread_id)


def _resolve_reasoning_profile(role_id: str):
    """The T3 capability profile for the replay pipeline, fail-open (D7).

    Resolved at TURN CONSTRUCTION (the top of `run_session_turn` /
    `arun_session_turn`, before the agent is built and invoked) and handed to
    the replay hook - NEVER resolved on the turn-return path and never
    mid-session (D6/D7: the capability reader is off the #73 retry axis). The
    reader is process-lifetime resolve-and-hold (`capability.py`): the first
    construction per process may perform the one bounded `/model/info` read
    (10s/5s, fail-open) BEFORE the model call - it can never delay the turn's
    RESULT - and every later construction is a cache hit.

    ANY failure - unset role env vars, a degraded reader, a config lie -
    degrades to None (profile unknown per D5 Rule 1): the session must
    always start. Unknown means the pipeline no-ops and gaps are logged."""
    try:
        from polymerhus.app.llm.capability import resolve_capability
        from polymerhus.app.llm.providers import resolve_role

        provider, model = resolve_role(role_id)
        return resolve_capability(provider, model)
    except Exception:  # noqa: BLE001 - fail-open, never into the turn path
        return None


def _log_replay_observability(report: dict, role_id: str, thread_id: str) -> None:
    """CACHE-TRACK + readability: the per-turn llm-response observability line.
    `cached_tokens` (usage observability) and the D11 grey-point heuristic
    (interleaved + shape + cache-presence - low confidence) are recorded as
    fields, NEVER gating and never on the #73 retry/timeout axis (D7):
    this hook is purely descriptive, non-blocking, fail-open."""
    logger.info(
        "llm-response: role=%s thread=%s reasoning_readability=%s surface=%s "
        "encrypted=%s cached_tokens=%s heuristic=%s",
        role_id, thread_id, report.get("readability"), report.get("surface"),
        report.get("encrypted"), report.get("cached_tokens"), report.get("heuristic"))


def _replay_reasoning(agent, config: dict, result: dict, role_id: str,
                      thread_id: str, profile) -> None:
    """T6 REPLAY at the session seam boundary: parse the turn's assistant
    message(s) per the T3 profile and RE-PERSIST them with the reasoning
    attached, byte-identical, so the next turn restores the replay-ready
    prefix and provider-native KV caching can hit (D8.1/D11.4).

    The re-persist goes through `agent.update_state` - the official langgraph
    state-replacement API - so it works on any checkpointer. Encrypted
    reasoning is re-persisted as well (readability tracked, never skipped).
    Failure to re-persist is logged and swallowed: replay is best-effort and
    must never break the turn. The `profile` is resolved at turn CONSTRUCTION
    (see `_resolve_reasoning_profile`) - never here, never on the return path
    (D6/D7: the reader is off the turn path; no capability read delays the
    turn's result)."""
    from polymerhus.app.llm.reasoning import (
        replay_assistant_reasoning,
    )

    messages = result.get("messages", [])
    if not isinstance(messages, list):
        return
    replacement, report = replay_assistant_reasoning(list(messages), profile)
    if replacement is not None:
        try:
            agent.update_state(config, {"messages": replacement})
        except Exception as exc:  # noqa: BLE001 - replay must never break the turn
            logger.warning(
                "reasoning replay re-persist failed for %s/%s: %s (turn result "
                "unchanged; replay is best-effort, never gating)",
                role_id, thread_id, exc)
            return
    _log_replay_observability(report, role_id, thread_id)


async def _areplay_reasoning(agent, config: dict, result: dict, role_id: str,
                             thread_id: str, profile) -> None:
    """Async replay re-persist (`aupdate_state`) - identical contract to
    `_replay_reasoning`, for the event-loop parent entry point."""
    from polymerhus.app.llm.reasoning import (
        replay_assistant_reasoning,
    )

    messages = result.get("messages", [])
    if not isinstance(messages, list):
        return
    replacement, report = replay_assistant_reasoning(list(messages), profile)
    if replacement is not None:
        try:
            await agent.aupdate_state(config, {"messages": replacement})
        except Exception as exc:  # noqa: BLE001 - replay must never break the turn
            logger.warning(
                "reasoning replay re-persist failed for %s/%s: %s (turn result "
                "unchanged; replay is best-effort, never gating)",
                role_id, thread_id, exc)
            return
    _log_replay_observability(report, role_id, thread_id)


def run_session_turn(
    role_id: str,
    thread_id: str,
    new_messages: Sequence[BaseMessage],
    *,
    checkpointer,
    tools: Sequence = (),
    response_format=None,
    system_prompt: str | None = None,
    middleware: Sequence = (),
    store=None,
    model_factory: ModelFactory | None = None,
    observe: bool = True,
) -> SessionTurn:
    """Run one resumable, tool-calling turn of a session-mode role (sync).

    The `checkpointer` (keyed by `thread_id`, e.g. `f"{run_id}:{role_id}"`) restores
    the thread's prior messages; `new_messages` are appended; the agent runs its
    model<->tool loop (`tools` bound via tool_calling) to a final answer, which is
    persisted back so the next turn resumes from here. `response_format` returns a
    parsed structured object as `content`."""
    profile = _resolve_reasoning_profile(role_id)
    agent = _build_agent(
        role_id, tools=tools, response_format=response_format, system_prompt=system_prompt,
        middleware=middleware, store=store, checkpointer=checkpointer, model_factory=model_factory,
    )
    config = _turn_config(role_id, thread_id, observe)
    if observe and checkpointer is not None:
        _attach_readability_metadata(
            config, _read_thread_state(checkpointer, thread_id))
    result = agent.invoke({"messages": list(new_messages)}, config)
    _replay_reasoning(agent, config, result, role_id, thread_id, profile)
    return _to_turn(result, response_format, thread_id)


async def arun_session_turn(
    role_id: str,
    thread_id: str,
    new_messages: Sequence[BaseMessage],
    *,
    checkpointer,
    tools: Sequence = (),
    response_format=None,
    system_prompt: str | None = None,
    middleware: Sequence = (),
    store=None,
    model_factory: ModelFactory | None = None,
    observe: bool = True,
) -> SessionTurn:
    """Async-native turn (`ainvoke`) - the entry point an async-native PARENT
    coordinator uses (ratified #94: the hunt-orchestrator first), so it can spawn
    and monitor child sessions without blocking its own loop. Identical contract to
    `run_session_turn`; pass an async checkpointer (`AsyncPostgresSaver`, already
    used by the analysis supervisor) in production."""
    profile = _resolve_reasoning_profile(role_id)
    agent = _build_agent(
        role_id, tools=tools, response_format=response_format, system_prompt=system_prompt,
        middleware=middleware, store=store, checkpointer=checkpointer, model_factory=model_factory,
    )
    config = _turn_config(role_id, thread_id, observe)
    if observe and checkpointer is not None:
        _attach_readability_metadata(
            config, await _aread_thread_state(checkpointer, thread_id))
    result = await agent.ainvoke({"messages": list(new_messages)}, config)
    await _areplay_reasoning(agent, config, result, role_id, thread_id, profile)
    return _to_turn(result, response_format, thread_id)


def _structured_response_format(schema):
    """Wrap a structured-output `schema` in `ToolStrategy` (tool-calling) - the
    `function_calling`-equivalent, so an open `dict` field (e.g. `Observation.anchor`,
    #44) survives, unlike the provider-native json_schema strict mode which 400s on
    it. This is why the one_shot path pins `method="function_calling"`; the session
    path pins `ToolStrategy` for the same reason."""
    from langchain.agents.structured_output import ToolStrategy

    return ToolStrategy(schema)


def stateful_turn(
    role_id: str,
    thread,
    new_messages: Sequence[BaseMessage],
    *,
    checkpointer,
    schema=None,
    system_prompt: str | None = None,
    model_factory: ModelFactory | None = None,
    middleware: Sequence = (),
    observe: bool = True,
):
    """The UBIQUITOUS stateful-agent invocation (#94): one turn of a sequentially
    dispatched agent that RESUMES from its OWN per-instance checkpoint and appends this
    turn to it.

    Every stateful agent in the project follows this one pattern - it is `structurally
    sync` (dispatched sequentially, so no async needed) yet STATEFUL. `thread` is a typed
    `SessionAddress` (`session_address.py`) - or, for back-compat, a raw thread-id string
    - so each concurrent instance has a DISTINCT checkpoint the next session resumes from
    soundly (never a shared, colliding key). Structured output (when `schema` is given)
    goes through `ToolStrategy` (the function_calling-equivalent, #44-safe). Returns the
    parsed `schema` object (or None), or the text content when no schema - the same shape
    the legacy `invoke_role` seam returned, so a call site swaps in place."""
    response_format = _structured_response_format(schema) if schema is not None else None
    return run_session_turn(
        role_id, _as_thread_id(thread), new_messages,
        checkpointer=checkpointer, response_format=response_format,
        system_prompt=system_prompt, model_factory=model_factory, observe=observe,
        middleware=middleware,
    ).content


def _read_thread_state(checkpointer, thread_id: str) -> dict | None:
    """The latest persisted state dict for a session thread, or None when the
    thread has no checkpoint yet (or the read fails - fail-open, mirroring the
    rest of the seam).

    The FULL read (`get_tuple` AND the `tup.checkpoint` access) sits in the try
    - a checkpointer with a coroutine-shaped `get_tuple` (an async-def saver
    on the sync path) degrades to None instead of crashing the turn (the
    crash and the async-path omission are #109 REDO findings; the async entry
    goes through `_aread_thread_state` instead, where the coroutine is
    awaited)."""
    try:
        tup = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
        if inspect.isawaitable(tup):
            return None
        if tup is None:
            return None
        values = tup.checkpoint.get("channel_values") or {}
        return dict(values)
    except Exception:
        return None


async def _aread_thread_state(checkpointer, thread_id: str) -> dict | None:
    """Async variant for an event-loop parent: same contract, via `aget_tuple`."""
    try:
        tup = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
        if inspect.isawaitable(tup):
            tup = await tup
        if tup is None:
            return None
        values = tup.checkpoint.get("channel_values") or {}
        return dict(values)
    except Exception:
        return None


def _turn_from_state(values: dict, thread_id: str) -> "SessionTurn | None":
    """Shape a persisted thread state into a `SessionTurn` - the same shape
    `arun_session_turn` reports (`content` = structured_response when a schema was set,
    else the last message's text; `messages` = the full persisted trail). So a parent that
    READS a child's memory consumes exactly what the child itself reported.

    The `messages` READ depends on `create_agent`'s persisted channel name. Guarded
    fail-open (the reviewer-flagged coupling): a thread state whose `channel_values`
    does not carry a `messages` LIST is treated as UNREADABLE - warn and return None -
    so a parent never reasons over a silently-empty trail if that channel is ever
    renamed internally."""
    if not isinstance(values, dict) or not isinstance(values.get("messages"), list):
        logger.warning(
            "session thread %s state lacks the expected 'messages' channel "
            "(create_agent internal rename?); treating as unreadable", thread_id)
        return None
    messages = values["messages"]
    content = values.get("structured_response")
    if content is None and messages:
        content = messages[-1].content
    return SessionTurn(content=content, messages=list(messages), thread_id=thread_id)


# The parent's memory READ seam (the counterpart to posting completions, `actor.py`):
# a coordinator that wants a sub-agent's accumulated reasoning reads that child's OWN
# session thread from the shared checkpointer. This is the primitive a "read sub-agent
# memory" TOOL would call - generic, because every stateful child lives in the same
# store under its `SessionAddress` thread.

def read_session_memory(checkpointer, thread) -> SessionTurn | None:
    """Read a child session's PERSISTED memory (its latest checkpoint) without making a
    turn: returns the last `SessionTurn`'s worth of state, or None when the thread has no
    checkpoint yet (or the store cannot be read). Use this - NOT a tool round-trip - to
    inspect a sub-agent's reasoning when it delivers only a notification to its parent.

    `thread` is a typed `SessionAddress` or a raw thread-id string (back-compat)."""
    thread_id = _as_thread_id(thread)
    values = _read_thread_state(checkpointer, thread_id)
    if values is None:
        return None
    return _turn_from_state(values, thread_id)


async def aread_session_memory(checkpointer, thread) -> SessionTurn | None:
    """Async-native variant for a parent running on the event loop (the async actor's
    `on_message` path). Same contract as `read_session_memory`."""
    thread_id = _as_thread_id(thread)
    values = await _aread_thread_state(checkpointer, thread_id)
    if values is None:
        return None
    return _turn_from_state(values, thread_id)
