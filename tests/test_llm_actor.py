"""Unit tier: the persistent async agent (actor) runtime (`app/llm/actor.py`, #94).

An agent classified as async is not a single turn - it is an independent unit that
STAYS ACTIVE after its turn, listening on a mailbox for sub-agent updates and taking a
further turn per update. These tests exercise that loop and the post-call-hook DELIVERY
scaffold at the public seam, with a FAKE tool-calling model and an `InMemorySaver`; the
unit tier touches no live model and no live database (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm.actor import (
    STOP,
    AgentInbox,
    AgentMessage,
    build_inbox_middleware,
    inbox_post_hook,
    run_session_agent,
)


class _FakeChatModel(BaseChatModel):
    """A one-reply scripted model: emits a FRESH `AIMessage(content)` each call (a fresh
    object per turn, so `add_messages` never dedups two turns' replies by id)."""

    content: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.content))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _seq_factory(*contents):
    """A `model_factory` that advances one content per BUILD (one build per turn), so
    successive turns of the same agent walk the script (turn 1 -> a1, turn 2 -> a2).
    The cursor lives in this closure, not on the model, because a pydantic chat model
    copies its fields - a cursor stored on the instance would never advance."""
    cursor = {"i": 0}

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _FakeChatModel(content=contents[min(i, len(contents) - 1)])

    return make


def test_agent_takes_initial_turn_then_listens_and_continues_on_update():
    """The core actor property: after its initial turn the agent stays active, and an
    inbox update drives a SECOND turn on the same thread - so the memory carries
    (start+a1+again+a2), exactly as a resumed session would."""
    saver = InMemorySaver()
    inbox = AgentInbox()

    def on_message(msg, last_turn):
        if msg.kind == "update":
            return [HumanMessage(content="again")]
        return STOP

    async def _drive():
        task = asyncio.ensure_future(run_session_agent(
            "hunting_orchestrator", "run1:orch", [HumanMessage(content="start")],
            checkpointer=saver, inbox=inbox, on_message=on_message,
            model_factory=_seq_factory("a1", "a2"),
            observe=False,
        ))
        await inbox.post(AgentMessage(kind="update"))   # drives turn 2
        await inbox.post(AgentMessage(kind="done"))     # handler returns STOP
        return await task

    result = asyncio.run(_drive())
    assert result.stop_reason == "handler_stop"
    assert len(result.turns) == 2
    assert [m.content for m in result.turns[1].messages] == ["start", "a1", "again", "a2"]


def test_agent_rests_on_idle_timeout_after_its_turn():
    """With no update arriving, the active agent rests: it takes its initial turn then
    stops on the idle window rather than spinning."""
    async def _drive():
        return await run_session_agent(
            "hunting_orchestrator", "r:orch", [HumanMessage(content="hi")],
            checkpointer=InMemorySaver(), inbox=AgentInbox(),
            on_message=lambda m, t: None, idle_timeout=0.05,
            model_factory=_seq_factory("a1"), observe=False,
        )

    result = asyncio.run(_drive())
    assert result.stop_reason == "idle_timeout"
    assert len(result.turns) == 1


def test_pure_listener_with_no_initial_turn_stops_on_stop_message():
    """A pure listener (`initial_messages=None`, no handler) takes no turn and stops on a
    `kind='stop'` message - the mailbox-only actor shape."""
    inbox = AgentInbox()

    async def _drive():
        task = asyncio.ensure_future(run_session_agent(
            "hunting_orchestrator", "r:orch", None,
            checkpointer=InMemorySaver(), inbox=inbox,
            model_factory=_seq_factory("x"), observe=False,
        ))
        await inbox.post(AgentMessage(kind="stop"))
        return await task

    result = asyncio.run(_drive())
    assert result.stop_reason == "stop_message"
    assert result.turns == []


def test_inbox_post_hook_delivers_from_a_worker_thread():
    """The post-call-hook scaffold: a sub-agent running OFF the loop (`to_thread`) posts
    an update through `inbox_post_hook`, and the active parent consumes it and takes a
    turn - proving the cross-thread delivery seam the not-yet-built routing plugs into."""
    saver = InMemorySaver()
    inbox = AgentInbox()

    def on_message(msg, last_turn):
        return STOP if msg.kind == "subagent_update" else None

    async def _drive():
        task = asyncio.ensure_future(run_session_agent(
            "hunting_orchestrator", "r:orch", [HumanMessage(content="start")],
            checkpointer=saver, inbox=inbox, on_message=on_message,
            model_factory=_seq_factory("a1"), observe=False,
        ))
        await asyncio.sleep(0)  # let the parent reach its listening state
        hook = inbox_post_hook(inbox, source="child-1")   # what a sub-agent would hold
        await asyncio.to_thread(hook, {"verdict": "successful"})  # delivered from a thread
        return await task

    result = asyncio.run(_drive())
    assert result.stop_reason == "handler_stop"
    assert len(result.turns) == 1  # initial turn; the update closed the actor


def test_build_inbox_middleware_posts_at_the_subagent_post_call_hook():
    """The middleware form of the delivery scaffold: a sub-agent run through the session
    seam with `build_inbox_middleware` notifies the parent inbox at its post-call hook
    (`after_agent`), with no live parent loop required. `None` inbox -> no middleware."""
    from polymerhus.app.llm.session import run_session_turn

    assert build_inbox_middleware(None) is None  # trivially inert

    inbox = AgentInbox()
    mw = build_inbox_middleware(inbox, source="child-1", on="after_agent")
    run_session_turn(
        "hunting_hunter", "r:hunter", [HumanMessage(content="go")],
        checkpointer=InMemorySaver(), middleware=[mw],
        model_factory=_seq_factory("done"), observe=False,
    )
    assert inbox.qsize() == 1
    msg = asyncio.run(inbox.get())
    assert msg.kind == "subagent_update" and msg.source == "child-1"
