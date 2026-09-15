"""Proposer trace correlation (convergence migration).

The supervisor proposer node opens NO hand-written SDK span - the node is
itself a fully-attributed chain span under the run-sessioned supervisor
graph, and each proposer's session turns carry the run tag for the join.
Step helpers (`trace_reasoning` / `trace_generation`) survive as thin
exceptions fed EXPLICIT run correlation from the dispatch state (never
ambient reads), so the WHY/WHAT records keep landing after the agent-span
wrappers go away.
"""
import sys
import types
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock


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
    client.update_current_span.side_effect = lambda **kw: calls.append(("update", kw))
    mod.propagate_attributes = propagate_attributes
    mod.get_client = lambda: client
    return mod


def test_proposer_node_opens_no_sdk_spans(monkeypatch):
    """The migrated node runs its body with zero hand-written observations -
    structure and join ride the handler tree plus the run tag."""
    from polymerhus.analysis.analyser_types import L1DeltaBatch
    from polymerhus.analysis.messages import AgentDispatch
    from polymerhus.analysis.supervisor import _make_proposer

    calls = []
    monkeypatch.setitem(sys.modules, "langfuse", _fake_langfuse(calls))

    def body(dispatch, state):
        return L1DeltaBatch()

    node = _make_proposer("assigner", body)
    from polymerhus.analysis.chunking import Chunk
    out = node({"dispatch": AgentDispatch(dispatch_id="d1", role="assigner",
                                          phase="A1",
                                          chunk=Chunk(chunk_id="katana:0")),
                "project_id": "p", "run_id": "stream-run1"})
    assert out["inflight"].status == "empty"
    assert calls == []


def test_assigner_body_threads_run_correlation_to_trace_generation(monkeypatch):
    """The assigner's structured-output record carries the dispatch run
    (stream- prefix stripped, matching the old wrapper) plus role tags."""
    import polymerhus.app.observability as obs
    from polymerhus.analysis.assigner import make_assigner_body
    from polymerhus.analysis.chunking import Chunk
    from polymerhus.recon.domain.types import AssetDelta

    seen = {}
    monkeypatch.setattr(obs, "trace_generation",
                        lambda *a, **k: seen.update(args=a, kwargs=k))

    chunk = Chunk(chunk_id="c",
                  assets=(AssetDelta(type="Endpoint",
                                     identity={"path": "/x",
                                               "baseurl": "https://a"}),))

    def invoke_fn(messages):
        from polymerhus.analysis.analyser_types import L1DeltaBatch
        return L1DeltaBatch()

    body = make_assigner_body(
        invoke_fn=invoke_fn,
        inventory_fn=lambda pid: {"services": ["checkout"]})
    dispatch = SimpleNamespace(dispatch_id="d1", role="assigner", phase="A1",
                               chunk=chunk, mode="create")
    body(dispatch, {"project_id": "p", "run_id": "stream-run1"})

    assert seen["kwargs"]["run_id"] == "run1"
    assert seen["kwargs"]["tags"] == ["analysis", "assigner"]
