"""Unit tier: the context-window compaction manager (#95 slices A + D + E).

Slice A is the measurement half: a per-thread usage ledger updated from the
provider's REAL per-step usage (input tokens + cache-read, plus what migrates
into the next prompt - the response output and pending tool payloads), and the
threshold trigger that flags a session as over budget (threshold x context_limit).
Slice D is the pure compact pass (tool-body offload + running summary). Slice E is
the CONCURRENCY half: the turn-end SPAWN (`after_agent`), the strict BARRIER
(`before_model`), and the synchronous BACKSTOP, staged through the graph's own
messages reducer - a call never proceeds on an over-budget window (ADR D1/D4).

These tests exercise the pure accounting, the compact pass, the manager state
machine, and the middleware hooks THROUGH THE REAL `create_agent` loop with a FAKE
tool-calling model and an in-memory checkpointer - no live model, no live gateway,
no database (CODING_STANDARD sections 6, 10). The window resolution (capability
reader) is mocked; the resolve-and-hold + fail-open contract is the same discipline
as the reasoning pipeline's.
"""
from __future__ import annotations

import threading
import time

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm import compaction as C
from polymerhus.app.llm import summary as S
from polymerhus.app.llm import tool_output as T
from polymerhus.app.llm.capability import CapabilityProfile
from polymerhus.app.llm.providers import LLMConfigError
from polymerhus.app.llm.session import (
    _attach_compaction_metadata,
    read_session_memory,
    run_session_turn,
)


def _usage(input_tokens, output_tokens=0, cache_read=0, reasoning=None):
    md = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if cache_read:
        md["input_token_details"] = {"cache_read": cache_read}
    if reasoning is not None:
        md["output_token_details"] = {"reasoning_tokens": reasoning}
    return md


# --- occupancy accounting (pure) ---------------------------------------------

def test_occupancy_sums_base_and_migrating_output():
    """One step's occupancy is the real base (input + cache-read) plus the response
    output that migrates into the next prompt. `input_tokens` alone under-counts
    once caching engages - cache-read is added, never ignored."""
    snap = C.occupancy_from_message(
        AIMessage(content="r", usage_metadata=_usage(1000, output_tokens=50, cache_read=40))
    )
    assert snap is not None
    assert snap.base_input == 1040
    assert snap.migrating_output == 50
    assert snap.occupancy == 1090
    assert snap.cache_read == 40


def test_occupancy_reasoning_is_recorded_not_double_counted():
    """Reasoning sits on the output side and is a SUBSET of output tokens: it is
    recorded for observability, never added again on top of migrating output."""
    snap = C.occupancy_from_message(
        AIMessage(content="r", usage_metadata=_usage(1000, output_tokens=50, reasoning=30))
    )
    assert snap.reasoning_tokens == 30
    assert snap.migrating_output == 50
    assert snap.occupancy == 1050


def test_occupancy_absent_usage_is_none():
    """No usage metadata (or not an assistant message) -> no real accounting; the
    ledger falls back to approximate counting instead of guessing a zero."""
    assert C.occupancy_from_message(AIMessage(content="no usage")) is None
    assert C.occupancy_from_message(HumanMessage(content="h")) is None


# --- the ledger (trigger) ----------------------------------------------------

def _window(limit=10000, threshold=0.9):
    return C.CompactionWindow(context_limit=limit, threshold=threshold)


def test_ledger_uses_last_usage_bearing_message():
    """The trail's occupancy is the LAST usage-bearing assistant step (each step's
    input already contains the whole prior trail) plus its migrating output."""
    ledger = C.UsageLedger(window=_window())
    trail = [
        HumanMessage(content="q"),
        AIMessage(content="a1", usage_metadata=_usage(100, output_tokens=10)),
        AIMessage(content="a2", usage_metadata=_usage(200, output_tokens=20)),
    ]
    entry = ledger.update("thr", trail)
    assert entry.occupancy == 220
    assert entry.approx is False


def test_ledger_counts_trailing_tool_payload():
    """Tool outputs carry no usage record but occupy the next prompt: a tool body
    that no later model step has yet consumed is approximate-counted into occupancy."""
    ledger = C.UsageLedger(window=_window())
    trail = [
        HumanMessage(content="q"),
        AIMessage(content="a", usage_metadata=_usage(100, output_tokens=10)),
        ToolMessage(content="x" * 4000, tool_call_id="t1"),
    ]
    entry = ledger.update("thr", trail)
    assert entry.occupancy > 110  # base 100 + migrating 10 + the ~1000-token tool body
    assert entry.approx is False


