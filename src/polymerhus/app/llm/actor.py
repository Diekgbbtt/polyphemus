"""Persistent async agents (actors) with a mailbox: the async-native PARENT runtime (#94).

`arun_session_turn` (session.py) is a single non-blocking turn. It is NOT the unit an
agent "classified as async" is meant to be: such an agent (a parent/coordinator - the
hunt-orchestrator first) runs as its OWN independent execution unit (an
`asyncio.Task`) that, after taking a turn, STAYS ACTIVE - listening on its mailbox for
updates from sub-agents and taking a further turn per update - until it decides to
stop. That is the actor / supervisor (blackboard) shape the async design calls for.

This module has two halves, both BUILT:

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
                       **Per-turn exception isolation (#186)**: `_turn` is the single
                       choke point every mailbox actor rides. A raising turn is
                       CONTAINED - a retryable raise (transport/timeout/5xx/429) is
                       retried under a bounded, escalating per-attempt budget, and on
                       exhaustion (or a non-retryable raise) the turn DEGRADES: a
                       no-decision reply wakes the parent (its fail-open fires
                       per-turn) and the actor task survives for the next turn.
                       `asyncio.CancelledError` is re-raised first - a task
                       cancellation is a BaseException, never degraded, never
                       retried. The degradation is delivered through the optional
                       `on_turn_degraded` hook (the caller's `build_inbox_delivery`
                       posts the None reply).

  BUILT - the DELIVERY of sub-agent updates into a parent's inbox via post-call hooks.
  A sub-agent run through the session seam with the middleware below notifies its
  parent automatically when its call completes:
    * `inbox_post_hook(inbox, ...)` - returns the plain `hook(payload)` callable a
                       sub-agent invokes when its call completes (thread-safe). A
                       no-op when handed no inbox, so a call site stays inert until
                       a parent is wired.
    * `build_inbox_middleware(inbox, ...)` - a `create_agent` middleware that posts
                       the sub-agent's turn result (final content, message trail, and
                       the `thread_id` the session ran on) into a target inbox at the
                       post-call hook point (`after_agent` or `after_model`), so the
                       parent's loop wakes and can take its next turn on the update.
                       Returns None when handed no inbox.
    * `subagent_completion_hook(inbox, ...)` - for a child that does NOT run through
                       the session seam (a pod dispatched inside a static config-driven
                       graph): posts the child's `thread_id` plus its result into the
                       parent's inbox on completion, so the parent can go READ that
                       child's memory (`read_session_memory`, session.py).

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

from polymerhus.app.llm.providers import attempt_timeouts
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


def _is_retryable(exc: BaseException) -> bool:
    """Classify a turn raise as retryable: the transport/timeout/5xx/429 class
    (#186). Lazy-imports the provider SDKs so this module's import stays I/O- and
    env-var-free (CODING_STANDARD section 6); a raise that matches none of the
    known classes is treated as non-retryable (a genuine application error
    degrades immediately rather than burning the escalating budget)."""
    if isinstance(exc, asyncio.TimeoutError):  # builtin: a wait_for-wrapped model call
        return True
    try:
        import httpx  # noqa: PLC0415

        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
    except Exception:  # noqa: BLE001 - httpx unavailable: fall through to openai
        pass
    try:
        import openai  # noqa: PLC0415

        if isinstance(exc, openai.APITimeoutError):
            return True
        if isinstance(exc, openai.APIConnectionError):
            return True
        if isinstance(exc, openai.RateLimitError):  # 429
            return True
        if isinstance(exc, openai.APIStatusError):
            status = getattr(exc, "status_code", None)
            if status is not None and status >= 500:  # 5xx (500/502/503/504)
                return True
    except Exception:  # noqa: BLE001 - openai unavailable: nothing matches
        pass
    return False


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
    on_turn_degraded: Callable[[str, Exception], Awaitable[None] | None] | None = None,
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
    actor). The turn kwargs mirror `arun_session_turn` one-for-one.

    `on_turn_degraded(thread_id, exc)` (default None) is the #186 degradation hook: a
    turn that exhausts its retry budget (or raises non-retryably) does NOT kill the
    actor - the hook is called so the caller can wake its parent with a no-decision
    (`None`) reply, and the loop keeps listening for the next message."""
    inbox = inbox or AgentInbox()
    result = AgentRunResult(thread_id=thread_id)

    turn_kwargs = dict(
        checkpointer=checkpointer, tools=tools, response_format=response_format,
        system_prompt=system_prompt, middleware=middleware, store=store,
        model_factory=model_factory, observe=observe,
    )

    async def _run_turn_attempt(messages: Sequence[BaseMessage], *,
                                read_timeout_s: float | None = None) -> SessionTurn:
        return await arun_session_turn(
            role_id, thread_id, list(messages), read_timeout_s=read_timeout_s,
            **turn_kwargs,
        )

    async def _turn(messages: Sequence[BaseMessage]) -> SessionTurn | None:
        """Take ONE turn on the thread, isolated against a raising LLM (#186):
        retry the retryable class (transport/timeout/5xx/429) under the bounded
        escalating per-attempt budget, then DEGRADE - wake the parent with a
        no-decision reply via `on_turn_degraded` - so the actor task survives
        for the next turn. A `CancelledError` is re-raised first (a task
        cancellation is the natural retirement, never a degrade). The retry
        re-invokes `arun_session_turn` with the SAME `new_messages`; langgraph
        commits only successful super-steps and `add_messages` dedups by message
        id, so the committed trail stays idempotent across the attempts."""
        try:
            turn = await _run_turn_attempt(messages)
            result.turns.append(turn)
            return turn
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the isolation boundary
            last_exc = exc
            if _is_retryable(exc):
                for budget in attempt_timeouts()[1:]:
                    try:
                        turn = await _run_turn_attempt(messages, read_timeout_s=budget)
                        result.turns.append(turn)
                        return turn
                    except asyncio.CancelledError:
                        raise
                    except Exception as rexc:  # noqa: BLE001 - classify, then continue
                        last_exc = rexc
                        if not _is_retryable(rexc):
                            break
            # retry budget exhausted (or a non-retryable raise): degrade. The
            # turn never happened - it is NOT appended to `result.turns` - and
            # the actor survives; the parent is woken so its fail-open fires
            # per-turn, never through a dead-task race.
            logger.warning("actor turn degraded on %s/%s: %s (the actor survives)",
                           role_id, thread_id, last_exc)
            if on_turn_degraded is not None:
                await _coerce(on_turn_degraded(thread_id, last_exc))
            return None

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


# --- the post-call-hook DELIVERY (sub-agent -> parent routing) -----------------

def inbox_post_hook(
    inbox: AgentInbox | None,
    *,
    kind: str = "subagent_update",
    source: str | None = None,
) -> Callable[[Any], None]:
    """Return the post-call hook a SUB-AGENT invokes when its call completes, to deliver
    an update into a PARENT's `inbox`. Thread-safe (a sub-agent dispatched via
    `asyncio.to_thread` can call it), and a no-op when `inbox` is None - so a call site
    can wire the hook unconditionally now.

    `payload` is free-form; when the sub-agent runs through the session seam,
    `build_inbox_middleware` calls this with the turn's result."""

    def hook(payload: Any = None) -> None:
        if inbox is None:
            return
        inbox.post_threadsafe(AgentMessage(kind=kind, payload=payload, source=source))

    return hook


def subagent_completion_hook(
    inbox: AgentInbox | None,
    *,
    kind: str = "subagent_complete",
    source: str | None = None,
) -> Callable[[str, Any], None]:
    """Build the post-call hook a PARENT wires onto a child that does NOT run through the
    session seam (a config-driven pod dispatched inside a static Job StateGraph, a crawl
    pod, etc., per the #94 hierarchy). When the child's work completes, the hook posts
    into the parent's `inbox` the child's `thread_id` (so the parent can go READ that
    child's memory via `read_session_memory` #86 seam) plus the child's free-form result.
    Thread-safe and a no-op for a None inbox, like `inbox_post_hook`."""

    def hook(thread_id: str, detail: Any = None) -> None:
        if inbox is None:
            return
        inbox.post_threadsafe(AgentMessage(
            kind=kind, payload={"thread_id": thread_id, "detail": detail}, source=source))

    return hook


def _turn_result_payload(state: dict, thread_id: str | None) -> dict:
    """Shape the agent state at a post-call hook into a delivery payload: the `content`
    mirroring `SessionTurn` (the parsed `structured_response` when a schema is set, else
    the last message's text), the full post-turn `messages` trail, and the `thread_id`
    the session ran on - the same shape `arun_session_turn` reports, so a parent that
    receives this can route on the agent's actual answer."""
    messages = state.get("messages") or []
    content = state.get("structured_response")
    if content is None and messages:
        content = messages[-1].content
    return {"content": content, "messages": list(messages), "thread_id": thread_id}


def build_inbox_middleware(
    inbox: AgentInbox | None,
    *,
    kind: str = "subagent_update",
    source: str | None = None,
    on: str = "after_agent",
):
    """Build a `create_agent` middleware that posts the sub-agent's result to a parent's
    inbox at the post-call hook point: `after_agent` (once, when the whole session turn
    finishes - the default) or `after_model` (after each model reply). The delivered
    payload is the turn result - `content`, the `messages` trail, and the `thread_id`
    (read from the run config) - mirroring `SessionTurn`, so the parent wakes and can
    take its next turn on the actual answer. Returns None when `inbox` is None (so
    `middleware=[m] if m else []` stays trivial)."""
    if inbox is None:
        return None

    from langchain.agents.middleware import AgentMiddleware
    from langgraph.config import get_config

    hook = inbox_post_hook(inbox, kind=kind, source=source)

    def _deliver(state) -> None:
        config = {}
        try:
            config = get_config()
        except Exception:
            pass  # not inside a graph run: no thread id to report
        thread_id = (config.get("configurable") or {}).get("thread_id")
        hook(_turn_result_payload(state, thread_id))

    class InboxDispatchMiddleware(AgentMiddleware):
        """Notifies a parent inbox with the sub-agent's turn result at the post-call
        hook point."""

        def after_model(self, state, runtime=None):
            if on == "after_model":
                _deliver(state)
            return None

        def after_agent(self, state, runtime=None):
            if on == "after_agent":
                _deliver(state)
            return None

    return InboxDispatchMiddleware()


def build_inbox_delivery(
    inbox: AgentInbox | None,
    *,
    kind: str = "subagent_update",
    source: str | None = None,
    on: str = "after_agent",
):
    """Build the parent-reply delivery PAIR `(middleware, degraded_hook)` (#186).

    `middleware` is the existing post-call delivery (`build_inbox_middleware`) -
    it posts the turn's REAL result at the hook point. `degraded_hook` is the
    fail-open sibling wired as `run_session_agent`'s `on_turn_degraded`: it posts
    a NO-DECISION (`content=None`) reply when a turn exhausts its retry budget,
    so the parent's fail-open fires PER TURN and the actor task survives for the
    next turn - exactly one reply per turn, the real result OR the None. Returns
    `(None, None)` when handed no inbox, so a call site stays inert until a parent
    is wired."""
    if inbox is None:
        return None, None
    middleware = build_inbox_middleware(inbox, kind=kind, source=source, on=on)
    hook = inbox_post_hook(inbox, kind=kind, source=source)

    def degraded_hook(thread_id: str | None, exc: Exception) -> None:
        logger.warning("actor turn degraded on %s (%s); posting a no-decision reply",
                       thread_id, exc)
        hook(_turn_result_payload({}, thread_id))

    return middleware, degraded_hook
