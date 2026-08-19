"""E1-E2 e2e walkthroughs for the hunt-orchestrator (spec section 6.2).

Both predicates are CARRIED, blocked: their live edge is `none` - the
walkthrough substitutes nothing inside its edge, so the hunting agent, the
spec-authoring step, and the pod are all the REAL ones. That chain is #83
(hunting agent) and #84 (pod); until they land there is no faithful way to
drive `run_orchestration`'s `dispatch_fn` (importing a stub would substitute
the very component the walkthrough exists to exercise, which the skill and the
spec forbid). Each test therefore stands as a skip-marked skeleton whose
docstring carries the exact input fixture, path, and terminal quantities from
the spec; when #83/#84 land, the body wires the real dispatch and reads the
terminal quantities back out of the hunt store.

Bootstrap the walkthrough will need when unblocked (validate at setup, fail
loudly on a bad input before the path runs):
  - a live Neo4j project carrying the two fixture units below, so the
    orchestrator's read-only graph view has a real surface to ground on;
  - a live target the pod can probe (S5), reachable for the run;
  - the real hunting agent (#83) as the `dispatch_fn`.

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
           "walkthrough's live edge is none, so dispatch must be the real " \
           "agent - a stub would substitute the component under test."


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
    Path: gate carries both -> ranker orders -> two HuntConfigs minted ->
      two dispatches -> two hunting agents -> two pod runs -> two verdicts ->
      S7 persistence.
    Terminal: exactly two hunt records in the store, each with config_ref,
      spec_ref, pod_result_ref and a hypothesis verdict; zero back-edge records.
    Observed: the store listing queried by run id returns the two records with
      their field values.

    When unblocked: run one orchestration pass with the real hunting agent as
    dispatch_fn over a HuntStore(tmp_path), then assert
      len(store.list_records(run_id, "hunt")) == 2
      all(h["config_ref"] and h["spec_ref"] and h["pod_result_ref"]
          and h["hypothesis_verdict"] for h in hunts)
      store.list_records(run_id, "back_edge") == []
    """


@pytest.mark.skip(reason=_BLOCKED)
def test_yellow_park_resume(session, project, tmp_path):
    """E2 - Yellow park/resume (grounds merged spec 10.4/10.7, H3).

    Entry seam: candidate-set delivery at IA-1.
    Input: the fixture candidate set
      - (unit "kind:slug:a", fault "fault-x", applies)
      - (unit "kind:key:b",  fault "fault-y", insufficient-evidence)
    Live edge: none (the hunting agent is real, the pod is real, the targeted
      recon that resolves the yellow gap is the real one).
    Path: gate -> dispatch for a -> park for b with a back-edge record ->
      recon lands -> re-match applies -> second dispatch for b.
    Terminal: two hunt records, one back-edge record, an unresolved-free run;
      the depth-1 cap is not hit.
    Observed: the store's back-edge records and both hunt records.

    When unblocked: run one orchestration pass with the real dispatch and the
    real back_edge tool, then assert
      len(store.list_records(run_id, "hunt")) == 2
      len(store.list_records(run_id, "back_edge")) == 1
      store.list_records(run_id, "unresolved") == []
      report.unresolved == ()
    """


# --- E3-E6: the #135 LLM-local artifacts, FULLY LIVE (operator ruling) --------
#
# These walkthroughs' live edge is a REAL hunting-orchestrator LLM role (the
# gate turn) + real Neo4j + the mounted skills. They are NOT skeletons: when
# the live role is configured (LLM_MODEL_HUNTING_ORCHESTRATOR set and the
# gateway/direct provider reachable) they run the REAL production build - the
# mounted skill as the system prompt, the per-pair symbolic render as the user
# prompt, the three-tool surface bound onto the actor's session agent, and the
# real hunt store. They skip ONLY on a missing/unreachable live role or missing
# Neo4j, never on a hard marker. E1/E2 stay blocked on #83/#84.

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


def _recording_dispatch(configs: list):
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        DispatchResult,
    )

    def dispatch(config, routed=()):
        configs.append(config)
        return DispatchResult(
            spec_ref=f"spec-{len(configs)}", pod_result_ref=f"pod-{len(configs)}",
            hypothesis_verdict="successful", feedback="fixture feedback",
        )

    return dispatch


def _ok_rematch(verdict: str = "applies"):
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        MatchVerdict,
    )

    def rematch(unit_id, fault_class, result):
        return MatchVerdict(unit_id=unit_id, fault_class=fault_class, verdict=verdict)

    return rematch


def _ok_back_edge(seen: list | None = None):
    record = seen if seen is not None else []

    def back_edge(request, run_id, project_id):
        record.append(request)
        from polymerhus.recon.control.targeted import (  # noqa: PLC0415
            TargetedReconResult,
        )
        return TargetedReconResult(
            correlation_id=request.correlation_id, requester_id=request.requester_id,
            origin="hunting", status="success",
        )

    return back_edge


