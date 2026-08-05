"""E1-E2 e2e walkthroughs for the hunting agent (spec section 6.2).

Both predicates are CARRIED, blocked: their live edge is `none` - the
walkthrough substitutes nothing inside its edge, so the dispatch is the REAL
hunting agent, the KB is the REAL symptom-technique KB (operator-built
external), and the pod is the REAL one. That chain is #84 (pod); until it
lands there is no faithful way to drive the agent's EVALUATE step (importing
a stub pod would substitute the very component the walkthrough exists to
exercise, which the skill and the spec forbid). Each test therefore stands as
a skip-marked skeleton whose docstring carries the exact input fixture, path,
and terminal quantities from the spec; when #84 lands, the body wires the real
pod and reads the terminal quantities back out of the hunt store.

The ISOLATED e2e tier (spec section 6.3, `test_hunting_agent_isolated_e2e.py`)
walks the REAL agent through its REAL infrastructure seams - store files,
system-prompt skill, join-key derivation, tracing - with fixture pod/KB/LLM
turns; it is NOT blocked and runs against the live stack.

Bootstrap the walkthrough will need when unblocked (validate at setup, fail
loudly on a bad input before the path runs):
  - a live Neo4j project carrying the fixture unit, so the surface context is
    a real adapted index-card;
  - a live target the pod can probe (S5), reachable for the run;
  - the real symptom-technique KB (IA-8) answering the join key.

Source: docs/design/hunting-67-hunting-agent-spec.md section 6.2 (Q3-amended
for E2: the insufficient-evidence path now requires `no-symptom-evidence`
with blocked observations, never `technical-infeasibility`).
"""
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from tests.conftest import neo4j_target, wait_for

URI, AUTH = neo4j_target()

_BLOCKED = "carried, blocked on the pod (#84): the walkthrough's live edge " \
           "is none, so EVALUATE must be the real pod - a stub would " \
           "substitute the component under test."


def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for the hunting-agent walkthrough: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "ht83_wt_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


@pytest.mark.skip(reason=_BLOCKED)
def test_confirmed_hypothesis(session, project, tmp_path):
    """E1 - Confirmed hypothesis (grounds H1 and D67-02, Q3-amended).

    Entry seam: the `HuntConfig` dispatch (IA-2).
    Input: a fixture `HuntConfig` with the five parts set to stated values -
      prompt template (rationale "fault-x applies to slug-a because ...",
      assumptions [...], supposed payload vectors [...], L0 evidence [...]),
      adapted index-card (spine + one-hop DFS of unit "kind:slug:a"), target
      caveats [...], prior-hunt insights [], tool registry [].
    Live edge: none (self-contained; the pod is the real one).
    Path: agent queries the fixture KB on `(fault-x, slug-a-technological-
      axis)` -> authors the spec -> pod executes -> {successful,
      symptom-confirmed} -> hypothesis-`successful` -> S7 persistence.
    Terminal: the store holds the spec record with a full typed base, the
      hypothesis verdict `successful`, and the feedback record; exactly one
      pod execution recorded.
    Observed: the hunt record read back from the store shows spec_ref,
      hypothesis verdict, and the pod result ref.

    When unblocked: build the agent with the real KB and the real pod over a
    HuntStore(tmp_path), dispatch the fixture config, then assert
      len(store.list_records(run_id, "spec")) == 1
      len(store.list_records(run_id, "evidence")) == 1
      result.hypothesis_verdict == "successful"
    """


@pytest.mark.skip(reason=_BLOCKED)
def test_inline_back_edge_revision(session, project, tmp_path):
    """E2 - Inline back-edge re-evaluation (grounds H3 and D67-14,
    Q3-amended).

    Entry seam: the `HuntConfig` dispatch (IA-2).
    Input: a fixture `HuntConfig` for a pair whose pod runs land
      `{unsuccessful, no-symptom-evidence}` with blocked observations in the
      trail (Q3-amended: `technical-infeasibility` derives `unsuccessful`,
      never `insufficient-evidence`).
    Live edge: none (the pod and the targeted recon that resolves the gap are
      the real ones).
    Path: hypothesis-`insufficient-evidence` -> inline need surfaced via
      feedback -> orchestrator executes the recon -> meaningful insight
      routes back -> revised verdict.
    Terminal: the hypothesis verdict is revised (not `insufficient-evidence`);
      the evidence trail contains the recon result.
    Observed: the store's hunt record and the back-edge record on the
      `correlation_id`.

    When unblocked: drive the real dispatch with the real back-edge tool,
    then assert
      store.list_records(run_id, "back_edge") has exactly one record
      the evidence record carries the routed recon result
      the final hypothesis verdict is not "insufficient-evidence"
    """
