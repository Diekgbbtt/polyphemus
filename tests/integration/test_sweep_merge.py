"""FR-SWEEP integration tier — the derived sweeps against live Neo4j.

Encodes L1D-24: the stale pool is exactly the assignable L0 nodes with no inbound
AGGREGATES (assigning one removes it from the pool). The redesigned missing-systems
sweep (operator correction 2026-07-20) is stale-L0-asset-driven ownership
resolution over the stale pool + existing inventory - a fail-open seam that is
unit-tested with an injected fake LLM (tests/recon/test_l1_domain_model_refactor.py);
here we only assert the live stale-pool reads it consumes.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.recon.domain import curator
from polymerhus.analysis import l1_curator, sweep
from polymerhus.analysis.l1_types import (
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
    SystemDelta,
)
from polymerhus.recon.domain.types import AssetDelta
from tests.conftest import wait_for

from tests.conftest import neo4j_target

# Single source of truth (tests/conftest.py::neo4j_target): env-driven so this
# file works BOTH in-network (bolt://neo4j:7687) and from the host against the
# published port. Was a hardcoded localhost constant, which cannot resolve
# inside the Docker network.
URI, AUTH = neo4j_target()
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


# --- L1D-24 (redesigned): stale-asset-driven ownership resolution over live data ---

def test_resolve_stale_owners_reads_live_stale_pool_and_inventory(session, project):
    """The redesigned sweep reads the live stale pool + existing inventory and
    grounds an injected propose_fn in them; it proposes owners without writing
    them back (seam). Uses a fake propose_fn so no live LLM is needed."""
    mf, read_fn = _mf(session), _read_fn(session)
    _write_endpoint(session, project, "/healthz")  # a stale, unassigned asset
    l1_curator.l1_curate([ServiceDelta(business_function_slug="catalog", provenance=PROV)], [], project, merge_fn=mf)

    seen = {}

    def fake_propose(context):
        seen["context"] = context
        return sweep.StaleOwnershipBatch(proposals=[
            sweep.StaleAssetOwnership(asset_ref={"path": "/healthz"}, service_slug="catalog"),
        ])

    batch = sweep.resolve_stale_owners(project, read_fn=read_fn, propose_fn=fake_propose)
    # the live stale pool + existing inventory reached the prompt context
    assert any(a.get("path") == "/healthz" for a in seen["context"]["stale_pool"])
    assert "catalog" in seen["context"]["inventory"]["services"]
    assert "WebPresentation" in seen["context"]["known_kinds"]
    # the proposal is returned (not written back - that leg is unbuilt by design)
    assert batch.proposals[0].service_slug == "catalog"


def test_resolve_stale_owners_no_stale_skips_llm(session, project):
    """No stale assets -> the LLM is never invoked and an empty batch is returned."""
    _, read_fn = _mf(session), _read_fn(session)

    def boom(context):  # must never be called
        raise AssertionError("propose_fn invoked despite empty stale pool")

    batch = sweep.resolve_stale_owners(project, read_fn=read_fn, propose_fn=boom)
    assert batch.proposals == []
