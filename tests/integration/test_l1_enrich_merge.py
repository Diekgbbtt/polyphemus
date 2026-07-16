"""FR-ENRICH integration tier — DataItem (flexible identity) + trust/data-flow
edges + the extensible DataRelationship vocabulary, written through l1_curator
into live Neo4j. Reuses the §15 sales_figure flow as the canonical scenario.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from agent.recon import curator
from agent.recon.analysis import l1_curator
from agent.recon.analysis.l1_types import (
    DataFlowDelta,
    DataItemDelta,
    DataRelationshipDelta,
    L0Ref,
    Provenance,
    ServiceDelta,
    SurfacesAtDelta,
    SystemEdgeDelta,
)
from agent.recon.types import AssetDelta
from tests.conftest import wait_for

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")
PROV = Provenance(job="analyser:run-1", model="m", prompt_id="p")


def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    try:
        subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=False)
    except Exception:  # noqa: BLE001
        pass
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for enrich integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "enrich_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _mf(session):
    return lambda cy, params: session.run(cy, **params).consume()


def _count(session, label, pid, **props):
    where = " AND ".join(f"n.{k} = ${k}" for k in props)
    q = f"MATCH (n:{label}) WHERE n.project_id = $p" + (f" AND {where}" if props else "") + " RETURN count(n) AS c"
    return session.run(q, p=pid, **props).single()["c"]


# --- DataItem flexible identity: idempotent MERGE, identity ⊥ membership ---

def test_dataitem_merge_idempotent_and_identity_independent_of_sites(session, project):
    mf = _mf(session)
    # write an L0 Parameter site for the item to surface at
    for name in ("figure_q", "figure_body"):
        cy, params = curator.build_asset_cypher(
            AssetDelta(type="Parameter",
                       identity={"name": name, "position": "query", "endpoint_path": "/x", "baseurl": "https://a"})
        )
        params["project_id"] = project
        session.run(cy, **params).consume()

    # same DataItem written twice, with a DIFFERENT set of surfaces_at sites each time
    l1_curator.enrich(project, data_items=[DataItemDelta(item_key="sales_figure", props={"type": "float"}, provenance=PROV)],
                      surfaces_at=[SurfacesAtDelta(item_key="sales_figure",
                                                   l0=L0Ref(label="Parameter", identity={"name": "figure_q", "position": "query", "endpoint_path": "/x", "baseurl": "https://a"}),
                                                   provenance=PROV)],
                      merge_fn=mf)
    l1_curator.enrich(project, data_items=[DataItemDelta(item_key="sales_figure", props={"type": "float", "note": "more"}, provenance=PROV)],
                      surfaces_at=[SurfacesAtDelta(item_key="sales_figure",
                                                   l0=L0Ref(label="Parameter", identity={"name": "figure_body", "position": "query", "endpoint_path": "/x", "baseurl": "https://a"}),
                                                   provenance=PROV)],
                      merge_fn=mf)
    # one DataItem node despite two runs + a growing member (SURFACES_AT) set
    assert _count(session, "L1DataItem", project, item_key="sales_figure") == 1
    surfaces = session.run(
        "MATCH (:L1DataItem {project_id: $p, item_key: 'sales_figure'})-[:SURFACES_AT]->(x) RETURN count(x) AS c", p=project,
    ).single()["c"]
    assert surfaces == 2  # membership grew; identity did not churn


# --- Tier-1 trust: PRODUCES/CONSUMES with the assumption on CONSUMES (the §15 flow) ---

def test_producer_consumer_flow_with_assumption(session, project):
    mf = _mf(session)
    # skeleton services + the data item
    l1_curator.l1_curate([ServiceDelta(business_function_slug="item-creation", provenance=PROV),
                          ServiceDelta(business_function_slug="sales-analysis", provenance=PROV)], [], project, merge_fn=mf)
    l1_curator.enrich(
        project,
        data_items=[DataItemDelta(item_key="sales_figure", provenance=PROV)],
        data_flows=[
            DataFlowDelta(service_slug="item-creation", item_key="sales_figure", direction="produces", provenance=PROV),
            DataFlowDelta(service_slug="sales-analysis", item_key="sales_figure", direction="consumes",
                          assumption="the figure was authorized for THIS user", provenance=PROV),
        ],
        merge_fn=mf,
    )
    rec = session.run(
        "MATCH (:L1Service {project_id: $p, business_function_slug: 'item-creation'})-[:PRODUCES]->(d:L1DataItem {item_key: 'sales_figure'}) "
        "MATCH (c:L1Service {project_id: $p, business_function_slug: 'sales-analysis'})-[r:CONSUMES]->(d) "
        "RETURN r.assumption AS a", p=project,
    ).single()
    assert rec["a"] == "the figure was authorized for THIS user"  # assumption on CONSUMES, derived from a represented flow


# --- extensible DataRelationship vocabulary + edge with predicate ---

def test_data_relationship_edge_and_catalogue(session, project):
    mf = _mf(session)
    seeded = l1_curator.seed_data_relationship_kinds(project, merge_fn=mf)
    assert seeded == len(l1_curator.DATA_RELATIONSHIP_KINDS)
    l1_curator.enrich(
        project,
        data_items=[DataItemDelta(item_key="client_id", provenance=PROV), DataItemDelta(item_key="email", provenance=PROV)],
        data_relationships=[DataRelationshipDelta(from_item_key="client_id", to_item_key="email",
                                                  kind="equals_hash_of", predicate="client_id = md5(email+id)",
                                                  rationale="derivation", provenance=PROV)],
        merge_fn=mf,
    )
    rec = session.run(
        "MATCH (:L1DataItem {project_id: $p, item_key: 'client_id'})-[r:DATA_RELATIONSHIP {kind: 'equals_hash_of'}]->"
        "(:L1DataItem {project_id: $p, item_key: 'email'}) RETURN r.predicate AS pred", p=project,
    ).single()
    assert rec["pred"] == "client_id = md5(email+id)"
    # the kind's catalogue row exists (extensible vocabulary)
    assert _count(session, "DataRelationshipKind", project, id="equals_hash_of") == 1


# --- systems as edges, not strings (L1D-18) ---

def test_system_edge_written_as_typed_edge(session, project):
    mf = _mf(session)
    l1_curator.seed_system_kinds(project, merge_fn=mf)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="sales-analysis", provenance=PROV)], [], project, merge_fn=mf)
    l1_curator.enrich(
        project,
        system_edges=[SystemEdgeDelta(service_slug="sales-analysis", system_kind="RESTApi", rel="EXPOSED_VIA", provenance=PROV),
                      SystemEdgeDelta(service_slug="sales-analysis", system_kind="AuthorizationSystem", rel="AUTHORIZED_BY", role="seller", provenance=PROV)],
        merge_fn=mf,
    )
    exposed = session.run(
        "MATCH (:L1Service {project_id: $p, business_function_slug: 'sales-analysis'})-[:EXPOSED_VIA]->(:L1System {system_kind: 'RESTApi'}) RETURN count(*) AS c", p=project,
    ).single()["c"]
    authz = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AUTHORIZED_BY {role: 'seller'}]->(:L1System {system_kind: 'AuthorizationSystem'}) RETURN count(r) AS c", p=project,
    ).single()["c"]
    assert exposed == 1 and authz == 1


# --- SURFACES_AT never creates the L0 node (sole-writer preserved) ---

def test_surfaces_at_missing_l0_is_noop(session, project):
    mf = _mf(session)
    l1_curator.enrich(project,
                      surfaces_at=[SurfacesAtDelta(item_key="ghost",
                                                   l0=L0Ref(label="Parameter", identity={"name": "nope", "position": "query", "endpoint_path": "/x", "baseurl": "https://a"}),
                                                   provenance=PROV)],
                      merge_fn=mf)
    # L0 Parameter was NOT created by l1_curator; the SURFACES_AT edge did not form
    assert _count(session, "Parameter", project) == 0
    edges = session.run("MATCH (:L1DataItem {project_id: $p})-[r:SURFACES_AT]->() RETURN count(r) AS c", p=project).single()["c"]
    assert edges == 0
