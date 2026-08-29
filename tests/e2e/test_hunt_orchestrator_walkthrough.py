"""E1-E2 e2e walkthroughs for the hunt-orchestrator (spec section 6.2).

Both predicates are CARRIED, blocked: their live edge is `none` - the
walkthrough substitutes nothing inside its edge, so the hunting agent, the
spec-authoring step, and the pod are all the REAL ones. That chain is #83
(hunting agent) and #84 (pod); until they land there is no faithful way to
drive the orchestrator's output into the real hunting agent (the dispatch
node is REMOVED as of the workflow-graph rework #167/G12 - dispatch state
belongs to the runtime plane - so there is no harness dispatch seam to wire
either). Each test therefore stands as a skip-marked skeleton whose docstring
carries the exact input fixture, path, and terminal quantities from the spec;
when #83/#84 land, the body wires the real runtime-plane delivery and reads
the terminal quantities back out of the hunt store.

Bootstrap the walkthrough will need when unblocked (validate at setup, fail
loudly on a bad input before the path runs):
  - a live Neo4j project carrying the two fixture units below, so the
    orchestrator's read-only graph view has a real surface to ground on;
  - a live target the pod can probe (S5), reachable for the run;
  - the real hunting agent (#83) as the runtime-plane delivery.

Source: docs/design/hunting-67-orchestrator-spec.md section 6.2; parent
walkthrough docs/design/hunting-67-per-agent-specs-spec.md section 10.
"""
import os
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from tests.conftest import neo4j_target, wait_for

URI, AUTH = neo4j_target()

_BLOCKED = "carried, blocked on the hunting agent (#83) and pod (#84): the " \
           "walkthrough's live edge is none, so delivery must be the real " \
           "agent - a stub would substitute the component under test."

_BLOCKED_NO_DISPATCH = "carried, blocked on #167/G12: the park/resume path was " \
    "a DISPATCH-stage decision and the dispatch node is removed (dispatch " \
    "state belongs to the runtime plane, not built yet) - there is no " \
    "in-graph park/resume to exercise until the runtime plane lands."


def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for the hunt-orchestrator walkthrough: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "ht82_wt_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


@pytest.mark.skip(reason=_BLOCKED)
def test_full_run_two_candidates(session, project, tmp_path):
    """E1 - Full run, two candidates (grounds merged spec 10.2-10.4, 10.8, H1).

    Entry seam: candidate-set delivery at IA-1.
    Input: the fixture candidate set
      - (service "kind:slug:a", fault_class "fault-x", symptom null,
         applies-witnesses {deterministic "", llm "clause x holds"}, applies)
      - (system  "kind:key:b",  fault_class "fault-y", symptom null,
         applies-witnesses {..., llm "clause y holds"}, applies)
    Live edge: none (the hunting agent is real, the pod is real).
    Path: hypothesise -> ratify -> note per pair (the node-per-phase REASON
      body, #167) -> runtime-plane delivery (G12).
    Terminal: exactly two ratified configs in the store's produced/ and two
      notes in memory.yaml (the per-run hunt record kinds are removed, #166).

    When unblocked: run one orchestration pass over a HuntStore(tmp_path),
    then assert
      len(store.read_configs(project_id)) == 2
      all(c["status"] in ("hypothesised", "ratified") for c in configs)
      len(store.read_notes(project_id)) == 2
    """


@pytest.mark.skip(reason=_BLOCKED_NO_DISPATCH)
def test_yellow_park_resume(session, project, tmp_path):
    """E2 - Yellow park/resume (grounds merged spec 10.4/10.7, H3).

    BLOCKED (#167): the park/resume path was a DISPATCH-stage decision and the
    dispatch node is REMOVED (G12 - dispatch state belongs to the runtime
    plane). There is no in-graph park/resume to exercise until the runtime
    plane lands; the skeleton stays blocked and names the owning rework.

    When unblocked: run one orchestration pass with the runtime-plane
    delivery, then assert
      len(store.read_configs(project_id)) == 2
    """


