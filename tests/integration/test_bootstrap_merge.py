"""FR-ELICIT integration tier — bootstrap writing the real L1 skeleton into live
Neo4j (services + linchpin auth Systems, NO AGGREGATES), idempotent, and the
bootstrap->assignment flow (an elicited Service later receives an AGGREGATES edge
from the analyser). Elicitation is mocked (canned batch) for the LLM.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from agent.recon import curator
from agent.recon.analysis import bootstrap, l1_curator
from agent.recon.analysis.analyser_types import L1DeltaBatch, ServiceProposal, SystemProposal
from agent.recon.analysis.l1_types import (
    AggregatesDelta,
    JudgmentEnvelope,
    L0Ref,
    Provenance,
    ServiceDelta,
)
from agent.recon.types import AssetDelta
from tests.conftest import wait_for

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")


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
        pytest.skip(f"neo4j not reachable for bootstrap integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "boot_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _mf(session):
    return lambda cy, params: session.run(cy, **params).consume()


def _count(session, label, pid, **props):
    where = " AND ".join(f"n.{k} = ${k}" for k in props)
    q = f"MATCH (n:{label}) WHERE n.project_id = $p" + (f" AND {where}" if props else "") + " RETURN count(n) AS c"
    return session.run(q, p=pid, **props).single()["c"]


def _canned_skeleton():
    return L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="checkout"),
                  ServiceProposal(business_function_slug="product-introspection")],
        systems=[SystemProposal(system_kind="RESTApi")],
    )


def _session_curate(session):
    def curate_fn(services, systems, project_id):
        return l1_curator.l1_curate(services, systems, project_id, merge_fn=_mf(session))
    return curate_fn


# --- AST-ELICIT-01/02/03: skeleton written, linchpins present, NO AGGREGATES ---

def test_bootstrap_writes_skeleton_with_no_l0_refs(session, project):
    l1_curator.seed_system_kinds(project, merge_fn=_mf(session))
    export = bootstrap.bootstrap_from_kb(
        project, "marketplace with checkout and product introspection",
        elicit_fn=lambda kb: _canned_skeleton(), curate_fn=_session_curate(session),
    )
    assert export.error is None
    assert _count(session, "L1Service", project, business_function_slug="checkout") == 1
    assert _count(session, "L1Service", project, business_function_slug="product-introspection") == 1
    # linchpin auth Systems present
    assert _count(session, "L1System", project, system_kind="AuthenticationMechanism") == 1
    assert _count(session, "L1System", project, system_kind="AuthorizationSystem") == 1
    # PURE business projection: no AGGREGATES edge exists anywhere for this project
    agg = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AGGREGATES]->() RETURN count(r) AS c", p=project,
    ).single()["c"]
    assert agg == 0


def test_bootstrap_is_idempotent(session, project):
    cf = _session_curate(session)
    for _ in range(2):
        bootstrap.bootstrap_from_kb(project, "kb", elicit_fn=lambda kb: _canned_skeleton(), curate_fn=cf)
    assert _count(session, "L1Service", project, business_function_slug="checkout") == 1
    assert _count(session, "L1System", project, system_kind="AuthenticationMechanism") == 1


# --- bootstrap -> assignment flow: an elicited Service receives an AGGREGATES edge ---

def test_elicited_service_can_receive_aggregates_assignment(session, project):
    mf = _mf(session)
    # bootstrap the skeleton (no L0 refs)
    bootstrap.bootstrap_from_kb(project, "kb", elicit_fn=lambda kb: _canned_skeleton(), curate_fn=_session_curate(session))
    # recon lands an L0 endpoint
    endpoint_id = {"path": "/categories/{id}/parameters", "method": "GET", "baseurl": "https://a"}
    l0_cy, l0_params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(endpoint_id), props={"status_code": 200})
    )
    l0_params["project_id"] = project
    session.run(l0_cy, **l0_params).consume()
    # assignment: the analyser attaches the endpoint to the elicited Service
    l1_curator.write_aggregates(
        [AggregatesDelta(
            service_slug="product-introspection",
            l0=L0Ref(label="Endpoint", identity=endpoint_id),
            envelope=JudgmentEnvelope(confidence=0.8, status="committed", evidence_refs=["obs"],
                                      provenance=Provenance(job="analyser:run-1")),
        )],
        project, merge_fn=mf,
    )
    # the elicited Service now has exactly one AGGREGATES edge to the L0 endpoint
    edges = session.run(
        "MATCH (:L1Service {project_id: $p, business_function_slug: 'product-introspection'})"
        "-[r:AGGREGATES]->(:Endpoint {project_id: $p}) RETURN count(r) AS c",
        p=project,
    ).single()["c"]
    assert edges == 1
