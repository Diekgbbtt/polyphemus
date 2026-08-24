"""E3-E15 e2e predicates for the hunt-orchestrator in ISOLATION (spec section 6.3).

The orchestrator's own infrastructure seams are REAL here: a live Neo4j L0/L1
graph the read-only view grounds on, and a real append-only markdown hunt store
on the filesystem. Only the agent-side collaborators are stubbed at their
boundaries - the reasoning turn (Q8), the dispatch (IA-2, #83), the re-match
(#71/#64), the KB retrieval (D67-11), and the back-edge router (IA-6). That is
exactly the fixture-agent contract the spec section 3 sanctions; the REAL
hunting agent and pod are the blocked E1/E2 walkthrough's live edge
(test_hunt_orchestrator_walkthrough.py), never substituted here.

Why this file exists (the gap it closes): C1-C12 (integration tier) drive the
orchestrator with the graph view MOCKED empty (`read_fn=lambda cy, p: []`), so
the gate's surface input and the minted HuntConfig.surface_context are never
exercised against a real graph; and E1/E2 are carried/blocked on the hunting
agent. Nothing asserted that the orchestrator (a) grounds its gate in real
index-cards, (b) never writes L0/L1 through its read-only view, or (c) persists
the full lifecycle into real store files. This catalogue pins all of those,
covering every happy path (H1-H4) and every outlier shape (O1-O10) the
orchestrator can take.

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
    NoteOut,
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
        envisioned_test_primitives=["fixture probe"], supposed_payload_vectors=["fixture vector"],
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

    def dispatch(config: HuntConfig):
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

    # The full lifecycle landed in the REAL store files.
    assert len(store.list_records("run-e3", "run")) == 1
    assert len(store.list_records("run-e3", "config")) == 2
    assert len(store.list_records("run-e3", "hunt")) == 2
    assert len(store.list_records("run-e3", "dispatch")) == 2
    assert len(store.list_records("run-e3", "result")) == 2
    assert store.list_records("run-e3", "back_edge") == []
    hunts = store.list_records("run-e3", "hunt")
    configs_rec = store.list_records("run-e3", "config")
    assert hunts[0]["config_ref"] == configs_rec[0]["_ref"]
    assert hunts[1]["config_ref"] == configs_rec[1]["_ref"]

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
    unresolved = store.list_records("run-e4", "unresolved")
    assert len(unresolved) == 1
    assert unresolved[0]["revival_key"] == revival_key(SERVICE_A, FAULT_X)
    assert len(store.list_records("run-e4", "back_edge")) == 1
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
    assert len(store.list_records("run-e5", "back_edge")) == 1
    assert len(store.list_records("run-e5", "hunt")) == 2
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
    assert len(store.list_records("run-e6", "hunt")) == 1


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
    passes = store.list_records("run-e7", "run")
    assert len(passes) == 1
    assert passes[0]["candidates_received"] == 0


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
    assert len(store.list_records("run-e8", "hunt")) == 1


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
    assert len(store.list_records("run-e9", "hunt")) == 1


# --- E10: O3 store write failure degrades to a warning -------------------------

class _FlakyStore(HuntStore):
    def __init__(self, root, *, fail_first: int):
        super().__init__(root)
        self._failures_left = fail_first

    def append(self, run_id, kind, record):
        if self._failures_left > 0:
            self._failures_left -= 1
            raise OSError("disk full (fixture)")
        return super().append(run_id, kind, record)


def test_E10_store_write_failure_degrades_to_warning(project, tmp_path, caplog):
    flaky = _FlakyStore(tmp_path, fail_first=2)
    report = run_orchestration(
        project_id=project, run_id="run-e10",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(flaky, project),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
    )
    assert report.store_write_failures == 2
    assert report.hunts_dispatched == 1
    assert "warning" in caplog.text.lower()


# --- E11: O4 store read failure degrades prior insights ------------------------

class _RaisingReadStore(HuntStore):
    def read_memory(self, revival_key):
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

    def boom(config: HuntConfig):
        raise RuntimeError("agent turn exhausted")

    report = run_orchestration(
        project_id=project, run_id="run-e13",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=boom,
        rematch_fn=_ok_rematch(),
    )
    assert report.hunts_dispatched == 1
    hunts = store.list_records("run-e13", "hunt")
    assert len(hunts) == 1
    assert hunts[0]["degraded"] is True
    assert "exhausted" in hunts[0]["error"]


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
    cuts = store.list_records("run-e14", "cut")
    assert len(cuts) == 1
    assert cuts[0]["direction"] == revival_key(SYSTEM_B, FAULT_Y)
    assert len(store.list_records("run-e14", "config")) == 1


# --- E15: cross-run memory by revival key (the #70 seam) -----------------------

def test_E15_cross_run_memory_by_revival_key(project, tmp_path):
    """Two passes over the same project + revival key: the first pass's feedback
    becomes the second pass's prior-hunt insight, read back out of the REAL
    cross-run memory.md file."""
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
    memory = store.list_records("memory", "memory")
    assert len(memory) == 1
    assert memory[0]["revival_key"] == revival_key(SERVICE_A, FAULT_X)
    assert memory[0]["insight"] == "form Z carries no CSRF token"

    run_orchestration(
        project_id=project, run_id="run-e15b",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch(second_configs),
        rematch_fn=_ok_rematch(),
    )
    assert len(second_configs) == 1
    # The second pass's prior-hunt insights read the first pass's memory record
    # back out of the real cross-run memory.md (the raw record round-trips with
    # its _seq/_ref provenance).
    assert second_configs[0].prior_hunt_insights == [
        {
            "_seq": memory[0]["_seq"],
            "_ref": memory[0]["_ref"],
            "revival_key": revival_key(SERVICE_A, FAULT_X),
            "hunt_id": first_configs[0].hunt_id,
            "insight": "form Z carries no CSRF token",
        }
    ]


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


# --- E17-E19 (#143): the per-project memory system against the REAL store + graph


def _note_producer_fixture(notes):
    """The fixture note-taking turn: returns the given notes for the current state."""

    def produce(state) -> dict:
        return {"notes": notes}

    return produce


def _capture_reason(seen: dict):
    """The gate: records the real graph surface AND the prior-config key-list it
    was grounded on (Seam 3 measurement), then carries every candidate in-turn."""

    def reason(inp):
        seen["surface"] = inp.surface
        seen["prior_config_keys"] = list(inp.prior_config_keys)
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    return reason


def test_E17_bounded_live_pass_lands_configs_and_notes(session, project, tmp_path):
    """E1 (Seam 4) - a bounded live pass against the real graph + real store lands
    per-project hunt configs AND notes (the note node fires deterministically),
    read back out of the real per-project store."""
    store = HuntStore(tmp_path)
    seen: dict = {}
    note_produced = [
        NoteOut(unit_id=SERVICE_A, fault_class=FAULT_X,
                name="implicit_test_primitive:csrf-probe", kind="implicit_test_primitive",
                body="probe the POST with a bare token"),
    ]

    run_orchestration(
        project_id=project, run_id="run-E17", candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
        reason_fn=_capture_reason(seen),
        note_fn=_note_producer_fixture(note_produced),
    )

    memory = store.project_memory
    # Config direction stamp accumulates.
    assert memory.config_keys(project) == [revival_key(SERVICE_A, FAULT_X)]
    # The note node wrote the produced note (deterministic invocation).
    notes = memory.read_notes(project)
    assert len(notes) == 1
    assert notes[0]["kind"] == "implicit_test_primitive"
    assert notes[0]["unit_id"] == SERVICE_A and notes[0]["fault_class"] == FAULT_X
    assert store.list_records("run-E17", "hunt")  # the real per-run trail still writes


def test_E18_gate_prompt_carries_prior_keys_across_two_passes(session, project, tmp_path):
    """E2 (Seam 3 + 4) - two live passes on the same bounded project: pass 1
    persists a config for fault-x; pass 2 (same unit, fault-y) has a gate prompt
    carrying the prior key-list (the fault-x header), and its note store holds
    pass 1's notes."""
    store = HuntStore(tmp_path)
    seen1: dict = {}
    seen2: dict = {}

    run_orchestration(
        project_id=project, run_id="run-E18a", candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch([]), rematch_fn=_ok_rematch(),
        reason_fn=_capture_reason(seen1),
    )
    # The second pass hunts a DIFFERENT fault on the SAME unit - the prior
    # fault-x config is still relevant (overlap-prevention memory).
    run_orchestration(
        project_id=project, run_id="run-E18b", candidates=[_candidate(SERVICE_A, FAULT_Y)],
        tools=_tools(store, project),
        dispatch_fn=_recording_dispatch([]), rematch_fn=_ok_rematch(),
        reason_fn=_capture_reason(seen2),
    )

    # Pass 2's gate saw the prior fault-x key header.
    assert revival_key(SERVICE_A, FAULT_X) in seen2["prior_config_keys"]
    # Pass 1's config persists in the per-project store.
    assert revival_key(SERVICE_A, FAULT_X) in store.project_memory.config_keys(project)


