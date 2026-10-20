"""Unit tier: the hunting MAILBOX actors (`attack/hunting/actors.py`, #94).

`arun_orchestration` drives the Q8 gate turn and the D2 re-match judge as
inbox-request turns of ONE `HuntOrchestratorActor` per run on the
`hunting_orchestrator` session thread (purely stateful, exactly like the
recon-orchestrator), and each hunt's authoring/judging rides a per-hunt
`HuntingHunterActor` on its `HuntSession` thread. These tests exercise the
actors at the public client seams (`reason` / `author` / `judge` /
`stop` / the registry) with FAKE models and an `InMemorySaver`; the unit tier
touches no live model and no live database (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.attack.hunting.actors import (
    HuntOrchestratorActor,
    HuntingActorRegistry,
    HuntingHunterActor,
)
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    GateDecision,
    GateInput,
    PhaseTurnInput,
    Witness,
)
from lightrag.tool import LightRagQueryTool


class _ToolFake(BaseChatModel):
    """A one-reply scripted model emitting a NAMED tool call each turn - the
    shape `ToolStrategy(GateDecision | RatifyDecision | NoteDecision)` consumes,
    so the session turn's `content` is the parsed pydantic object."""

    call_name: str
    args: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="",
            tool_calls=[{"name": self.call_name, "args": self.args, "id": "c1", "type": "tool_call"}],
        ))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # Async-native on purpose: `ainvoke` on a SYNC-only BaseChatModel routes
        # `_generate` through `run_in_executor`, and langgraph (1.2.5) deadlocks
        # that path when the agent thread RESUMES from a checkpoint - the second
        # turn's model call never returns. Production models (ChatOpenAI) are
        # async-native, so the fakes must mirror that.
        return self._generate(
            messages,
            stop=stop,
            run_manager=run_manager.get_sync() if run_manager else None,
            **kwargs,
        )

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


class _TextFake(BaseChatModel):
    """A free-text fake (the hunter turns carry no response_format): emits a
    JSON body as plain content, which `_parse_json_object` recovers."""

    body: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.body))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # Async-native: see `_ToolFake._agenerate` for why (sync-only fakes
        # deadlock the resumed agent thread's model call).
        return self._generate(
            messages,
            stop=stop,
            run_manager=run_manager.get_sync() if run_manager else None,
            **kwargs,
        )

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        # As of #197 the author lane ALWAYS binds the lightrag tool, so a plain-
        # text fake must tolerate `bind_tools` (returns self - a tool-free reply
        # concludes the turn exactly like a real model declining the tool).
        return self


class _ToolLoopFake(BaseChatModel):
    """A per-instance two-reply scripted model: the first model call emits a
    `query_lightrag` tool call, the second emits the final text answer. The
    counter lives on the instance because ONE agent turn's tool loop reuses the
    same model for every model call."""

    tool_args: dict = {}
    final_body: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        calls = getattr(self, "_calls", 0)
        self._calls = calls + 1
        if calls == 0:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{
                    "name": "query_lightrag",
                    "args": self.tool_args,
                    "id": "c1",
                    "type": "tool_call",
                }],
            ))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.final_body))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # Async-native: see `_ToolFake._agenerate` for why.
        return self._generate(
            messages,
            stop=stop,
            run_manager=run_manager.get_sync() if run_manager else None,
            **kwargs,
        )

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _factory(args_list):
    """A `model_factory` yielding a fresh scripted model per turn, walking the
    script (one build per `run_session_agent` turn)."""
    cursor = {"i": 0}

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        args = args_list[min(i, len(args_list) - 1)]
        return _ToolFake(call_name=args[0], args=args[1])

    return make


