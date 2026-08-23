"""E3-E15 e2e predicates for the hunt-orchestrator in ISOLATION (spec section 6.3).

The orchestrator's own infrastructure seams are REAL here: a live Neo4j L0/L1
graph the read-only view grounds on, and the real per-project memory store on
the filesystem (#166 - `data/<project_id>/orchestration/` with
`hunt_configs/produced`, `hunt_configs/consumed`, and `memory.yaml`; the
append-only per-run kind files are removed). Only the agent-side collaborators
are stubbed at their boundaries - the reasoning turn (Q8), the dispatch
(IA-2, #83), the re-match (#71/#64), the KB retrieval (D67-11), and the
back-edge router (IA-6). That is exactly the fixture-agent contract the spec
section 3 sanctions; the REAL hunting agent and pod are the blocked E1/E2
walkthrough's live edge (test_hunt_orchestrator_walkthrough.py), never
substituted here.

Why this file exists (the gap it closes): C1-C12 (integration tier) drive the
orchestrator with the graph view MOCKED empty (`read_fn=lambda cy, p: []`), so
the gate's surface input and the minted HuntConfig.surface_context are never
exercised against a real graph; and E1/E2 are carried/blocked on the hunting
agent. Nothing asserted that the orchestrator (a) grounds its gate in real
index-cards, (b) never writes L0/L1 through its read-only view, or (c) persists
the hypothesised configs and notes into the real per-project store. This
catalogue pins all of those, covering every happy path (H1-H4) and every
outlier shape (O1-O10) the orchestrator can take.

Source: docs/design/hunting-67-orchestrator-spec.md section 6.3.
"""
from __future__ import annotations

import subprocess
import uuid

import pytest

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    DispatchResult,
    EnvisionedDirection,
    GateDecision,
    HuntConfig,
    MatchVerdict,
    OrchestratorTools,
    ReadOnlyGraphView,
    ReadOnlyGraphViewError,
    Witness,
    revival_key,
    run_orchestration,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.recon.control.targeted import TargetedReconResult
from tests.conftest import neo4j_target, wait_for

SERVICE_A = "Service:slug:a"
SYSTEM_B = "System:key:b"
FAULT_X = "fault-x"
FAULT_Y = "fault-y"
SLUG = "a"
KIND = "key"
DISCRIMINATOR = "b"
BASE = "https://a.example"


def _driver():
    from neo4j import GraphDatabase

    uri, auth = neo4j_target()
    d = GraphDatabase.driver(uri, auth=auth)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    try:
        subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=False)
    except Exception:  # noqa: BLE001 - offline/CI: the skip below is the gate
        pass
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for hunt-orchestrator isolated e2e: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


def _seed_project(session, pid):
    """A real two-unit L1 graph: a public Service, a CSR System it is exposed
    via, and an L0 Endpoint it AGGREGATES - so the read-only view returns real
    index-cards with a non-empty spine and per-family edge degrees."""
    session.run(
        "MERGE (:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $p, exposure: 'public'}) "
        "MERGE (:L1TestableUnit:L1System {kind: $kind, discriminator: $disc, project_id: $p, rendering_model: 'CSR'}) "
        "MERGE (:Endpoint {path: '/api/a', method: 'GET', baseurl: $base, project_id: $p})",
        slug=SLUG, kind=KIND, disc=DISCRIMINATOR, base=BASE, p=pid,
    )
    session.run(
        "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
        "MATCH (sy:L1System {kind: $kind, discriminator: $disc, project_id: $p}) "
        "MERGE (s)-[:EXPOSED_VIA]->(sy)",
        slug=SLUG, kind=KIND, disc=DISCRIMINATOR, p=pid,
    )
    session.run(
        "MATCH (s:L1Service {business_function_slug: $slug, project_id: $p}) "
        "MATCH (e:Endpoint {path: '/api/a', baseurl: $base, project_id: $p}) "
        "MERGE (s)-[:AGGREGATES {status: 'committed'}]->(e)",
        slug=SLUG, base=BASE, p=pid,
    )


def _graph_counts(session, pid):
    """(nodes, edges) touching the project - the read-only proof snapshot."""
    nodes = session.run(
        "MATCH (n) WHERE n.project_id = $p RETURN count(n) AS c", p=pid,
    ).single()["c"]
    edges = session.run(
        "MATCH (a)-[r]->(b) WHERE a.project_id = $p OR b.project_id = $p "
        "RETURN count(r) AS c", p=pid,
    ).single()["c"]
    return nodes, edges


