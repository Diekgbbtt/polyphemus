"""Unit tier: the hunting MAILBOX actors (`attack/hunting/actors.py`, #94).

`arun_orchestration` drives the Q8 gate turn and the D2 re-match judge as
inbox-request turns of ONE `HuntOrchestratorActor` per run on the
`hunting_orchestrator` session thread (purely stateful, exactly like the
recon-orchestrator), and each hunt's authoring/judging rides a per-hunt
`HuntingHunterActor` on its `HuntSession` thread. These tests exercise the
actors at the public client seams (`reason` / `rematch` / `author` / `judge` /
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
    EnvisionedDirection,
    GateDecision,
    GateInput,
    MatchVerdict,
    PhaseTurnInput,
    Witness,
)
from lightrag.tool import LightRagQueryTool
from polymerhus.recon.control.targeted import TargetedReconResult


class _ToolFake(BaseChatModel):
    """A one-reply scripted model emitting a NAMED tool call each turn - the
    shape `ToolStrategy(GateDecision | MatchVerdict)` consumes, so the session
    turn's `content` is the parsed pydantic object."""

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

def test_hunt_orchestrator_actor_gate_then_rematch_on_one_thread():
    """ONE actor per run: a Q8 gate turn then a D2 re-match turn on the SAME
    `hunting_orchestrator` thread, each replying its structured object, and
    stop() ends it cleanly."""
    gate_args = {"directions": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x", "carried": True,
         "rationale": "plausible"}
    ]}
    verdict_args = {"unit_id": "Service:slug:a", "fault_class": "fault-x",
                    "verdict": "applies"}

    async def _drive():
        actor = HuntOrchestratorActor(
            "run1", checkpointer=InMemorySaver(),
            model_factory=_factory([("GateDecision", gate_args), ("MatchVerdict", verdict_args)]),
            observe=False,
        )
        decision = await actor.reason(_gate_input())
        verdict = await actor.rematch(
            "Service:slug:a", "fault-x",
            TargetedReconResult(correlation_id="c1", requester_id="r", origin="hunting",
                                status="success", pod_exports=[]),
        )
        await actor.stop()
        return decision, verdict

    decision, verdict = asyncio.run(_drive())
    assert isinstance(decision, GateDecision)
    assert decision.directions[0].carried is True
    assert isinstance(verdict, MatchVerdict)
    assert verdict.verdict == "applies"


def test_hunt_orchestrator_actor_fail_open_on_raising_model():
    """A dead/raising actor never aborts the pass: reason/rematch degrade to
    None, which the pass's fail-open canon handles (carry / unresolved)."""
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
        verdict = await actor.rematch("a", "f", None)
        await actor.stop()
        return decision, verdict

    decision, verdict = asyncio.run(_drive())
    assert decision is None
    assert verdict is None


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
            "run-1", author_tools=["fake-tool"],
            checkpointer=InMemorySaver(), observe=False,
        )
        actor = registry.actor_for("hunt-1")
        assert "fake-tool" in actor._tools
        await actor._ensure_started()
        await actor._task
        return actor

    actor = asyncio.run(_drive())
    assert actor._tools == ["fake-tool"]
    assert captured["tools"] == ["fake-tool"]


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