class _RecordingToolFake(_ToolFake):
    """`_ToolFake` plus a per-call message recorder (the Q4 pin: which messages
    the actor's session turns actually carry). `recorder` is `object`-typed on
    purpose: a `list`-typed pydantic field would be re-validated into a COPY,
    and the test's `seen` list would stay empty."""

    recorder: object = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.recorder is not None:
            self.recorder.append(list(messages))
        return _ToolFake._generate(
            self, messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.recorder is not None:
            self.recorder.append(list(messages))
        return _ToolFake._generate(
            self, messages, stop=stop,
            run_manager=run_manager.get_sync() if run_manager else None, **kwargs)


def _gate_input() -> GateInput:
    return GateInput(candidates=[
        DeliveredCandidate(
            unit_id="Service:slug:a",
            fault_class="fault-x",
            applies_witnesses=Witness(deterministic="clause-1", llm="matches"),
            match_verdict="applies",
        ),
    ])


# --- the hunt-orchestrator actor -------------------------------------------------

def test_hunt_orchestrator_actor_reason_on_one_thread():
    """ONE actor per run: a Q8 gate turn on the `hunting_orchestrator` thread
    replying its structured object, and stop() ends it cleanly."""
    gate_args = {"directions": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x", "carried": True,
         "rationale": "plausible"}
    ]}

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(),
            model_factory=_factory([("GateDecision", gate_args)]),
            observe=False,
        )
        decision = await actor.reason(_gate_input())
        await actor.stop()
        return decision

    decision = asyncio.run(_drive())
    assert isinstance(decision, GateDecision)
    assert decision.directions[0].carried is True


def _gate_input_with_overview() -> GateInput:
    gate_input = _gate_input()
    gate_input.overview = (
        "APPLICATION OVERVIEW (the deployed application the following items "
        "belong to):\nDomain: shop"
    )
    return gate_input


def test_gate_turn_heads_with_the_dedicated_overview_message_once_per_thread():
    """Q4: the hypothesise turn heads with the dedicated Overview-only
    HumanMessage and the gate prompt chains to it; a SECOND gate turn on the
    same run thread does NOT restack the Overview (the #187 stacking
    precedent: the run thread is monotonic across all faults/pairs)."""
    gate_args = {"directions": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x", "carried": True,
         "rationale": "plausible"}
    ]}
    seen: list = []

    def factory(role_id):
        return _RecordingToolFake(
            call_name="GateDecision", args=gate_args, recorder=seen)

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(), model_factory=factory, observe=False,
        )
        first = await actor.hypothesise(_gate_input_with_overview())
        second = await actor.hypothesise(_gate_input_with_overview())
        await actor.stop()
        return first, second

    first, second = asyncio.run(_drive())
    assert isinstance(first, GateDecision) and isinstance(second, GateDecision)
    assert len(seen) == 2
    first_humans = [m.content for m in seen[0] if m.type == "human"]
    assert len(first_humans) == 2
    assert first_humans[0].startswith("APPLICATION OVERVIEW (")
    assert first_humans[1].startswith(
        "Grounded in the application overview above")
    second_contents = [m.content for m in seen[1]]
    overviews = [c for c in second_contents if c.startswith("APPLICATION OVERVIEW (")]
    assert len(overviews) == 1  # only the head-of-thread copy
    last_human = [m.content for m in seen[1] if m.type == "human"][-1]
    assert not last_human.startswith("Grounded in the application overview above")


def test_hypothesise_retries_once_on_a_wrong_union_member():
    """The relaxed (voluntary) rung can return the wrong union member on the
    hypothesise turn (NoteDecision / RatifyDecision). A wrong member is retried
    ONCE with an explicit correction, so a good retry recovers the pair instead
    of silently losing it (and feeding the degraded-turn breaker)."""
    gate_args = {"directions": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x", "carried": True,
         "rationale": "plausible"}]}
    note_args = {"notes": []}
    factory = _factory([("NoteDecision", note_args), ("GateDecision", gate_args)])

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(), model_factory=factory, observe=False,
        )
        decision = await actor.hypothesise(_gate_input())
        await actor.stop()
        return decision

    decision = asyncio.run(_drive())
    assert isinstance(decision, GateDecision)
    assert decision.directions[0].carried is True