@pytest.fixture
def project(session):
    pid = "ht82iso_" + uuid.uuid4().hex[:8]
    _seed_project(session, pid)
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _candidate(unit_id: str, fault_class: str, *, verdict: str = "applies",
               llm_witness: str | None = "witness") -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id, fault_class=fault_class,
        applies_witnesses=Witness(deterministic=None, llm=llm_witness),
        match_verdict=verdict,
    )


def _carry(candidate: DeliveredCandidate, *, carried: bool = True) -> EnvisionedDirection:
    return EnvisionedDirection(
        unit_id=candidate.unit_id, fault_class=candidate.fault_class, carried=carried,
        rationale="fixture rationale", assumptions=["fixture assumption"],
        envisioned_test_primitives=["fixture probe"],
    )


def _tools(store: HuntStore, project_id: str, *, back_edge=None, graph_view=None) -> OrchestratorTools:
    """The orchestrator's tools: the real hunt store, a stubbed back-edge, and
    by default the REAL read-only graph view (no injected read_fn - it grounds
    in live Neo4j through the config-backed client the live tier rebinds)."""
    return OrchestratorTools(
        back_edge=back_edge,
        store_reads=store,
        graph_view=graph_view or ReadOnlyGraphView(project_id),
    )


def _recording_dispatch(configs: list, *, feedback: str = "ok"):
    """The fixture hunting agent (IA-2): records every minted config and
    returns a successful result - the spec-sanctioned fixture agent."""

    def dispatch(config: HuntConfig, routed=()):
        configs.append(config)
        return DispatchResult(
            spec_ref="spec-1", pod_result_ref="pod-1",
            hypothesis_verdict="successful", feedback=feedback,
        )

    return dispatch


def _recording_reason(seen: dict):
    """The gate (Q8): records the REAL graph surface it was grounded on, then
    carries every accepted candidate in-turn."""

    def reason(inp):
        seen["surface"] = inp.surface
        seen["kb_degraded"] = inp.kb_degraded
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    return reason


def _ok_rematch(verdict: str = "applies"):
    def rematch(unit_id: str, fault_class: str, result: TargetedReconResult) -> MatchVerdict:
        return MatchVerdict(unit_id=unit_id, fault_class=fault_class, verdict=verdict)

    return rematch


def _ok_back_edge(seen: list | None = None, *, status: str = "success"):
    record = seen if seen is not None else []

    def back_edge(request, run_id, project_id):
        record.append(request)
        return TargetedReconResult(
            correlation_id=request.correlation_id, requester_id=request.requester_id,
            origin="hunting", status=status,
        )

    return back_edge


# --- E3: H1 full run against the REAL graph (grounding + lifecycle + read-only)

