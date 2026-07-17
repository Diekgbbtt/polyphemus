"""FR-PODSTREAM unit tier — the batch-mode delivery/completeness guarantee for the
analyser (exactly-once delivery of every AssetDelta via the slice + every
Observation via the dedicated channel), with injected fakes (no live DB/LLM).
Store-level idempotency is the integration tier (tests/integration/test_delivery_merge.py).

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md FR-PODSTREAM ledger).
"""
from agent.recon.analysis import delivery
from agent.recon.analysis import pod as analyser_pod
from agent.recon.analysis.analyser_types import L1DeltaBatch, ServiceProposal
from agent.recon.analysis.pod import AnalyserExport, build_analyser_graph, run_analyser


# --- AST-PODSTREAM-01: collect_observations returns each Observation once, id-deduped ---

def test_collect_observations_dedups_by_id():
    captured = {}

    def fake_read(cy, params):
        captured["cy"] = cy
        captured["params"] = params
        # two physical rows share one id (defensive dedup); a third is distinct
        return [
            {"o": {"id": "obs1", "macro_kind": "reflected_input", "severity": "medium",
                   "evidence": "x=<script>", "rationale": "reflects", "source_job": "arjun", "source_tool": "arjun"}},
            {"o": {"id": "obs1", "macro_kind": "reflected_input", "severity": "medium",
                   "evidence": "x=<script>", "rationale": "reflects", "source_job": "arjun", "source_tool": "arjun"}},
            {"o": {"id": "obs2", "macro_kind": "verbose_error", "severity": "low",
                   "evidence": "stacktrace", "rationale": "leaks", "source_job": "httpx", "source_tool": "httpx"}},
        ]

    out = delivery.collect_observations("proj-1", read_fn=fake_read)
    assert "MATCH (o:Observation)" in captured["cy"]
    assert captured["params"] == {"project_id": "proj-1"}
    assert [o["id"] for o in out] == ["obs1", "obs2"]  # deduped by id, one each
    assert out[0]["macro_kind"] == "reflected_input" and out[0]["evidence"] == "x=<script>"


def test_collect_observations_skips_rows_without_id():
    def fake_read(cy, params):
        return [{"o": {"id": None, "macro_kind": "x"}}, {"o": {"id": "ok", "macro_kind": "y"}}]

    out = delivery.collect_observations("p", read_fn=fake_read)
    assert [o["id"] for o in out] == ["ok"]  # a row with no id cannot be delivered/deduped


# --- AST-PODSTREAM-02: the analyser asset slice excludes Observation nodes ---

def test_analyser_slice_excludes_observation_nodes(monkeypatch):
    canned = {
        "nodes": [
            {"id": "e1", "type": "Endpoint", "name": "/a"},
            {"id": "p1", "type": "Parameter", "name": "q"},
            {"id": "o1", "type": "Observation", "name": "reflected_input"},
        ],
        "links": [
            {"source": "o1", "target": "e1", "type": "OBSERVED_ON"},  # anchor edge - must drop with o1
            {"source": "p1", "target": "e1", "type": "PARAM_OF"},
        ],
    }
    import agent.recon.graph_read as graph_read
    monkeypatch.setattr(graph_read, "fetch_project_graph", lambda pid: canned)

    slice_ = analyser_pod.default_read_fn("proj-1")
    types = {n["type"] for n in slice_["nodes"]}
    assert "Observation" not in types  # observations are NOT double-delivered in the slice
    assert types == {"Endpoint", "Parameter"}
    # the dropped observation's anchor edge is gone; the asset-asset edge survives
    assert slice_["links"] == [{"source": "p1", "target": "e1", "type": "PARAM_OF"}]


# --- AST-PODSTREAM-03: run_analyser auto-delivers observations when caller passes none ---

def _capturing_graph(sink: dict):
    def fake_read(pid):
        return {"nodes": [{"type": "Endpoint", "path": "/x"}], "links": []}

    def fake_analyse(l0_slice, observations):
        sink["observations"] = observations  # what actually reached the analyse step
        return L1DeltaBatch(services=[ServiceProposal(business_function_slug="s")])

    def fake_curate(batch, project_id, provenance):
        return AnalyserExport(services_written=1)

    return build_analyser_graph(read_fn=fake_read, analyse_fn=fake_analyse, curate_fn=fake_curate)


def test_run_analyser_auto_delivers_observations():
    sink = {}
    delivered = [{"id": "obs1", "macro_kind": "reflected_input"}]
    graph = _capturing_graph(sink)

    # observations=None (default) -> auto-delivered from the injected deliver_fn
    run_analyser("proj-1", "run-1", graph=graph, deliver_fn=lambda pid: delivered)
    assert sink["observations"] == delivered  # the run's observations reached the analyser


def test_run_analyser_honours_explicit_observations_without_delivering():
    sink = {}
    called = {"deliver": False}
    graph = _capturing_graph(sink)

    def deliver_fn(pid):
        called["deliver"] = True
        return [{"id": "should-not-be-used"}]

    # an explicit list (even empty) is honoured as-is; delivery is NOT invoked
    run_analyser("proj-1", "run-1", observations=[], graph=graph, deliver_fn=deliver_fn)
    assert sink["observations"] == []
    assert called["deliver"] is False


# --- AST-PODSTREAM-05: observation delivery is fail-open ---

def test_observation_delivery_fail_open():
    def exploding_read(cy, params):
        raise RuntimeError("neo4j down")

    # deliver_observations must degrade to an empty delivery, never raise
    out = delivery.deliver_observations("proj-1", read_fn=exploding_read)
    assert out == []


def test_run_analyser_still_runs_when_delivery_fails():
    """End-to-end fail-open: the real deliver wrapper degrades a failing observation
    read to [], so the analyser still runs over the asset slice."""
    sink = {}
    graph = _capturing_graph(sink)

    def failing_read(cy, params):
        raise RuntimeError("neo4j down")

    # production uses deliver_observations (the fail-open wrapper); wire it with a
    # read that raises and confirm the run completes with empty observations.
    out = run_analyser("proj-1", "run-1", graph=graph,
                       deliver_fn=lambda pid: delivery.deliver_observations(pid, read_fn=failing_read))
    assert out.services_written == 1  # ran over the asset slice with empty observations
    assert sink["observations"] == []
