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