def test_E3_full_run_grounds_in_real_graph_and_never_writes(session, project, tmp_path):
    store = HuntStore(tmp_path)
    seen: dict = {}
    configs: list = []
    before = _graph_counts(session, project)

    report = run_orchestration(
        project_id=project, run_id="run-e3",
        candidates=[_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch(configs),
        rematch_fn=_ok_rematch(),
        reason_fn=_recording_reason(seen),
        kb_retrieve_fn=lambda fault_class: {"probing_techniques": ["csrf-probe"]},
    )

    assert report.hunts_dispatched == 2
    assert report.unresolved == () and report.budget_cut == ()

    # The gate grounded in the REAL graph: two real index-cards, one per kind,
    # carrying the typed spine and the per-family edge degrees (DD-4 counts).
    cards = {c["kind"]: c for c in seen["surface"]}
    assert set(cards) == {"Service", "System"}
    assert cards["Service"]["key"] == {"business_function_slug": SLUG}
    assert cards["Service"]["spine"].get("exposure") == "public"
    assert cards["Service"]["edge_degree"].get("EXPOSED_VIA") == 1
    assert cards["Service"]["edge_degree"].get("AGGREGATES") == 1
    assert cards["System"]["key"] == {"kind": KIND, "discriminator": DISCRIMINATOR}
    assert cards["System"]["spine"].get("rendering_model") == "CSR"

    # The REAL surface flows into every minted HuntConfig (D3 part 2).
    assert len(configs) == 2
    assert all(cfg.surface_context["cards"] == seen["surface"] for cfg in configs)
    # The KB probing techniques become the fault-targeting tool registry (D10).
    assert all(cfg.tool_registry == [{"technique": "csrf-probe"}] for cfg in configs)

    # The full lifecycle landed in the REAL per-project store (memory-system
    # spec #166): the hypothesised configs in produced/, one note per unit in
    # memory.yaml; the per-run run/hunt/dispatch/result/back_edge kind files
    # are removed (G10/G11/G12).
    assert len(store.read_configs(project)) == 2
    assert len(store.read_notes(project)) == 2
    assert store.read_configs(project)[0]["status"] == "hypothesised"

    # D67-04 on a REAL graph: the run wrote nothing to L0/L1.
    assert _graph_counts(session, project) == before


# --- E4: O8 unresolved at the depth-1 cap, graph still untouched --------------

def test_E4_park_resume_unresolved_at_depth_cap(session, project, tmp_path):
    store = HuntStore(tmp_path)
    back_edges: list = []
    before = _graph_counts(session, project)
    yellow = _candidate(SERVICE_A, FAULT_X, verdict="insufficient-evidence")

    report = run_orchestration(
        project_id=project, run_id="run-e4",
        candidates=[yellow],
        tools=_tools(store, project, back_edge=_ok_back_edge(back_edges)),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(verdict="insufficient-evidence"),
    )

    assert report.hunts_dispatched == 0
    assert len(back_edges) == 1
    assert back_edges[0].origin == "hunting"
    assert report.unresolved == (revival_key(SERVICE_A, FAULT_X),)
    # the unresolved state rides the report trail (the per-run `unresolved` /
    # `back_edge` kind records are removed, #166); the direction's hypothesised
    # draft was still minted to produced/ at the unit boundary BEFORE the
    # dispatch-stage unresolved decision - it stays as an in-progress config
    # (G10), never dispatched
    assert len(store.read_configs(project)) == 1
    assert len(store.read_notes(project)) == 1
    # The back-edge path wrote nothing to the graph either.
    assert _graph_counts(session, project) == before


# --- E5: H3 park/resume positive path -----------------------------------------

def test_E5_park_resume_rematch_applies_dispatches(project, tmp_path):
    store = HuntStore(tmp_path)
    back_edges: list = []
    configs: list = []
    yellow = _candidate(SERVICE_A, FAULT_X, verdict="insufficient-evidence")

    report = run_orchestration(
        project_id=project, run_id="run-e5",
        candidates=[_candidate(SYSTEM_B, FAULT_Y), yellow],
        tools=_tools(store, project, back_edge=_ok_back_edge(back_edges)),
        dispatch_fn=_recording_dispatch(configs),
        rematch_fn=_ok_rematch(verdict="applies"),
    )

    assert report.hunts_dispatched == 2
    assert report.unresolved == ()
    assert len(back_edges) == 1
    # the back-edge/hunt kind records are removed (#166); the re-matched
    # direction's config persists in produced/ like any other
    assert len(store.read_configs(project)) == 2
    # The re-matched yellow's config carries the back-edge caveat (spec 5).
    re_matched = [c for c in configs if c.unit_id == SERVICE_A]
    assert len(re_matched) == 1
    assert re_matched[0].target_caveats == ["yellow match re-matched after back-edge"]


# --- E6: H2 deterministic prune ------------------------------------------------

def test_E6_deterministic_prune_before_the_gate(project, tmp_path):
    store = HuntStore(tmp_path)
    seen: dict = {}

    report = run_orchestration(
        project_id=project, run_id="run-e6",
        candidates=[
            _candidate(SERVICE_A, FAULT_X),
            _candidate(SYSTEM_B, FAULT_Y, verdict="does-not-apply"),
        ],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
        reason_fn=_recording_reason(seen),
    )

    assert report.hunts_dispatched == 1
    assert report.pruned_by_verdict == 1
    # The gate still grounded in the REAL graph even though one direction was
    # pruned before it (Q8 level 1 prune is intake-side, not gate-side).
    assert any(c["kind"] == "Service" for c in seen["surface"])
    assert len(store.read_configs(project)) == 1  # only the carried direction minted


# --- E7: O1 empty candidate set is an empty pass -------------------------------

def test_E7_empty_candidate_set_is_an_empty_pass(project, tmp_path):
    store = HuntStore(tmp_path)
    report = run_orchestration(
        project_id=project, run_id="run-e7",
        candidates=[], tools=_tools(store, project),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
    )
    assert report.hunts_dispatched == 0
    # the empty pass persists nothing in the memory topology (the per-run
    # `run` record with candidates_received is removed, #166)
    assert store.read_configs(project) == []
    assert store.read_notes(project) == []


# --- E8: O7 duplicate + O10 malformed are dropped, counted ---------------------

def test_E8_duplicate_and_malformed_dropped_counted(project, tmp_path):
    store = HuntStore(tmp_path)
    report = run_orchestration(
        project_id=project, run_id="run-e8",
        candidates=[
            _candidate(SERVICE_A, FAULT_X),
            _candidate(SERVICE_A, FAULT_X),  # duplicate
            _candidate(SYSTEM_B, FAULT_Y, llm_witness=None),  # malformed
        ],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
        known_faults=[FAULT_X, FAULT_Y],
    )
    assert report.hunts_dispatched == 1
    assert report.duplicates_dropped == 1
    assert report.malformed_dropped == 1
    assert len(store.read_configs(project)) == 1


# --- E9: H4/D67-11 KB degradation never prunes a direction ---------------------

def test_E9_kb_failure_degrades_the_gate_never_prunes(project, tmp_path):
    store = HuntStore(tmp_path)
    seen: dict = {}
    configs: list = []

    def kb_retrieve(fault_class):
        raise RuntimeError("KB unavailable")

    report = run_orchestration(
        project_id=project, run_id="run-e9",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch(configs),
        rematch_fn=_ok_rematch(),
        reason_fn=_recording_reason(seen),
        kb_retrieve_fn=kb_retrieve,
    )

    assert seen["kb_degraded"] is True
    assert report.hunts_dispatched == 1
    assert configs[0].tool_registry == []  # no KB -> empty registry
    assert len(store.read_configs(project)) == 1


# --- E10: O3 store write failure degrades to a warning -------------------------

class _FlakyStore(HuntStore):
    def __init__(self, root, *, fail_first: int):
        super().__init__(root)
        self._failures_left = fail_first

    def _write_guard(self):
        if self._failures_left > 0:
            self._failures_left -= 1
            raise OSError("disk full (fixture)")

    def write_config(self, project_id, config, *, directory="produced"):
        self._write_guard()
        return super().write_config(project_id, config, directory=directory)

    def append_note(self, project_id, key, note):
        self._write_guard()
        return super().append_note(project_id, key, note)


def test_E10_store_write_failure_degrades_to_warning(project, tmp_path, caplog):
    flaky = _FlakyStore(tmp_path, fail_first=2)
    report = run_orchestration(
        project_id=project, run_id="run-e10",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(flaky, project),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
    )
    # the 1-candidate pass makes exactly two store writes (the config at the
    # mint + the unit-boundary note); both fail (O3 - warned + counted), the
    # pass still completes and dispatches
    assert report.store_write_failures == 2
    assert report.hunts_dispatched == 1
    assert "warning" in caplog.text.lower()


# --- E11: O4 store read failure degrades prior insights ------------------------

class _RaisingReadStore(HuntStore):
    def read_configs_by_key(self, project_id, key):
        raise OSError("store read failed (fixture)")

    def read_notes(self, project_id, key=None):
        raise OSError("store read failed (fixture)")


def test_E11_store_read_failure_degrades_prior_insights(project, tmp_path, caplog):
    store = _RaisingReadStore(tmp_path)
    configs: list = []
    report = run_orchestration(
        project_id=project, run_id="run-e11",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch(configs),
        rematch_fn=_ok_rematch(),
    )
    assert report.hunts_dispatched == 1
    assert configs[0].prior_hunt_insights == []
    assert "warning" in caplog.text.lower()


# --- E12: O5 graph-view query failure degrades the gate ------------------------

def test_E12_graph_view_failure_degrades_the_gate(project, tmp_path, caplog):
    store = HuntStore(tmp_path)
    seen: dict = {}

    def broken_read(cypher, params):
        raise RuntimeError("graph read failed (fixture)")

    graph_view = ReadOnlyGraphView(project, read_fn=broken_read)
    report = run_orchestration(
        project_id=project, run_id="run-e12",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project, graph_view=graph_view),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
        reason_fn=_recording_reason(seen),
    )
    assert report.hunts_dispatched == 1
    assert seen["surface"] == []  # degraded to the candidate set + KB alone (O5)
    assert "warning" in caplog.text.lower()