def test_ledger_absent_usage_falls_back_to_approx(caplog):
    """No usage metadata anywhere -> approximate counting over the whole trail,
    fail-open, logged - never the primary and never a crash."""
    ledger = C.UsageLedger(window=_window())
    entry = ledger.update("thr", [HumanMessage(content="hello world"), AIMessage(content="reply")])
    assert entry.occupancy > 0
    assert entry.approx is True
    assert "approx" in caplog.text


def test_trigger_fires_at_the_boundary():
    """The trigger is `occupancy >= threshold x context_limit`: the boundary is
    inclusive, one token below is not over budget."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    assert C.is_over_budget(900, window) is True
    assert C.is_over_budget(899, window) is False


# --- window + threshold resolution (D2) --------------------------------------

def test_window_budget_is_threshold_times_limit():
    assert C.CompactionWindow(context_limit=150_000, threshold=0.90).budget == 135_000


def test_threshold_resolution_param_then_env_then_default(monkeypatch):
    """Threshold: explicit param wins, then the env override, then the 0.90 default."""
    monkeypatch.delenv(C.COMPACTION_THRESHOLD_ENV, raising=False)
    assert C.resolve_window("role", threshold=None).threshold == 0.90
    assert C.resolve_window("role", threshold=0.50).threshold == 0.50
    monkeypatch.setenv(C.COMPACTION_THRESHOLD_ENV, "0.25")
    assert C.resolve_window("role", threshold=None).threshold == 0.25


def test_threshold_env_override_is_validated_fail_fast(monkeypatch):
    """An unusable threshold is a config lie: it fails fast (LLMConfigError), never
    silently degrades - mirroring the context-limit env override precedent."""
    for bad in ("abc", "0", "1.5", "-0.5"):
        monkeypatch.setenv(C.COMPACTION_THRESHOLD_ENV, bad)
        try:
            C.resolve_window("role", threshold=None)
        except LLMConfigError:
            continue
        raise AssertionError(f"threshold env {bad!r} did not raise LLMConfigError")


def test_window_resolves_from_capability_and_fails_open(monkeypatch, caplog):
    """The window is the capability profile's context limit (resolve-and-hold); a
    failing reader degrades to the conservative default, logged, never raised."""
    import polymerhus.app.llm.capability as cap
    import polymerhus.app.llm.providers as providers

    monkeypatch.setattr(
        cap, "resolve_capability",
        lambda p, m: CapabilityProfile(context_limit=200_000),
    )
    monkeypatch.setattr(providers, "resolve_role", lambda role: ("provider", "model"))
    assert C.resolve_window("role", threshold=None).context_limit == 200_000

    def _boom(p, m):
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(cap, "resolve_capability", _boom)
    w = C.resolve_window("role", threshold=None)
    assert w.context_limit == C.DEFAULT_CONTEXT_LIMIT
    assert "default" in caplog.text


# --- the middleware hook through the real loop -------------------------------

class _UsageFakeModel(BaseChatModel):
    """A scripted fake that returns an assistant message carrying real-looking usage
    metadata, so the `after_model` ledger update can be driven through the real
    `run_session_turn` loop."""

    usage: dict | None = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="answer", usage_metadata=self.usage))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def test_after_model_updates_ledger_through_the_real_loop():
    """The middleware's `after_model` hook updates the per-thread ledger from the
    real loop's trail (thread id resolved from the graph config) and returns None -
    it never spawns compaction in this slice."""
    window = C.CompactionWindow(context_limit=100_000, threshold=0.9)
    mw = C.create_compaction_middleware(window=window)
    thread_id = "run1:role"

    run_session_turn(
        "assigner", thread_id, [HumanMessage(content="go")],
        checkpointer=InMemorySaver(),
        middleware=[mw],
        model_factory=lambda role: _UsageFakeModel(usage=_usage(1000, output_tokens=50, cache_read=40)),
        observe=False,
    )
    entry = mw.ledger.entry(thread_id)
    assert entry is not None
    assert entry.occupancy == 1090
    assert entry.over_budget is False


def test_after_model_is_fail_open_on_garbage_state():
    """A malformed or empty state, or a hook call outside a graph context (no thread
    id), degrades to a no-op - it never raises into the turn."""
    mw = C.create_compaction_middleware(window=_window())
    assert mw.after_model({"messages": []}, None) is None
    assert mw.after_model({"messages": "not-a-list"}, None) is None
    assert mw.ledger.entry("never") is None


# --- slice D: the compact pass (pure assembly, sentinel byte-identity) --------

SENTINEL_BODY = "line-A\n" + ("middle-" * 10000) + "\nline-Z"

GOOD_SUMMARY_TEXT = (
    "The hunter enumerated three auth endpoints and patched two; the login "
    "flow still exposes the third path to close."
)


def _good_summariser():
    """A fake slice-C summariser that always passes the quality gate and records
    the composed user message - the sentinel evidence of what the pass folded."""
    seen = {}

    def fake(messages, budget):
        seen["user"] = messages[-1].content if messages else ""
        seen["calls"] = seen.get("calls", 0) + 1
        return S.SummaryUpdate(summary_text=GOOD_SUMMARY_TEXT)

    fake.seen = seen
    return fake


def _contents(messages):
    return " ".join(getattr(m, "content", "") or "" for m in messages)


def _tool_message(messages, tool_call_id):
    found = [m for m in messages
             if isinstance(m, ToolMessage) and m.tool_call_id == tool_call_id]
    assert len(found) == 1
    return found[0]


def test_profile_with_reasoning_reserves_byte_identical_tail():
    """A reasoning-capable profile reserves a byte-identical tail: the message at
    the end stays IDENTICAL (same object, same content), is NOT offloaded even
    when its body crosses the cut line (D7), and the report lists exempted versus
    summarised spans."""
    profile = CapabilityProfile(reasoning_in_response=True)
    store = T.InMemoryToolOutputStore()
    tail_tool = ToolMessage(content=SENTINEL_BODY, tool_call_id="tail-tc")
    trail = [
        HumanMessage(content="go"),
        AIMessage(content="reason-one"),
        AIMessage(content="reason-two"),
        AIMessage(content="reason-three"),
        tail_tool,
    ]
    fake = _good_summariser()
    res = C.compact_pass(
        trail, thread_id="thr", profile=profile, store=store, summariser=fake,
        replay_keep_tokens=C.approx_tokens([tail_tool]),
    )
    assert res.report.exempted_spans == 1
    assert res.report.summarised_spans == 3
    assert res.report.offloaded_bodies == 0
    assert res.report.readability == "compacted"
    assert res.report.summary_status == "ok"
    assert isinstance(res.report.new_summary, S.RunningSummary)
    assert res.messages[-1] is tail_tool
    assert res.messages[-1].content == SENTINEL_BODY
    assert store.get_body("thr", "tail-tc") is None
    assert res.messages[-2].type == "system"
    assert res.messages[-2].content.startswith("[running summary]")
    assert "reason-one" not in _contents(res.messages)
    for name in ("reason-one", "reason-two", "reason-three"):
        assert name in fake.seen["user"]


def test_no_reasoning_profile_means_empty_tail():
    """Profile None or a falsy reasoning_in_response means NO replay surface: the
    tail is empty and every reasoning-bearing AI message is summarisable (D7)."""
    trail = [AIMessage(content="one"), AIMessage(content="two"),
             AIMessage(content="three")]
    for profile in (None,
                    CapabilityProfile(reasoning_in_response=None),
                    CapabilityProfile(reasoning_in_response=False)):
        res = C.compact_pass(
            trail, thread_id="thr", profile=profile, store=T.InMemoryToolOutputStore(),
            summariser=_good_summariser())
        assert res.report.exempted_spans == 0
        assert res.report.summarised_spans == 3
        assert res.report.readability == "compacted"
        assert len(res.messages) == 1
        assert res.messages[0].type == "system"


def test_over_cut_tool_bodies_offload_and_pairing_falls_back():
    """An over-cut tool body becomes a HEADER in the staged trail and its FULL body
    lands in the store byte-identical; the tool name/args come from the preceding
    AIMessage's tool_calls (matched by tool-call id), falling back to name='tool'
    and empty args when no pairing is found."""
    store = T.InMemoryToolOutputStore()
    paired = ToolMessage(content=SENTINEL_BODY, tool_call_id="t1")
    orphan = ToolMessage(content="o" * 3200, tool_call_id="no-call")
    trail = [
        HumanMessage(content="go"),
        AIMessage(content="reason", tool_calls=[
            {"id": "t1", "name": "terminal", "args": {"command": "ls -la"}}]),
        paired,
        orphan,
    ]
    fake = _good_summariser()
    res = C.compact_pass(trail, thread_id="thr", profile=None, store=store, summariser=fake)
    assert res.report.offloaded_bodies == 2
    assert res.report.summarised_spans == 1
    t1 = _tool_message(res.messages, "t1")
    assert "terminal" in t1.content and "ls -la" in t1.content
    ref = T.header_ref_from_text(t1.content)
    assert ref is not None
    assert store.get_body("thr", ref) == SENTINEL_BODY
    orphan_staged = _tool_message(res.messages, "no-call")
    assert "tool=tool" in orphan_staged.content
    assert "command=" in orphan_staged.content


def test_prior_synthetic_summary_is_replaced_not_duplicated():
    """A prior synthetic summary message (SystemMessage starting with the running-
    summary prefix) is REMOVED and replaced: after the pass exactly ONE synthetic
    summary message remains, carrying the new text, not the old."""
    prior = SystemMessage(content="[running summary] OLD-NARRATIVE told the story so far")
    trail = [prior, HumanMessage(content="fresh question"),
             AIMessage(content="fresh reasoning")]
    fake = _good_summariser()
    res = C.compact_pass(
        trail, thread_id="thr", profile=None, store=T.InMemoryToolOutputStore(),
        summariser=fake,
        existing=S.RunningSummary(summary_text="OLD-NARRATIVE told the story so far"),
    )
    synth = [m for m in res.messages
             if isinstance(m, SystemMessage) and m.content.startswith("[running summary]")]
    assert len(synth) == 1
    assert GOOD_SUMMARY_TEXT in synth[0].content
    assert "OLD-NARRATIVE" not in synth[0].content
    assert prior not in res.messages
    assert res.report.summary_status == "ok"
    assert res.report.new_summary is not None
    assert "OLD-NARRATIVE" in fake.seen["user"]
    assert "fresh reasoning" in fake.seen["user"]


def test_reclaimed_tokens_before_minus_after_positive():
    """reclaimed_tokens is the approximate before-minus-after occupancy of the
    trail, floored at 0; a pass that removes reasoning and offloads a big body
    reclaims a positive amount."""
    store = T.InMemoryToolOutputStore()
    trail = [
        HumanMessage(content="go"),
        AIMessage(content="deep-reasoning-a"),
        AIMessage(content="deep-reasoning-b"),
        AIMessage(content="deep-reasoning-c"),
        ToolMessage(content=SENTINEL_BODY, tool_call_id="big"),
    ]
    res = C.compact_pass(trail, thread_id="thr", profile=None, store=store, summariser=_good_summariser())
    assert res.report.reclaimed_tokens == max(
        0, C.approx_tokens(trail) - C.approx_tokens(res.messages))
    assert res.report.reclaimed_tokens > 0


def test_reclaimed_tokens_are_floored_at_zero():
    """A pass with nothing to compact (no AI spans, no offload, no prior summary)
    reclaims zero tokens - the count never goes negative."""
    res = C.compact_pass(
        [HumanMessage(content="only this")], thread_id="thr", profile=None,
        store=T.InMemoryToolOutputStore(), summariser=_good_summariser())
    assert res.report.reclaimed_tokens == 0
    assert res.messages == [HumanMessage(content="only this")]


def test_no_spans_and_no_existing_skips_the_summariser():
    """No summarisable AI spans AND no existing summary means the summariser is
    never invoked (the pass may still offload over-cut tool bodies)."""
    store = T.InMemoryToolOutputStore()
    trail = [HumanMessage(content="go"),
             ToolMessage(content=SENTINEL_BODY, tool_call_id="t1")]

    def fail(messages, budget):
        raise AssertionError("summarise must not be called with nothing to summarise")

    res = C.compact_pass(trail, thread_id="thr", profile=None, store=store, summariser=fail)
    assert res.report.summary_status == "ok"
    assert res.report.readability == "unchanged"
    assert res.report.offloaded_bodies == 1
    assert res.report.summarised_spans == 0
    assert _tool_message(res.messages, "t1") is res.messages[-1]


def test_failed_summarise_leaves_original_unchanged(monkeypatch):
    """A failed summariser (retry exhaustion -> the fail-closed signal) leaves the
    ORIGINAL trail unchanged - nothing staged - and reports the status with zero
    reclaimed tokens (D1/D6 fail-safe)."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "0.05,0.05,0.05")
    store = T.InMemoryToolOutputStore()
    trail = [HumanMessage(content="go"), AIMessage(content="r1"),
             AIMessage(content="r2")]
    res = C.compact_pass(trail, thread_id="thr", profile=None, store=store, summariser=lambda m, b: None)
    assert [m.content for m in res.messages] == [m.content for m in trail]
    assert res.messages is not trail
    assert res.report.summary_status == "failed"
    assert res.report.readability == "unchanged"
    assert res.report.reclaimed_tokens == 0
    assert res.report.new_summary is None


