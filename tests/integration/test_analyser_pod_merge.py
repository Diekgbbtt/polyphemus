"""FR-ANALYSER integration tier — the analyser subgraph writing real L1 nodes via
the sanctioned l1_curator into the live Neo4j, with a MOCKED analyse step (canned
L1DeltaBatch) standing in for the LLM. Proves AST-ANALYSER-01: the analyser is a
pure f(L0-slice+obs)->L1-deltas whose writes are idempotent MERGEs (running twice
yields one node).
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.recon.domain import curator
from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    L1DeltaBatch,
    ServiceProposal,
    SystemProposal,
)
from polymerhus.analysis import l1_curator
from polymerhus.analysis.pod import AnalyserExport, build_analyser_graph, run_analyser
from polymerhus.recon.domain.types import AssetDelta
from tests.conftest import wait_for

from tests.conftest import neo4j_target

# Single source of truth (tests/conftest.py::neo4j_target): env-driven so this
# file works BOTH in-network (bolt://neo4j:7687) and from the host against the
# published port. Was a hardcoded localhost constant, which cannot resolve
# inside the Docker network.
URI, AUTH = neo4j_target()


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
        pytest.skip(f"neo4j not reachable for analyser integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "anlz_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _canned_batch(endpoint_id):
    return L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="product-introspection", props={"label": "Introspection"})],
        systems=[SystemProposal(kind="RESTApi")],
        aggregates=[AggregatesProposal(
            service_slug="product-introspection", confidence=0.82, evidence_refs=["obs:cat"],
            l0=L0Ref_dict(endpoint_id),
        )],
    )


def L0Ref_dict(identity):
    from polymerhus.analysis.l1_types import L0Ref
    return L0Ref(label="Endpoint", identity=dict(identity))


# --- AST-ANALYSER-01: pure f(L0-slice+obs)->L1-deltas, idempotent MERGE ---

def test_analyser_writes_l1_idempotently_via_curator(session, project):
    endpoint_id = {"path": "/categories/{id}/parameters", "method": "GET", "baseurl": "https://a"}
    # recon precedes analysis: a real L0 Endpoint exists (AGGREGATES MATCHes it)
    l0_cy, l0_params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(endpoint_id), props={"status_code": 200})
    )
    l0_params["project_id"] = project
    session.run(l0_cy, **l0_params).consume()

    # curate through the REAL l1_curator, but with the test session as the write
    # path (correct auth) instead of neo4j_client (which would read the dummy
    # NEO4J_PASSWORD in a bare run). Mirrors the FR-LCUR integration pattern.
    def session_curate_fn(batch, project_id, provenance):
        from polymerhus.analysis.analyser_types import proposals_to_deltas
        services, systems, aggregates = proposals_to_deltas(batch, provenance)
        mf = lambda cy, p: session.run(cy, **p).consume()
        sw, syw = l1_curator.l1_curate(services, systems, project_id, merge_fn=mf)
        aw = l1_curator.write_aggregates(aggregates, project_id, merge_fn=mf)
        return AnalyserExport(services_written=sw, systems_written=syw, aggregates_written=aw)

    # analyse step is mocked (canned batch) standing in for the LLM
    graph = build_analyser_graph(
        read_fn=lambda p: {"nodes": [{"type": "Endpoint", **endpoint_id}], "links": []},
        analyse_fn=lambda s, o: _canned_batch(endpoint_id),
        curate_fn=session_curate_fn,
    )

    for _ in range(2):  # run the analyser twice on the same input
        export = run_analyser(project, "run-1", [], graph=graph)
        assert export.error is None

    def _count(label, **props):
        where = " AND ".join(f"n.{k} = ${k}" for k in props)
        q = f"MATCH (n:{label}) WHERE n.project_id = $p" + (f" AND {where}" if props else "") + " RETURN count(n) AS c"
        return session.run(q, p=project, **props).single()["c"]

    # idempotent: one Service, one System, one AGGREGATES edge — no duplicates
    assert _count("L1Service", business_function_slug="product-introspection") == 1
    assert _count("L1System", kind="RESTApi") == 1
    edges = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AGGREGATES]->(:Endpoint {project_id: $p}) RETURN count(r) AS c",
        p=project,
    ).single()["c"]
    assert edges == 1
    # the AGGREGATES envelope carries the analyser's confidence + system provenance
    env = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AGGREGATES]->() RETURN r.confidence AS c, r.prov_job AS j",
        p=project,
    ).single()
    assert env["c"] == 0.82
    assert env["j"] == "analyser:run-1"