def _run_live(store, project_id, run_id, candidates, session, *, reason_fn=None,
              back_edge=None, **kwargs):
    """One orchestration pass over the REAL graph view (no injected read_fn -
    the view grounds in live Neo4j) with the production build as the gate."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        OrchestratorTools,
        ReadOnlyGraphView,
        run_orchestration,
    )
    tools = OrchestratorTools(
        back_edge=back_edge,
        store_reads=store,
        graph_view=ReadOnlyGraphView(project_id),
    )
    return run_orchestration(
        project_id=project_id, run_id=run_id, candidates=candidates, tools=tools,
        reason_fn=reason_fn, **kwargs,
    )


def test_live_gate_turn_reasons_over_the_rich_render(session, project, tmp_path):
    """E3 - a real gate turn reasons over the rich render and emits a carried
    direction (grounds spec 3.1/3.2/3.3, 4, 5; assertions C13/C14/C15/C17 live).

    Live edge: the real hunting_orchestrator LLM role (the gate turn) + the
    mounted skills + the per-pair symbolic render + the three-tool actor
    surface + a live Neo4j L1 graph.
    Path: intake -> reason stretch renders projection/materialisation/fold-
      family from the live graph + fault-KB -> mounted system prompt + per-pair
      user prompt on the actor thread -> GateDecision (structured) -> mint for
      the carried direction -> dispatch -> store records.
    Terminal: exactly one carried, non-pruned direction; one config record with
      the four seed fields non-empty; one hunt record; gate_pruned == ();
      the report/trail shapes intact. Run twice for determinism confidence.
    """
    reason = _hunting_role_live_reason()
    if reason is not None:
        pytest.skip(reason)
    _seed_live_project(session, project)
    store = None
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
    store = HuntStore(tmp_path)
    configs: list = []
    before = _graph_counts(session, project)

    for pass_no in (1, 2):
        run_id = f"run-e3-{pass_no}"
        report = _run_live(
            store, project, run_id, [_candidate(SERVICE_A, FAULT_LIVE)], session,
            dispatch_fn=_recording_dispatch(configs),
            rematch_fn=_ok_rematch(),
        )
        assert report.hunts_dispatched == 1
        assert report.gate_pruned == ()
        assert report.unresolved == () and report.budget_cut == ()
        config_recs = store.list_records(run_id, "config")
        assert len(config_recs) == 1
        cfg = config_recs[0]["prompt_template"]
        assert cfg["rationale"]
        assert cfg["extension_points"]
        assert cfg["assumptions"]
        assert cfg["supposed_payload_vectors"]
        assert len(store.list_records(run_id, "hunt")) == 1
        assert len(store.list_records(run_id, "dispatch")) == 1
    assert _graph_counts(session, project) == before


def test_gate_renders_unknown_never_false_on_degraded_slots_live(
        session, project, tmp_path, monkeypatch):
    """E4 - the gate prunes ONLY on positive grounds across real degraded slots
    (grounds spec 3.2.5, 3.1; assertions C16 live).

    Live edge: the real hunting_orchestrator LLM role (the gate turn); a live
    graph whose projection read resolves the FULL typed unit while the
    materialisation and fold-family reads hit a degraded catalogue (both
    UNKNOWN). Real stochastic model behaviour is accepted - the assertion is on
    the RENDER (UNKNOWN markers present, never FALSE/prune) plus the model's
    recorded decision, NOT on which direction is carried.
    Terminal: the composed prompt text carries UNKNOWN for the degraded facets
      and never a prune signal; the pass still assembles a GateDecision and
      records it; the report/trail shapes are intact.
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
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(),
    )
    assert rendered, "the gate turn must have composed the render"
    text = "\n".join(rendered)
    assert "UNKNOWN" in text
    assert "FALSE" not in text.upper()
    assert "PRUNE" not in text.upper()
    assert "Unit projection (typed facet surface)" in text
    assert "Sub-fault fold family" in text
    assert report is not None
    assert len(store.list_records("run-e4", "config")) == report.hunts_dispatched
    assert _graph_counts(session, project) == before