def test_terminal_summarise_leaves_original_unchanged():
    """A window-cap (terminal) summariser is never retried (D6) and leaves the
    ORIGINAL trail unchanged with the terminal status reported."""
    store = T.InMemoryToolOutputStore()
    trail = [HumanMessage(content="go"), AIMessage(content="r1"),
             AIMessage(content="r2")]

    def terminal(messages, budget):
        raise Exception("maximum context length exceeded")

    res = C.compact_pass(trail, thread_id="thr", profile=None, store=store, summariser=terminal)
    assert [m.content for m in res.messages] == [m.content for m in trail]
    assert res.report.summary_status == "terminal"
    assert res.report.readability == "unchanged"
    assert res.report.reclaimed_tokens == 0
    assert res.report.new_summary is None


def test_tail_messages_stay_byte_identical_when_compaction_fires():
    """Even when the pass compacts (spans summarised, readability compacted), every
    message in the reserved tail is byte-identical to its input - the D7 unit
    contract."""
    profile = CapabilityProfile(reasoning_in_response=True)
    store = T.InMemoryToolOutputStore()
    tail_human = HumanMessage(content="FINAL-QUESTION-MARKER")
    trail = [AIMessage(content="summarise-me"), AIMessage(content="also-me"),
             tail_human]
    res = C.compact_pass(
        trail, thread_id="thr", profile=profile, store=store, summariser=_good_summariser(),
        replay_keep_tokens=C.approx_tokens([tail_human]),
    )
    assert res.report.summarised_spans == 2
    assert res.report.exempted_spans == 1
    assert res.report.readability == "compacted"
    assert res.messages[-1] is tail_human
    assert res.messages[-1].content == tail_human.content


