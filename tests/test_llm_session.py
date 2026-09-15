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
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
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


def test_stateful_turn_negotiates_schema_response_format(monkeypatch):
    """Directive (#99, ADR A1, ticket #147): structured session output is now
    NEGOTIATED - a structured-output-capable (or unknown) profile hands
    `run_session_turn` a `ProviderStrategy(schema, strict=False)` (the open-dict-
    tolerant json_schema rung), a tool-calling-only profile hands a
    `ToolStrategy`. With no schema it passes `response_format=None`."""
    from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
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
    assert isinstance(seen["rf"], ProviderStrategy)
    assert seen["rf"].schema is _Schema
    assert seen["rf"].schema_spec.strict is False
    S.stateful_turn("assigner", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=None, observe=False)
    assert seen["rf"] is None


def test_stateful_turn_tool_calling_only_profile_uses_toolstrategy(monkeypatch):
    """A tool-calling-only profile degrades the no-tools session turn to
    `ToolStrategy` (the proven force-tool rung) - the open `dict` field survives."""
    from langchain.agents.structured_output import ToolStrategy
    from pydantic import BaseModel

    import polymerhus.app.llm.session as S

    class _Open(BaseModel):
        anchor: dict = {}
        label: str = "y"

    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")

    seen = {}
    capability_calls = 0

    def fake_capability(provider, model):
        nonlocal capability_calls
        capability_calls += 1
        return type("_P", (), {"supports_structured_output": False,
                               "supports_tool_calling": True})()

    monkeypatch.setattr(S, "resolve_capability", fake_capability)

    def fake_run(role_id, thread_id, msgs, *, response_format=None, **kw):
        seen["rf"] = response_format
        return S.SessionTurn(content="ok", messages=[], thread_id=thread_id)

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    S.stateful_turn("triager", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=_Open, observe=False)
    assert isinstance(seen["rf"], ToolStrategy)
    assert capability_calls == 1  # resolved once (resolve-and-hold)


def test_stateful_turn_unknown_profile_fails_open_to_json_schema(monkeypatch):
    """Resolve-and-hold on an unknown/absent profile (or a resolution failure)
    degrades to the semantic default `json_schema` and the session still starts
    (D7 fail-open) - repeated turns do not re-resolve."""
    from langchain.agents.structured_output import ProviderStrategy
    from pydantic import BaseModel

    import polymerhus.app.llm.session as S

    class _Schema(BaseModel):
        x: int = 0

    calls = 0

    def fake_capability(provider, model):
        nonlocal calls
        calls += 1
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(S, "resolve_capability", fake_capability)
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")
    seen = {}

    def fake_run(role_id, thread_id, msgs, *, response_format=None, **kw):
        seen["rf"] = response_format
        return S.SessionTurn(content="ok", messages=[], thread_id=thread_id)

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    S.stateful_turn("triager", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=_Schema, observe=False)
    assert isinstance(seen["rf"], ProviderStrategy)
    assert seen["rf"].schema_spec.strict is False


def test_stateful_turn_neither_profile_uses_toolstrategy(monkeypatch):
    """The operator-ratified session-seam rider (2026-08-21, spec line 51): a
    neither-capability no-tools session turn resolves its json_mode rung to
    `ToolStrategy` on the SESSION path - json_mode is a one-shot-seam-only rung,
    inexpressible through create_agent's response_format vocabulary.
    `negotiate_method` yields json_mode for the neither profile; the seam maps
    every non-json_schema method to `ToolStrategy`."""
    from langchain.agents.structured_output import ToolStrategy
    from pydantic import BaseModel

    import polymerhus.app.llm.session as S

    class _Open(BaseModel):
        anchor: dict = {}
        label: str = "y"

    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")

    seen = {}

    def fake_capability(provider, model):
        return type("_P", (), {"supports_structured_output": False,
                               "supports_tool_calling": False})()

    monkeypatch.setattr(S, "resolve_capability", fake_capability)

    def fake_run(role_id, thread_id, msgs, *, response_format=None, **kw):
        seen["rf"] = response_format
        return S.SessionTurn(content="ok", messages=[], thread_id=thread_id)

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    S.stateful_turn("triager", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=_Open, observe=False)
    assert isinstance(seen["rf"], ToolStrategy)


def test_stateful_turn_tool_bound_is_unchanged_toolstrategy(monkeypatch):
    """Tool-bound sessions stay on native tool calling - a tool loop has no
    method-swap (A1 rung 2). The explicit `ToolStrategy` response_format passed
    by tool-loop callers (orchestrator/hunting) flows through unchanged."""
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
    strategy = ToolStrategy(_Schema)
    S.stateful_turn("assigner", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=_Schema, observe=False)
    S.run_session_turn("assigner", "t", [HumanMessage(content="x")],
                       checkpointer=None, response_format=strategy, observe=False)
    assert isinstance(seen["rf"], ToolStrategy)


