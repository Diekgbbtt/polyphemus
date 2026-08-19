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
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm import compaction as C
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
