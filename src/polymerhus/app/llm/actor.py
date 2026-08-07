"""Persistent async agents (actors) with a mailbox: the async-native PARENT runtime (#94).

`arun_session_turn` (session.py) is a single non-blocking turn. It is NOT the unit an
agent "classified as async" is meant to be: such an agent (a parent/coordinator - the
hunt-orchestrator first) runs as its OWN independent execution unit (an
`asyncio.Task`) that, after taking a turn, STAYS ACTIVE - listening on its mailbox for
updates from sub-agents and taking a further turn per update - until it decides to
stop. That is the actor / supervisor (blackboard) shape the async design calls for.

This module has two halves:

  BUILT - the durable listening loop and its mailbox:
    * `AgentInbox`   - the message queue an active agent listens on (an
                       `asyncio.Queue`, with a thread-safe `post_threadsafe` so a
                       sub-agent running off the loop - `asyncio.to_thread` today -
                       can still deliver into it).
    * `run_session_agent(...)` - runs an (optional) initial `arun_session_turn`, then
                       loops: await the next inbox message, hand it to `on_message`,
                       and - when the handler returns follow-up messages - take the
                       next turn on the SAME `thread_id` so checkpointed memory carries
                       across the agent's whole active lifetime. Ends on `STOP`, an
                       idle timeout, a turn cap, or task cancellation.

  DESIGNED-NOT-BUILT (the scaffold you asked for) - the DELIVERY of sub-agent updates
  into a parent's inbox via post-call hooks. The interface is present and inert so the
  real sub-agent -> parent routing wires in later WITHOUT refactoring the loop or the
  turn:
    * `inbox_post_hook(inbox, ...)` - returns a plain `hook(payload)` callable a
                       sub-agent invokes when its call completes (thread-safe).
    * `build_inbox_middleware(inbox, ...)` - a `create_agent` middleware that posts an
                       update to a target inbox on `after_model` / `after_agent`, so a
                       sub-agent run through the session seam notifies its parent
                       automatically. Both no-op when handed no inbox.

Importing this module performs no I/O and needs no env var (CODING_STANDARD section 6):
the middleware base class is imported lazily inside the factory, never at import.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

from langchain_core.messages import BaseMessage

from polymerhus.app.llm.session import SessionTurn, arun_session_turn

logger = logging.getLogger(__name__)


class _Stop:
    """The sentinel an `on_message` handler returns to end the agent's active life."""

    _singleton: "_Stop | None" = None

    def __new__(cls) -> "_Stop":
        if cls._singleton is None:
            cls._singleton = super().__new__(cls)
        return cls._singleton

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "STOP"


# The terminal signal a message handler returns to stop the loop (vs. new messages to
# take another turn, or None to keep listening without one).
STOP = _Stop()


@dataclass(frozen=True)
class AgentMessage:
    """One update delivered to an active agent's inbox: a sub-agent result, a budget
    signal, a cancellation, etc. `kind` lets the handler route; `payload` carries the
    update; `source` names the deliverer (a sub-agent's id) for provenance."""

    kind: str
    payload: Any = None
    source: str | None = None