def test_stateful_turn_structured_output_parse_failure_degrades_to_none(monkeypatch):
    """FAIL-OPEN invariant (the reasoning-token-exhaustion / schema-gap fix): a
    stateful turn whose provider output does not parse into the schema - the
    native `StructuredOutputValidationError` raised by `create_agent`'s factory
    when a reasoning model returns a bare `[]` / empty / prose instead of the
    wrapped object - must degrade to None (the exhausted-generation signal),
    exactly like the one-shot `invoke_role` seam, NEVER propagate and kill the
    pod (which would silently drop the already-parsed assets)."""
    from langchain.agents.structured_output import StructuredOutputValidationError
    from pydantic import BaseModel

    import polymerhus.app.llm.session as S

    class _Schema(BaseModel):
        observations: list = []

    seen = {}

    def boom(role_id, thread_id, msgs, *, response_format=None, **kw):
        seen["called"] = True
        raise StructuredOutputValidationError("_Schema", ValueError("bad json"), None)

    monkeypatch.setattr(S, "run_session_turn", boom)
    result = S.stateful_turn("triager", "t", [HumanMessage(content="x")],
                             checkpointer=None, schema=_Schema, observe=False)
    assert result is None
    assert seen["called"] is True


def test_stateful_turn_other_error_also_degrades_to_none(monkeypatch):
    """Fail-open is broad: a NON-parse exception (transport / provider error) also
    degrades the stateful turn to None rather than crashing the caller - the same
    shape the one-shot escalating wrapper returns on exhaustion."""
    import polymerhus.app.llm.session as S

    def boom(role_id, thread_id, msgs, *, response_format=None, **kw):
        raise RuntimeError("provider on fire")

    monkeypatch.setattr(S, "run_session_turn", boom)
    result = S.stateful_turn("triager", "t", [HumanMessage(content="x")],
                             checkpointer=None, schema=None, observe=False)
    assert result is None


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


# --- T1 (#213): streamed generation is the DEFAULT session mode --------------

class _StreamFake(BaseChatModel):
    """A streaming chat model: `_stream` emits reasoning chunks (on
    `additional_kwargs.reasoning_content`) then the final answer's content chunks,
    with a selectable reasoning burn and whether content is ever emitted."""

    reasoning_pieces: list = []
    content_pieces: list = []
    idx: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for piece in self.reasoning_pieces:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="", additional_kwargs={"reasoning_content": piece}))
        for piece in self.content_pieces:
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        # a real provider always closes the stream with an empty final chunk
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _stream_factory(*, reasoning_pieces=(), content_pieces=()):
    """A `model_factory` yielding a fresh streaming fake per turn."""

    def make(role_id):
        return _StreamFake(
            reasoning_pieces=list(reasoning_pieces), content_pieces=list(content_pieces))

    return make


def test_run_session_turn_streams_and_captures_reasoning():
    """T1: `run_session_turn` now STREAMS the model call (`stream_events`), so a
    turn that emits reasoning before its answer has BOTH surfaces captured - the
    turn returns the generated content and carries the streamed reasoning."""
    saver = InMemorySaver()
    turn = run_session_turn(
        "assigner", "s1",
        [HumanMessage(content="hello")],
        checkpointer=saver,
        model_factory=_stream_factory(
            reasoning_pieces=["Need maybe mention", " the admin routes"],
            content_pieces=["final", " answer"]),
        observe=False,
        reasoning_budget_chars=100_000,
    )
    assert turn.content == "final answer"
    assert turn.reasoning == "Need maybe mention the admin routes"
    assert turn.blackloop is False


def test_arun_session_turn_streams_and_captures_reasoning():
    """Same contract on the async path (`astream_events`), the production parent-
    coordinator entry point."""
    saver = InMemorySaver()

    async def _one():
        return await arun_session_turn(
            "assigner", "s2",
            [HumanMessage(content="hello")],
            checkpointer=saver,
            model_factory=_stream_factory(
                reasoning_pieces=["deep", " deliberation"],
                content_pieces=["answer"]),
            observe=False,
            reasoning_budget_chars=100_000,
        )

    turn = asyncio.run(_one())
    assert turn.content == "answer"
    assert turn.reasoning == "deep deliberation"