def test_region_human_inputs_fold_into_the_summary_when_one_is_produced():
    """D1: when a summary is produced, older turn INPUTS in the region BEFORE the
    tail fold into it too (the summary now carries the user's directives) - the
    window actually shrinks. When no summary fires (nothing to fold), every message
    stays verbatim - a lone unmatched question is never dropped."""
    store = T.InMemoryToolOutputStore()
    profile = CapabilityProfile(reasoning_in_response=True)
    oldest_q = HumanMessage(content="OLDEST-QUESTION")
    mid_q = HumanMessage(content="MID-QUESTION")
    tail_q = HumanMessage(content="CURRENT-QUESTION")
    trail = [oldest_q, AIMessage(content="r1"), mid_q, AIMessage(content="r2"), tail_q]
    res = C.compact_pass(
        trail, thread_id="thr", profile=profile, store=store, summariser=_good_summariser(),
        replay_keep_tokens=C.approx_tokens([tail_q]),
    )
    assert res.report.readability == "compacted"
    assert res.report.summarised_spans == 2
    assert [m.content for m in res.messages] == [
        "[running summary]\n" + GOOD_SUMMARY_TEXT, tail_q.content]

    bare = C.compact_pass(
        [HumanMessage(content="only this question")], thread_id="thr",
        profile=None, store=store, summariser=_good_summariser())
    assert [m.content for m in bare.messages] == ["only this question"]


