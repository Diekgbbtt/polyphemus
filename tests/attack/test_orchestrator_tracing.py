"""Unit tier for the orchestrator gate step records (convergence migration).

Actor turns ride the session seam under the handler, so no hand-written gate
span is opened - `orchestrator_gate_span` is deleted and this module keeps
only the thin-exception `trace_gate_step` step records fed explicit run
correlation, plus the run-end flush. Fakes the `langfuse` module (lazy import)
so the contract is pinned with no live Langfuse.
"""
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock

from polymerhus.attack.hunting import orchestrator_tracing


def _fake_langfuse(calls):
    mod = types.ModuleType("langfuse")

    @contextmanager
    def propagate_attributes(**kw):
        calls.append(("propagate", kw))
        yield

    @contextmanager
    def _observation(**kw):
        calls.append(("observation", kw))
        span = MagicMock()
        span.update.side_effect = lambda **ukw: calls.append(("update", ukw))
        yield span

    client = MagicMock()
    client.start_as_current_observation.side_effect = _observation
    client.flush.side_effect = lambda: calls.append(("flush", {}))
    mod.propagate_attributes = propagate_attributes
    mod.get_client = lambda: client
    return mod


def test_orchestrator_gate_span_is_deleted():
    """The gate-span wrapper is gone - the pass trace rides the handler."""
    assert not hasattr(orchestrator_tracing, "orchestrator_gate_span")


def test_trace_gate_step_with_run_id_correlates_explicitly(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))
    orchestrator_tracing.trace_gate_step("symbolic-render", input={"pair": "p"},
                                         run_id="run1",
                                         tags=["attack", "hunting",
                                               "orchestrator-gate"])

    kinds = [c[0] for c in calls]
    assert kinds == ["propagate", "observation", "update"]
    prop = dict(calls[0][1])
    assert prop["session_id"] == "run1"
    assert prop["tags"] == ["attack", "hunting", "orchestrator-gate"]


def test_trace_gate_step_without_run_id_keeps_ambient_behaviour(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))
    orchestrator_tracing.trace_gate_step("symbolic-render", input={"pair": "p"})
    assert [c[0] for c in calls] == ["observation", "update"]


def test_flush_delegates_to_client(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))
    orchestrator_tracing.flush_orchestrator_traces()
    assert ("flush", {}) in calls


def test_helpers_fail_open_when_langfuse_raises(monkeypatch):
    broken = types.ModuleType("langfuse")

    def boom(*_a, **_k):
        raise RuntimeError("langfuse unavailable")

    broken.get_client = boom
    broken.propagate_attributes = boom
    monkeypatch.setitem(sys.modules, "langfuse", broken)
    orchestrator_tracing.trace_gate_step("symbolic-render", run_id="r")
    orchestrator_tracing.flush_orchestrator_traces()  # reaching here is the assertion
