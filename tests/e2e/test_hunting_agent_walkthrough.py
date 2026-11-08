"""E1-E2 e2e walkthroughs for the hunting agent (spec section 6.2).

Both predicates are CARRIED, blocked: their live edge is `none` - the
walkthrough substitutes nothing inside its edge, so the dispatch is the REAL
hunting agent, the KB is the REAL symptom-technique KB (operator-built
external), and the pod is the REAL one. That chain is #84 (pod); until it
lands there is no faithful way to drive the agent's pass (importing a stub pod
would substitute the very component the walkthrough exists to exercise, which
the skill and the spec forbid). Each test therefore stands as a skip-marked
skeleton whose docstring carries the exact input fixture, path, and terminal
quantities from the spec; when #84 lands, the body wires the real pod and
reads the terminal quantities back off the spec set and the pod-export
envelope (the durable `spec`/`evidence` store records are removed, #166 - the
agent's durable trail is #164's own memory, G5).

T10b (#397) translated the carried skeleton's vocabulary to the threat and
spec-set contract: a produced threat file is the dispatch record, the hunter's
terminal spec status is `ratified`, and the retired hypothesis-verdict
derivation is not a live contract.

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

Source: docs/design/hunting-67-hunting-agent-spec.md section 6.2 (Q3-amended;
the E2 inline back-edge is RETIRED with the verdict-processing workflow, so
the E2 skeleton records the retired behaviour).
"""
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from tests.conftest import neo4j_target, wait_for

URI, AUTH = neo4j_target()

_BLOCKED = "carried, blocked on the pod (#84): the walkthrough's live edge " \
           "is none, so the execution must be the real pod - a stub would " \
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

    Entry seam: a produced threat-model threat file (S2 8.4) dispatched as the
    hunter's threat payload.
    Input: a fixture unit threat model whose threat carries the unit/fault locus,
    the threat rationale, and the skill-procedure excerpt; the hunter authors the
    spec set from it.
    Live edge: none (self-contained; the pod is the real one).
    Path: the hunter's pass sequence grounds the spec, writes the `hypothesised`
    set, promotes the surviving spec to `ratified`, then the pod executes it
    and returns a `successful` / `symptom-confirmed` PodExport.
    Terminal: exactly one `ratified` spec and one pod-export envelope; the
    hunter's durable trail is its own spec set and notes (the pre-#164
    spec/evidence store records were removed, #166).
    Observed: the pod envelope's verdict and terminal reason on the spec's
    dispatch record.

    When unblocked: build the hunter with the real KB and the real pod over a
    `HunterMemoryStore(tmp_path)`, dispatch the fixture threat, then assert the
    pod envelope carries `verdict == "successful"` and
    `terminal_reason == "symptom-confirmed"`.
    """


@pytest.mark.skip(reason=_BLOCKED)
def test_inline_back_edge_revision(session, project, tmp_path):
    """E2 - Inline back-edge re-evaluation (grounds H3 and D67-14,
    Q3-amended).

    Historical skeleton (superseded by the unit threat model rewrite, T5/T10):
    the inline back-edge and the hypothesis-verdict derivation are RETIRED, so
    this predicate no longer describes a live contract. It is kept as a
    collecting skeleton so the carried walkthrough is visible, not as a live
    assertion.
    Input: a fixture unit threat model whose pod run lands
    `{unsuccessful, no-symptom-evidence}` with blocked observations in the
    trail.
    Path (retired): hypothesis-`insufficient-evidence` -> inline recon -> a
    revised verdict.
    Terminal (current): the failed spec stays `dropped` and the run's trail
    records the pod evidence; there is no revised hypothesis verdict.
    """