def test_hypothesise_gives_up_after_a_failed_retry():
    """A retry that is STILL the wrong member degrades to no-decision (None)."""
    note_args = {"notes": []}
    factory = _factory([("NoteDecision", note_args), ("NoteDecision", note_args)])

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(), model_factory=factory, observe=False,
        )
        decision = await actor.hypothesise(_gate_input())
        await actor.stop()
        return decision

    assert asyncio.run(_drive()) is None


def test_hunt_orchestrator_actor_fail_open_on_raising_model():
    """A dead/raising actor never aborts the pass: reason degrades to None,
    which the pass's fail-open canon handles (carry)."""
    class _Boom(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("llm down")

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("llm down")

        @property
        def _llm_type(self) -> str:
            return "fake"

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(), model_factory=lambda role: _Boom(),
            observe=False,
        )
        decision = await actor.reason(_gate_input())
        await actor.stop()
        return decision

    decision = asyncio.run(_drive())
    assert decision is None


def test_orchestrator_actor_records_the_provider_degrade_cause():
    """#329: a turn that dies on a provider 429 is swallowed into a no-decision
    (the actor survives), and the actor RECORDS the exception so the pass can
    classify the abort as provider-caused."""
    import httpx
    import openai

    from polymerhus.app.llm.provider_failure import is_provider_unavailable

    def _rate_limit():
        request = httpx.Request("POST", "https://api.example.test/v1")
        return openai.RateLimitError(
            "Rate limit exceeded", response=httpx.Response(429, request=request),
            body=None)

    class _Throttled(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise _rate_limit()

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            raise _rate_limit()

        @property
        def _llm_type(self) -> str:
            return "fake"

        def bind_tools(self, tools, **kwargs):
            return self

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(),
            model_factory=lambda role: _Throttled(), observe=False,
        )
        decision = await actor.reason(_gate_input())
        cause = actor.last_degrade_cause()
        await actor.stop()
        return decision, cause

    decision, cause = asyncio.run(_drive())
    assert decision is None
    assert cause is not None
    assert is_provider_unavailable(cause)


def test_hunt_orchestrator_actor_reason_without_candidates_is_noop():
    async def _drive():
        actor = HuntOrchestratorActor("run1", checkpointer=InMemorySaver(), observe=False)
        out = await actor.reason(GateInput(candidates=[]))
        await actor.stop()
        return out

    assert asyncio.run(_drive()) is None  # never spawned a turn


def test_hunt_orchestrator_actor_stop_is_idempotent_without_spawn():
    async def _drive():
        actor = HuntOrchestratorActor("run1", checkpointer=InMemorySaver(), observe=False)
        await actor.stop()  # never spawned: no-op
        await actor.stop()  # idempotent

    asyncio.run(_drive())  # must not raise


def test_hunt_orchestrator_thread_keeps_one_system_message():
    """#187: ONE gate-skill SystemMessage per hunting_orchestrator thread, added
    once at the front (as `system_prompt`), never re-added per phase turn. A run
    that drives several hypothesise/ratify/note turns on the SAME thread sends
    EVERY model call the SAME single gate-skill SystemMessage at the front - the
    old per-turn `SystemMessage(content=_gate_skill())` re-add stacked a
    byte-identical copy into the trail on every turn (the ~145K of ~14 stale
    copies behind the #187 timeout)."""
    gate_args = {"directions": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x", "carried": True,
         "rationale": "plausible"}]}
    ratify_args = {"configs": []}
    note_args = {"notes": []}
    seen: list = []
    cursor = {"i": 0}
    script = [
        ("GateDecision", gate_args), ("RatifyDecision", ratify_args),
        ("NoteDecision", note_args),
        ("GateDecision", gate_args), ("RatifyDecision", ratify_args),
        ("NoteDecision", note_args),
    ]

    class _Recording(_ToolFake):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(list(messages))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def factory(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        name, args = script[min(i, len(script) - 1)]
        return _Recording(call_name=name, args=args)

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(), model_factory=factory, observe=False,
        )
        phase_input = PhaseTurnInput(pair=_gate_input().candidates[0])
        for _ in range(2):
            assert await actor.hypothesise(_gate_input()) is not None
            assert await actor.ratify(phase_input) is not None
            assert await actor.note(phase_input) is not None
        await actor.stop()
        return actor

    actor = asyncio.run(_drive())
    assert len(seen) == 6  # six phase turns on the same thread
    for model_input in seen:
        system_messages = [m for m in model_input
                           if isinstance(m, SystemMessage)
                           and not str(m.content or "").startswith("[running summary]")]
        assert len(system_messages) == 1, "exactly ONE gate-skill system message per call"
        assert "hunt-orchestrator" in str(system_messages[0].content)
        assert model_input[0] is system_messages[0], "the gate skill sits once at the front"
    # The messages CHANNEL (the persisted trail) carries NO per-turn skill copies:
    # only the six phase HumanMessages survive on the thread.
    trail = actor._task.result().turns[-1].messages
    plain_system = [m for m in trail if isinstance(m, SystemMessage)]
    assert plain_system == []
    humans = [m for m in trail if isinstance(m, HumanMessage)]
    assert len(humans) == 6