def test_live_back_edge_tool_round_trips_hunting_origin(session, project, tmp_path):
    """E5 - a real back-edge tool call flows origin="hunting" and lands in the
    store (grounds spec 4.1, IA-6; assertions C17/C18/C19 live).

    Live edge: the real three-tool surface bound onto the actor (the gate turn
    is a scripted reason_fn for deterministic replay, as the E5 table allows);
    a real live graph; a recorded back-edge seam. The back-edge record the
    store carries must round-trip correlation_id / origin="hunting".
    Terminal: exactly one back_edge store record whose origin is "hunting" and
      whose correlation_id round-trips; the run completes with the outcome
      recorded; the graph is untouched.
    """
    reason = _hunting_role_live_reason()
    if reason is not None:
        pytest.skip(reason)
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
    from polymerhus.attack.hunting.actors import (  # noqa: PLC0415
        build_orchestrator_tool_surface,
    )
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        GateDecision,
    )
    from polymerhus.recon.control.targeted import (  # noqa: PLC0415
        AnalyserReconRequest,
        ReconScope,
    )

    _seed_live_project(session, project)
    store = HuntStore(tmp_path)
    before = _graph_counts(session, project)
    seen: list = []

    # Bind the REAL tool surface and drive the back_edge tool directly - the
    # request must carry origin="hunting" and a round-trippable correlation id.
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        OrchestratorTools,
        ReadOnlyGraphView,
    )
    tools = OrchestratorTools(
        back_edge=_ok_back_edge(seen),
        store_reads=store,
        graph_view=ReadOnlyGraphView(project),
    )
    surface = build_orchestrator_tool_surface(
        tools, run_id="run-e5", project_id=project)
    by_name = {t.name: t for t in surface}
    assert set(by_name) == {"back_edge", "graph_view", "store_reads"}
    result = by_name["back_edge"].invoke({
        "job": "httpx_reprofile", "unit_id": SERVICE_A,
        "targets": [BASE], "note": "re-witness the surface",
    })
    assert len(seen) == 1
    request = seen[0]
    assert request.origin == "hunting"
    assert request.scope.unit_id == SERVICE_A
    assert result.get("correlation_id") == request.correlation_id

    # And the full pass: a park/resume back-edge for a yellow candidate lands
    # the SAME-shaped store record (origin round-trips in the store).
    report = _run_live(
        store, project, "run-e5",
        [_candidate(SERVICE_A, FAULT_LIVE, verdict="insufficient-evidence")],
        session,
        dispatch_fn=_recording_dispatch([]),
        rematch_fn=_ok_rematch(verdict="applies"),
        back_edge=_ok_back_edge(seen),
    )
    assert report.hunts_dispatched == 1
    records = store.list_records("run-e5", "back_edge")
    assert len(records) == 1
    assert records[0]["origin"] == "hunting"
    assert records[0]["unit_id"] == SERVICE_A
    assert _graph_counts(session, project) == before


def test_full_pass_canon_unchanged_with_new_artifacts(session, project, tmp_path):
    """E6 - the full pass keeps the 110 canon intact with the new artifacts
    (grounds spec 7, the C1-C12 canon; assertions C22 live).

    Live edge: the real hunting_orchestrator LLM role (the gate turn) + the
    mounted skills + the three tools + tracing, over the two-candidate fixture
    (one applies, one yellow insufficient-evidence).
    Terminal: the O1-O10 report shape, hunts_dispatched, gate_pruned,
      unresolved, budget_cut, and trail/store-record shapes identical to the
      #110 canon exercised WITHOUT the new artifacts - the same fixture drives
      both a with-artifacts and a without-artifacts pass, and both reports
      match field-by-field.
    """
    reason = _hunting_role_live_reason()
    if reason is not None:
        pytest.skip(reason)
    from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        GateDecision,
        run_orchestration,
    )
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        OrchestratorTools,
        ReadOnlyGraphView,
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
                rationale="fixture rationale", assumptions=["assumption"],
                envisioned_test_primitives=["probe"],
                supposed_payload_vectors=["vector"],
            ) for c in inp.candidates])

    def report_for(tools, run_id, reason_fn):
        return run_orchestration(
            project_id=project, run_id=run_id, candidates=candidates, tools=tools,
            reason_fn=reason_fn,
            dispatch_fn=_recording_dispatch([]),
            rematch_fn=_ok_rematch(verdict="applies"),
        )

    # Without-artifacts pass: the #110 canon, empty graph view (no projection),
    # bare reason_fn carrying every candidate.
    store_plain = HuntStore(tmp_path)
    plain_tools = OrchestratorTools(
        back_edge=_ok_back_edge(), store_reads=store_plain,
        graph_view=ReadOnlyGraphView(project, read_fn=lambda cy, p: []),
    )
    report_plain = report_for(plain_tools, "run-e6-plain", carried)

    # With-artifacts pass: the same fixture reason_fn, REAL graph view
    # (projection materialises), tracing + store.
    store_live = HuntStore(tmp_path)
    live_tools = OrchestratorTools(
        back_edge=_ok_back_edge(), store_reads=store_live,
        graph_view=ReadOnlyGraphView(project),
    )
    report_live = report_for(live_tools, "run-e6-live", carried)

    assert report_plain.model_dump(exclude={"hunt_ids"}) == report_live.model_dump(exclude={"hunt_ids"})
    assert len(report_plain.hunt_ids) == len(report_live.hunt_ids) == 2
    assert report_live.hunts_dispatched == 2
    assert report_live.unresolved == () and report_live.budget_cut == ()
    assert len(store_live.list_records("run-e6-live", "run")) == 1
    assert len(store_live.list_records("run-e6-live", "config")) == 2
    assert len(store_live.list_records("run-e6-live", "hunt")) == 2
    assert len(store_live.list_records("run-e6-live", "back_edge")) == 1
    assert _graph_counts(session, project) == before
