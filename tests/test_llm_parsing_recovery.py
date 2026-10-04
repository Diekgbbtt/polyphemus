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
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_openai.chat_models.base import _convert_message_to_dict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES

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


def _valid_call(call_id: str = "valid-1") -> AIMessage:
    """An assistant tool call that ToolNode would answer - except the run was
    interrupted before it could run, so the checkpoint left it unanswered."""
    return AIMessage(content="", tool_calls=[{
        "name": "seed_echo", "args": {"x": "hi"}, "id": call_id}])


@tool
def seed_echo(x: str) -> str:
    """Echo a string (the tool the pending-thread fixture binds)."""
    return f"echo:{x}"


def _spy_middleware(record: list):
    """A pass-through middleware that records the metadata `get_config()` carried
    into `before_model`, so a test can prove the seam set the resumption signal."""
    from langchain.agents.middleware import AgentMiddleware
    from langgraph.config import get_config

    class _Spy(AgentMiddleware):
        def before_model(self, state, runtime=None):
            record.append(dict(get_config().get("metadata") or {}))
            return None

    return _Spy()


def _resumed_middleware(monkeypatch, pending=("tools",)):
    """The recovery middleware with the seam's resumption signal faked, exactly as
    the session seam delivers it (config metadata `session_pending_next`)."""
    import langgraph.config as langconfig

    from polymerhus.app.llm.parsing_recovery import parsing_recovery_middleware

    monkeypatch.setattr(
        langconfig, "get_config",
        lambda: {"metadata": {"session_pending_next": list(pending)}})
    return parsing_recovery_middleware()



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


# --- the gated reconciliation (#280) -----------------------------------------

def test_session_turn_marks_a_pending_thread_as_resumed():
    """The seam reads `StateSnapshot.next` BEFORE invoking and passes it as config
    metadata only when the thread's prior run left pending tasks. A completed
    thread carries no signal. This is the gate that keeps completed-turn poison
    untouched while a genuine resumption still reconciles."""
    from langchain.agents import create_agent

    # A thread interrupted before the tools node: `next == ('tools',)`.
    saver = InMemorySaver()
    cfg = {"configurable": {"thread_id": "pending"}}
    seed_agent = create_agent(
        _Scripted(replies=[_valid_call()], idx={}, received=[]),
        tools=[seed_echo], checkpointer=saver, interrupt_before=["tools"])
    seed_agent.invoke({"messages": [HumanMessage(content="go")]}, cfg)
    assert seed_agent.get_state(cfg).next == ("tools",)

    seen: list = []
    turn = run_session_turn("assigner", "pending", [HumanMessage(content="continue")],
                            checkpointer=saver, tools=[seed_echo],
                            model_factory=_factory(AIMessage(content="resumed")),
                            middleware=[_spy_middleware(seen)], observe=False)
    assert any(r.get("session_pending_next") == ["tools"] for r in seen), seen
    # The resumed turn reconciled the interrupted valid call positionally.
    assert _pairing_ok(turn.messages)
    interrupted = [m for m in turn.messages
                   if isinstance(m, ToolMessage) and m.tool_call_id == "valid-1"]
    assert len(interrupted) == 1 and interrupted[0].status == "error"

    # A completed thread carries no `next`: the signal must be absent.
    saver2 = InMemorySaver()
    cfg2 = {"configurable": {"thread_id": "done"}}
    create_agent(_Scripted(replies=[AIMessage(content="ok")], idx={}, received=[]),
                 tools=[seed_echo], checkpointer=saver2).invoke(
        {"messages": [HumanMessage(content="go")]}, cfg2)
    seen2: list = []
    run_session_turn("assigner", "done", [HumanMessage(content="more")],
                     checkpointer=saver2, model_factory=_factory(AIMessage(content="ok2")),
                     middleware=[_spy_middleware(seen2)], observe=False)
    assert seen2 and all("session_pending_next" not in r for r in seen2), seen2


def test_before_model_reconciles_positionally_on_a_resumed_turn(monkeypatch):
    """On a resumed turn the reconciliation inserts the answering ToolMessage
    IMMEDIATELY after each unanswered AI tool call (valid OR invalid), so the
    wire positional-adjacency contract holds. The update is a full replacement
    (RemoveMessage(REMOVE_ALL) + the repaired trail)."""
    mw = _resumed_middleware(monkeypatch)
    trail = [
        HumanMessage(content="go"),
        _poison(),                       # invalid call, unanswered
        HumanMessage(content="continue"),
        _valid_call("valid-1"),          # valid call, interrupted before tools
        HumanMessage(content="more"),
    ]
    update = mw.before_model({"messages": trail}, None)
    assert update is not None
    repaired = update["messages"]
    assert isinstance(repaired[0], RemoveMessage)
    assert repaired[0].id == REMOVE_ALL_MESSAGES
    msgs = repaired[1:]
    # Positional: the answer sits between the AI call and the following Human.
    assert isinstance(msgs[1], AIMessage)
    assert isinstance(msgs[2], ToolMessage) and msgs[2].tool_call_id == POISON_ID
    assert "bad json" in msgs[2].content
    assert isinstance(msgs[3], HumanMessage)
    assert isinstance(msgs[4], AIMessage)
    assert isinstance(msgs[5], ToolMessage) and msgs[5].tool_call_id == "valid-1"
    assert "interrupted" in msgs[5].content.lower()
    assert isinstance(msgs[6], HumanMessage)
    # Every wire tool_call id is answered - valid and invalid alike.
    assert _pairing_ok(msgs)