# --- the per-hunt hunting-hunter actor --------------------------------------------

def test_hunting_hunter_actor_authors_and_judges_on_one_thread():
    """ONE actor per hunt: the author (D4) and judge (D5) turns on the SAME
    `HuntSession` thread, free-text JSON replies parsed back, stop() clean."""
    body_a = json.dumps({"target_identity": {"url": "http://a/", "unit_id": "Service:slug:a"}, "rationale": "spec"})
    body_j = json.dumps({"meaningful_insight": False, "next_step": "end", "rationale": "r"})
    cursor = {"i": 0}

    def factory(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _TextFake(body=(body_a, body_j)[min(i, 1)])

    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-7", checkpointer=InMemorySaver(), model_factory=factory,
            observe=False,
        )
        spec = await actor.author("compose the spec")
        verdict = await actor.judge("any judgment text")
        await actor.stop()
        return spec, verdict

    spec, verdict = asyncio.run(_drive())
    assert spec == {"target_identity": {"url": "http://a/", "unit_id": "Service:slug:a"}, "rationale": "spec"}
    assert verdict == {"meaningful_insight": False, "next_step": "end", "rationale": "r"}


def test_hunting_hunter_actor_unparseable_turn_is_none():
    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-8", checkpointer=InMemorySaver(),
            model_factory=lambda role: _TextFake(body="not json at all"), observe=False,
        )
        out = await actor.author("compose")
        await actor.stop()
        return out

    assert asyncio.run(_drive()) is None  # degraded turn, fail-open


def test_hunting_hunter_actor_resumes_after_two_author_turns():
    """Regression: two consecutive turns on the SAME per-hunt thread must both
    complete. This used to deadlock inside the second turn's model call with
    sync-only fakes (langgraph resume + `run_in_executor`); the fakes are now
    async-native, matching the production ChatOpenAI path."""
    cursor = {"i": 0}

    def factory(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _TextFake(body=json.dumps({"spec": i}))

    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-r", checkpointer=InMemorySaver(), model_factory=factory,
            observe=False,
        )
        first = await actor.author("compose first")
        second = await actor.author("compose second")
        await actor.stop()
        return first, second

    first, second = asyncio.run(_drive())
    assert first == {"spec": 0}
    assert second == {"spec": 1}


# --- the per-run registry -----------------------------------------------------------

def test_registry_routes_per_hunt_and_reaps_every_actor():
    """The run's registry keys actors by hunt_id: concurrent hunts never
    collide, and stop_all() reaps every spawned actor (idempotent)."""
    async def _drive():
        registry = HuntingActorRegistry(
            "run1", checkpointer=InMemorySaver(),
            model_factory=lambda role: _TextFake(body='{"hunt": "x"}'), observe=False,
        )
        # per-hunt distinct threads
        a = registry.actor_for("hunt-a")
        b = registry.actor_for("hunt-b")
        assert a.thread_id != b.thread_id
        assert "hunt-a" in a.thread_id and "hunt-b" in b.thread_id
        assert registry.actor_for("hunt-a") is a  # same actor, same thread
        # the bound author/judge closures route to the right hunt
        out = await registry.author_fn("hunt-a")("compose")
        await registry.stop_all()
        return out

    outcome = asyncio.run(_drive())
    assert outcome == {"hunt": "x"}


