"""E3-E16 e2e predicates for the hunt-orchestrator in ISOLATION (spec section 6.3,
re-scoped by #167: the graph ENDs at the REASON stretch - the dispatch node
(G12) and the O9 budget stage (G7) are removed).

The orchestrator's own infrastructure seams are REAL here: a live Neo4j L0/L1
graph the read-only view grounds on, and the real per-project memory store on
the filesystem (#166 - `data/<project_id>/orchestration/` with
`hunt_configs/produced`, `hunt_configs/consumed`, and `memory.yaml`; the
append-only per-run kind files are removed). Only the agent-side collaborators
are stubbed at their boundaries - the hypothesise / ratify / note phase turns
(the node-per-phase REASON body, #167) and the KB retrieval (D67-11). That is
exactly the fixture-agent contract the spec section 3 sanctions; the REAL
hunting agent and pod are the blocked E1/E2 walkthrough's live edge
(test_hunt_orchestrator_walkthrough.py), never substituted here.

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
    EnvisionedDirection,
    GateDecision,
    NoteDecision,
    NoteRecord,
    OrchestratorTools,
    RatifyDecision,
    ReadOnlyGraphView,
    ReadOnlyGraphViewError,
    Witness,
    revival_key,
    run_orchestration,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
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


def _carry(candidate: DeliveredCandidate, *, carried: bool = True,
           classes: list[str] | None = None) -> EnvisionedDirection:
    return EnvisionedDirection(
        unit_id=candidate.unit_id, fault_class=candidate.fault_class, carried=carried,
        rationale="fixture rationale",
        research_direction="probe CSRF token verification",
        vulnerability_classes=classes or ["CSRF"],
    )


def _tools(store: HuntStore, project_id: str, *, graph_view=None) -> OrchestratorTools:
    """The orchestrator's tools: the real hunt store and by default the REAL
    read-only graph view (no injected read_fn - it grounds in live Neo4j
    through the config-backed client the live tier rebinds)."""
    return OrchestratorTools(
        store_reads=store,
        graph_view=graph_view or ReadOnlyGraphView(project_id),
    )


def _recording_hypothesise(seen: dict):
    """The hypothesise turn (Q8): records the REAL graph surface it was
    grounded on, then carries every accepted pair with a CSRF class."""

    def hypothesise(inp):
        seen["surface"] = inp.surface
        seen["kb_degraded"] = inp.kb_degraded
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    return hypothesise


def _ratify_drafts(inp) -> RatifyDecision:
    """The fixture ratify turn: every draft ends ratified."""
    configs = []
    for draft in inp.configs:
        amended = draft.model_copy(deep=True)
        amended.status = "ratified"
        configs.append(amended)
    return RatifyDecision(configs=configs)


def _note_pair(inp) -> NoteDecision:
    """The fixture note turn: one note for the pair."""
    return NoteDecision(notes=[NoteRecord(
        key=revival_key(inp.pair.unit_id, inp.pair.fault_class),
        note="fixture note walking the reasoning",
    )])


# --- E3: H1 full run against the REAL graph (grounding + lifecycle + read-only)

def test_E3_full_run_grounds_in_real_graph_and_never_writes(session, project, tmp_path):
    store = HuntStore(tmp_path)
    seen: dict = {}
    before = _graph_counts(session, project)

    report = run_orchestration(
        project_id=project, run_id="run-e3",
        candidates=[_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        tools=_tools(store, project),
        hypothesise_fn=_recording_hypothesise(seen),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )

    assert report.pairs_processed == 2
    assert report.configs_ratified == 2
    assert not hasattr(report, "unresolved") and not hasattr(report, "budget_cut")

    # The hypothesise turn grounded in the REAL graph: two real index-cards,
    # one per kind, carrying the typed spine and the per-family edge degrees.
    cards = {c["kind"]: c for c in seen["surface"]}
    assert set(cards) == {"Service", "System"}
    assert cards["Service"]["key"] == {"business_function_slug": SLUG}
    assert cards["Service"]["spine"].get("exposure") == "public"
    assert cards["Service"]["edge_degree"].get("EXPOSED_VIA") == 1
    assert cards["Service"]["edge_degree"].get("AGGREGATES") == 1
    assert cards["System"]["key"] == {"kind": KIND, "discriminator": DISCRIMINATOR}
    assert cards["System"]["spine"].get("rendering_model") == "CSR"

    # The REAL surface flows into every minted HuntConfig (D3 part 2).
    configs = store.read_configs(project)
    assert len(configs) == 2
    assert all(cfg["surface_context"]["cards"] == seen["surface"] for cfg in configs)
    # #202: the tool_registry slot is retired - no minted config carries it.
    assert all("tool_registry" not in cfg for cfg in configs)

    # The full lifecycle landed in the REAL per-project store (memory-system
    # spec #166): the ratified configs in produced/, one note per pair in
    # memory.yaml; the per-run run/hunt/dispatch/result/back_edge kind files
    # are removed (G10/G11/G12).
    assert len(store.read_configs(project)) == 2
    assert len(store.read_notes(project)) == 2
    assert store.read_configs(project)[0]["status"] == "ratified"

    # D67-04 on a REAL graph: the run wrote nothing to L0/L1.
    assert _graph_counts(session, project) == before


# --- E4: the dispatch-stage park/resume unresolved path is REMOVED (G12) ------

def test_E4_dispatch_stage_is_removed_and_graph_still_untouched(session, project, tmp_path):
    """E4 - re-scoped by #167/G12: the park/resume unresolved path was a
    DISPATCH-stage decision; the dispatch node is removed (dispatch state
    belongs to the runtime plane). A yellow candidate still reasons through the
    phase machine (carry + ratify + note) and the graph is untouched."""
    store = HuntStore(tmp_path)
    before = _graph_counts(session, project)
    yellow = _candidate(SERVICE_A, FAULT_X, verdict="insufficient-evidence")

    report = run_orchestration(
        project_id=project, run_id="run-e4",
        candidates=[yellow],
        tools=_tools(store, project),
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )

    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert not hasattr(report, "unresolved")       # the dispatch-stage field is gone
    assert not hasattr(report, "budget_cut")       # and the budget stage is gone (G7)
    assert len(store.read_configs(project)) == 1
    assert len(store.read_notes(project)) == 1
    # the phase machine wrote nothing to the graph either.
    assert _graph_counts(session, project) == before


# --- E5: a raising ratify turn degrades fail-open (drafts stay hypothesised) ---

def test_E5_ratify_failure_keeps_the_drafts_hypothesised(project, tmp_path, caplog):
    """E5 - the ratify phase degrades fail-open: a raising ratify turn skips
    the phase's side effect - the hypothesised drafts stay on disk - but the
    pass completes (the graph still ENDs at the note phase)."""
    store = HuntStore(tmp_path)

    def boom(inp):
        raise RuntimeError("ratify turn exhausted")

    report = run_orchestration(
        project_id=project, run_id="run-e5",
        candidates=[_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        tools=_tools(store, project),
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=boom,
        note_fn=_note_pair,
    )
    assert report.pairs_processed == 2
    assert report.configs_hypothesised == 2
    assert report.configs_ratified == 0
    configs = store.read_configs(project)
    assert len(configs) == 2
    assert all(c["status"] == "hypothesised" for c in configs)
    assert "warning" in caplog.text.lower()


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
        hypothesise_fn=_recording_hypothesise(seen),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )

    assert report.pairs_processed == 1
    assert report.pruned_by_verdict == 1
    # The hypothesise turn still grounded in the REAL graph even though one
    # direction was pruned before it (Q8 level 1 prune is intake-side).
    assert any(c["kind"] == "Service" for c in seen["surface"])
    assert len(store.read_configs(project)) == 1  # only the carried pair minted


# --- E7: O1 empty candidate set is an empty pass -------------------------------

def test_E7_empty_candidate_set_is_an_empty_pass(project, tmp_path):
    store = HuntStore(tmp_path)
    report = run_orchestration(
        project_id=project, run_id="run-e7",
        candidates=[], tools=_tools(store, project),
        hypothesise_fn=lambda inp: GateDecision(directions=[]),
    )
    assert report.pairs_processed == 0
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
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
        known_faults=[FAULT_X, FAULT_Y],
    )
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert report.duplicates_dropped == 1
    assert report.malformed_dropped == 1
    assert len(store.read_configs(project)) == 1


# --- E9: the gate grounds via the direct materialisation read, never degrades --

def test_E9_gate_grounds_on_materialisation_never_prunes(project, tmp_path):
    """The gate's `kb_retrieve_fn` duplicate seam is RETIRED: the gate grounds
    via the direct fault-KB materialisation read, so `kb_degraded` is always
    False and the gate never prunes on degraded grounds."""
    store = HuntStore(tmp_path)
    seen: dict = {}

    report = run_orchestration(
        project_id=project, run_id="run-e9",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        hypothesise_fn=_recording_hypothesise(seen),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )

    assert seen["kb_degraded"] is False  # the direct materialisation read is the gate's grounding
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    configs = store.read_configs(project)
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

    def update_config(self, project_id, config, *, directory="produced"):
        self._write_guard()
        return super().update_config(project_id, config, directory=directory)

    def append_note(self, project_id, key, note):
        self._write_guard()
        return super().append_note(project_id, key, note)


def test_E10_store_write_failure_degrades_to_warning(project, tmp_path, caplog):
    flaky = _FlakyStore(tmp_path, fail_first=2)
    report = run_orchestration(
        project_id=project, run_id="run-e10",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(flaky, project),
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    # the 1-candidate pass makes exactly three store writes (the hypothesise
    # create, the ratify upsert, the note append); the first two fail (O3 -
    # warned + counted), the pass still completes
    assert report.store_write_failures == 2
    assert report.pairs_processed == 1
    assert "warning" in caplog.text.lower()


# --- E11: O4 store read failure degrades prior insights ------------------------

class _RaisingReadStore(HuntStore):
    def read_hunter_specs(self, project_id, key):
        raise OSError("store read failed (fixture)")

    def read_hunter_notes(self, project_id, key):
        raise OSError("store read failed (fixture)")


def test_E11_store_read_failure_degrades_prior_insights(project, tmp_path, caplog):
    store = _RaisingReadStore(tmp_path)
    report = run_orchestration(
        project_id=project, run_id="run-e11",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    configs = store.read_configs(project)
    assert configs[0]["prior_hunt_insights"] == []
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
        hypothesise_fn=_recording_hypothesise(seen),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert seen["surface"] == []  # degraded to the candidate set + KB alone (O5)
    assert "warning" in caplog.text.lower()


# --- E13: the dispatch node is removed (G12) ----------------------------------

def test_E13_no_dispatch_node_on_the_graph(project, tmp_path):
    """E13 - re-scoped by #167/G12: there is no dispatch node to fail on - the
    graph ENDs at the note phase. The pass still persists the configs and notes
    (the orchestrator's REASON stretch is the whole graph now)."""
    from polymerhus.attack.hunting.orchestrator_graph import build_hunting_graph

    store = HuntStore(tmp_path)
    report = run_orchestration(
        project_id=project, run_id="run-e13",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert len(store.read_configs(project)) == 1
    g = build_hunting_graph(
        hypothesise_node=lambda s: {}, ratify_node=lambda s: {}, note_node=lambda s: {})
    assert "dispatch" not in g.nodes
    assert "budget" not in g.nodes


# --- E14: the O9 budget stage is REMOVED (G7) ----------------------------------

def test_E14_budget_stage_is_removed(project, tmp_path):
    """E14 - re-scoped by #167/G7: no direction is ever cut (spending is the
    runtime plane's and the pod's) - both pairs ratify, the report has no
    budget-cut field."""
    store = HuntStore(tmp_path)
    report = run_orchestration(
        project_id=project, run_id="run-e14",
        candidates=[_candidate(SERVICE_A, FAULT_X), _candidate(SYSTEM_B, FAULT_Y)],
        tools=_tools(store, project),
        hypothesise_fn=lambda inp: GateDecision(
            directions=[_carry(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    assert report.pairs_processed == 2
    assert report.configs_ratified == 2
    assert not hasattr(report, "budget_cut")
    configs = store.read_configs(project)
    assert len(configs) == 2
    assert all(c["status"] == "ratified" for c in configs)
    assert len(store.read_notes(project)) == 2


# --- E15: cross-pass memory by config_key (the #202 downstream read) ----------

def test_E15_cross_run_memory_by_config_key(project, tmp_path):
    """Two passes over the same project: the DOWNSTREAM hunter records (the
    TestImplementationSpecs + the Q16 durable PodExport verdicts, keyed by the
    `config_key`) become the later pass's prior-hunt insights, read back out of
    the REAL per-project stores (#202 - the orchestrator's own prior configs +
    notes are no longer the insight source)."""
    import json  # noqa: PLC0415

    from polymerhus.attack.hunting.hunt_store import semantic_key  # noqa: PLC0415
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore  # noqa: PLC0415

    store = HuntStore(tmp_path)
    hunter = HunterMemoryStore(tmp_path)
    seen_first: dict = {}
    seen_second: dict = {}

    run_orchestration(
        project_id=project, run_id="run-e15a",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        hypothesise_fn=_recording_hypothesise(seen_first),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    assert len(store.read_configs(project)) == 1
    assert len(store.read_notes(project)) == 1

    # a downstream hunter authored a specified spec + the pod's durable export
    # record under the ratified config's config_key (the Q16 record)
    config_key = semantic_key(SERVICE_A, FAULT_X, "CSRF")
    hunter.write_spec(
        project, config_key, fault_keyword="f1", strategy_keyword="probe",
        spec={"fault_id": "F1", "spec_id": "S1", "status": "specified",
              "strategy": "probe", "fault_key": config_key, "spec_ref": "r",
              "mechanism": "m", "supports": [], "conflicts": [],
              "test": "submit a tokenless foreign-origin request"},
    )
    hunter.write_note(
        project, action="append", fault_key=config_key, note_name="pod-1",
        kind="freeform",
        body=json.dumps({"verdict": "unsuccessful",
                         "terminal_reason": "no-symptom-evidence", "clean": True}),
        provenance={"run_id": "run-e15a", "source": "pod-src", "verdict_stub": True},
    )

    run_orchestration(
        project_id=project, run_id="run-e15b",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=_tools(store, project),
        hypothesise_fn=_recording_hypothesise(seen_second),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    # The second pass's prior-hunt insights read the DOWNSTREAM hunter records
    # (spec + verdict) by config_key, shallow-projected.
    insights = store.read_configs(project)[-1]["prior_hunt_insights"]
    kinds = {i.get("kind") for i in insights}
    assert "prior_spec" in kinds and "prior_verdict" in kinds
    assert any(i.get("spec_id") == "S1" for i in insights)
    assert any(i.get("verdict") == "unsuccessful" for i in insights)


# --- E16 (#110): the graph engine's actor lives past a completed pass ----------

def test_E16_actor_lives_past_completion_and_reuses_the_run_thread(project, tmp_path):
    """#110 loop-restart property with the real store + real graph grounding: the
    registry-held orchestration actor is NOT reaped when a pass completes - a
    second pass on the same run_id reuses the SAME actor (the same
    hunting_orchestrator thread serves every pair AND every pass of the run).
    The default phase seams (None -> the actor) drive both passes."""
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
        tools=tools,
    )
    actor_after_first = _ORCHESTRATOR_ACTORS.get("run-e16")
    assert first.pairs_processed == 1
    assert actor_after_first is not None  # the completed pass did NOT reap it

    second = run_orchestration(
        project_id=project, run_id="run-e16",
        candidates=[_candidate(SERVICE_A, FAULT_X)],
        tools=tools,
    )
    actor_after_second = _ORCHESTRATOR_ACTORS.get("run-e16")
    assert second.pairs_processed == 1
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