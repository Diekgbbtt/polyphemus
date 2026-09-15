"""E2E walkthrough (#206 E1): the recovery capability end-to-end through the real
seam, in the two blackloop shapes the diagnosis established.

- **Shape A (streamed cut)**: a reasoning-only stream is CUT mid-flight (T1) and
  `stateful_turn` composes the recovery generation on the same thread (T2) - the
  caller sees recovered content instead of None, and the failed reasoning survives
  in the thread as a foldable span.
- **Shape B (silent-empty, phantom usage)**: a persisted failed message carrying a
  giant phantom usage pins occupancy; the native turn-end compaction bounds it (T4)
  and the thread CONVERGES under budget.

Why a scripted streaming model rather than a live provider call: the runtime
condition the recovery reads is the streamed reasoning/content split, and the
condition compaction reads is per-step occupancy - both reproduced exactly by a
scripted fake, while a live provider call adds only latency, never a different
code path (the #95/#210 walkthrough discipline). Everything else is the real
deployed wiring: `stateful_turn`, `run_session_turn`, the compaction middleware,
and the `create_agent` loop.

Runs host-side with fakes + `InMemorySaver` (docker down); the in-network run is
the sanctioned e2e runner.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm import compaction as C
from polymerhus.app.llm.session import read_session_memory, run_session_turn, stateful_turn

GOOD_SUMMARY = ("The blacklooped reasoning was cut and folded into a chainable "
                "conclusion; the workflow continues from there.")


def _usage(input_tokens, output_tokens=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


class _BlackloopThenAnswer(BaseChatModel):
    """A scripted streaming model: on its FIRST turn it burns reasoning chunks with
    no content (the blackloop - the cut fires); on later turns it streams a short
    answer carrying realistic per-step usage. `_generate` serves the compaction
    summariser's structured call."""

    reasoning_piece: str = "Need maybe mention the admin routes."
    answered: bool = False
    body: str = "the workflow step's conclusion"
    usage: dict | None = None

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.answered:
            for _ in range(4000):
                yield ChatGenerationChunk(message=AIMessageChunk(
                    content="", additional_kwargs={"reasoning_content": self.reasoning_piece}))
            return
        for piece in ("conclusion", " reached"):
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        if self.usage is not None:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="", usage_metadata=self.usage))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        humans = [str(m.content or "") for m in messages if isinstance(m, HumanMessage)]
        if any(h.startswith("Prior running summary:") for h in humans):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{"name": "SummaryUpdate", "args": {
                    "objective": GOOD_SUMMARY, "resume_point": "continue from the folded conclusion"},
                    "id": "sum", "type": "tool_call"}]))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=self.body, usage_metadata=self.usage))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _recovery_factory():
    """A `model_factory` handing out a fresh scripted model per call: the first turn
    blackloops, the recovery (and every later) turn answers."""
    state = {"i": 0}

    def make(role_id):
        i = state["i"]
        state["i"] = i + 1
        blackloop = i == 0
        return _BlackloopThenAnswer(
            answered=not blackloop,
            body=f"step-{i} conclusion",
            usage=_usage(900 + i * 100, output_tokens=60) if not blackloop else None,
        )

    return make


def _summariser_spy(provider, model, **kw):
    """The compaction summariser's model (resolved via `build_chat_model`): answers
    the structured `SummaryUpdate` call the pass composes."""
    return _BlackloopThenAnswer(answered=True)


# --- Shape A: the streamed cut + recovery, through the real seam ---------------