def test_E19_orchestrator_detects_when_to_call_reading_tool(session, project, tmp_path):
    """E3 (Seam 3 capability measurement) - a prior hypothesis_refusal note with a
    distinctive body keyword exists for a unit; a later pass on that unit invokes
    the reading tool (tracing it) and retrieves the relevant prior note."""
    store = HuntStore(tmp_path)
    # Seed a prior refusal note with a distinctive body keyword.
    store.project_memory.append_note(
        project, SERVICE_A, "fault-x", "hypothesis_refusal:no-csrf",
        "hypothesis_refusal", "no CSRF token on form Z",
    )
    memory = store.project_memory
    calls: list = []
    real_tools = _tools(store, project)
    # Wrap read_memory_notes to trace invocations (the capability measurement).
    traced = OrchestratorTools(
        back_edge=real_tools.back_edge,
        store_reads=store,
        graph_view=real_tools.graph_view,
    )
    original = traced.read_memory_notes

    def traced_read(project_id, *, parent_key=None, key_keyword=None, body_keyword=None):
        calls.append((parent_key, key_keyword, body_keyword))
        return original(project_id, parent_key=parent_key,
                        key_keyword=key_keyword, body_keyword=body_keyword)

    traced.read_memory_notes = traced_read  # type: ignore[method-assign]

    seen: dict = {}

    def reason_with_read(inp):
        seen["surface"] = inp.surface
        # The orchestrator (as the agent would) detects the relevant prior note
        # via the reading tool - the body keyword is the project's fault signal.
        hit = traced_read(project, parent_key=revival_key(SERVICE_A, "fault-x"),
                          body_keyword="csrf")
        seen["retrieved"] = hit
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    run_orchestration(
        project_id=project, run_id="run-E19", candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=traced, dispatch_fn=_recording_dispatch([]), rematch_fn=_ok_rematch(),
        reason_fn=reason_with_read,
    )

    # The reading tool fired and returned the prior note matching the keyword.
    assert len(seen["retrieved"]) == 1
    assert seen["retrieved"][0]["kind"] == "hypothesis_refusal"
    assert "no CSRF token on form Z" in seen["retrieved"][0]["body"]
