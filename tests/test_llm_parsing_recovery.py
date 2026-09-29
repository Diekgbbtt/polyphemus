"""Part 1 (#280): parsing-error recovery at the session seam.

The captured failure: one malformed model tool call checkpoints as an
`AIMessage` with the parse failure in `invalid_tool_calls` and an EMPTY
`tool_calls`. The pinned `create_agent` routing only inspects `tool_calls`, so
the agent loop exits without answering; every later turn replays an unanswered
assistant `tool_calls` entry (the wire serializer emits `invalid_tool_calls` as
`tool_calls`) and the upstream rejects the request with HTTP 400 forever.

These tests pin the contract fix: unanswered INVALID calls are answered with an
error `ToolMessage` before the next request is built (structural prevention),
never by dropping the call from the wire. Real captured poison, no live model.
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_openai.chat_models.base import _convert_message_to_dict
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm.session import arun_session_turn, run_session_turn

# The captured poison (GitHub #280): invalid call name `RatifyDecision`, id
# `call_00_7lvazxncbaqxxj2duxixi74j`, args `{"configs">[{"hunt_id":: `.
POISON_ID = "call_00_7lvazxncbaqxxj2duxixi74j"
POISON_ARGS = '{"configs">[{"hunt_id":: '


def _poison(call_id: str = POISON_ID) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[],
        invalid_tool_calls=[{
            "name": "RatifyDecision",
            "args": POISON_ARGS,
            "id": call_id,
            "error": "bad json",
        }],
    )


class _Scripted(BaseChatModel):
    """A scripted tool-calling model that records the exact trail each call was
    handed (so a test can prove the answer was in place BEFORE the request)."""

    replies: list = []
    idx: dict = {}
    received: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        i = self.idx.get("i", 0)
        self.idx["i"] = i + 1
        self.received.append(list(messages))
        msg = self.replies[min(i, len(self.replies) - 1)]
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self


def _factory(*replies):
    state = {"model": None}

    def make(role_id):
        model = _Scripted(replies=list(replies), idx={}, received=[])
        state["model"] = model
        return model

    make.state = state
    return make


def _wire_payload(messages):
    """Build the next request's message payload with the pinned wire serializer."""
    payload = []
    for m in messages:
        if isinstance(m, HumanMessage):
            continue
        payload.append(_convert_message_to_dict(m))
    return payload


def _pairing_ok(messages) -> bool:
    payload = _wire_payload(messages)
    wired = [tc["id"] for d in payload for tc in (d.get("tool_calls") or [])]
    tool_ids = [d.get("tool_call_id") for d in payload if d.get("role") == "tool"]
    return all(i in tool_ids for i in wired) and bool(wired)


# --- the wire contract -------------------------------------------------------

def test_recovery_answer_makes_the_poison_trail_replay_valid():
    """Contract: after recovery the pinned wire serializer emits a `tool` answer
    for every wired `tool_calls` id, including the captured poison's invalid
    call (which the serializer emits as a tool_call)."""
    trail = [HumanMessage(content="go"), _poison(), ToolMessage(
        content="Error: bad json. Please fix your mistakes.",
        tool_call_id=POISON_ID, name="RatifyDecision", status="error")]
    assert _pairing_ok(trail)
    # And the poison WITHOUT the answer is exactly the broken replay.
    assert not _pairing_ok([HumanMessage(content="go"), _poison()])


# --- sync / async two-turn emulation ----------------------------------------

def test_sync_turn_answers_the_poison_before_the_next_request():
    """The scripted model emits the captured poison on its first call; the
    recovery answers it and routes back to the model IN THE SAME turn, so the
    model's second call is handed a paired trail. Turn 2 resumes cleanly."""
    factory = _factory(_poison(), AIMessage(content="recovered"),
                       AIMessage(content="turn2"))
    saver = InMemorySaver()
    turn1 = run_session_turn("assigner", "t", [HumanMessage(content="go")],
                             checkpointer=saver, model_factory=factory, observe=False)
    assert turn1.content == "recovered"
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == POISON_ID
               for m in turn1.messages)
    assert _pairing_ok(turn1.messages)
    # The answering ToolMessage was present in the second model request.
    second_request = factory.state["model"].received[1]
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == POISON_ID
               for m in second_request)
    turn2 = run_session_turn("assigner", "t", [HumanMessage(content="again")],
                             checkpointer=saver, model_factory=_factory(
                                 AIMessage(content="turn2b")),
                             observe=False)
    assert turn2.content == "turn2b"


def test_async_turn_answers_the_poison_before_the_next_request():
    """The async entry point (`arun_session_turn`) shares the seam and owns the
    same recovery contract."""
    async def _run():
        factory = _factory(_poison(), AIMessage(content="recovered"))
        saver = InMemorySaver()
        turn = await arun_session_turn(
            "assigner", "t", [HumanMessage(content="go")],
            checkpointer=saver, model_factory=factory, observe=False)
        assert turn.content == "recovered"
        assert _pairing_ok(turn.messages)
        assert any(isinstance(m, ToolMessage) and m.tool_call_id == POISON_ID
                   for m in factory.state["model"].received[1])

    asyncio.run(_run())