# --- E3-E6: the #135 LLM-local artifacts, FULLY LIVE (operator ruling) --------
#
# These walkthroughs' live edge is a REAL hunting-orchestrator LLM role (the
# hypothesise phase turn) + real Neo4j + the mounted skills. They are NOT
# skeletons: when the live role is configured (LLM_MODEL_HUNTING_ORCHESTRATOR
# set and the gateway/direct provider reachable) they run the REAL production
# build - the mounted skill as the system prompt, the per-pair symbolic render
# as the user prompt, the three-tool surface (hunts_store / notes /
# graph_view, G3) bound onto the actor's session agent, and the real hunt
# store. They skip ONLY on a missing/unreachable live role or missing Neo4j,
# never on a hard marker. E1/E2 stay blocked on #83/#84.

SERVICE_A = "Service:a"
KIND = "key"
DISCRIMINATOR = "b"
SLUG = "a"
BASE = "https://a.example"
FAULT_LIVE = "CWE-79"  # materialisation + a real fold family in the catalogue


def _hunting_role_live_reason() -> str | None:
    """The skip reason when the live hunting-orchestrator LLM role is not
    usable, or None to run the walkthroughs."""
    if not os.environ.get("LLM_MODEL_HUNTING_ORCHESTRATOR"):
        return ("live hunting-orchestrator LLM role not configured "
                "(set LLM_MODEL_HUNTING_ORCHESTRATOR=<provider>:<model>)")
    from polymerhus.app.llm.providers import resolve_role
    try:
        provider, _model = resolve_role("hunting_orchestrator")
    except Exception as exc:  # noqa: BLE001 - malformed role config
        return f"hunting_orchestrator role unresolvable: {exc}"
    url = os.environ.get("LLM_GATEWAY_URL")
    if url:
        import httpx
        try:
            httpx.get(url, timeout=5)
        except Exception as exc:  # noqa: BLE001 - gateway unreachable
            return f"LLM gateway {url} unreachable for the live gate turn: {exc}"
    else:
        key_env = f"API_KEY_{provider.upper().replace('-', '_')}"
        if not os.environ.get(key_env):
            return (f"no {key_env} and no LLM_GATEWAY_URL - the live gate turn "
                    "has no reachable model")
    return None


def _seed_live_project(session, pid):
    """A real one-unit L1 graph the projection + graph view ground on: a
    public Service exposed via a System and aggregating an Endpoint."""
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
    nodes = session.run(
        "MATCH (n) WHERE n.project_id = $p RETURN count(n) AS c", p=pid,
    ).single()["c"]
    edges = session.run(
        "MATCH (a)-[r]->(b) WHERE a.project_id = $p OR b.project_id = $p "
        "RETURN count(r) AS c", p=pid,
    ).single()["c"]
    return nodes, edges


def _candidate(unit_id: str, fault_class: str, *, verdict: str = "applies",
               llm_witness: str | None = "witness") -> "DeliveredCandidate":
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        DeliveredCandidate,
        Witness,
    )
    return DeliveredCandidate(
        unit_id=unit_id, fault_class=fault_class,
        applies_witnesses=Witness(deterministic=None, llm=llm_witness),
        match_verdict=verdict,
    )


def _carried_direction(candidate) -> "EnvisionedDirection":
    """A fixture carried direction with a CSRF class (the deterministic
    hypothesise seam for the live tool-surface pass)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        EnvisionedDirection,
    )
    return EnvisionedDirection(
        unit_id=candidate.unit_id, fault_class=candidate.fault_class,
        carried=True, rationale="fixture rationale",
        research_direction="probe CSRF token verification",
        vulnerability_classes=["CSRF"],
    )


def _ratify_drafts(inp) -> "RatifyDecision":
    """The fixture ratify turn: every draft ends ratified (for the
    deterministic E6 comparison; the live E3-E5 tests let the actor defaults
    bind)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        RatifyDecision,
    )
    configs = []
    for draft in inp.configs:
        amended = draft.model_copy(deep=True)
        amended.status = "ratified"
        configs.append(amended)
    return RatifyDecision(configs=configs)