# --- slice E: the spawn / barrier / backstop through the real loop -------------

class _RecordingUsageModel(BaseChatModel):
    """A scripted fake that returns an assistant message carrying real-looking usage
    metadata AND records every messages list it was handed - so a test can assert
    exactly what trail the next turn's model call saw after the compaction barrier."""

    usage: dict | None = None
    content: str = "answer"
    seen: list | None = None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.seen is not None:
            self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=self.content, usage_metadata=self.usage))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _recording_factory(usage, seen, content="answer"):
    """A `model_factory` yielding a fresh `_RecordingUsageModel` per turn whose
    `seen` recorder is the SHARED list (assigned after construction - pydantic would
    otherwise deep-copy the list passed to the field)."""

    def make(role):
        model = _RecordingUsageModel(usage=usage, content=content)
        model.seen = seen
        return model

    return make


def test_after_agent_spawns_and_next_before_model_applies_staged_trail():
    """D1/D4 spawn + barrier through the real loop: turn 1 crosses the budget, turn 1's
    after_agent spawns the out-of-band pass, and turn 2's before_model AWAITS it and
    returns a state update the messages reducer applies - the next model call carries
    the compacted trail (synthetic summary present, summarised spans absent)."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    seen: list = []
    mw = C.create_compaction_middleware(
        window=window,
        store=T.InMemoryToolOutputStore(),
        summariser=_good_summariser(),
        profile=None,
    )
    thread_id = "runA:role"
    saver = InMemorySaver()
    factory = _recording_factory(_usage(1000, output_tokens=10), seen, content="answer")

    run_session_turn("assigner", thread_id, [HumanMessage(content="go")],
                     checkpointer=saver, middleware=[mw], model_factory=factory, observe=False)
    run_session_turn("assigner", thread_id, [HumanMessage(content="continue")],
                     checkpointer=saver, middleware=[mw], model_factory=factory, observe=False)

    assert mw.ledger.entry(thread_id).over_budget is True
    assert mw.manager.streak(thread_id) == 0
    turn2_input = seen[-1]
    assert isinstance(turn2_input[0], SystemMessage)
    assert turn2_input[0].content.startswith("[running summary]")
    assert GOOD_SUMMARY_TEXT in turn2_input[0].content
    assert turn2_input[-1].content == "continue"
    assert len(turn2_input) == 2
    assert all("go" not in str(m.content) and "answer" not in str(m.content) for m in turn2_input)


def test_backstop_compacts_synchronously_when_no_task_is_pending():
    """D4 BACKSTOP through the real loop: an over-budget ledger with NO pending task
    (a lost or restarted pass) runs compact_pass SYNCHRONOUSLY inside before_model -
    the model call still receives the compacted trail, never the over-budget window."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    ledger = C.UsageLedger(window)
    seen: list = []
    mw = C.create_compaction_middleware(
        window=window, ledger=ledger,
        store=T.InMemoryToolOutputStore(),
        summariser=_good_summariser(),
        profile=None,
    )
    thread_id = "runB:role"
    saver = InMemorySaver()
    run_session_turn("assigner", thread_id, [HumanMessage(content="seed")],
                     checkpointer=saver,
                     model_factory=_recording_factory(
                         _usage(1000, output_tokens=10), seen, content="reasoning-seed"),
                     observe=False)
    # The ledger's boundary is the CHANNEL trail (ids assigned by the graph's own
    # reducer) - the same trail `after_model` would have fed the ledger in the
    # production path. The backstop then compacts exactly the measured trail and
    # preserves the fresh "proceed" input on top.
    seed = read_session_memory(saver, thread_id)
    assert seed is not None
    seed_trail = seed.messages
    ledger.update(thread_id, seed_trail)
    assert ledger.entry(thread_id).over_budget is True
    assert mw.manager.pending(thread_id) is None

    run_session_turn("assigner", thread_id, [HumanMessage(content="proceed")],
                     checkpointer=saver, middleware=[mw],
                     model_factory=_recording_factory(
                         _usage(1000, output_tokens=10), seen, content="answer-big"),
                     observe=False)

    turn1_input = seen[-1]
    assert isinstance(turn1_input[0], SystemMessage)
    assert GOOD_SUMMARY_TEXT in turn1_input[0].content
    assert turn1_input[-1].content == "proceed"
    assert not any("reasoning-seed" in str(m.content) for m in turn1_input)


