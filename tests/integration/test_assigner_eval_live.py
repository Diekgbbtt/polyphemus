"""The Assigner eval harness against a LIVE graph (AMV-9).

`assignment_metrics` and `bar_sweep` are pure and live in the unit tier. What cannot
be proved there is that `read_assignment` produces the census those functions consume
- it is Cypher, and Cypher is only correct against a real Neo4j. These pin the two
failure modes a mocked test would have missed: a query that returns no row at all for
a project in a legitimate state, and a count that collapses when a co-counted label is
empty.
"""
import uuid

import pytest

from polymerhus.analysis.evaluation import assignment_metrics, read_assignment
from polymerhus.app.clients import neo4j_client
from polymerhus.recon.domain.types import AssetDelta

BU = "https://eval.example"


def _cleanup(project_id):
    neo4j_client.merge("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", {"p": project_id})


@pytest.fixture()
def project():
    pid = f"aeval-{uuid.uuid4().hex[:8]}"
    yield pid
    _cleanup(pid)


def _seed_endpoints(project_id, paths):
    from polymerhus.recon.domain.curator import curate

    curate(
        [AssetDelta(type="BaseURL", identity={"url": BU}, props={"profile": "restapi"}),
         *[AssetDelta(type="Endpoint", identity={"path": p, "method": "GET", "baseurl": BU})
           for p in paths]],
        [], project_id,
    )


def _seed_service_and_edges(project_id, slug, paths, confidence=0.9):
    from polymerhus.analysis import l1_curator
    from polymerhus.analysis.l1_types import (
        AggregatesDelta, JudgmentEnvelope, L0Ref, Provenance, ServiceDelta,
    )

    prov = Provenance(job="analyser:eval")
    l1_curator.l1_curate(
        [ServiceDelta(business_function_slug=slug, props={"service_contract": "Owns things."},
                      provenance=prov)],
        [], project_id,
    )
    l1_curator.write_aggregates(
        [AggregatesDelta(
            service_slug=slug,
            l0=L0Ref(label="Endpoint",
                     identity={"path": p, "method": "GET", "baseurl": BU}),
            envelope=JudgmentEnvelope(confidence=confidence,
                                      evidence_refs=[f"path segment {p}"], provenance=prov))
         for p in paths],
        project_id,
    )


def test_read_assignment_returns_a_row_for_a_project_with_no_assignments(project):
    """The state that most needs to be visible is TOTAL non-assignment - the live
    defect where 114 sound judgments wrote zero. A chained MATCH would return no row
    at all here and report zero Endpoints too, hiding the surface that went unjudged
    behind an apparently empty project."""
    _seed_endpoints(project, ["/a", "/b", "/c"])

    census = read_assignment(project)
    assert census["endpoints"] == 3          # the surface IS there...
    assert census["aggregates"] == 0         # ...and nothing was assigned
    assert census["assigned_endpoints"] == 0
    assert census["mean_confidence"] == 0.0

    m = assignment_metrics(census)
    assert m["stale_pool"] == 3 and m["stale_rate"] == 1.0 and m["coverage"] == 0.0


def test_read_assignment_counts_coverage_and_multi_owner_endpoints(project):
    """Shared ownership is real (D3), but an arm where it is common has stopped
    discriminating between contracts - so it needs its own column rather than
    inflating the aggregate count invisibly."""
    _seed_endpoints(project, ["/orders/1", "/orders/2", "/unowned"])
    _seed_service_and_edges(project, "checkout", ["/orders/1", "/orders/2"], confidence=0.9)
    _seed_service_and_edges(project, "dispatch", ["/orders/2"], confidence=0.8)

    census = read_assignment(project)
    assert census["endpoints"] == 3
    assert census["aggregates"] == 3            # 2 + 1
    assert census["assigned_endpoints"] == 2    # /unowned has no owner
    assert census["multi_owner_endpoints"] == 1  # /orders/2 has two
    assert sorted(census["confidences"]) == [0.8, 0.9, 0.9]
    assert census["mean_confidence"] == round((0.8 + 0.9 + 0.9) / 3, 3)

    m = assignment_metrics(census)
    assert m["coverage"] == round(2 / 3, 3)
    assert m["stale_pool"] == 1


def test_evaluate_assigner_over_real_projects_carries_the_arm_label(project):
    """End to end on the harness: a completed run, read back, attributed to the arm
    it was run under, with the confidence-bar curve derived from real edge data."""
    from polymerhus.analysis.evaluation import evaluate_assigner

    _seed_endpoints(project, ["/x", "/y"])
    _seed_service_and_edges(project, "checkout", ["/x"], confidence=0.95)

    summary = evaluate_assigner({"skill": [project]})
    assert summary["skill"]["primary_key"] == "n_aggregates"
    assert summary["skill"]["breadth"]["values"] == [1]
    assert summary["skill"]["projects"] == [project]
    assert summary["skill"]["integrity"]["stale_pool"] == [1]
    # the bar sweep is real data: one edge at 0.95 clears every candidate bar
    assert summary["skill"]["bar_sweep"]["kept"]["0.9"] == 1
    assert summary["skill"]["bar_sweep"]["kept"]["0.5"] == 1