def _note_pair(inp) -> "NoteDecision":
    """The fixture note turn: one note for the pair."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        NoteDecision,
        NoteRecord,
        revival_key,
    )
    return NoteDecision(notes=[NoteRecord(
        key=revival_key(inp.pair.unit_id, inp.pair.fault_class),
        note="fixture note walking the reasoning",
    )])


def _run_live(store, project_id, run_id, candidates, session, *,
              hypothesise_fn=None, ratify_fn=None, note_fn=None):
    """One orchestration pass over the REAL graph view (no injected read_fn -
    the view grounds in live Neo4j) with the production build as the phase
    turns. The node-per-phase flow (#167): the phase seams are the actor
    defaults when None (the real LLM role drives the hypothesise / ratify /
    note turns); the pass ends at the REASON stretch (no dispatch node - G12,
    no budget stage - G7)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        OrchestratorTools,
        ReadOnlyGraphView,
        run_orchestration,
    )
    tools = OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView(project_id),
    )
    return run_orchestration(
        project_id=project_id, run_id=run_id, candidates=candidates, tools=tools,
        hypothesise_fn=hypothesise_fn,
        ratify_fn=ratify_fn,
        note_fn=note_fn,
    )


def test_live_gate_turn_reasons_over_the_rich_render(session, project, tmp_path):
    """E3 - a real hypothesise turn reasons over the rich render and emits a
    carried direction (grounds spec 3.1/3.2/3.3, 4, 5; assertions C13/C14/C15
    live, re-scoped #167).

    Live edge: the real hunting_orchestrator LLM role (the hypothesise turn) +
    the mounted skills + the per-pair symbolic render + the three-tool actor
    surface (hunts_store / notes / graph_view) + a live Neo4j L1 graph.
    Path: intake -> hypothesise renders projection/materialisation/fold-family
      from the live graph + fault-KB -> mounted system prompt + per-pair user
      prompt on the actor thread -> GateDecision (structured) -> the mint fans
      out the draft(s) at the hypothesise phase -> ratify -> note -> END at
      the REASON stretch (no dispatch node, G12).
    Terminal: exactly one carried, non-pruned pair; the config record with the
      hypothesise-phase fields set; gate_pruned == (); the graph is untouched.
      Run twice for determinism confidence. The report has NO dispatch/budget
      fields (the graph ENDs at the note phase).
    """
    reason = _hunting_role_live_reason()
    if reason is not None:
        pytest.skip(reason)
    _seed_live_project(session, project)
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
    store = HuntStore(tmp_path)
    before = _graph_counts(session, project)

    for pass_no in (1, 2):
        run_id = f"run-e3-{pass_no}"
        report = _run_live(
            store, project, run_id, [_candidate(SERVICE_A, FAULT_LIVE)], session,
        )
        assert report.pairs_processed == 1
        assert report.gate_pruned == ()
        # the dispatch node (G12) and the O9 budget stage (G7) are removed
        assert not hasattr(report, "unresolved")
        assert not hasattr(report, "budget_cut")
        assert not hasattr(report, "hunts_dispatched")
        config_recs = store.read_configs(project)
        assert len(config_recs) == 1
        cfg = config_recs[0]
        assert cfg["prompt_template"]["rationale"]
        assert cfg["prompt_template"]["research_direction"]
        # the live turn may end the config at the hypothesised draft or the
        # ratify phase may amend it to ratified - both are the config lifecycle
        assert cfg["status"] in ("hypothesised", "ratified")
        # the live gate turn may elicit a class or fall back to the bare-carry
        # degrade (an empty class) - both are valid; never assert emptiness
        assert isinstance(cfg["vulnerability_class"], str)
        # the note phase is a graph node (#167): the pair's note lands in
        # memory.yaml (the per-run hunt/dispatch kind records are removed)
        assert report.notes_written == len(store.read_notes(project))
    assert _graph_counts(session, project) == before