def test_three_consecutive_failures_release_on_last_known_good_and_stop_auto_spawn(caplog):
    """D6 fail-safe through the real loop: 3 consecutive failed/terminal passes hit the
    LOCAL cap - auto-spawn stops, the escalation is loud (log + ledger flag), and every
    turn's model call proceeds on last-known-good with the over-budget flag retained."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)

    def terminal(messages, budget):
        raise Exception("maximum context length exceeded")

    seen: list = []
    mw = C.create_compaction_middleware(
        window=window, store=T.InMemoryToolOutputStore(), summariser=terminal, profile=None)
    thread_id = "runC:role"
    saver = InMemorySaver()
    factory = _recording_factory(_usage(1000, output_tokens=10), seen, content="answer")

    for msg in ("one", "two", "three", "four", "five"):
        run_session_turn("assigner", thread_id, [HumanMessage(content=msg)],
                         checkpointer=saver, middleware=[mw], model_factory=factory, observe=False)

    assert mw.manager.streak(thread_id) == 3
    assert mw.manager.is_escalated(thread_id) is True
    assert mw.ledger.entry(thread_id).over_budget is True
    assert mw.ledger.entry(thread_id).escalated is True
    assert mw.manager.pending(thread_id) is None
    assert len(seen) == 5
    assert "cap" in caplog.text


def test_call_does_not_proceed_while_a_pass_is_pending():
    """D1 strict barrier through the real loop: while a spawned pass is in flight, the
    next turn's before_model BLOCKS on the pending Future - the model is NOT called
    until the pass completes, and then receives the compacted trail."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    entered = threading.Event()
    release = threading.Event()

    def slow_summariser(messages, budget):
        entered.set()
        release.wait(timeout=20)
        return S.SummaryUpdate(summary_text=GOOD_SUMMARY_TEXT)

    seen: list = []
    mw = C.create_compaction_middleware(
        window=window, store=T.InMemoryToolOutputStore(), summariser=slow_summariser,
        profile=None)
    thread_id = "runD:role"
    saver = InMemorySaver()
    factory = _recording_factory(_usage(1000, output_tokens=10), seen, content="answer")

    run_session_turn("assigner", thread_id, [HumanMessage(content="go")],
                     checkpointer=saver, middleware=[mw], model_factory=factory, observe=False)
    assert entered.wait(timeout=10) is True
    assert mw.manager.pending(thread_id) is not None

    results: dict = {}

    def run_turn_two():
        results["turn"] = run_session_turn(
            "assigner", thread_id, [HumanMessage(content="continue")],
            checkpointer=saver, middleware=[mw], model_factory=factory, observe=False)

    t = threading.Thread(target=run_turn_two)
    t.start()
    time.sleep(0.2)
    assert mw.manager.pending(thread_id) is None  # the barrier popped it and is awaiting
    assert len(seen) == 1  # the next model call has NOT proceeded while the pass is pending
    release.set()
    t.join(timeout=20)
    assert not t.is_alive()
    assert len(seen) == 2
    turn2_input = seen[-1]
    assert isinstance(turn2_input[0], SystemMessage)
    assert GOOD_SUMMARY_TEXT in turn2_input[0].content
    assert turn2_input[-1].content == "continue"