def test_before_model_skips_without_the_resumption_signal(monkeypatch):
    """No resumption signal -> no reconciliation. A COMPLETED turn whose trail
    already carries pre-existing unanswered poison is deliberately NOT repaired
    (the old unconditional legacy repair is gone)."""
    import langgraph.config as langconfig

    from polymerhus.app.llm.parsing_recovery import parsing_recovery_middleware

    monkeypatch.setattr(langconfig, "get_config", lambda: {"metadata": {}})
    mw = parsing_recovery_middleware()
    trail = [HumanMessage(content="go"), _poison(), HumanMessage(content="continue")]
    assert mw.before_model({"messages": trail}, None) is None


def test_reconciliation_is_idempotent(monkeypatch):
    """An already-answered trail reconciles to nothing - never a second answer."""
    mw = _resumed_middleware(monkeypatch)
    answered = [HumanMessage(content="go"), _poison(), ToolMessage(
        content="Error: bad json. Please fix your mistakes.",
        tool_call_id=POISON_ID, name="RatifyDecision", status="error")]
    assert mw.before_model({"messages": answered}, None) is None


def test_reconciliation_is_fail_open(monkeypatch):
    """A state or config that explodes never raises into the turn."""
    import langgraph.config as langconfig

    from polymerhus.app.llm.parsing_recovery import parsing_recovery_middleware

    monkeypatch.setattr(
        langconfig, "get_config",
        lambda: {"metadata": {"session_pending_next": ["tools"]}})
    mw = parsing_recovery_middleware()

    class _Boom(dict):
        def get(self, key, default=None):
            raise RuntimeError("boom")

    assert mw.before_model(_Boom(), None) is None

    def _explode():
        raise RuntimeError("config boom")

    monkeypatch.setattr(langconfig, "get_config", _explode)
    assert mw.before_model({"messages": [HumanMessage(content="go"), _poison()]},
                           None) is None


def test_resumption_signal_read_is_fail_open():
    """A state read that explodes degrades to 'no signal' and never raises, for
    both the sync and the async seam."""
    from polymerhus.app.llm.session import (
        _aread_pending_resumption,
        _read_pending_resumption,
    )

    class _ExplodingSync:
        def get_state(self, config):
            raise RuntimeError("state boom")

    class _ExplodingAsync:
        async def aget_state(self, config):
            raise RuntimeError("state boom")

    sync_config = {"configurable": {"thread_id": "t"}}
    _read_pending_resumption(_ExplodingSync(), sync_config)
    assert "session_pending_next" not in sync_config.get("metadata", {})

    async def _run():
        async_config = {"configurable": {"thread_id": "t"}}
        await _aread_pending_resumption(_ExplodingAsync(), async_config)
        assert "session_pending_next" not in async_config.get("metadata", {})

    asyncio.run(_run())


def test_async_before_model_reconciles_symmetrically(monkeypatch):
    """`abefore_model` delegates to the same reconciliation, so the async seam
    reconciles too."""
    mw = _resumed_middleware(monkeypatch)
    trail = [HumanMessage(content="go"), _poison(), HumanMessage(content="continue")]

    async def _run():
        return await mw.abefore_model({"messages": trail}, None)

    update = asyncio.run(_run())
    assert update is not None
    msgs = update["messages"][1:]
    assert isinstance(msgs[2], ToolMessage) and msgs[2].tool_call_id == POISON_ID
    assert isinstance(msgs[3], HumanMessage)
    assert _pairing_ok(msgs)


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


# --- the tail-request guard (#280 follow-up) ---------------------------------

def _no_orphan_answer(messages) -> bool:
    """No `tool` message on the wire without a matching assistant `tool_calls` entry
    (the second 400 invariant, distinct from `_pairing_ok`'s call->answer one)."""
    payload = _wire_payload(messages)
    wired = {tc["id"] for d in payload for tc in (d.get("tool_calls") or [])}
    tool_ids = [d.get("tool_call_id") for d in payload if d.get("role") == "tool"]
    return all(t in wired for t in tool_ids)


