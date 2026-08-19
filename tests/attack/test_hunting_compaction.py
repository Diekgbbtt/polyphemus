"""Unit tier: slice F of #95 - the hunting hunter's async lane runs compacted.

D9 wires the context-window compaction middleware into the per-hunt
`HuntingHunterActor`'s `run_session_agent` turns (the production async lane
ONLY; the sync ContextVar `hunt_session` rollback lane is deliberately NOT
touched). This module exercises the wiring end-to-end with FAKE models and an
`InMemorySaver`: the actor attaches the middleware, the author/judge turns still
parse under an in-flight compact pass, the no-middleware baseline is identical,
the shared summariser factory builds a structured-output call under the #73 read
budget, and a raising capability reader degrades the profile, never the hunter.

Hermetic by construction: no live model, no live gateway, no database
(CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
import pytest

from polymerhus.app.llm import compaction as C
from polymerhus.app.llm import summary as S
from polymerhus.attack.hunting import llm as HL
from polymerhus.attack.hunting.actors import HuntingHunterActor

GOOD_SUMMARY_TEXT = (
    "The hunter enumerated three auth endpoints and patched two; the login "
    "flow still exposes the third path to close."
)

# The author's reply is a long JSON body so the compact pass reclaims real tokens.
AUTHOR_BODY = json.dumps({
    "target_identity": {"unit": "a"},
    "rationale": "spec " + ("long-reasoning-trail " * 400),
})
JUDGE_BODY = json.dumps({"meaningful_insight": False, "next_step": "end", "rationale": "r"})


def _usage(input_tokens, output_tokens=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


@pytest.fixture
def clean_llm_env(monkeypatch):
    """Drop the LLM env vars so the fail-open window/profile resolution stays
    deterministic and never touches a gateway (hermetic unit tier)."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL_HUNTING_HUNTER", raising=False)
    monkeypatch.delenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", raising=False)
    monkeypatch.delenv("LLM_ATTEMPT_TIMEOUTS_S", raising=False)


class _CompactedHunterFake(BaseChatModel):
    """A scripted fake for the compacted hunter lane.

    The hunter's session turns (free-text, no response_format) emit the scripted
    JSON body with real-looking usage; the compaction summariser's structured call
    (whose composed user message opens with the running-summary preamble) emits a
    `SummaryUpdate` tool call."""

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


def _hunter_factory(bodies, usage=None):
    """A turn `model_factory` yielding a fresh `_CompactedHunterFake` per build -
    the hunter's turns walk `bodies`, the last entry repeats."""
    cursor = {"i": 0}

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _CompactedHunterFake(
            body=bodies[min(i, len(bodies) - 1)], usage=usage)

    return make


def _patch_summary_model(monkeypatch, budgets=None, summary_text=GOOD_SUMMARY_TEXT):
    """Point the summariser's model build at the scripted fake and record the
    per-attempt read budget (#73), exactly as the production `build_chat_model`
    path applies it (`read_timeout=budget` at construction, never an invoke kwarg)."""
    import polymerhus.app.llm.providers as P

    monkeypatch.setenv("LLM_MODEL_HUNTING_HUNTER", "openai:gpt-test")

    def spy(provider, model, **kw):
        if budgets is not None:
            budgets.append(kw.get("read_timeout"))
        return _CompactedHunterFake(body="", summary_text=summary_text)

    monkeypatch.setattr(P, "build_chat_model", spy)


def _drive_hunter(compaction, bodies, *, usage=None, run_id="run1", hunt_id="hunt-x"):
    """Drive one HuntingHunterActor through author then judge and return
    `(actor, spec, verdict)`."""
    factory = _hunter_factory(bodies, usage=usage)

    async def _drive():
        actor = HuntingHunterActor(run_id, hunt_id, checkpointer=InMemorySaver(),
                                   model_factory=factory, observe=False,
                                   compaction=compaction)
        spec = await actor.author("compose the spec")
        verdict = await actor.judge("judge the result")
        await actor.stop()
        return actor, spec, verdict

    return asyncio.run(_drive())


# --- (a) the actor attaches the compaction middleware to its turns -------------

def test_hunter_actor_auto_wires_compaction_middleware(clean_llm_env):
    """D9: a hunter constructed with a fake model_factory attaches the hunting-side
    compaction middleware to its turns BY DEFAULT (compaction=None auto-wires); the
    middleware's after_model ledger records the actor's per-hunt thread."""
    actor, spec, verdict = _drive_hunter(None, [AUTHOR_BODY, JUDGE_BODY])
    assert spec == json.loads(AUTHOR_BODY)
    assert verdict == json.loads(JUDGE_BODY)
    manager = actor.compaction_manager
    assert manager is not None
    assert manager.ledger.entry(actor.thread_id) is not None


# --- (b) author/judge still work end-to-end under a live compact pass ----------