# --- slice E: the manager state machine (no live model) -----------------------

def test_manager_spawns_pending_awaits_and_applies():
    """The manager state machine: a spawn over-budget creates a pending Future; the
    barrier awaits it and returns the REMOVE_ALL + staged reducer update, clearing the
    pending slot and keeping the streak at 0."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    ledger = C.UsageLedger(window)
    trail = [HumanMessage(content="q"), AIMessage(content="r1", usage_metadata=_usage(1000))]
    ledger.update("thr", trail)
    mgr = C.CompactionManager(
        window, ledger, store=T.InMemoryToolOutputStore(),
        summariser=_good_summariser(), profile=None)
    fut = mgr.spawn("thr", trail)
    assert fut is not None
    assert mgr.pending("thr") is fut
    update = mgr.ensure_under_budget("thr", trail)
    assert update is not None
    assert update["messages"][0].type == "remove"
    assert update["messages"][0].id == "__remove_all__"
    assert any(m.content.startswith("[running summary]") for m in update["messages"])
    assert mgr.pending("thr") is None
    assert mgr.streak("thr") == 0
    assert mgr.is_escalated("thr") is False


def test_fresh_delta_survives_the_barrier_and_the_backstop():
    """D1 boundary splice: a message added AFTER the ledger measured the trail (the
    current turn's own input) is preserved verbatim on top of the staged trail in
    BOTH the barrier (pending pass) and the backstop (no pending pass) paths - the
    remove_all replacement must never eat input the pass never saw."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    measured = [HumanMessage(content="q", id="q1"),
                AIMessage(content="r1", id="a1", usage_metadata=_usage(1000))]
    fresh = HumanMessage(content="fresh turn input", id="f1")
    current = measured + [fresh]

    ledger = C.UsageLedger(window)
    ledger.update("thr", measured)
    mgr = C.CompactionManager(
        window, ledger, store=T.InMemoryToolOutputStore(),
        summariser=_good_summariser(), profile=None)
    assert mgr.spawn("thr", measured) is not None
    update = mgr.ensure_under_budget("thr", current)
    assert update is not None
    assert update["messages"][0].type == "remove"
    contents = [getattr(m, "content", None) for m in update["messages"]]
    assert any(c and str(c).startswith("[running summary]") for c in contents)
    assert contents[-1] == "fresh turn input"
    assert "q" not in contents and "r1" not in contents

    ledger2 = C.UsageLedger(window)
    ledger2.update("thr", measured)
    mgr2 = C.CompactionManager(
        window, ledger2, store=T.InMemoryToolOutputStore(),
        summariser=_good_summariser(), profile=None)
    update2 = mgr2.ensure_under_budget("thr", current)  # nothing pending -> backstop
    assert update2 is not None
    assert update2["messages"][0].type == "remove"
    contents2 = [getattr(m, "content", None) for m in update2["messages"]]
    assert any(c and str(c).startswith("[running summary]") for c in contents2)
    assert contents2[-1] == "fresh turn input"
    assert "q" not in contents2 and "r1" not in contents2


