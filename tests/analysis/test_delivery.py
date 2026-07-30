"""FR-PODSTREAM unit tier — the batch-mode delivery/completeness guarantee for the
analyser (exactly-once delivery of every AssetDelta via the slice + every
Observation via a dedicated channel), with injected fakes (no live DB/LLM).
Store-level idempotency is the integration tier (tests/integration/test_delivery_merge.py).

REWIRED (#48 section 11 step 6, ratified 2026-07-30): `run_analyser` no longer
drives a compiled `build_analyser_graph` subgraph with injected read/analyse/curate
fakes - the legacy pod is retired, and `run_analyser` is now a thin wrapper that
always drives the chunk-fed supervised path (`supervisor.run_analyser_chunked`).
The AST-PODSTREAM-03/05 tests below are rewired onto the SAME collaborator surface
`run_analyser` now exposes: an injectable `run_supervisor_fn` (defaulting to
`run_analyser_chunked`) that receives an `observations_fn` collaborator carrying
whatever `run_analyser` resolved (explicit vs auto-delivered). The INTENT of every
assertion is unchanged: dedup by id, fail-open on a delivery error, and an explicit
`observations` list bypassing auto-delivery.

Each test names the assertion it encodes (docs/design/L1-MVP-plan.md FR-PODSTREAM ledger).
"""
from polymerhus.analysis import delivery
from polymerhus.analysis import pod as analyser_pod
from polymerhus.analysis.pod import AnalyserExport, run_analyser


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
    import polymerhus.recon.domain.graph_read as graph_read
    monkeypatch.setattr(graph_read, "fetch_project_graph", lambda pid: canned)

    slice_ = analyser_pod.default_read_fn("proj-1")
    types = {n["type"] for n in slice_["nodes"]}
    assert "Observation" not in types  # observations are NOT double-delivered in the slice
    assert types == {"Endpoint", "Parameter"}
    # the dropped observation's anchor edge is gone; the asset-asset edge survives
    assert slice_["links"] == [{"source": "p1", "target": "e1", "type": "PARAM_OF"}]


# --- AST-PODSTREAM-03: run_analyser auto-delivers observations when caller passes none ---

def _spying_supervisor(sink: dict, export=None):
    def spy(project_id, run_id, **collaborators):
        sink["project_id"] = project_id
        sink["run_id"] = run_id
        obs_fn = collaborators.get("observations_fn")
        sink["observations"] = obs_fn(project_id) if obs_fn is not None else None
        return export if export is not None else AnalyserExport(services_written=1)
    return spy


def test_run_analyser_auto_delivers_observations():
    sink = {}
    delivered = [{"id": "obs1", "macro_kind": "reflected_input"}]

    # observations=None (default) -> auto-delivered from the injected deliver_fn,
    # threaded into the supervised pass as an observations_fn override.
    run_analyser("proj-1", "run-1", run_supervisor_fn=_spying_supervisor(sink),
                 deliver_fn=lambda pid: delivered)
    assert sink["observations"] == delivered  # the run's observations reached the supervised pass


def test_run_analyser_honours_explicit_observations_without_delivering():
    sink = {}
    called = {"deliver": False}

    def deliver_fn(pid):
        called["deliver"] = True
        return [{"id": "should-not-be-used"}]

    # an explicit list (even empty) is honoured as-is; delivery is NOT invoked
    run_analyser("proj-1", "run-1", observations=[],
                 run_supervisor_fn=_spying_supervisor(sink), deliver_fn=deliver_fn)
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
    """End-to-end fail-open: a raising deliver_fn degrades to empty observations
    inside run_analyser itself, so the supervised pass still runs."""
    sink = {}

    def failing_deliver(pid):
        raise RuntimeError("neo4j down")

    out = run_analyser("proj-1", "run-1", run_supervisor_fn=_spying_supervisor(sink),
                       deliver_fn=failing_deliver)
    assert out.services_written == 1  # the supervised pass still ran
    assert sink["observations"] == []  # degraded to empty, never raised
