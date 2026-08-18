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
from langchain_core.messages import AIMessage
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
    Witness,
)
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

    @property
    def _llm_type(self) -> str:
        return "fake"


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


# --- the per-hunt hunting-hunter actor --------------------------------------------

def test_hunting_hunter_actor_authors_and_judges_on_one_thread():
    """ONE actor per hunt: the author (D4) and judge (D5) turns on the SAME
    `HuntSession` thread, free-text JSON replies parsed back, stop() clean."""
    body_a = json.dumps({"target_identity": {"unit": "a"}, "rationale": "spec"})
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
    assert spec == {"target_identity": {"unit": "a"}, "rationale": "spec"}
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