def test_author_tools_reach_run_session_agent(monkeypatch):
    """author_tools on the registry land on the actor and are forwarded to
    run_session_agent's kwargs when non-empty."""
    import polymerhus.app.llm.actor as llm_actor

    captured = {}

    async def fake_run_session_agent(
        role_id, thread_id, initial_messages, **kwargs
    ):
        captured.update(kwargs)

    monkeypatch.setattr(llm_actor, "run_session_agent", fake_run_session_agent)

    async def _drive():
        registry = HuntingActorRegistry(
            "run-1", author_tools=["fake-tool"], project_id="proj-1",
            checkpointer=InMemorySaver(), observe=False,
        )
        actor = registry.actor_for("hunt-1")
        assert "fake-tool" in actor._tools
        await actor._ensure_started()
        await actor._task
        return actor

    actor = asyncio.run(_drive())
    assert actor._tools == ["fake-tool"]
    # The actor's turns are scoped to the run's project in the usage ledger.
    assert captured["usage_scope"] == "proj-1"
    # The skill binding (#232) rides the same bounding seam: the universal
    # read-only pair `load_skill` + `record_skill_lesson`, then the auth
    # capability's `auth_store` (#220).
    assert [getattr(t, "name", t) for t in captured["tools"]] == [
        "fake-tool",
        "load_skill",
        "record_skill_lesson",
        "auth_store",
    ]


def test_hunting_hunter_actor_runs_query_lightrag_tool_loop_hermetically():
    """The full tool-calling loop, without any live service: the outer model
    first calls `query_lightrag`, the fake client/llm answer hermetically, a
    ToolMessage is produced, and the actor's final author reply uses the tool
    output (the mini live smoke, repeatable in the unit suite)."""
    class _FakeClient:
        def query_data(self, payload):
            return {
                "status": "success",
                "message": "ok",
                "data": {
                    "entities": [],
                    "relationships": [],
                    "chunks": [
                        {
                            "reference_id": "doc-1",
                            "file_path": "WSTG-ATHZ/x.md",
                            "content": "Methodology text about object id tampering.",
                        }
                    ],
                    "references": [
                        {"reference_id": "doc-1", "file_path": "WSTG-ATHZ/x.md"}
                    ],
                },
                "metadata": {"processing_info": {"final_chunks_count": 1}},
            }

    class _FakeLlm:
        def stream(self, prompt):
            yield {"type": "delta", "text": '{"scenario_id": "SIM-01", "summary": "ok",'}
            yield {
                "type": "delta",
                "text": (
                    '"ontology_explanations": [{"entity_type": "AttackTechnique", '
                    '"entity_name": "Object-level authorization comparison", '
                    '"explanation": "Compare authorization behavior for adjacent ids."}],'
                ),
            }
            yield {"type": "delta", "text": '"knowledge_gaps": ["g"]}'}
            yield {"type": "finish", "finish_reason": "stop"}

    tool = LightRagQueryTool(client=_FakeClient(), llm=_FakeLlm())
    tool_args = {
        "scenario_id": "SIM-01",
        "attack_goal": "Identify a bounded comparison hypothesis",
        "concern": "object-level authorization",
        "acceptable_technique_families": ["Object-level authorization comparison"],
    }
    final_body = json.dumps({
        "methodology": "Object-level authorization comparison",
        "verdict": "grounded",
    })

    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-tool", checkpointer=InMemorySaver(),
            model_factory=lambda role: _ToolLoopFake(
                tool_args=tool_args, final_body=final_body,
            ),
            observe=False, author_tools=[tool],
        )
        out = await actor.author("compose")
        await actor.stop()
        return out, actor

    out, actor = asyncio.run(_drive())
    assert out == {"methodology": "Object-level authorization comparison", "verdict": "grounded"}
    trail = actor._task.result().turns[-1].messages
    tool_msgs = [m for m in trail if type(m).__name__ == "ToolMessage"]
    assert tool_msgs, "the query_lightrag tool call must be executed"
    assert "Object-level authorization comparison" in tool_msgs[0].content


