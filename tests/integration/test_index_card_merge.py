"""FR-INDEXCARD integration tier — the index-card projection + DFS-down against
live Neo4j. Proves DD-4 live: a Service with N aggregated endpoints has a card
whose AGGREGATES degree is N, carrying no member payload; DFS-down is one hop.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from agent.recon import curator
from agent.recon.analysis import index_card, l1_curator
from agent.recon.analysis.l1_types import (
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
    SystemDelta,
    SystemEdgeDelta,
)
from agent.recon.types import AssetDelta
from tests.conftest import wait_for

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")
PROV = Provenance(job="it", model="m", prompt_id="p")
ENV = JudgmentEnvelope(confidence=0.8, status="committed", evidence_refs=["o"], provenance=PROV)


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
        pytest.skip(f"neo4j not reachable for index-card integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "card_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _mf(session):
    return lambda cy, params: session.run(cy, **params).consume()


def _read_fn(session):
    return lambda cy, params: [dict(r) for r in session.run(cy, **params)]


def test_service_card_degree_not_member_set(session, project):
    mf, read_fn = _mf(session), _read_fn(session)
    l1_curator.seed_system_kinds(project, merge_fn=mf)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="catalog", props={"api_paradigm": "REST"}, provenance=PROV)], [], project, merge_fn=mf)
    # aggregate 5 distinct concrete endpoints to the service
    for i in range(5):
        path = f"/api/products/{i}"
        cy, params = curator.build_asset_cypher(AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": "https://a"}))
        params["project_id"] = project
        session.run(cy, **params).consume()
        l1_curator.write_aggregates([AggregatesDelta(service_slug="catalog", l0=L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": "https://a"}), envelope=ENV)], project, merge_fn=mf)
    # also a typed system edge
    l1_curator.enrich(project, system_edges=[SystemEdgeDelta(service_slug="catalog", system_kind="RESTApi", rel="EXPOSED_VIA", provenance=PROV)], merge_fn=mf)

    cards = index_card.index_cards(project, read_fn=read_fn)
    catalog = next(c for c in cards if c["label"] == "catalog")
    # DD-4: degree by family, not the member set
    assert catalog["edge_degree"]["AGGREGATES"] == 5
    assert catalog["edge_degree"]["EXPOSED_VIA"] == 1
    assert catalog["spine"] == {"api_paradigm": "REST"}
    # the card carries NO member endpoint payload
    import json
    blob = json.dumps(catalog)
    assert "/api/products/" not in blob


def test_dfs_down_one_typed_hop(session, project):
    mf, read_fn = _mf(session), _read_fn(session)
    l1_curator.seed_system_kinds(project, merge_fn=mf)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="sales", provenance=PROV)], [], project, merge_fn=mf)
    l1_curator.enrich(project, system_edges=[
        SystemEdgeDelta(service_slug="sales", system_kind="RESTApi", rel="EXPOSED_VIA", provenance=PROV),
        SystemEdgeDelta(service_slug="sales", system_kind="AuthorizationSystem", rel="AUTHORIZED_BY", role="seller", provenance=PROV),
    ], merge_fn=mf)

    exposed = index_card.dfs_down(project, "sales", "EXPOSED_VIA", read_fn=read_fn)
    assert len(exposed) == 1
    assert exposed[0]["props"]["system_kind"] == "RESTApi"
    # a different edge family returns a different neighbour (one typed hop each)
    authz = index_card.dfs_down(project, "sales", "AUTHORIZED_BY", read_fn=read_fn)
    assert authz[0]["props"]["system_kind"] == "AuthorizationSystem"


def test_bootstrapped_service_has_zero_degree_card(session, project):
    mf, read_fn = _mf(session), _read_fn(session)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="fresh", provenance=PROV)], [], project, merge_fn=mf)
    cards = index_card.index_cards(project, read_fn=read_fn)
    fresh = next(c for c in cards if c["label"] == "fresh")
    assert fresh["edge_degree"] == {}  # a member-less bootstrapped Service still has a card
