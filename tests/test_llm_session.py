"""Unit tier: the session path (`app/llm/session.py`, #94).

The session seam is the resumable, TOOL-CALLING agent: a `session`-mode role runs
via `create_agent`, binds its tools through tool_calling (not the legacy one-shot
`function_calling` path), and its conversation persists across invocations through
an injected checkpointer keyed by `thread_id`. These tests exercise that at the
public seam - `run_session_turn` - with a FAKE tool-calling model and an
`InMemorySaver`; the unit tier touches no live model and no live database
(CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import asyncio

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm.session import (
    arun_session_turn,
    run_session_turn,
)


class _FakeChatModel(BaseChatModel):
    """A scripted chat model that supports `bind_tools` (so `create_agent` can drive
    the tool_calling loop). Each model call returns the next scripted reply; the
    index advances on the instance so a multi-call turn walks the script."""

    replies: list = []
    idx: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        i = self.idx.get("i", 0)
        self.idx["i"] = i + 1
        msg = self.replies[min(i, len(self.replies) - 1)]
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _factory(*replies):
    """A `model_factory` yielding a fresh scripted fake per turn."""

    def make(role_id):
        return _FakeChatModel(replies=list(replies), idx={})

    return make


# --- stateful_turn: the ubiquitous stateful-agent pattern (#94) ---------------

class _CountFake(BaseChatModel):
    """Replies with the NUMBER of messages it was handed - so a resumed turn (which
    sees the prior trail) reports a larger count than a fresh one, proving the session
    carried across `stateful_turn` calls without needing a scripted cursor."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=str(len(messages))))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def test_stateful_turn_resumes_its_thread_and_returns_content():
    """`stateful_turn` returns the turn's content (the `invoke_role`-shaped value) and
    RESUMES its thread: turn 1 sees 1 message, turn 2 on the same thread sees 3 (its
    reply + the new human), proving the context progressed rather than reset."""
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = lambda role: _CountFake()  # noqa: E731
    c1 = stateful_turn("assigner", "run1:assigner", [HumanMessage(content="a")],
                       checkpointer=saver, model_factory=factory, observe=False)
    c2 = stateful_turn("assigner", "run1:assigner", [HumanMessage(content="b")],
                       checkpointer=saver, model_factory=factory, observe=False)
    assert c1 == "1"          # only the first human
    assert c2 == "3"          # first human + its ai reply + the second human -> resumed


def test_stateful_turn_wraps_schema_in_toolstrategy_not_native(monkeypatch):
    """Directive: structured session output goes through `ToolStrategy` (tool-calling,
    the function_calling-equivalent) so an open dict field survives - NEVER the native
    json_schema. `stateful_turn(schema=X)` must hand `run_session_turn` a `ToolStrategy`
    wrapping X; with no schema it passes `response_format=None`."""
    from langchain.agents.structured_output import ToolStrategy
    from pydantic import BaseModel

    import polymerhus.app.llm.session as S

    class _Schema(BaseModel):
        x: int = 0

    seen = {}

    def fake_run(role_id, thread_id, msgs, *, response_format=None, **kw):
        seen["rf"] = response_format
        return S.SessionTurn(content="ok", messages=[], thread_id=thread_id)

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    S.stateful_turn("assigner", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=_Schema, observe=False)
    assert isinstance(seen["rf"], ToolStrategy)
    S.stateful_turn("assigner", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=None, observe=False)
    assert seen["rf"] is None


def test_session_carries_prior_conversation_across_turns():
    """The core session property: a second turn on the same thread resumes the
    checkpointed history, so the post-turn trail is human1+ai1+human2+ai2 = 4
    messages. A one_shot call would retain nothing."""
    saver = InMemorySaver()
    run_session_turn("assigner", "run1:assigner", [HumanMessage(content="hello")],
                     checkpointer=saver, model_factory=_factory(AIMessage(content="a1")),
                     observe=False)
    turn2 = run_session_turn("assigner", "run1:assigner", [HumanMessage(content="again")],
                             checkpointer=saver, model_factory=_factory(AIMessage(content="a2")),
                             observe=False)
    assert [m.content for m in turn2.messages] == ["hello", "a1", "again", "a2"]
    assert turn2.content == "a2"


def test_distinct_thread_ids_do_not_share_memory():
    """Sessions are isolated by thread_id (per-agent keying `run:role`): a turn on a
    different thread never resumes another thread's history."""
    saver = InMemorySaver()
    run_session_turn("assigner", "runA:assigner", [HumanMessage(content="a")],
                     checkpointer=saver, model_factory=_factory(AIMessage(content="x")), observe=False)
    turn_b = run_session_turn("assigner", "runB:assigner", [HumanMessage(content="b")],
                              checkpointer=saver, model_factory=_factory(AIMessage(content="y")), observe=False)
    assert [m.content for m in turn_b.messages] == ["b", "y"]  # only its own two messages


_tool_inputs: list[str] = []


@tool
def _echo(x: str) -> str:
    """Echo the input back."""
    _tool_inputs.append(x)
    return f"echoed:{x}"


def test_session_runs_the_tool_calling_loop_and_middleware_hooks_fire():
    """Directive 2 (tool_calling, not function_calling): the model emits a tool_call,
    the agent EXECUTES the bound tool, feeds the result back, and finishes. Directive
    1 (the compaction/inference-config seam): `AgentMiddleware` hooks fire at the
    trigger points (`after_model` per LLM turn, `wrap_tool_call` around tool output)."""
    _tool_inputs.clear()
    fired: list[str] = []

    class Probe(AgentMiddleware):
        def after_model(self, state, runtime=None):
            fired.append("after_model")
            return None

        def wrap_tool_call(self, request, handler):
            fired.append("wrap_tool_call")
            return handler(request)

    replies = (
        AIMessage(content="", tool_calls=[{"name": "_echo", "args": {"x": "hi"}, "id": "c1"}]),
        AIMessage(content="final"),
    )
    turn = run_session_turn(
        "crawler", "r:crawler", [HumanMessage(content="go")],
        checkpointer=InMemorySaver(), tools=[_echo], middleware=[Probe()],
        model_factory=_factory(*replies), observe=False,
    )
    assert _tool_inputs == ["hi"]                 # the tool was actually invoked (tool_calling)
    assert turn.content == "final"                # the loop ran to a final answer
    assert "after_model" in fired                 # after-LLM-turn hook seam fires
    assert "wrap_tool_call" in fired              # after-tool-output hook seam fires


def test_arun_session_turn_carries_memory_across_turns():
    """The async-native entry point (`ainvoke`) an async parent coordinator uses:
    same resumable-memory contract as the sync turn, driven on the event loop."""
    saver = InMemorySaver()

    async def _two_turns():
        await arun_session_turn("assigner", "run1:assigner", [HumanMessage(content="hello")],
                                checkpointer=saver, model_factory=_factory(AIMessage(content="a1")),
                                observe=False)
        return await arun_session_turn("assigner", "run1:assigner", [HumanMessage(content="again")],
                                       checkpointer=saver, model_factory=_factory(AIMessage(content="a2")),
                                       observe=False)

    turn2 = asyncio.run(_two_turns())
    assert [m.content for m in turn2.messages] == ["hello", "a1", "again", "a2"]
    assert turn2.content == "a2"