def test_arun_session_turn_cuts_blackloop_and_thread_stays_resumable():
    """T1: a stream that burns reasoning with NO content past the detection bound
    is CUT mid-flight (never waiting for the full generation), surfaced as a
    blackloop turn with the captured reasoning - and the SAME thread remains
    resumeable for the follow-up recovery turn."""
    saver = InMemorySaver()

    async def _cut_then_recover():
        cut = await arun_session_turn(
            "assigner", "s3",
            [HumanMessage(content="hello")],
            checkpointer=saver,
            model_factory=_stream_factory(
                reasoning_pieces=["Need maybe mention"] * 4000,  # burns past the bound
                content_pieces=[]),
            observe=False,
            reasoning_budget_chars=8000,
        )
        assert cut.blackloop is True
        assert cut.content == ""
        assert "Need maybe mention" in cut.reasoning
        # the thread must be healthy for the recovery turn (T2):
        recovered = await arun_session_turn(
            "assigner", "s3",
            [HumanMessage(content="answer now")],
            checkpointer=saver,
            model_factory=_stream_factory(
                reasoning_pieces=["ok"], content_pieces=["recovered"]),
            observe=False,
            reasoning_budget_chars=100_000,
        )
        return recovered

    recovered = asyncio.run(_cut_then_recover())
    assert recovered.content == "recovered"
    assert recovered.blackloop is False


# --- T2 (#214): the recovery turn inside `stateful_turn` ---------------------

def _sequential_factory(*models):
    """A `model_factory` that hands out a FRESH `_StreamFake` per call, walking a
    scripted sequence (turn 1's model, the recovery turn's model, ...) - so a
    stateful_turn whose first generation blackloops can be followed by a recovering
    one. (`BaseChatModel.dict()` only yields `_type`, so instances are rebuilt from
    their pieces directly.)"""
    state = {"i": 0}

    def make(role_id):
        idx = min(state["i"], len(models) - 1)
        state["i"] += 1
        model = models[idx]
        return _StreamFake(
            reasoning_pieces=list(model.reasoning_pieces),
            content_pieces=list(model.content_pieces),
        )

    return make


def test_stateful_turn_recovers_after_blackloop_cut():
    """T2: a streamed-cut blackloop routes to a recovery generation on the SAME thread
    instead of degrading to None - the recovery is itself streamed + single-bounded, and
    its content is what the caller sees."""
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=["Need maybe mention"] * 4000, content_pieces=[]),
        _StreamFake(reasoning_pieces=["ok"], content_pieces=["recovered"]),
    )
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=8000,
    )
    assert result == "recovered"


def test_stateful_turn_recovery_re_blackloop_fails_open_to_none():
    """T2 fail-open preserved: if the recovery generation ALSO blackloops (a re-blackloop
    is cut - the recovery is streamed + bounded, never unbounded), `stateful_turn`
    degrades to None exactly as today - never crashes the caller."""
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=["loop"] * 4000, content_pieces=[]),
        _StreamFake(reasoning_pieces=["loop"] * 4000, content_pieces=[]),
    )
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=8000,
    )
    assert result is None


def test_stateful_turn_recovery_composes_prior_context_and_instruction():
    """T2: the recovery generation carries the prior context (the failed turn's
    new_messages persisted in the checkpointer) + a bounded compacted rendering of the
    failed reasoning + the verbatim blackloop instruction - asserted from the persisted
    thread after the recovery completes."""
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=["Need maybe mention the admin routes"] * 300,
                    content_pieces=[]),
        _StreamFake(reasoning_pieces=[], content_pieces=["conclusion"]),
    )
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=200,
    )
    assert result == "conclusion"
    tup = saver.get_tuple({"configurable": {"thread_id": "run1:assigner"}})
    messages = tup.checkpoint["channel_values"]["messages"]
    texts = [str(getattr(m, "content", "") or "") for m in messages]
    assert "the job" in texts[0]
    assert any("END THIS STEP NOW" in t for t in texts)
    assert any("Need maybe mention the admin routes" in t for t in texts)


def test_stateful_turn_recovers_from_length_finish_exception_shape_a(monkeypatch):
    """T2 (shape A): a `LengthFinishReasonError` carries the failed reasoning on
    `exc.completion` (the failed message was NOT persisted) - stateful_turn extracts
    it and composes the recovery generation instead of degrading blindly."""
    from polymerhus.app.llm import session as S
    from polymerhus.app.llm.session import stateful_turn

    class _FakeCompletion:
        reasoning_content = "Need maybe mention the admin routes"

    class _FakeLengthFinishError(Exception):
        def __init__(self):
            super().__init__("finish_reason=length")
            self.completion = _FakeCompletion()

    real_run = S.run_session_turn
    calls = {"n": 0}

    def fake_run(role_id, thread_id, msgs, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _FakeLengthFinishError()
        return real_run(role_id, thread_id, msgs, **kwargs)

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=[], content_pieces=["recovered"]))
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=100,
    )
    assert result == "recovered"
    assert calls["n"] == 2