def test_answer_is_never_written_unless_the_request_is_the_last_element():
    """#280 follow-up (the post-turn-stop orphan): the answer is appended at the tail,
    so it may only be written when the tool-call request IS the last element. A stale
    unanswered invalid call whose message is not the tail must be left alone - the old
    whole-trail scan answered it, producing an orphan `tool` message with no adjacent
    call, which the upstream rejects with HTTP 400 ("Messages with role 'tool' must be
    a response to a preceding message with 'tool_calls'")."""
    from polymerhus.app.llm.parsing_recovery import (
        build_parsing_error_answers,
        parsing_recovery_middleware,
    )

    trail = [
        HumanMessage(content="go"),
        _poison(),                                       # stale, NOT the tail
        AIMessage(content="plain reply, no tool call"),  # the last element
    ]
    assert build_parsing_error_answers(trail) == []
    assert parsing_recovery_middleware().after_model({"messages": trail}, None) is None
    assert _no_orphan_answer(trail)


def test_answer_is_written_when_the_request_is_the_last_element():
    """The guard keeps the prevention: a poison that IS the tail (the model's own
    reply) is still answered, and the wire stays orphan-free."""
    from polymerhus.app.llm.parsing_recovery import build_parsing_error_answers

    trail = [HumanMessage(content="go"), _poison()]
    answers = build_parsing_error_answers(trail)
    assert len(answers) == 1 and answers[0].tool_call_id == POISON_ID
    assert _no_orphan_answer([*trail, *answers])


# --- the mixed-call residual (F13) -------------------------------------------

def test_malformed_call_is_answered_behind_a_structured_output_answer():
    """F13: the observed `graph_view` symptom. The structured-output path
    (`create_agent._handle_model_output`) appends its own answer `ToolMessage` INSIDE
    the model node, so a malformed ordinary call carried by the SAME assistant message
    sits one message behind the literal tail. The tail window walks back over that
    trailing tool answer and still pairs the malformed call, so the resumed thread
    never replays an unanswered `tool_calls` entry."""
    from langchain.agents.structured_output import ToolStrategy
    from pydantic import BaseModel

    class Decision(BaseModel):
        note: str = ""

    mixed = AIMessage(
        content="",
        tool_calls=[{"name": "Decision", "args": {"note": "ok"}, "id": "call_dec"}],
        invalid_tool_calls=[{
            "name": "graph_view", "args": '{"cypher": "MATCH ',
            "id": POISON_ID, "error": "bad json"}],
    )
    saver = InMemorySaver()
    turn = run_session_turn(
        "hunting_orchestrator", "mixed-structured", [HumanMessage(content="go")],
        checkpointer=saver, tools=[seed_echo], model_factory=_factory(mixed),
        response_format=ToolStrategy(Decision), observe=False)
    assert _pairing_ok(turn.messages)
    assert _no_orphan_answer(turn.messages)
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == POISON_ID
               and m.status == "error" for m in turn.messages)


def test_valid_and_malformed_calls_in_one_message_are_both_answered():
    """F13 case: a VALID ordinary call and a malformed ordinary call in the SAME
    assistant message. Answering the invalid call must NOT jump back to the model -
    the jump bypasses the tools routing and would leave the valid call unanswered, a
    second fresh-poison path. The valid call runs through ToolNode exactly once."""
    calls = {"n": 0}

    @tool
    def _echo(x: str) -> str:
        """Echo a string."""
        calls["n"] += 1
        return f"echo:{x}"

    mixed = AIMessage(
        content="",
        tool_calls=[{"name": "_echo", "args": {"x": "hi"}, "id": "valid-9"}],
        invalid_tool_calls=[{
            "name": "graph_view", "args": '{"cypher": "MATCH ',
            "id": POISON_ID, "error": "bad json"}],
    )
    saver = InMemorySaver()
    turn = run_session_turn(
        "hunting_orchestrator", "mixed-ordinary", [HumanMessage(content="go")],
        checkpointer=saver, tools=[_echo],
        model_factory=_factory(mixed, AIMessage(content="final")), observe=False)
    assert turn.content == "final"
    assert calls["n"] == 1
    assert _pairing_ok(turn.messages)
    assert _no_orphan_answer(turn.messages)


def test_tail_window_stops_at_a_human_boundary_after_a_tool_answer():
    """The refined window still refuses a stale call before a stop boundary: a later
    `HumanMessage` blocks the answer even when a `tool` message trails the call. Only
    trailing `tool` answers are walked; a human (or later assistant) message is a stop
    boundary and is never crossed (#280 follow-up guard preserved)."""
    from polymerhus.app.llm.parsing_recovery import build_parsing_error_answers

    trail = [
        HumanMessage(content="go"),
        _valid_call("v1"),
        ToolMessage(content="ok", tool_call_id="v1", name="seed_echo"),
        _poison(),                       # unanswered, but a stop boundary follows
        HumanMessage(content="next turn"),
    ]
    assert build_parsing_error_answers(trail) == []