def test_hunter_actor_author_and_judge_survive_a_compact_pass(clean_llm_env, monkeypatch):
    """D9 end-to-end: an over-budget author turn spawns the out-of-band pass, the
    judge's before_model awaits and applies the staged trail, and BOTH turns still
    parse - the production async lane runs compacted while staying functional, and
    the pass is observable through the manager's last report (D11)."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    budgets: list = []
    _patch_summary_model(monkeypatch, budgets=budgets)
    mw = HL.build_hunter_compaction_middleware(
        window=window, store=C.InMemoryToolOutputStore())

    actor, spec, verdict = _drive_hunter(
        mw, [AUTHOR_BODY, JUDGE_BODY], usage=_usage(1000, output_tokens=10))
    assert spec == json.loads(AUTHOR_BODY)
    assert verdict == json.loads(JUDGE_BODY)
    report = mw.manager.last_report(actor.thread_id)
    assert report is not None
    assert report.readability == C.READABILITY_COMPACTED
    assert report.summary_status == "ok"
    assert report.reclaimed_tokens > 0
    assert budgets  # the pass drove the summariser under the escalating budget


# --- (c) with no middleware the behaviour is identical (inert default) ----------

def test_hunter_without_compaction_behaves_identically(clean_llm_env):
    """D9 preserve-the-baseline: with compaction explicitly NOT wired
    (compaction=False) and with the default auto-wired middleware (inert: nothing
    over budget, no summariser spawned) the author/judge turns produce IDENTICAL
    parsed results - wiring must never change the hunter's observable behaviour."""
    baseline_actor, baseline_spec, baseline_verdict = _drive_hunter(
        False, [AUTHOR_BODY, JUDGE_BODY])
    auto_actor, auto_spec, auto_verdict = _drive_hunter(None, [AUTHOR_BODY, JUDGE_BODY])
    assert (auto_spec, auto_verdict) == (baseline_spec, baseline_verdict)
    assert (baseline_spec, baseline_verdict) == (json.loads(AUTHOR_BODY), json.loads(JUDGE_BODY))
    assert baseline_actor.compaction_manager is None
    manager = auto_actor.compaction_manager
    assert manager is not None
    assert manager.pending(auto_actor.thread_id) is None  # nothing spawned: inert


def test_hunter_summariser_failure_degrades_never_spawns(clean_llm_env, monkeypatch):
    """D9 inert default preserved: when the summariser can never produce a summary
    (a model with no structured-output surface), the middleware stays functional
    and the author/judge turns still parse - the failing pass degrades to
    last-known-good, never into the hunter."""
    import polymerhus.app.llm.providers as P

    class _BareText(BaseChatModel):
        body: str = ""

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.body))])

        @property
        def _llm_type(self) -> str:
            return "fake"

    monkeypatch.setenv("LLM_MODEL_HUNTING_HUNTER", "openai:gpt-test")

    def spy(provider, model, **kw):
        return _BareText(body="")

    monkeypatch.setattr(P, "build_chat_model", spy)

    # A tiny window so the over-budget trigger fires even without usage metadata.
    window = C.CompactionWindow(context_limit=10, threshold=0.9)
    mw = HL.build_hunter_compaction_middleware(window=window)
    assert mw.manager.summariser is not None
    actor, spec, verdict = _drive_hunter(mw, [AUTHOR_BODY, JUDGE_BODY], usage=_usage(100, output_tokens=5))
    assert spec == json.loads(AUTHOR_BODY)
    assert verdict == json.loads(JUDGE_BODY)


# --- (d) the summariser factory: a structured call under the read budget --------

def test_build_summariser_structured_call_under_budget(clean_llm_env, monkeypatch):
    """D5/#73: the shared summariser factory builds a structured-output call on the
    role's own model; driving it through `summarise` invokes it WITH the escalating
    read budget and returns a SummaryUpdate-derived RunningSummary, and a direct
    call returns a SummaryUpdate under its own budget."""
    budgets: list = []
    _patch_summary_model(monkeypatch, budgets=budgets)
    summariser = S.build_summariser("hunting_hunter")

    outcome = S.summarise(summariser, existing=None, spans=[AIMessage(content="reason-one")])
    assert outcome.status == "ok"
    assert outcome.summary.summary_text == GOOD_SUMMARY_TEXT
    assert budgets == [300.0]  # the first escalating attempt's default budget

    composed = S.build_summary_messages(None, [AIMessage(content="more")])
    direct = summariser(composed, 42.0)
    assert isinstance(direct, S.SummaryUpdate)
    assert direct.summary_text == GOOD_SUMMARY_TEXT
    assert budgets == [300.0, 42.0]


# --- (e) the profile resolution fails open --------------------------------------

def test_hunter_profile_resolution_fails_open(clean_llm_env, monkeypatch):
    """D9 fail-open: a raising capability reader degrades the hunter's compaction
    to NO reasoning surface (empty replay tail) and the DEFAULT window - the
    middleware constructs anyway and never breaks the hunter."""
    import polymerhus.app.llm.capability as cap

    monkeypatch.setenv("LLM_MODEL_HUNTING_HUNTER", "openai:gpt-test")

    def _boom(provider, model):
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(cap, "resolve_capability", _boom)
    mw = HL.build_hunter_compaction_middleware()
    assert mw.manager.profile is None  # no reasoning surface, fail-open
    assert mw.manager.window.context_limit == C.DEFAULT_CONTEXT_LIMIT
    assert mw.manager.summariser is not None  # the role's own model summariser survives
