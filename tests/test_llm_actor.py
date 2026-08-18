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


def test_build_inbox_middleware_posts_the_real_turn_result_to_the_parent():
    """The delivery middleware posts the SUB-AGENT'S ACTUAL RESULT at its post-call hook
    (`after_agent`): `content` (the turn's answer), the `messages` trail, and the
    `thread_id` the session ran on - so the parent's loop can route on the real answer.
    `None` inbox -> no middleware."""
    from polymerhus.app.llm.session import run_session_turn

    assert build_inbox_middleware(None) is None  # trivially inert

    inbox = AgentInbox()
    mw = build_inbox_middleware(inbox, source="child-1", on="after_agent")
    run_session_turn(
        "hunting_hunter", "r:hunter", [HumanMessage(content="go")],
        checkpointer=InMemorySaver(), middleware=[mw],
        model_factory=_seq_factory("done"), observe=False,
    )
    assert inbox.qsize() == 1  # exactly one post-call hook per session turn
    msg = asyncio.run(inbox.get())
    assert msg.kind == "subagent_update" and msg.source == "child-1"
    assert msg.payload["content"] == "done"                       # the real answer
    assert msg.payload["thread_id"] == "r:hunter"                  # which session it ran on
    assert [m.content for m in msg.payload["messages"]] == ["go", "done"]


def test_build_inbox_middleware_after_model_posts_the_result_no_tools():
    """With `on="after_model"` the delivery posts at every model reply - still the real
    content (there are no tools in this turn, so the final reply's content is the answer)
    - which is the hook point the dynamic-config / progress workstreams target."""
    from polymerhus.app.llm.session import run_session_turn

    inbox = AgentInbox()
    mw = build_inbox_middleware(inbox, source="child-1", on="after_model")
    run_session_turn(
        "hunting_orchestrator", "r:orch", [HumanMessage(content="go")],
        checkpointer=InMemorySaver(), middleware=[mw],
        model_factory=_seq_factory("hi"), observe=False,
    )
    assert inbox.qsize() == 1
    msg = asyncio.run(inbox.get())
    assert msg.payload["content"] == "hi"
    assert msg.payload["thread_id"] == "r:orch"


def test_subagent_completion_hook_posts_thread_id_for_non_session_children():
    """A child that does NOT run through the session seam (a pod dispatched inside a
    static config-driven graph) still notifies its parent on completion: the hook posts
    the child's `thread_id` plus its result into the parent's inbox, so the parent can go
    READ that child's memory (`read_session_memory`). No-op for a None inbox."""
    from polymerhus.app.llm.actor import subagent_completion_hook

    assert subagent_completion_hook(None)("r:pod:1", {"verdict": "success"}) is None  # inert

    inbox = AgentInbox()
    hook = subagent_completion_hook(inbox, kind="pod_complete", source="pod-1")

    async def _drive():
        await asyncio.to_thread(hook, "r:0:subfinder:https://a:triager", {"verdict": "success"})
        return await inbox.get()

    msg = asyncio.run(_drive())
    assert msg.kind == "pod_complete" and msg.source == "pod-1"
    assert msg.payload["thread_id"] == "r:0:subfinder:https://a:triager"
    assert msg.payload["detail"]["verdict"] == "success"


def test_read_session_memory_returns_the_persisted_turn():
    """The parent's memory-read seam: after a child has run a stateful turn, the parent
    can read the child's PERSISTED session memory (its checkpoint) without making a
    turn - receiving the same shape `SessionTurn` the child itself reported."""
    from polymerhus.app.llm.session import read_session_memory, run_session_turn

    saver = InMemorySaver()
    run_session_turn(
        "hunting_hunter", "r:hunter", [HumanMessage(content="go")],
        checkpointer=saver, model_factory=_seq_factory("done"), observe=False,
    )
    memory = read_session_memory(saver, "r:hunter")
    assert memory is not None
    assert memory.thread_id == "r:hunter"
    assert memory.content == "done"
    assert [m.content for m in memory.messages] == ["go", "done"]


def test_read_session_memory_missing_thread_is_none():
    """A thread with no checkpoint yet (or an unreadable store) reads back None - the
    fail-open contract: the parent can treat "no memory yet" as a plain absent result."""
    from polymerhus.app.llm.session import read_session_memory

    assert read_session_memory(InMemorySaver(), "r:never-ran") is None


def test_aread_session_memory_matches_the_sync_read():
    """The async variant (an event-loop parent's `on_message` path) reads the same
    persisted memory as the sync read."""
    from polymerhus.app.llm.session import aread_session_memory, run_session_turn

    saver = InMemorySaver()
    run_session_turn(
        "hunting_hunter", "r:hunter", [HumanMessage(content="go")],
        checkpointer=saver, model_factory=_seq_factory("done"), observe=False,
    )

    async def _drive():
        return await aread_session_memory(saver, "r:hunter")

    memory = asyncio.run(_drive())
    assert memory is not None
    assert memory.content == "done"
    assert [m.content for m in memory.messages] == ["go", "done"]
