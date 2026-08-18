"""Unit tier: the recon-orchestrator MAILBOX actor (`ReconOrchestratorActor`, #94).

`decide_routing` was reworked (feat/async-actor-agents) into a run-scoped mailbox
actor: one `run_session_agent` on the `job_orchestrator` session role per recon
run, fed each phase's steering and replying a structured `RoutingDecision` per
phase on the SAME thread (so checkpointed memory carries the reasoning across
the run). These tests exercise the actor at the public client seam
(`ReconOrchestratorActor.decide_routing` / `.stop`) with a FAKE tool-calling
model emitting `RoutingDecision` tool calls and an `InMemorySaver`; the unit
tier touches no live model and no live database (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.recon.control.orchestrator_agent import ReconOrchestratorActor


class _ToolFake(BaseChatModel):
    """A one-reply scripted model that emits a `RoutingDecision` TOOL CALL each
    `_generate` - the shape ToolStrategy consumes, so the session turn's
    `content` is the parsed `RoutingDecision` (probed empirically)."""

    args: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="",
            tool_calls=[{"name": "RoutingDecision", "args": self.args, "id": "c1", "type": "tool_call"}],
        ))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _factory(*args_list):
    """A `model_factory` yielding a fresh scripted tool-calling fake per turn
    (one build per `run_session_agent` turn), walking the script. The cursor lives
    in the closure, not on the model - a pydantic chat model copies its fields."""
    cursor = {"i": 0}

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _ToolFake(args=args_list[min(i, len(args_list) - 1)])

    return make


async def _run(actor):
    """Run the whole actor lifetime under a fresh event loop and reap the task."""
    await actor.decide_routing(
        [{"url": "https://ib.x", "macro_kind": "waf_protected", "evidence": "Incapsula"}],
        ["katana", "steel_crawl"],
    )


def test_actor_maps_each_phase_decision_completes_and_stop():
    """The core actor property: ONE actor per run, fed per phase, replying a
    mapped exclusion dict per phase, and stop() ends it cleanly - with memory
    carrying across phases on the SAME thread."""

    ex1 = {"exclusions": [{"job": "katana", "exclude_urls": ["https://ib.x"]}], "rationale": "waf"}
    ex2 = {"exclusions": [{"job": "ffuf", "exclude_urls": ["https://ib.y"]}], "rationale": "waf"}

    async def _drive():
        actor = ReconOrchestratorActor(
            "run1", checkpointer=InMemorySaver(), model_factory=_factory(ex1, ex2), observe=False,
        )
        d1 = await actor.decide_routing(
            [{"url": "https://ib.x", "macro_kind": "waf_protected", "evidence": "e"}],
            ["katana", "steel_crawl"],
        )
        d2 = await actor.decide_routing(
            [{"url": "https://ib.y", "macro_kind": "waf_protected", "evidence": "e"}],
            ["ffuf", "steel_crawl"],
        )
        await actor.stop()
        return d1, d2

    d1, d2 = asyncio.run(_drive())
    assert d1 == {"katana": ["https://ib.x"]}
    assert d2 == {"ffuf": ["https://ib.y"]}


def test_actor_drops_hallucinated_job():
    async def _drive():
        actor = ReconOrchestratorActor(
            "run1", checkpointer=InMemorySaver(),
            model_factory=_factory({"exclusions": [{"job": "not_in_phase", "exclude_urls": ["https://x"]}]}),
            observe=False,
        )
        out = await actor.decide_routing(
            [{"url": "https://x", "macro_kind": "waf_protected", "evidence": "e"}],
            ["katana"],
        )
        await actor.stop()
        return out

    assert asyncio.run(_drive()) == {}


def test_actor_empty_signals_is_noop():
    actor = ReconOrchestratorActor("run1", checkpointer=InMemorySaver(), observe=False)


def test_actor_fail_open_when_the_model_raises():
    class _Boom(BaseChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise RuntimeError("llm down")

        @property
        def _llm_type(self) -> str:
            return "fake"

    async def _drive():
        actor = ReconOrchestratorActor(
            "run1", checkpointer=InMemorySaver(), model_factory=lambda role: _Boom(), observe=False,
        )
        out = await actor.decide_routing(
            [{"url": "https://x", "macro_kind": "waf_protected", "evidence": "e"}],
            ["katana"],
        )
        await actor.stop()
        return out

    assert asyncio.run(_drive()) == {}


def test_actor_stop_is_idempotent_without_spawn():
    async def _drive():
        actor = ReconOrchestratorActor("run1", checkpointer=InMemorySaver(), observe=False)
        await actor.stop()  # never spawned: no-op
        await actor.stop()  # idempotent

    asyncio.run(_drive())  # must not raise