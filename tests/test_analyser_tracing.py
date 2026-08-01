"""Unit tier for the reusable analyser Langfuse span (#18/#9).

Closes the observability hole where the A.1 proposers (Assigner / mechanism-typist /
DataPlane data-modeller) produced no named, session-correlated agent span and never
captured their reasoning - unlike the Bootstrapper. Fakes the `langfuse` module (the
helper imports it lazily) so both the happy path and the fail-open contract are pinned
without a live Langfuse.
"""
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock

from polymerhus.app.observability import analyser_tracing


def _fake_langfuse(calls):
    mod = types.ModuleType("langfuse")

    @contextmanager
    def propagate_attributes(**kw):
        calls.append(("propagate", kw))
        yield

    @contextmanager
    def _observation(**kw):
        calls.append(("observation", kw))
        yield MagicMock()

    client = MagicMock()
    client.start_as_current_observation.side_effect = _observation
    client.update_current_span.side_effect = lambda **kw: calls.append(("update", kw))
    client.flush.side_effect = lambda: calls.append(("flush", {}))

    mod.propagate_attributes = propagate_attributes
    mod.get_client = lambda: client
    return mod


def test_analyser_span_opens_session_correlated_agent_span(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))

    with analyser_tracing.analyser_span("mechanism_typist", project_id="p",
                                        run_id="run1", phase="A1", dispatch_id="d1"):
        analyser_tracing.trace_reasoning("I hypothesise a WebPresentation", call="typist-reflection")

    kinds = [c[0] for c in calls]
    assert kinds == ["propagate", "observation", "update"]      # span opened, then reasoning attached
    prop = dict(calls[0][1])
    assert prop["session_id"] == "run1"                          # correlated to the run (the #18 gap)
    assert prop["trace_name"] == "analyser-mechanism_typist"     # per-agent name
    assert "mechanism_typist" in prop["tags"] and "analysis" in prop["tags"]
    assert dict(calls[2][1])["output"] == "I hypothesise a WebPresentation"


def test_trace_generation_records_structured_output_as_nested_observation(monkeypatch):
    """The observability fix (moodique cc29fd4a): a proposer's structured output - e.g. the
    Assigner's aggregates with confidences - must reach Langfuse as its OWN generation
    observation, not clobber the agent span's prose I/O."""
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))

    analyser_tracing.trace_generation(
        "assigner-aggregates", input={"chunk": "c0", "bar": 0.75},
        output={"proposed": [{"service_slug": "catalogue", "confidence": 0.6}], "stats": {"withheld": 1}})

    obs = [c for c in calls if c[0] == "observation"]
    assert len(obs) == 1                                        # a dedicated nested observation
    kw = dict(obs[0][1])
    assert kw["as_type"] == "generation" and kw["name"] == "assigner-aggregates"
    assert kw["input"]["bar"] == 0.75                           # input slice captured
    # the confidence that explains a withhold is now inspectable in the trace
    assert calls[0][1]["input"]["chunk"] == "c0"


def test_trace_reasoning_skips_empty_prose(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))
    analyser_tracing.trace_reasoning("")
    assert calls == []                                           # nothing to attach


def test_flush_delegates_to_client(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))
    analyser_tracing.flush_analyser_traces()
    assert ("flush", {}) in calls


def test_all_helpers_fail_open_when_langfuse_raises(monkeypatch):
    """Tracing is best-effort: a broken/misconfigured Langfuse must never raise out of a
    proposer. The span degrades to a usable (nullcontext) with-block."""
    broken = types.ModuleType("langfuse")

    def boom(*_a, **_k):
        raise RuntimeError("langfuse unavailable")

    broken.get_client = boom
    broken.propagate_attributes = boom
    monkeypatch.setitem(sys.modules, "langfuse", broken)

    with analyser_tracing.analyser_span("assigner", project_id="p", run_id="r"):
        analyser_tracing.trace_reasoning("x")
    analyser_tracing.flush_analyser_traces()  # reaching here without raising is the assertion