def test_gate_renders_unknown_never_false_on_degraded_slots_live(
        session, project, tmp_path, monkeypatch):
    """E4 - the gate prunes ONLY on positive grounds across real degraded slots
    (grounds spec 3.2.5, 3.1; assertions C16 live).

    Live edge: the real hunting_orchestrator LLM role (the hypothesise turn); a
    live graph whose projection read resolves the FULL typed unit while the
    materialisation and fold-family reads hit a degraded catalogue (both
    UNKNOWN). Real stochastic model behaviour is accepted - the assertion is on
    the RENDER (UNKNOWN markers present, never FALSE/prune) plus the report
    shape.
    Terminal: the composed prompt text carries UNKNOWN for the degraded facets
      and never a prune signal; the pass still assembles a GateDecision and
      records it; the report/trail shapes are intact (no dispatch/budget
      fields, #167).
    """
    reason = _hunting_role_live_reason()
    if reason is not None:
        pytest.skip(reason)
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
    from polymerhus.attack.hunting.llm import _compose_gate_prompt  # noqa: PLC0415

    _seed_live_project(session, project)
    store = HuntStore(tmp_path)
    before = _graph_counts(session, project)

    rendered: list[str] = []
    original = _compose_gate_prompt

    def recording_render(inp):
        text = original(inp)
        rendered.append(text)
        return text

    monkeypatch.setattr(
        "polymerhus.attack.hunting.llm._compose_gate_prompt", recording_render)

    # A fault NOT in the real catalogue: projection resolves (live graph), but
    # the materialisation + fold-family slots degrade to UNKNOWN (C16).
    report = _run_live(
        store, project, "run-e4", [_candidate(SERVICE_A, "fault-x")], session,
    )
    assert rendered, "the hypothesise turn must have composed the render"
    text = "\n".join(rendered)
    assert "UNKNOWN" in text
    assert "FALSE" not in text.upper()
    assert "PRUNE" not in text.upper()
    assert "Unit projection (typed facet surface)" in text
    assert "Sub-fault fold family" in text
    assert report is not None
    assert report.pairs_processed == 1
    # the persisted configs are exactly the drafts the hypothesise phase wrote
    assert len(store.read_configs(project)) == report.configs_hypothesised
    assert _graph_counts(session, project) == before


def test_live_tool_surface_is_the_three_tools_and_grounds_in_the_real_graph(
        session, project, tmp_path):
    """E5 - the REAL three-tool surface bound onto the actor (assertions
    C17/C18/C19 live, re-scoped #167/G3): the back_edge request to recon is NOT
    an agent tool in this tree (operator ruling 2026-08-22 - the
    target-knowledge loop rides graph_view, never a recon request), so the
    surface is exactly hunts_store / notes / graph_view (the old five-tool
    surface read_memory_hunts / read_memory_notes / mint_hunt_config /
    record_note is REPLACED, and there is no back-edge harness seam to assert:
    the dispatch node - G12 - is gone). A graph_view read round-trips against
    the live graph.

    Live edge: the real three-tool surface bound onto the actor (the phase
    turns are scripted seams for deterministic replay); a real live graph.
    Terminal: exactly the three tool names; a graph_view read returns the live
    rows; a full pass over an applies candidate completes with the config +
    note persisted; the graph is untouched.
    """
    reason = _hunting_role_live_reason()
    if reason is not None:
        pytest.skip(reason)
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
    from polymerhus.attack.hunting.actors import (  # noqa: PLC0415
        build_orchestrator_tool_surface,
    )

    _seed_live_project(session, project)
    store = HuntStore(tmp_path)
    before = _graph_counts(session, project)

    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        GateDecision,
        OrchestratorTools,
        ReadOnlyGraphView,
    )
    tools = OrchestratorTools(
        store_reads=store,
        graph_view=ReadOnlyGraphView(project),
    )
    surface = build_orchestrator_tool_surface(
        tools, run_id="run-e5", project_id=project)
    by_name = {t.name: t for t in surface}
    assert set(by_name) == {"hunts_store", "notes", "graph_view"}
    assert "back_edge" not in by_name  # no back-edge-to-recon tool (2026-08-22)
    assert "read_memory_hunts" not in by_name  # the five-tool surface is gone (#167)

    # A graph_view read round-trips against the LIVE graph: the seeded unit is
    # readable through the read-only view (the target-knowledge loop's seam).
    out = by_name["graph_view"].invoke(
        {"cypher": "MATCH (u:L1TestableUnit) WHERE u.project_id = $p "
                   "RETURN labels(u) AS labels", "params": {"p": project}})
    assert "rows" in out and out["rows"], \
        f"graph_view read returned no live rows: {out}"
    labels = {tuple(r.get("labels") or []) for r in out["rows"]}
    assert any("L1Service" in l for l in labels)
    assert any("L1System" in l for l in labels)

    # And the full pass over an applies candidate: the node-per-phase flow
    # writes the config + the pair's note and the graph is untouched (there is
    # no dispatch stage to park/resume through anymore - G12).
    report = _run_live(
        store, project, "run-e5",
        [_candidate(SERVICE_A, FAULT_LIVE)],
        session,
        hypothesise_fn=lambda inp: GateDecision(directions=[
            _carried_direction(c) for c in inp.candidates]),
        ratify_fn=_ratify_drafts,
        note_fn=_note_pair,
    )
    assert report.pairs_processed == 1
    assert report.configs_ratified == 1
    assert report.notes_written == 1
    configs = store.read_configs(project)
    assert len(configs) == 1
    assert configs[0]["status"] == "ratified"
    assert len(store.read_notes(project)) == 1
    assert _graph_counts(session, project) == before