# --- bounded retry, idempotence, clean trails --------------------------------

def test_bounded_retry_never_loops_unboundedly(monkeypatch):
    """A model that poisons EVERY attempt is bounced back only a bounded number
    of times; the turn then ends on a valid (paired) trail."""
    monkeypatch.setenv("LLM_PARSING_RECOVERY_MAX_ANSWERS", "2")
    poisons = [_poison(f"call_{i}") for i in range(10)]
    factory = _factory(*poisons)
    saver = InMemorySaver()
    turn = run_session_turn("assigner", "t", [HumanMessage(content="go")],
                            checkpointer=saver, model_factory=factory, observe=False)
    # 2 jump-retries + one final non-jumping answer = 3 model calls.
    assert len(factory.state["model"].received) == 3
    assert _pairing_ok(turn.messages)
    answers = [m for m in turn.messages
               if isinstance(m, ToolMessage) and m.status == "error"]
    assert len(answers) == 3


def test_recovery_is_idempotent_never_answers_a_call_twice():
    """Running the recovery over an already-answered trail is a no-op."""
    from polymerhus.app.llm.parsing_recovery import build_parsing_error_answers

    msgs = [HumanMessage(content="go"), _poison(), ToolMessage(
        content="Error: bad json. Please fix your mistakes.",
        tool_call_id=POISON_ID, name="RatifyDecision", status="error")]
    assert build_parsing_error_answers(msgs) == []


def test_clean_trail_is_a_no_op():
    """A normal assistant turn with no invalid calls is untouched."""
    from polymerhus.app.llm.parsing_recovery import (
        build_parsing_error_answers,
        parsing_recovery_middleware,
    )

    msgs = [HumanMessage(content="go"), AIMessage(content="done")]
    assert build_parsing_error_answers(msgs) == []
    mw = parsing_recovery_middleware()
    assert mw.after_model({"messages": msgs}, None) is None
    assert mw.before_model({"messages": msgs}, None) is None


def test_valid_tool_loop_is_unchanged_single_answer():
    """A valid tool call is answered exactly once by ToolNode; the recovery must
    not add a second answer nor jump."""
    calls = {"n": 0}

    @tool
    def _echo(x: str) -> str:
        """Echo a string."""
        calls["n"] += 1
        return f"echo:{x}"

    factory = _factory(
        AIMessage(content="", tool_calls=[{"name": "_echo", "args": {"x": "hi"},
                                           "id": "valid-1"}]),
        AIMessage(content="final"),
    )
    saver = InMemorySaver()
    turn = run_session_turn("assigner", "t", [HumanMessage(content="go")],
                            checkpointer=saver, tools=[_echo], model_factory=factory,
                            observe=False)
    assert turn.content == "final"
    assert calls["n"] == 1
    tool_msgs = [m for m in turn.messages if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].status != "error"
    assert _pairing_ok(turn.messages)


# --- legacy checkpointed repair ---------------------------------------------

def test_legacy_repair_answers_a_seeded_unanswered_invalid_call(monkeypatch):
    """A checkpointed trail that already carries an unanswered invalid call (a
    thread poisoned before the fix) is repaired by `before_model` before the
    next request is built."""
    monkeypatch.setenv("LLM_PARSING_RECOVERY_MAX_ANSWERS", "3")
    from langchain.agents import create_agent

    saver = InMemorySaver()
    cfg = {"configurable": {"thread_id": "legacy"}}
    # Seed the poisoned checkpoint directly (the pre-fix state).
    seed_agent = create_agent(_Scripted(replies=[AIMessage(content="x")],
                                        idx={}, received=[]),
                              tools=[], checkpointer=saver)
    seed_agent.update_state(cfg, {"messages": [
        HumanMessage(content="go"), _poison()]})

    factory = _factory(AIMessage(content="healed"))
    turn = run_session_turn("assigner", "legacy", [HumanMessage(content="continue")],
                            checkpointer=saver, model_factory=factory, observe=False)
    assert _pairing_ok(turn.messages)
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == POISON_ID
               for m in factory.state["model"].received[0])
    answers = [m for m in turn.messages
               if isinstance(m, ToolMessage) and m.tool_call_id == POISON_ID]
    assert len(answers) == 1


def test_recovery_middleware_is_wired_into_every_session_turn(monkeypatch):
    """`_build_agent` is the one shared construction point: the recovery
    middleware must be present for both turn entry points."""
    import polymerhus.app.llm.session as S

    captured = {}
    real = S._build_agent

    def spy(*args, **kwargs):
        agent = real(*args, **kwargs)
        captured["agent"] = agent
        return agent

    monkeypatch.setattr(S, "_build_agent", spy)
    saver = InMemorySaver()
    run_session_turn("assigner", "t", [HumanMessage(content="x")],
                     checkpointer=saver, model_factory=_factory(AIMessage(content="ok")),
                     observe=False)
    nodes = set(captured["agent"].get_graph().nodes)
    assert "ParsingRecoveryMiddleware.after_model" in nodes