# --- E13: O6 dispatch target failure degrades the hunt record ------------------

def test_E13_dispatch_failure_degrades_the_hunt(project, tmp_path):
    store = HuntStore(tmp_path)

    def boom(config: HuntConfig, routed=()):
        raise RuntimeError("agent turn exhausted")

    report = run_orchestration(
        project_id=project, run_id="run-e13",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=boom,
        rematch_fn=_ok_rematch(),
    )
    assert report.hunts_dispatched == 1
    # the degraded hunt record is removed (#166): the pass still dispatches and
    # the minted config persists; the degraded/error detail rides the in-memory
    # trail (the report exposes hunt_ids, never the record's error field)
    assert len(store.read_configs(project)) == 1


# --- E14: O9 budget cut records the un-dispatched direction --------------------

def test_E14_budget_cut_records_undispatched_direction(project, tmp_path):
    store = HuntStore(tmp_path)

    def budget_fn(directions):
        return directions[:1]

    report = run_orchestration(
        project_id=project, run_id="run-e14",
        candidates=[_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
        budget_fn=budget_fn,
    )
    assert report.hunts_dispatched == 1
    assert report.budget_cut == (revival_key(SYSTEM_B, FAULT_Y),)
    # the cut rides the report trail (the per-run `cut` record is removed,
    # #166); ALL configs were minted to produced/ BEFORE the budget stage, so
    # the cut direction's hypothesised draft stays on disk (G10: a budget cut
    # is a dispatch-stage decision, never a config deletion)
    assert len(store.read_configs(project)) == 2
    assert len(store.read_notes(project)) == 2


# --- E15: cross-pass memory by revival key (the #166 per-project store) ---------

def test_E15_cross_run_memory_by_revival_key(project, tmp_path):
    """Two passes over the same project + revival key: the first pass's
    persisted config (produced/) + note (memory.yaml) become the second pass's
    prior-hunt insights, read back out of the REAL per-project store - the
    cross-run memory.md (and its dispatch-feedback insight) is removed (#166),
    the store is per-project and per-pass durable (memory-system spec 10)."""
    store = HuntStore(tmp_path)
    first_configs: list = []
    second_configs: list = []

    run_orchestration(
        project_id=project, run_id="run-e15a",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch(first_configs, feedback="form Z carries no CSRF token"),
        rematch_fn=_ok_rematch(),
    )
    assert len(store.read_configs(project)) == 1
    assert len(store.read_notes(project)) == 1

    run_orchestration(
        project_id=project, run_id="run-e15b",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch(second_configs),
        rematch_fn=_ok_rematch(),
    )
    assert len(second_configs) == 1
    # The second pass's prior-hunt insights read the first pass's persisted
    # config and note back out of the real per-project store.
    insights = second_configs[0].prior_hunt_insights
    assert any(i.get("unit_id") == SERVICE_A and i.get("fault_class") == FAULT_X
               for i in insights)
    assert any(i.get("note") for i in insights)


# --- E16 (#110): the graph engine's actor lives past a completed pass ----------

def test_E16_actor_lives_past_completion_and_reuses_the_run_thread(project, tmp_path):
    """#110 loop-restart property with the real store + real graph grounding: the
    registry-held orchestration actor is NOT reaped when a pass completes - a
    second pass on the same run_id reuses the SAME actor (the same
    hunting_orchestrator thread serves every pair AND every pass of the run)."""
    import asyncio

    from polymerhus.attack.hunting.hunt_orchestrator import (
        _ORCHESTRATOR_ACTORS,
        _reap_orchestrator,
    )

    store = HuntStore(tmp_path)
    tools = _tools(store, project)
    first = run_orchestration(
        project_id=project, run_id="run-e16",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=tools, dispatch_fn=_recording_dispatch([]), rematch_fn=_ok_rematch(),
    )
    actor_after_first = _ORCHESTRATOR_ACTORS.get("run-e16")
    assert first.hunts_dispatched == 1
    assert actor_after_first is not None  # the completed pass did NOT reap it

    second = run_orchestration(
        project_id=project, run_id="run-e16",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=tools, dispatch_fn=_recording_dispatch([]), rematch_fn=_ok_rematch(),
    )
    actor_after_second = _ORCHESTRATOR_ACTORS.get("run-e16")
    assert second.hunts_dispatched == 1
    assert actor_after_second is actor_after_first  # the SAME thread across passes

    asyncio.run(_reap_orchestrator("run-e16"))  # teardown: the stop path reaps it
    assert _ORCHESTRATOR_ACTORS.get("run-e16") is None


# --- The read-only view rejects a write through the REAL seam ------------------

def test_read_only_view_rejects_writes(project):
    view = ReadOnlyGraphView(project)
    with pytest.raises(ReadOnlyGraphViewError):
        view.merge("MATCH (n) MERGE (m) ...")  # write-shaped call through the view
    assert view.read(
        "MATCH (u:L1TestableUnit) WHERE u.project_id = $project_id RETURN count(u) AS c",
        {"project_id": project},
    )  # reads still reach the live graph through the view
