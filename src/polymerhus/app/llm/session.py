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

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from langchain_core.messages import BaseMessage

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
    agent = _build_agent(
        role_id, tools=tools, response_format=response_format, system_prompt=system_prompt,
        middleware=middleware, store=store, checkpointer=checkpointer, model_factory=model_factory,
    )
    result = agent.invoke({"messages": list(new_messages)}, _turn_config(role_id, thread_id, observe))
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
    agent = _build_agent(
        role_id, tools=tools, response_format=response_format, system_prompt=system_prompt,
        middleware=middleware, store=store, checkpointer=checkpointer, model_factory=model_factory,
    )
    result = await agent.ainvoke({"messages": list(new_messages)}, _turn_config(role_id, thread_id, observe))
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
    ).content


def _read_thread_state(checkpointer, thread_id: str) -> dict | None:
    """The latest persisted state dict for a session thread, or None when the thread has
    no checkpoint yet (or the read fails - fail-open, mirroring the rest of the seam)."""
    try:
        tup = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    except Exception:
        return None
    if tup is None:
        return None
    values = tup.checkpoint.get("channel_values") or {}
    return dict(values)


async def _aread_thread_state(checkpointer, thread_id: str) -> dict | None:
    """Async variant for an event-loop parent: same contract, via `aget_tuple`."""
    try:
        tup = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    except Exception:
        return None
    if tup is None:
        return None
    values = tup.checkpoint.get("channel_values") or {}
    return dict(values)


def _turn_from_state(values: dict, thread_id: str) -> SessionTurn:
    """Shape a persisted thread state into a `SessionTurn` - the same shape
    `arun_session_turn` reports (`content` = structured_response when a schema was set,
    else the last message's text; `messages` = the full persisted trail). So a parent that
    READS a child's memory consumes exactly what the child itself reported."""
    messages = values.get("messages") or []
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