def test_blackloop_cut_recovery_e2e(monkeypatch):
    """Shape A end-to-end: a reasoning-only stream is CUT and `stateful_turn`
    composes the recovery generation - the caller sees recovered content (not None),
    and the failed reasoning survives in the thread as a foldable span the native
    compaction can fold."""
    import polymerhus.app.llm.providers as P
    import polymerhus.app.llm.roles as R

    monkeypatch.setenv("LLM_MODEL_ANALYSER", "opencode:gpt-test")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("LLM_COMPACTION_THRESHOLD", "0.5")
    monkeypatch.setattr(P, "build_chat_model", _summariser_spy)
    monkeypatch.setattr(R, "build_chat_model", _summariser_spy)

    window = C.CompactionWindow(context_limit=2000, threshold=0.5)  # budget 1000
    mw = C.build_role_compaction_middleware("assigner", window=window)
    saver = InMemorySaver()
    thread_id = "run-e2e-blackloop:assigner"
    factory = _recovery_factory()

    recovered = stateful_turn(
        "assigner", thread_id, [HumanMessage(content="the job")],
        checkpointer=saver, model_factory=factory, middleware=[mw],
        observe=False, reasoning_budget_chars=200,
    )
    assert recovered is not None
    assert "conclusion" in str(recovered)

    mem = read_session_memory(saver, thread_id)
    assert mem is not None
    joined = " ".join(str(m.content or "") for m in mem.messages)
    assert "Need maybe mention the admin routes" in joined, \
        "the failed reasoning must survive in the thread as a foldable span"
    assert "conclusion" in joined

    # The chain continues: more turns accumulate and the native turn-end compaction
    # settles with a chainable summary - the recovery's reasoning folded, not dropped.
    for k in range(3):
        stateful_turn(
            "assigner", thread_id, [HumanMessage(content=f"continue {k}")],
            checkpointer=saver, model_factory=factory, middleware=[mw],
            observe=False, reasoning_budget_chars=200,
        )
    report = mw.manager.last_report(thread_id)
    assert report is not None, "the native compaction must settle"
    assert report.summary_status == "ok"
    assert report.new_summary is not None


# --- Shape B: a persisted phantom-usage failed message converges (T4) ----------

class _PhantomUsageModel(BaseChatModel):
    """A model whose FIRST turn returns a failed reasoning message (empty content,
    a giant reasoning payload, a giant phantom usage - shape B) and whose later turns
    answer normally. The summariser call answers with a SummaryUpdate."""

    huge: bool = True
    usage: dict = _usage(22688, output_tokens=131072)  # the 214688-total phantom

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        humans = [str(m.content or "") for m in messages if isinstance(m, HumanMessage)]
        if any(h.startswith("Prior running summary:") for h in humans):
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{"name": "SummaryUpdate", "args": {
                    "objective": GOOD_SUMMARY, "resume_point": "resume from the folded conclusion"},
                    "id": "sum", "type": "tool_call"}]))])
        if self.huge:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "Need maybe mention the admin routes. " * 4000},
                usage_metadata=self.usage))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="a normal follow-up", usage_metadata=_usage(120, output_tokens=20)))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def test_phantom_usage_thread_converges_under_budget_e2e(monkeypatch):
    """Shape B end-to-end: a persisted failed message with a giant phantom usage
    pins occupancy; the native compaction bounds it (T4 - usage stripped, reasoning
    excerpted) and the thread CONVERGES under budget - the compaction-loop is
    eliminated through the real seam."""
    import polymerhus.app.llm.providers as P
    import polymerhus.app.llm.roles as R

    monkeypatch.setenv("LLM_MODEL_ANALYSER", "opencode:gpt-test")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("LLM_COMPACTION_THRESHOLD", "0.5")
    monkeypatch.setattr(P, "build_chat_model", _summariser_spy)
    monkeypatch.setattr(R, "build_chat_model", _summariser_spy)

    window = C.CompactionWindow(context_limit=2000, threshold=0.5)  # budget 1000
    mw = C.build_role_compaction_middleware("assigner", window=window)
    saver = InMemorySaver()
    thread_id = "run-e2e-phantom:assigner"

    model = _PhantomUsageModel(huge=True)
    run_session_turn("assigner", thread_id, [HumanMessage(content="the job")],
                     checkpointer=saver, middleware=[mw],
                     model_factory=lambda role: model, observe=False,
                     reasoning_budget_chars=500_000)
    # The next turn's barrier awaits + settles the pass that bounds the phantom.
    run_session_turn("assigner", thread_id, [HumanMessage(content="continue")],
                     checkpointer=saver, middleware=[mw],
                     model_factory=lambda role: _PhantomUsageModel(huge=False), observe=False)

    report = mw.manager.last_report(thread_id)
    assert report is not None, "the phantom-usage pass must settle"
    assert report.summary_status == "ok"

    mem = read_session_memory(saver, thread_id)
    assert mem is not None
    occupancy, _approx = C.compute_occupancy(mem.messages)
    assert occupancy < window.budget, (
        f"thread must converge under budget: occupancy={occupancy} budget={window.budget}")
    # The failed reasoning was FOLDED by the native compaction - its core survives
    # in the chainable running summary (seam S4), never dropped.
    joined = " ".join(str(m.content or "") for m in mem.messages)
    assert "blacklooped reasoning" in joined