def test_stateful_turn_length_finish_without_reasoning_fails_open_to_none(monkeypatch):
    """T2 (shape A, no reasoning): a `LengthFinishReasonError` with NO extractable
    reasoning (nothing to recover from) degrades to None exactly as today."""
    from polymerhus.app.llm import session as S
    from polymerhus.app.llm.session import stateful_turn

    class _FakeLengthFinishError(Exception):
        def __init__(self):
            super().__init__("finish_reason=length")
            self.completion = None

    def fake_run(role_id, thread_id, msgs, **kwargs):
        raise _FakeLengthFinishError()

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    saver = InMemorySaver()
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, observe=False,
    )
    assert result is None


def test_stateful_turn_recovers_on_empty_content_with_reasoning():
    """T2 (empty-content signature): a turn that completes EMPTY-CONTENT while still
    emitting reasoning (the silent-empty shape) is recovered, never returned empty."""
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=["brief thinking"], content_pieces=[]),
        _StreamFake(reasoning_pieces=[], content_pieces=["recovered"]),
    )
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=8000,
    )
    assert result == "recovered"


def test_stateful_turn_empty_without_reasoning_is_a_legitimate_empty():
    """T2: empty content with NO reasoning is a legitimate empty (not a blackloop) -
    returned as-is, never routed to recovery."""
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = _sequential_factory(_StreamFake(reasoning_pieces=[], content_pieces=[]))
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=8000,
    )
    assert result == ""


# --- T5 (#217): blackloop_recovery observability -----------------------------

def test_stateful_turn_records_blackloop_recovery_metadata():
    """T5: after a blackloop is recovered, the thread's last-recovery record carries
    shape, output_produced and cut point - the material the D11 trace field shows."""
    from polymerhus.app.llm import session as S
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=["Need maybe mention"] * 4000, content_pieces=[]),
        _StreamFake(reasoning_pieces=[], content_pieces=["recovered"]),
    )
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=8000,
    )
    assert result == "recovered"
    record = S._last_blackloop_recovery["run1:assigner"]
    assert record["shape"] == "streamed_cut"
    assert record["output_produced"] is True
    assert record["cut_point_chars"] > 0


def test_stateful_turn_records_blackloop_recovery_failure_output():
    """T5: a recovery that FAILS (re-blackloop, output NOT produced) still records
    the field with output_produced=False - the occurrence is never silent."""
    from polymerhus.app.llm import session as S
    from polymerhus.app.llm.session import stateful_turn

    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=["loop"] * 4000, content_pieces=[]),
        _StreamFake(reasoning_pieces=["loop"] * 4000, content_pieces=[]),
    )
    result = stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=False,
        reasoning_budget_chars=8000,
    )
    assert result is None
    record = S._last_blackloop_recovery["run1:assigner"]
    assert record["shape"] == "streamed_cut"
    assert record["output_produced"] is False


def test_blackloop_recovery_metadata_rides_the_trace_when_observing(monkeypatch):
    """T5: with observability on, the last-recovery record rides the config metadata
    of the NEXT turn - the same `langfuse_session_id` trace the D11 readability
    fields ride (recorded AFTER the outcome is known, never gating)."""
    from polymerhus.app.llm import session as S
    from polymerhus.app.llm.session import stateful_turn

    merged = {}
    real_attach = S._attach_blackloop_metadata

    def fake_attach(config, thread_id):
        real_attach(config, thread_id)
        merged["meta"] = dict(config.get("metadata", {}))

    monkeypatch.setattr(S, "_attach_blackloop_metadata", fake_attach)
    saver = InMemorySaver()
    factory = _sequential_factory(
        _StreamFake(reasoning_pieces=["loop"] * 4000, content_pieces=[]),
        _StreamFake(reasoning_pieces=[], content_pieces=["recovered"]),
    )
    stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, observe=True,
        reasoning_budget_chars=8000,
    )
    # a further turn on the same thread rides the record
    stateful_turn(
        "assigner", "run1:assigner", [HumanMessage(content="continue")],
        checkpointer=saver, model_factory=_sequential_factory(
            _StreamFake(reasoning_pieces=[], content_pieces=["next"])),
        observe=True,
    )
    assert "blackloop_recovery" in merged["meta"]
    assert "langfuse_session_id" in merged["meta"]
