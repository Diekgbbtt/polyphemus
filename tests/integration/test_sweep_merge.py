"""FR-SWEEP integration tier — the derived sweeps against live Neo4j.

Encodes L1D-24: the stale pool is exactly the assignable L0 nodes with no inbound
AGGREGATES (assigning one removes it from the pool), and the missing-systems
sweep is the SystemKind catalogue rows with no instantiated :L1System.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from agent.recon import curator
from agent.recon.analysis import l1_curator, sweep
from agent.recon.analysis.l1_types import (
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
    SystemDelta,
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
        pytest.skip(f"neo4j not reachable for sweep integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "sweep_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _mf(session):
    return lambda cy, params: session.run(cy, **params).consume()


def _read_fn(session):
    return lambda cy, params: [dict(r) for r in session.run(cy, **params)]


def _write_endpoint(session, project, path):
    cy, params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": "https://a"}, props={"status_code": 200})
    )
    params["project_id"] = project
    session.run(cy, **params).consume()


# --- L1D-24: the stale pool is the derived "no inbound AGGREGATES" set ---

def test_stale_pool_reflects_unassigned_endpoints(session, project):
    mf, read_fn = _mf(session), _read_fn(session)
    for path in ("/api/products", "/healthz"):
        _write_endpoint(session, project, path)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="catalog", provenance=PROV)], [], project, merge_fn=mf)

    # before assignment: both endpoints are stale
    before = {n["path"] for n in sweep.stale_pool(project, read_fn=read_fn)}
    assert before == {"/api/products", "/healthz"}
    assert sweep.stale_pool_count(project, read_fn=read_fn) == 2

    # assign /api/products -> it leaves the stale pool; /healthz remains
    l1_curator.write_aggregates(
        [AggregatesDelta(service_slug="catalog", l0=L0Ref(label="Endpoint", identity={"path": "/api/products", "method": "GET", "baseurl": "https://a"}), envelope=ENV)],
        project, merge_fn=mf,
    )
    after = {n["path"] for n in sweep.stale_pool(project, read_fn=read_fn)}
    assert after == {"/healthz"}
    assert sweep.stale_pool_count(project, read_fn=read_fn) == 1
    # the surviving row carries its L0 label
    rows = sweep.stale_pool(project, read_fn=read_fn)
    assert rows[0]["_label"] == "Endpoint"


# --- L1D-24: missing-systems sweep over the SystemKind registry ---

def test_missing_system_kinds_after_seeding_and_one_instance(session, project):
    mf, read_fn = _mf(session), _read_fn(session)
    seeded = l1_curator.seed_system_kinds(project, merge_fn=mf)
    assert seeded == 13

    # nothing instantiated yet: all 13 kinds are missing
    assert len(sweep.missing_system_kinds(project, read_fn=read_fn)) == 13

    # instantiate a RESTApi System -> it drops out of the missing set
    l1_curator.l1_curate([], [SystemDelta(system_kind="RESTApi", provenance=PROV)], project, merge_fn=mf)
    missing = sweep.missing_system_kinds(project, read_fn=read_fn)
    assert "RESTApi" not in missing
    assert len(missing) == 12
    assert "GraphQLApi" in missing  # an unrepresented kind is still reported