class AgentInbox:
    """The mailbox an active async agent listens on. Sub-agents / post-call hooks post
    updates here; the agent's loop consumes them one at a time.

    The queue binds to the loop that first CONSUMES it (`get`), which is the agent's own
    loop. `post` / `post_nowait` are for producers already on that loop;
    `post_threadsafe` is for a producer on another thread (a sub-agent dispatched via
    `asyncio.to_thread`), scheduling the put back onto the agent's loop."""

    def __init__(self, maxsize: int = 0):
        self._q: asyncio.Queue[AgentMessage] = asyncio.Queue(maxsize=maxsize)
        self._loop: asyncio.AbstractEventLoop | None = None

    async def get(self) -> AgentMessage:
        self._loop = asyncio.get_running_loop()
        return await self._q.get()

    async def post(self, message: AgentMessage) -> None:
        await self._q.put(message)

    def post_nowait(self, message: AgentMessage) -> None:
        self._q.put_nowait(message)

    def post_threadsafe(self, message: AgentMessage) -> None:
        """Deliver from ANOTHER thread (a sub-agent running off the agent's loop). Falls
        back to a direct put when the loop is not yet captured (no consumer has begun)."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._q.put_nowait, message)
        else:  # no consumer yet on a loop: best-effort direct enqueue
            self._q.put_nowait(message)

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        return self._q.qsize()


# `on_message(message, last_turn)` -> the next turn's messages (take a turn), `None`
# (consumed; keep listening), or `STOP` (end the agent). May be sync or async.
MessageHandler = Callable[
    [AgentMessage, "SessionTurn | None"],
    "Sequence[BaseMessage] | _Stop | None | Awaitable[Sequence[BaseMessage] | _Stop | None]",
]


@dataclass
class AgentRunResult:
    """The outcome of an active agent's whole lifetime: every turn it took (in order),
    its thread id, and why it stopped."""

    turns: list[SessionTurn] = field(default_factory=list)
    thread_id: str = ""
    stop_reason: str = ""

    @property
    def last(self) -> SessionTurn | None:
        return self.turns[-1] if self.turns else None


async def _coerce(value):
    return await value if inspect.isawaitable(value) else value


async def run_session_agent(
    role_id: str,
    thread_id: str,
    initial_messages: Sequence[BaseMessage] | None,
    *,
    checkpointer,
    inbox: AgentInbox | None = None,
    on_message: MessageHandler | None = None,
    idle_timeout: float | None = None,
    max_turns: int | None = None,
    tools: Sequence = (),
    response_format=None,
    system_prompt: str | None = None,
    middleware: Sequence = (),
    store=None,
    model_factory=None,
    observe: bool = True,
) -> AgentRunResult:
    """Run an async-native agent that stays ACTIVE after its turn, listening on `inbox`.

    Launch it as its own unit of execution - `asyncio.create_task(run_session_agent(...))` -
    and it becomes an independent actor: it takes the initial turn (when
    `initial_messages` is given; pass `None` for a pure listener), then repeatedly
    awaits the next inbox message and hands it to `on_message`. A handler that returns
    follow-up messages triggers the next `arun_session_turn` on the SAME `thread_id`, so
    the checkpointer resumes the agent's memory across its entire active life; `STOP`
    ends it; `None` keeps it listening. Absent `on_message`, the default policy is to
    keep listening and stop only on a `kind == "stop"` message.

    Stops on: `STOP` from the handler, `idle_timeout` seconds with an empty inbox,
    `max_turns` reached, or task cancellation (propagated - the natural way to retire an
    actor). The turn kwargs mirror `arun_session_turn` one-for-one."""
    inbox = inbox or AgentInbox()
    result = AgentRunResult(thread_id=thread_id)

    turn_kwargs = dict(
        checkpointer=checkpointer, tools=tools, response_format=response_format,
        system_prompt=system_prompt, middleware=middleware, store=store,
        model_factory=model_factory, observe=observe,
    )

    async def _turn(messages: Sequence[BaseMessage]) -> SessionTurn:
        turn = await arun_session_turn(role_id, thread_id, list(messages), **turn_kwargs)
        result.turns.append(turn)
        return turn

    last_turn: SessionTurn | None = None
    if initial_messages:
        last_turn = await _turn(initial_messages)

    while True:
        if max_turns is not None and len(result.turns) >= max_turns:
            result.stop_reason = "max_turns"
            break
        try:
            message = await (asyncio.wait_for(inbox.get(), idle_timeout)
                             if idle_timeout is not None else inbox.get())
        except asyncio.TimeoutError:
            result.stop_reason = "idle_timeout"
            break

        if on_message is None:
            if message.kind == "stop":
                result.stop_reason = "stop_message"
                break
            continue

        follow = await _coerce(on_message(message, last_turn))
        if follow is STOP:
            result.stop_reason = "handler_stop"
            break
        if follow:
            last_turn = await _turn(follow)  # another turn on the same thread: memory carries

    return result


# --- the post-call-hook DELIVERY scaffold (designed-not-built) -----------------

def inbox_post_hook(
    inbox: AgentInbox | None,
    *,
    kind: str = "subagent_update",
    source: str | None = None,
) -> Callable[[Any], None]:
    """Return the post-call hook a SUB-AGENT invokes when its call completes, to deliver
    an update into a PARENT's `inbox`. Thread-safe (a sub-agent dispatched via
    `asyncio.to_thread` can call it), and a no-op when `inbox` is None - so a call site
    can wire the hook unconditionally now and the real routing (which parent, which
    payload) is a later, refactor-free change.

    This is the interface half of the not-yet-built delivery: `run_session_agent`
    already CONSUMES what this posts."""
    def hook(payload: Any = None) -> None:
        if inbox is None:
            return
        inbox.post_threadsafe(AgentMessage(kind=kind, payload=payload, source=source))

    return hook


def build_inbox_middleware(
    inbox: AgentInbox | None,
    *,
    kind: str = "subagent_update",
    source: str | None = None,
    on: str = "after_agent",
):
    """Build a `create_agent` middleware that posts an update to a parent's `inbox` when
    a sub-agent's session turn finishes (`after_agent`) or after each model reply
    (`after_model`) - the post-call-hook delivery, expressed on the same middleware seam
    the session path already exposes. Returns None when `inbox` is None (so
    `middleware=[m] if m else []` stays trivial). The delivered payload is a stub (the
    hook point is what matters here); enriching it with the real sub-agent result is the
    designed-not-built follow-up."""
    if inbox is None:
        return None

    from langchain.agents.middleware import AgentMiddleware

    hook = inbox_post_hook(inbox, kind=kind, source=source)

    class InboxDispatchMiddleware(AgentMiddleware):
        """Notifies a parent inbox at the sub-agent's post-call hook point."""

        def after_model(self, state, runtime=None):
            if on == "after_model":
                hook({"hook": "after_model"})
            return None

        def after_agent(self, state, runtime=None):
            if on == "after_agent":
                hook({"hook": "after_agent"})
            return None

    return InboxDispatchMiddleware()