def test_manager_cap_stops_auto_spawn_and_a_later_trigger_resets():
    """D6: consecutive failed passes count LOCALLY; at the cap (3) auto-spawn stops and
    the manager escalates loudly; a later TRIGGER (the thread recovering to under
    budget) resets the streak, so a new over-budget episode re-arms the mechanism."""
    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    ledger = C.UsageLedger(window)
    trail = [HumanMessage(content="q"), AIMessage(content="r1", usage_metadata=_usage(1000))]
    ledger.update("thr", trail)

    def terminal(messages, budget):
        raise Exception("maximum context length exceeded")

    mgr = C.CompactionManager(
        window, ledger, store=T.InMemoryToolOutputStore(),
        summariser=terminal, profile=None)
    for _ in range(3):
        assert mgr.spawn("thr", trail) is not None
        assert mgr.ensure_under_budget("thr", trail) is None  # released on last-known-good
    assert mgr.streak("thr") == 3
    assert mgr.is_escalated("thr") is True
    assert mgr.spawn("thr", trail) is None  # at the cap: auto-spawn STOPS

    ledger.update("thr", [HumanMessage(content="small")])  # the thread recovers
    assert mgr.spawn("thr", [HumanMessage(content="q")]) is None  # under budget now
    assert mgr.streak("thr") == 0
    assert mgr.is_escalated("thr") is False

    mgr.summariser = _good_summariser()
    new_trail = [HumanMessage(content="q"), AIMessage(content="r2", usage_metadata=_usage(1000))]
    ledger.update("thr", new_trail)  # a NEW over-budget episode
    assert mgr.spawn("thr", new_trail) is not None  # re-armed
    assert mgr.ensure_under_budget("thr", new_trail) is not None  # the new pass applies
    assert mgr.streak("thr") == 0


def test_staged_trail_reducer_handles_id_none_defensively():
    """The staged update uses RemoveMessage(REMOVE_ALL) + the staged trail - never
    per-message ids - so messages whose id is None (a freshly built trail) are removed
    and re-added safely through the add_messages reducer, never a crash and never a
    leftover collision."""
    from langgraph.graph.message import add_messages

    window = C.CompactionWindow(context_limit=1000, threshold=0.9)
    ledger = C.UsageLedger(window)
    mgr = C.CompactionManager(
        window, ledger, store=T.InMemoryToolOutputStore(),
        summariser=_good_summariser(), profile=None)
    no_id_human = HumanMessage(content="keep-me")
    assert no_id_human.id is None
    summary = SystemMessage(content="[running summary] NEW-NARRATIVE")
    result = C.CompactResult(
        messages=[summary, no_id_human],
        report=C.CompactReport(
            exempted_spans=0, summarised_spans=1, offloaded_bodies=0, reclaimed_tokens=10,
            readability=C.READABILITY_COMPACTED, summary_status="ok",
            new_summary=S.RunningSummary(summary_text="NEW-NARRATIVE"),
        ),
    )
    current = [HumanMessage(content="keep-me"), AIMessage(content="old-reasoning")]
    update = mgr.apply_staged("thr", result)
    merged = add_messages(current, update["messages"])
    assert [m.content for m in merged] == ["[running summary] NEW-NARRATIVE", "keep-me"]
    assert len(merged) == 2


def test_attach_compaction_metadata_surfaces_the_last_pass():
    """D11: the session seam surfaces the last settled pass on the same trace - the
    `compaction_*` fields ride the config metadata (replayed, like readability), and
    an absent middleware/report simply omits them (fail-open)."""
    class _Manager:
        def __init__(self):
            self.reports = {}

        def last_report(self, thread_id):
            return self.reports.get(thread_id)

    class _Middleware:
        def __init__(self, manager):
            self.manager = manager

    report = C.CompactReport(
        exempted_spans=1, summarised_spans=2, offloaded_bodies=0, reclaimed_tokens=123,
        readability=C.READABILITY_COMPACTED, summary_status="ok",
        new_summary=S.RunningSummary(summary_text="NEW-NARRATIVE"))

    manager = _Manager()
    manager.reports["t1"] = report
    config = {"metadata": {"langfuse_session_id": "t1"}}
    _attach_compaction_metadata(config, [_Middleware(manager)], "t1")
    assert config["metadata"]["compaction_readability"] == "compacted"
    assert config["metadata"]["compaction_reclaimed_tokens"] == 123
    assert config["metadata"]["compaction_summary_status"] == "ok"

    # No settled pass -> fields omitted, never a raise (fail-open).
    config2 = {"metadata": {"langfuse_session_id": "t2"}}
    _attach_compaction_metadata(config2, [_Middleware(manager)], "t2")
    assert "compaction_readability" not in config2["metadata"]
    # No compaction middleware -> omitted.
    config3 = {"metadata": {}}
    _attach_compaction_metadata(config3, [], "t1")
    assert "compaction_readability" not in config3["metadata"]
