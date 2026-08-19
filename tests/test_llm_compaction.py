"""Unit tier: the context-window compaction ledger + threshold trigger (#95 slice A).

The measurement half of the adaptive context-window manager: a per-thread usage
ledger updated from the provider's REAL per-step usage (input tokens + cache-read,
plus what migrates into the next prompt - the response output and pending tool
payloads), and the threshold trigger that flags a session as over budget
(threshold x context_limit). The ledger updates in the `after_model` middleware
hook - non-blocking, and it NEVER spawns compaction (the spawn and the barrier are
later slices). cache-read is recorded as observability, never a gate (D11 item 3).

These tests exercise the pure accounting plus the middleware hook through the real
agent loop with a FAKE tool-calling model and an in-memory checkpointer - no live
model, no live gateway, no database (CODING_STANDARD sections 6, 10). The window
resolution (capability reader) is mocked; the resolve-and-hold + fail-open contract
is the same discipline as the reasoning pipeline's.
"""
from __future__ import annotations

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
    from polymerhus.app.llm.session import run_session_turn

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