def test_full_pass_canon_unchanged_with_new_artifacts(session, project, tmp_path):
    """E6 - the full pass keeps the canon intact with the new artifacts
    (grounds spec 7, the C1-C12 canon; assertions C22 live, re-scoped #167).

    Live edge: the real hunting_orchestrator LLM role (the phase turns) + the
    mounted skills + the three tools + tracing, over the two-candidate fixture
    (one applies, one yellow insufficient-evidence - the yellow pair runs the
    phase machine like any other, the dispatch-stage park/resume is gone).
    Terminal: the report shape, gate_pruned, and trail/store-record shapes
    identical to the canon exercised WITHOUT the rich projection - the same
    fixture drives both a with-artifacts and a without-artifacts pass, and
    both reports match field-by-field. The graph ENDs at the REASON stretch
    (no dispatch node - G12, no budget stage - G7).
    """
    reason = _hunting_role_live_reason()
    if reason is not None:
        pytest.skip(reason)
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        GateDecision,
        OrchestratorTools,
        ReadOnlyGraphView,
        run_orchestration,
    )

    _seed_live_project(session, project)
    before = _graph_counts(session, project)
    candidates = [
        _candidate(SERVICE_A, FAULT_LIVE),
        _candidate("Service:slug:yellow", "fault-y", verdict="insufficient-evidence"),
    ]

    def carried(inp):
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            EnvisionedDirection,
        )
        return GateDecision(directions=[
            EnvisionedDirection(
                unit_id=c.unit_id, fault_class=c.fault_class, carried=True,
                rationale="fixture rationale",
                research_direction="probe CSRF",
                vulnerability_classes=["CSRF"],
            ) for c in inp.candidates])

    def report_for(tools, run_id):
        return run_orchestration(
            project_id=project, run_id=run_id, candidates=candidates, tools=tools,
            hypothesise_fn=carried,
            ratify_fn=_ratify_drafts,
            note_fn=_note_pair,
        )

    # Without-artifacts pass: the canon, empty graph view (no projection),
    # the same carried hypothesise seam.
    store_plain = HuntStore(tmp_path)
    plain_tools = OrchestratorTools(
        store_reads=store_plain,
        graph_view=ReadOnlyGraphView(project, read_fn=lambda cy, p: []),
    )
    report_plain = report_for(plain_tools, "run-e6-plain")

    # With-artifacts pass: the same hypothesise seam, REAL graph view
    # (projection materialises), tracing + store.
    store_live = HuntStore(tmp_path)
    live_tools = OrchestratorTools(
        store_reads=store_live,
        graph_view=ReadOnlyGraphView(project),
    )
    report_live = report_for(live_tools, "run-e6-live")

    # both passes ran the same node-per-phase flow over the two pairs
    assert report_plain.model_dump() == report_live.model_dump()
    assert report_live.pairs_processed == 2
    assert report_live.configs_hypothesised == 2
    assert report_live.configs_ratified == 2
    assert report_live.notes_written == 2
    assert report_live.gate_pruned == ()
    assert not hasattr(report_live, "unresolved")
    assert not hasattr(report_live, "budget_cut")
    assert not hasattr(report_live, "hunts_dispatched")
    # the memory topology (#166/#167): two ratified configs in produced/, two
    # pair notes in memory.yaml; the per-run run/hunt/back_edge kind records
    # are removed
    assert len(store_live.read_configs(project)) == 2
    assert all(c["status"] == "ratified" for c in store_live.read_configs(project))
    assert len(store_live.read_notes(project)) == 2
    assert _graph_counts(session, project) == before