def test_lightrag_tool_always_bound(monkeypatch):
    # As of #197 the HUNTING_LIGHTRAG_TOOL gate is REMOVED: the lightrag tool is
    # always bound into the author lane (fail-open when the KB is unavailable).
    import polymerhus.attack.hunting.actors as actors

    monkeypatch.setattr(
        actors,
        "_lightrag_author_tools",
        lambda: ["lightrag-tool"],
    )
    registry = actors.HuntingActorRegistry("run-1")
    assert "lightrag-tool" in registry.actor_for("hunt-1")._tools


def test_run_scoped_actors_tag_turns_with_the_run_id():
    """Convergence join: both run-scoped actors expose the bare run id as the
    turn tags now that the hand-written agent/gate spans are gone."""
    from polymerhus.attack.hunting.actors import HuntingHunterActor, HuntOrchestratorActor

    assert HuntOrchestratorActor("run1")._extra_tags == ["run1"]
    assert HuntingHunterActor("run1", "hunt-a")._extra_tags == ["run1"]


# --- A6: the hunt verdict strategy is negotiated, not pinned --------------------

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _a6_negotiated_tool_strategy(monkeypatch):
    """A6: the actor's `structured_response_format` negotiation resolves to
    `ToolStrategy` in this scripted-model suite (the fakes emit the
    ToolStrategy tool-call shape), while production negotiates per profile."""
    from langchain.agents.structured_output import ToolStrategy
    import polymerhus.app.llm.session as _S

    def _fake(role_id, schema, *, tools_bound):
        return ToolStrategy(schema)

    monkeypatch.setattr(_S, "structured_response_format", _fake)


