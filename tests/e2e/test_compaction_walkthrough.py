"""E2E walkthrough (#95 D9): compaction fires in BOTH production consumer state machines.

Two consumers are wired (ADR D9): the hunting hunter's TOOL-CALLING async actor lane
(`HuntingHunterActor` -> `run_session_agent`) and the analysis mechanism-typist's
CHAINED TEXT-GENERATOR session lane (`stateful_invoke_fn` -> `stateful_turn` ->
`run_session_turn`). This file drives BOTH through their REAL consumer entry points -
no faked `stateful_turn`, no inlined middleware - against the real session loop and a
realistic model, asserting the observable outcome (a running-summary message on the
thread / the manager's last report with reclaimed tokens).

Why a scripted model rather than a live provider call: the runtime condition
compaction READS is per-step occupancy (the provider's `input_tokens` + `cache_read`
usage metadata), not the model's text. A scripted ChatOpenAI-shaped fake emitting
realistic usage metadata therefore reproduces the runtime condition exactly, while a
live provider call adds only latency and a free-tier rate limit - never a different
code path. Everything else is the real deployed wiring: the consumer entry points,
the role middleware builder, and the `create_agent` loop.

Runs in-network (the sanctioned e2e runner, `docker compose run --rm tests`) against
the real checkpointer resolution; the compaction component is checkpointer-agnostic,
so the in-process saver the consumers resolve is the honest seam.
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm import compaction as C
from polymerhus.app.llm.session import read_session_memory
from polymerhus.attack.hunting import llm as HL
from polymerhus.attack.hunting.actors import HuntingHunterActor

GOOD_SUMMARY_TEXT = (
    "The hunter enumerated three auth endpoints and patched two; the login "
    "flow still exposes the third path to close."
)

AUTHOR_BODY = json.dumps({
    "target_identity": {"unit": "a"},
    "rationale": "spec " + ("long-reasoning-trail " * 400),
})
JUDGE_BODY = json.dumps({"meaningful_insight": False, "next_step": "end", "rationale": "r"})


def _usage(input_tokens, output_tokens=0, cache_read=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_token_details": {"cache_read": cache_read},
    }


class _RealisticModel(BaseChatModel):
    """A ChatOpenAI-shaped fake emitting REAL per-step usage metadata.

    Turn calls return a long answer carrying the occupancy the ledger reads; the
    compaction summariser's structured call (whose composed user message opens with
    the running-summary preamble) returns a `SummaryUpdate` tool call."""

    body: str = ""
    summary_text: str = GOOD_SUMMARY_TEXT
    usage: dict | None = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(m, HumanMessage)
               and str(m.content or "").startswith("Prior running summary:")
               for m in messages):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{"name": "SummaryUpdate", "args": {
                    "summary_text": self.summary_text, "decisions": ["keep it"]},
                    "id": "sum", "type": "tool_call"}]))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=self.body, usage_metadata=self.usage))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _turn_factory(bodies, usage):
    cursor = {"i": 0}

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _RealisticModel(body=bodies[min(i, len(bodies) - 1)], usage=usage)

    return make


def test_hunter_tool_calling_lane_compacts_e2e(monkeypatch):
    """D9 consumer 1 (tool-calling): an over-budget author turn on the per-hunt
    `HuntingHunterActor` spawns the out-of-band pass, the judge's barrier awaits and
    applies it, and BOTH turns still parse - the actor lane runs compacted, observable
    through the manager's last report (D11)."""
    import polymerhus.app.llm.providers as P

    monkeypatch.setenv("LLM_MODEL_HUNTING_HUNTER", "opencode:gpt-test")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)

    def spy(provider, model, **kw):
        return _RealisticModel(body="", summary_text=GOOD_SUMMARY_TEXT)

    monkeypatch.setattr(P, "build_chat_model", spy)

    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    mw = HL.build_hunter_compaction_middleware(
        window=window, store=C.InMemoryToolOutputStore())

    async def drive():
        actor = HuntingHunterActor(
            "run-e2e-hunter", "hunt-x", checkpointer=InMemorySaver(),
            model_factory=_turn_factory([AUTHOR_BODY, JUDGE_BODY], _usage(1000, output_tokens=10)),
            observe=False, compaction=mw)
        spec = await actor.author("compose the spec")
        verdict = await actor.judge("judge the result")
        await actor.stop()
        return actor, spec, verdict

    actor, spec, verdict = asyncio.run(drive())
    assert spec == json.loads(AUTHOR_BODY)
    assert verdict == json.loads(JUDGE_BODY)
    report = mw.manager.last_report(actor.thread_id)
    assert report is not None
    assert report.readability == C.READABILITY_COMPACTED
    assert report.summary_status == "ok"
    assert report.reclaimed_tokens > 0


def test_mechanism_typist_chained_lane_compacts_e2e(monkeypatch):
    """D9 consumer 2 (chained text generator): repeated reflection turns on the
    mechanism-typist's ONE growing session thread cross the budget, the next turn's
    barrier applies the staged running summary, and the persisted thread carries the
    synthetic summary message - the chained lane compacts as a whole."""
    import polymerhus.app.llm.providers as P

    monkeypatch.setenv("LLM_MODEL_ANALYSER", "opencode:gpt-test")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("LLM_COMPACTION_THRESHOLD", "0.01")

    def spy(provider, model, **kw):
        return _RealisticModel(
            body="the mechanism layer evidences a shared REST paradigm overlay " + ("x" * 4000),
            summary_text=GOOD_SUMMARY_TEXT,
            usage=_usage(5000, output_tokens=50))

    # The turn model resolves through `chat_model_for` (which holds a module-level
    # `build_chat_model` reference) while the summariser resolves the provider's
    # `build_chat_model` lazily - patch both so the chained lane is fully faked.
    import polymerhus.app.llm.roles as R
    monkeypatch.setattr(P, "build_chat_model", spy)
    monkeypatch.setattr(R, "build_chat_model", spy)

    from polymerhus.analysis.mechanism_typist import stateful_invoke_fn

    saver = InMemorySaver()
    invoke = stateful_invoke_fn("run-e2e-typist", saver)
    invoke([HumanMessage(content="reflect on the first surface")], schema=None)
    invoke([HumanMessage(content="reflect on the second surface")], schema=None)

    mem = read_session_memory(saver, "run-e2e-typist:mechanism_typist")
    assert mem is not None
    contents = [str(m.content) for m in mem.messages]
    assert any(c.startswith("[running summary]") for c in contents), \
        "the compacted thread must carry the synthetic running-summary message"
    assert GOOD_SUMMARY_TEXT in "".join(contents)
