"""FR-MERGE integration tier - the L1 sole-writer's destructive reconciliation
(merge / delete / relabel) against the REAL neo4j:5.26 container.

Mirrors tests/integration/test_l1_curator_merge.py exactly: connect from the host
to the published bolt port, apply the L0+L1 schema, run against a unique per-test
project_id, DETACH DELETE it on teardown, and skip cleanly if Neo4j is
unreachable (never fake a pass). APOC is absent on this container, so the merge
re-point is the explicit per-rel-type path.

Assertions (docs/design/post-recon-curation-and-l1-remediation-plan.md §3):
  * AST-MERGE-01  test_merge_repoints_all_edges ; test_merge_idempotent
  * AST-MERGE-02  test_delete_l1_only
  * AST-MERGE-03  test_relabel_service_to_system
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.recon.domain import curator
from polymerhus.analysis import l1_curator
from polymerhus.analysis.l1_types import (
    AggregatesDelta,
    DataFlowDelta,
    DeleteOp,
    JudgmentEnvelope,
    L0Ref,
    MergeOp,
    Provenance,
    RelabelOp,
    ServiceDelta,
    SystemDelta,
    SystemEdgeDelta,
)
from polymerhus.recon.domain.types import AssetDelta
from tests.conftest import wait_for

from tests.conftest import neo4j_target

# Single source of truth (tests/conftest.py::neo4j_target): env-driven so this
# file works BOTH in-network (bolt://neo4j:7687) and from the host against the
# published port. Was a hardcoded localhost constant, which cannot resolve
# inside the Docker network.
URI, AUTH = neo4j_target()
PROV = Provenance(job="curation", model="m", prompt_id="p")
ENV = JudgmentEnvelope(confidence=0.9, status="committed", evidence_refs=["obs:x"], provenance=PROV)


def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    try:
        subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=False)
    except Exception:  # noqa: BLE001 - docker CLI may be absent in some CI
        pass
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for FR-MERGE integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "l1rec_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _merge_fn(session):
    return lambda cy, params: session.run(cy, **params).consume()


def _count(session, label, pid, **props):
    where = " AND ".join(f"n.{k} = ${k}" for k in props)
    q = (
        f"MATCH (n:{label}) WHERE n.project_id = $p"
        + (f" AND {where}" if props else "")
        + " RETURN count(n) AS c"
    )
    return session.run(q, p=pid, **props).single()["c"]


def _write_l0_endpoint(session, pid, identity, **props):
    """Write a real L0 Endpoint through the L0 curator's own builder (the sole L0
    write path), so re-pointed cross-layer edges have genuine co-resident targets."""
    cy, params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(identity), props=props or {"status_code": 200})
    )
    params["project_id"] = pid
    session.run(cy, **params).consume()


def _ep(path):
    return {"path": path, "method": "GET", "baseurl": "https://a"}


# --- AST-MERGE-01: merge re-points ALL of B's edges onto A, copies props, deletes B ---

def test_merge_repoints_all_edges(session, project):
    mf = _merge_fn(session)
    # canonical A and duplicate B (both L1Service), with props to prove the copy rule
    l1_curator.l1_curate(
        [ServiceDelta(business_function_slug="checkout", props={"label": "canon"}, provenance=PROV),
         ServiceDelta(business_function_slug="check-out", props={"note": "fromB"}, provenance=PROV)],
        [], project, merge_fn=mf,
    )
    # A aggregates endpoint1; B aggregates endpoint2 (distinct), PRODUCES a DataItem,
    # and is AUTHENTICATED_BY a System - three different edge types to re-point.
    _write_l0_endpoint(session, project, _ep("/a"))
    _write_l0_endpoint(session, project, _ep("/b"))
    l1_curator.write_aggregates([AggregatesDelta(service_slug="checkout", l0=L0Ref(label="Endpoint", identity=_ep("/a")), envelope=ENV)], project, merge_fn=mf)
    l1_curator.write_aggregates([AggregatesDelta(service_slug="check-out", l0=L0Ref(label="Endpoint", identity=_ep("/b")), envelope=ENV)], project, merge_fn=mf)
    l1_curator.enrich(
        project,
        data_flows=[DataFlowDelta(service_slug="check-out", item_key="session_token", direction="produces", provenance=PROV)],
        system_edges=[SystemEdgeDelta(service_slug="check-out", kind="AuthenticationMechanism", rel="AUTHENTICATED_BY", provenance=PROV)],
        merge_fn=mf,
    )

    out = l1_curator.reconcile(
        project,
        merges=[MergeOp(label="L1Service", canonical={"business_function_slug": "checkout"}, duplicate={"business_function_slug": "check-out"}, provenance=PROV)],
        merge_fn=mf,
    )
    assert out == {"merged": 1, "deleted": 0, "relabelled": 0}

    # exactly one service survives; the duplicate is gone
    assert _count(session, "L1Service", project, business_function_slug="checkout") == 1
    assert _count(session, "L1Service", project, business_function_slug="check-out") == 0

    rec = session.run(
        "MATCH (a:L1Service {project_id: $p, business_function_slug: 'checkout'}) "
        "RETURN a.label AS label, a.note AS note, a.superseded_from AS sup, a.superseded_prov_job AS spj, "
        "count { (a)-[:AGGREGATES]->(:Endpoint) } AS aggs, "
        "count { (a)-[:PRODUCES]->(:L1DataItem {item_key: 'session_token'}) } AS produces, "
        "count { (a)-[:AUTHENTICATED_BY]->(:L1System {kind: 'AuthenticationMechanism'}) } AS authn",
        p=project,
    ).single()
    assert rec["aggs"] == 2       # BOTH endpoints now hang off the canonical
    assert rec["produces"] == 1   # B's PRODUCES re-pointed onto A
    assert rec["authn"] == 1      # B's AUTHENTICATED_BY re-pointed onto A
    assert rec["label"] == "canon"           # A keeps its own prop value
    assert rec["note"] == "fromB"            # A gains B's B-only prop
    assert rec["sup"] == ["L1Service:business_function_slug=check-out"]  # superseded marker
    assert rec["spj"] == "curation"          # provenance stamped
    # no dangling edge still points at a (now-deleted) duplicate
    assert _count(session, "L1Service", project) == 1


# --- AST-MERGE-01: a second merge run is a no-op (idempotent) ---

def test_merge_idempotent(session, project):
    mf = _merge_fn(session)
    l1_curator.l1_curate(
        [ServiceDelta(business_function_slug="orders", provenance=PROV),
         ServiceDelta(business_function_slug="order", provenance=PROV)],
        [], project, merge_fn=mf,
    )
    _write_l0_endpoint(session, project, _ep("/o"))
    l1_curator.write_aggregates([AggregatesDelta(service_slug="order", l0=L0Ref(label="Endpoint", identity=_ep("/o")), envelope=ENV)], project, merge_fn=mf)
    op = MergeOp(label="L1Service", canonical={"business_function_slug": "orders"}, duplicate={"business_function_slug": "order"}, provenance=PROV)

    l1_curator.reconcile(project, merges=[op], merge_fn=mf)
    l1_curator.reconcile(project, merges=[op], merge_fn=mf)  # replay

    assert _count(session, "L1Service", project) == 1
    rec = session.run(
        "MATCH (a:L1Service {project_id: $p, business_function_slug: 'orders'}) "
        "RETURN a.superseded_from AS sup, count { (a)-[:AGGREGATES]->() } AS aggs",
        p=project,
    ).single()
    # the second run matched no duplicate: no double-append, no duplicated edge
    assert rec["sup"] == ["L1Service:business_function_slug=order"]
    assert rec["aggs"] == 1


# --- AST-MERGE-02: delete DETACH-deletes an L1 node only, never an L0 node ---

def test_delete_l1_only(session, project):
    mf = _merge_fn(session)
    l1_curator.l1_curate([], [SystemDelta(kind="WAF", provenance=PROV)], project, merge_fn=mf)
    _write_l0_endpoint(session, project, _ep("/keep"))
    assert _count(session, "L1System", project, kind="WAF") == 1
    assert _count(session, "Endpoint", project) == 1

    out = l1_curator.reconcile(
        project,
        deletes=[
            DeleteOp(label="L1System", identity={"kind": "WAF", "discriminator": "__singleton__"}, provenance=PROV),
            DeleteOp(label="Endpoint", identity=_ep("/keep"), provenance=PROV),  # L0 -> skipped fail-open at build
            DeleteOp(label="L1Service", identity={"business_function_slug": "ghost"}, provenance=PROV),  # missing -> safe no-op
        ],
        merge_fn=mf,
    )
    # only the two L1 ops dispatched (the L0 op was skipped at build time)
    assert out == {"merged": 0, "deleted": 2, "relabelled": 0}
    assert _count(session, "L1System", project, kind="WAF") == 0  # L1 node deleted
    assert _count(session, "Endpoint", project) == 1                     # L0 node UNTOUCHED
    # no catalogue nodes exist in the model any more (operator correction 2026-07-20)
    assert _count(session, "SystemKind", project) == 0


# --- AST-MERGE-03: relabel a mis-typed Service to a System (the de-risking finding) ---

def test_relabel_service_to_system(session, project):
    mf = _merge_fn(session)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="graphql-api", props={"label": "GQL"}, provenance=PROV)], [], project, merge_fn=mf)
    _write_l0_endpoint(session, project, _ep("/graphql"))
    l1_curator.write_aggregates([AggregatesDelta(service_slug="graphql-api", l0=L0Ref(label="Endpoint", identity=_ep("/graphql")), envelope=ENV)], project, merge_fn=mf)

    out = l1_curator.reconcile(
        project,
        relabels=[RelabelOp(
            from_label="L1Service", to_label="L1System",
            identity={"business_function_slug": "graphql-api"},
            new_identity={"kind": "GraphQLApi", "discriminator": "__singleton__"},
            provenance=PROV,
        )],
        merge_fn=mf,
    )
    assert out == {"merged": 0, "deleted": 0, "relabelled": 1}

    rec = session.run(
        "MATCH (n {project_id: $p, kind: 'GraphQLApi'}) "
        "RETURN labels(n) AS labels, n.business_function_slug AS old_slug, n.discriminator AS disc, "
        "n.label AS keptprop, n.relabelled_from AS rf, n.prov_job AS pj, n.kind AS kind, "
        "count { (n)-[:EVIDENCED_BY]->(:Endpoint) } AS evidenced, "
        "count { (n)-[:AGGREGATES]->() } AS aggs",
        p=project,
    ).single()
    # re-keyed to a System: labels swapped, old identity key removed, System key set
    assert set(rec["labels"]) == {"L1System", "L1TestableUnit"}
    assert rec["old_slug"] is None                 # business_function_slug removed
    assert rec["disc"] == "__singleton__"          # re-keyed identity
    assert rec["kind"] == "GraphQLApi"             # kind attribute set on relabel
    assert rec["keptprop"] == "GQL"                # non-identity props preserved
    # AGGREGATES -> EVIDENCED_BY (semantics change with the type)
    assert rec["evidenced"] == 1
    assert rec["aggs"] == 0
    # operator correction 2026-07-20: no catalogue node / OF_KIND edge is created
    assert _count(session, "SystemKind", project) == 0
    # provenance stamped
    assert rec["rf"] == "L1Service:business_function_slug=graphql-api"
    assert rec["pj"] == "curation"
    # the old L1Service label/key is gone -> a relabel replay cannot re-MATCH it (no-op)
    assert _count(session, "L1Service", project, business_function_slug="graphql-api") == 0
    l1_curator.reconcile(
        project,
        relabels=[RelabelOp(from_label="L1Service", to_label="L1System",
                            identity={"business_function_slug": "graphql-api"},
                            new_identity={"kind": "GraphQLApi", "discriminator": "__singleton__"},
                            provenance=PROV)],
        merge_fn=mf,
    )
    assert _count(session, "L1System", project, kind="GraphQLApi") == 1  # still exactly one