def test_a6_hunt_verdict_uses_the_negotiated_strategy(monkeypatch):
    """A6: the hunt orchestrator computes `response_format` from the REAL
    binding fact via `structured_response_format("hunting_orchestrator",
    <gate union>, tools_bound=...)` and passes its result through to the
    session agent (no raw pin)."""
    from typing import get_args
    from langchain.agents.structured_output import ToolStrategy
    import polymerhus.app.llm.actor as _A
    import polymerhus.app.llm.session as _S
    from polymerhus.attack.hunting.hunt_orchestrator import NoteDecision, RatifyDecision

    calls = {}
    sentinel = ToolStrategy(GateDecision)

    def _fake_format(role_id, schema, *, tools_bound):
        calls.update(role_id=role_id, schema=schema, tools_bound=tools_bound)
        return sentinel

    monkeypatch.setattr(_S, "structured_response_format", _fake_format)
    seen = {}

    async def _fake_run(*args, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(_A, "run_session_agent", _fake_run)

    async def _drive():
        actor = HuntOrchestratorActor("run1", checkpointer=InMemorySaver(),
                                      model_factory=_factory([("GateDecision", {})]),
                                      observe=False, project_id="proj-1")
        await actor._ensure_started()
        await actor.stop()

    asyncio.run(_drive())
    assert calls["role_id"] == "hunting_orchestrator"
    assert set(get_args(calls["schema"])) == {
        GateDecision, RatifyDecision, NoteDecision}
    assert calls["tools_bound"] is True  # the #236 read grants always bind a surface
    assert seen["response_format"] is sentinel
    # The orchestrator's turns are scoped to the run's project in the usage ledger.
    assert seen["usage_scope"] == "proj-1"


# --- #292: the conciseness directive in the orchestrator tool descriptions ----

def test_orchestrator_store_tool_descriptions_carry_the_conciseness_directive():
    """The orchestrator's `hunts_store` / `notes` tool descriptions carry the
    single-sourced conciseness directive verbatim (#292), so the model reads the
    writing cap wherever it decides what to write."""
    from types import SimpleNamespace

    from polymerhus.attack.hunting.actors import build_orchestrator_tool_surface
    from polymerhus.attack.hunting.llm import HUNTING_CONCISENESS_DIRECTIVE

    tools = SimpleNamespace(graph_view=None, store_reads=None, phase_context=None)
    surface = {t.name: t for t in build_orchestrator_tool_surface(
        tools, run_id="run1", project_id="proj-1")}
    for name in ("hunts_store", "notes"):
        assert HUNTING_CONCISENESS_DIRECTIVE in surface[name].description, name


def test_hunt_orchestrator_actor_binds_the_read_grants(monkeypatch, tmp_path):
    """#236: the orchestrator's session binds exactly `ORCHESTRATOR_SURFACE` -
    the three seam-backed tools plus the two operator-ruled read grants. The
    full `load_skill` lists descriptions and loads any named body;
    `record_skill_lesson` and `write_skill` are never on this surface."""
    from polymerhus.attack.hunting.hunt_orchestrator import (
        ORCHESTRATOR_READ_GRANTS,
        ORCHESTRATOR_SURFACE,
        OrchestratorTools,
        ReadOnlyGraphView,
    )
    from polymerhus.attack.hunting.hunt_store import HuntStore

    seen = {}

    async def fake_run_session_agent(*args, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr("polymerhus.app.llm.actor.run_session_agent",
                        fake_run_session_agent)
    store = HuntStore(tmp_path)
    tools = OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView("project-1", read_fn=lambda cy, p: []),
    )

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", tools=tools, project_id="project-1",
            checkpointer=InMemorySaver(), observe=False,
        )
        await actor._ensure_started()
        await actor.stop()

    asyncio.run(_drive())

    by_name = {t.name: t for t in seen["tools"]}
    assert set(by_name) == set(ORCHESTRATOR_SURFACE)
    assert set(by_name) == {"hunts_store", "notes", "graph_view",
                            "search_http_history", "get_http_artifact",
                            "load_skill"}
    assert ORCHESTRATOR_READ_GRANTS <= set(by_name)
    assert "record_skill_lesson" not in by_name
    assert "write_skill" not in by_name
    # The grants carry no auth capability and no `authn` skill (the
    # orchestrator's listing surface is capability-free).
    assert "auth_store" not in by_name
    # The full load: the listing works and a named load returns the body.
    listing = by_name["load_skill"].invoke({"pattern": "^ssrf$"})
    assert "- ssrf: " in listing
    loaded = by_name["load_skill"].invoke({"name": "ssrf"})
    assert "description-only" not in loaded
    assert loaded.strip()
    assert loaded.startswith("# ")
    # The HTTP-history read pair is the SAME implementation the hunter binds.
    from polymerhus.attack.hunting.hunter_tools import (
        HttpHistoryGetTool,
        HttpHistorySearchTool,
    )
    assert isinstance(by_name["search_http_history"], HttpHistorySearchTool)
    assert isinstance(by_name["get_http_artifact"], HttpHistoryGetTool)


def test_hunt_orchestrator_actor_binds_the_read_grants_without_a_store_seam(
    monkeypatch,
):
    """The grants are UNCONDITIONAL: a drive with no store seam still binds the
    HTTP-history read pair and the full `load_skill` grant (the seam-backed
    three are the only part gated on the injected tools object)."""
    from polymerhus.attack.hunting.hunt_orchestrator import ORCHESTRATOR_READ_GRANTS

    seen = {}

    async def fake_run_session_agent(*args, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr("polymerhus.app.llm.actor.run_session_agent",
                        fake_run_session_agent)

    async def _drive():
        actor = HuntOrchestratorActor("run1", checkpointer=InMemorySaver(),
                                      observe=False)
        await actor._ensure_started()
        await actor.stop()

    asyncio.run(_drive())

    assert {t.name for t in seen["tools"]} == set(ORCHESTRATOR_READ_GRANTS)
