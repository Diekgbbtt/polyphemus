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

    monkeypatch.setenv("LLM_TRIAGER", "openrouter:some/model")

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
    monkeypatch.setenv("LLM_TRIAGER", "openrouter:some/model")
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

    monkeypatch.setenv("LLM_TRIAGER", "openrouter:some/model")

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


def test_session_turns_bind_the_thread_as_the_conversation(monkeypatch):
    """D12: the session seam binds the thread id as the ambient conversation for
    the turn, so every model constructed inside it (the turn's own, and any a
    middleware builds, e.g. the compaction summariser) carries the provider's
    conversation request primitives (opencode-go `x-opencode-session`). Both
    turn entry points - sync and async - bind it."""
    from polymerhus.app.llm import session as S

    class _FakeAgent:
        def invoke(self, *args, **kwargs):
            return {"messages": []}

        async def ainvoke(self, *args, **kwargs):
            return {"messages": []}

    seen: list[str] = []
    real_scope = S.conversation_scope

    def _spy(conversation_id):
        seen.append(conversation_id)
        return real_scope(conversation_id)

    monkeypatch.setattr(S, "_build_agent", lambda *a, **k: _FakeAgent())
    monkeypatch.setattr(S, "conversation_scope", _spy)

    run_session_turn("triager", "run-3:triager", [], checkpointer=None, observe=False)
    asyncio.run(arun_session_turn("triager", "run-3:triager", [],
                                  checkpointer=None, observe=False))
    assert seen == ["run-3:triager", "run-3:triager"]


def test_a6_structured_response_format_tools_bound_constrained_is_toolstrategy(monkeypatch):
    """A6: tools-bound + constrained profile -> ToolStrategy (the relaxed model
    makes it voluntary at bind time)."""
    from langchain.agents.structured_output import ToolStrategy
    from pydantic import BaseModel
    import polymerhus.app.llm.session as S

    class _Schema(BaseModel):
        x: int = 0

    monkeypatch.setenv("LLM_TRIAGER", "openrouter:some/model")

    def fake_capability(provider, model):
        from polymerhus.app.llm.capability import CapabilityProfile
        return CapabilityProfile(supports_structured_output=True,
                                 supports_tool_calling=True,
                                 supports_forced_tool_choice=False,
                                 source="operator-override")

    monkeypatch.setattr(S, "resolve_capability", fake_capability)
    rf = S.structured_response_format("triager", _Schema, tools_bound=True)
    assert isinstance(rf, ToolStrategy)


def test_a6_structured_response_format_no_tools_structured_is_providerstrategy(monkeypatch):
    from langchain.agents.structured_output import ProviderStrategy
    from pydantic import BaseModel
    import polymerhus.app.llm.session as S

    class _Schema(BaseModel):
        x: int = 0

    monkeypatch.setenv("LLM_TRIAGER", "openrouter:some/model")

    def fake_capability(provider, model):
        from polymerhus.app.llm.capability import CapabilityProfile
        return CapabilityProfile(supports_structured_output=True,
                                 supports_tool_calling=True)

    monkeypatch.setattr(S, "resolve_capability", fake_capability)
    rf = S.structured_response_format("triager", _Schema, tools_bound=False)
    assert isinstance(rf, ProviderStrategy)


def test_a6_stateful_turn_passes_the_tools_fact(monkeypatch):
    """A6: `stateful_turn` passes tools_bound=True when tools are bound."""
    from pydantic import BaseModel
    import polymerhus.app.llm.session as S

    class _Schema(BaseModel):
        x: int = 0

    seen = {}

    def fake_format(role_id, schema, *, tools_bound):
        seen["tools_bound"] = tools_bound
        return None

    monkeypatch.setattr(S, "structured_response_format", fake_format)

    def fake_run(role_id, thread_id, msgs, *, response_format=None, **kw):
        return S.SessionTurn(content="ok", messages=[], thread_id=thread_id)

    monkeypatch.setattr(S, "run_session_turn", fake_run)
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool

    @tool
    def _t(x: str) -> str:
        """T."""
        return x

    S.stateful_turn("triager", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=_Schema, observe=False, tools=[_t])
    assert seen["tools_bound"] is True
    S.stateful_turn("triager", "t", [HumanMessage(content="x")],
                    checkpointer=None, schema=_Schema, observe=False)
    assert seen["tools_bound"] is False


def test_a6_fail_open_degrades_to_the_axis_semantic_default(monkeypatch):
    """A6/D7: a resolution failure degrades to the AXIS semantic default -
    `ProviderStrategy` (json_schema) for a pure turn, `ToolStrategy`
    (function_calling) for a tool-bound loop - so a tool loop never strands
    on the wrong rung."""
    from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
    from pydantic import BaseModel
    import polymerhus.app.llm.session as S

    class _Schema(BaseModel):
        x: int = 0

    def boom(provider, model):
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(S, "resolve_capability", boom)
    monkeypatch.setenv("LLM_TRIAGER", "openrouter:some/model")
    assert isinstance(
        S.structured_response_format("triager", _Schema, tools_bound=False),
        ProviderStrategy)
    assert isinstance(
        S.structured_response_format("triager", _Schema, tools_bound=True),
        ToolStrategy)


def test_union_schema_never_builds_providerstrategy(monkeypatch):
    """A union schema is carried by `ToolStrategy` ONLY: the pinned langchain
    `ProviderStrategy` rejects a `types.UnionType` (`_SchemaSpec` raises
    `Unsupported schema type`), while `ToolStrategy` flattens the variants
    (`_iter_variants`). The A6 seam must never hand a union to
    `ProviderStrategy`, whatever the negotiated/fail-open method says
    (regression: the hunt orchestrator's four-way verdict union)."""
    from langchain.agents.structured_output import ToolStrategy
    from pydantic import BaseModel
    import polymerhus.app.llm.session as S

    class _Gate(BaseModel):
        outcome: str = "failed"

    class _Note(BaseModel):
        note: str = ""

    monkeypatch.setenv("LLM_TRIAGER", "openrouter:some/model")

    def fake_capability(provider, model):
        from polymerhus.app.llm.capability import CapabilityProfile
        return CapabilityProfile(supports_structured_output=True,
                                 supports_tool_calling=True)

    monkeypatch.setattr(S, "resolve_capability", fake_capability)
    rf = S.structured_response_format("triager", _Gate | _Note, tools_bound=False)
    assert isinstance(rf, ToolStrategy)
    assert len(rf.schema_specs) == 2
