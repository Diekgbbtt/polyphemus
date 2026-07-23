"""FR-PODSTREAM integration tier — re-delivery is idempotent (AST-PODSTREAM-04).

Delivery is at-least-once across runs (each analyser pull re-reads the whole
graph). This proves that re-delivering the same asset+observation set through the
real l1_curator into live Neo4j MERGE-dedups: a second identical run yields no
duplicate L1 nodes/edges (L1D-22). The analyse step is mocked (canned batch); the
point under test is delivery + idempotent write, not the LLM.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.recon.domain import curator
from polymerhus.analysis import delivery
from polymerhus.analysis.analyser_types import (
    AggregatesProposal, L1DeltaBatch, ServiceProposal, SystemProposal, proposals_to_deltas,
)
from polymerhus.analysis import l1_curator
from polymerhus.analysis.pod import AnalyserExport, build_analyser_graph, run_analyser
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta, Observation
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
        pytest.skip(f"neo4j not reachable for delivery integration tests: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "deliv_it_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _seed_surface(session, project):
    """Curate one Endpoint asset + one Observation anchored to it (L0)."""
    endpoint_id = {"path": "/api/Orders", "method": "GET", "baseurl": "https://a"}
    l0_cy, l0_params = curator.build_asset_cypher(
        AssetDelta(type="Endpoint", identity=dict(endpoint_id), props={"status_code": 200})
    )
    l0_params["project_id"] = project
    session.run(l0_cy, **l0_params).consume()

    obs = Observation(
        macro_kind="reflected_input", severity="medium", evidence="q=<script>",
        rationale="reflects unsanitised input", source_job="arjun", source_tool="arjun",
        anchor={"type": "Endpoint", "identity": dict(endpoint_id)},
    )
    obs_cy, obs_params = curator.build_observation_cypher(obs)
    obs_params["project_id"] = project
    session.run(obs_cy, **obs_params).consume()
    return endpoint_id


def test_redelivery_is_idempotent(session, project):
    endpoint_id = _seed_surface(session, project)

    # delivery reads the real graph via the test session (correct auth)
    def sess_read(cy, params):
        return [r.data() for r in session.run(cy, **params)]

    # every delivered observation reaches the analyser exactly once (id-deduped)
    delivered = delivery.collect_observations(project, read_fn=sess_read)
    assert len(delivered) == 1 and delivered[0]["macro_kind"] == "reflected_input"

    def session_curate_fn(batch, project_id, provenance):
        services, systems, aggregates = proposals_to_deltas(batch, provenance)
        mf = lambda cy, p: session.run(cy, **p).consume()
        sw, syw = l1_curator.l1_curate(services, systems, project_id, merge_fn=mf)
        aw = l1_curator.write_aggregates(aggregates, project_id, merge_fn=mf)
        return AnalyserExport(services_written=sw, systems_written=syw, aggregates_written=aw)

    def canned_analyse(l0_slice, observations):
        # the delivered observation reached the analyse step
        assert any(o["macro_kind"] == "reflected_input" for o in observations)
        return L1DeltaBatch(
            services=[ServiceProposal(business_function_slug="orders")],
            systems=[SystemProposal(kind="RESTApi")],
            aggregates=[AggregatesProposal(service_slug="orders", confidence=0.9,
                        l0=L0Ref(label="Endpoint", identity=dict(endpoint_id)))],
        )

    graph = build_analyser_graph(
        read_fn=lambda p: {"nodes": [{"type": "Endpoint", **endpoint_id}], "links": []},
        analyse_fn=canned_analyse,
        curate_fn=session_curate_fn,
    )

    # run the analyser TWICE with auto-delivery (observations=None) on the same graph
    for _ in range(2):
        export = run_analyser(project, "run-1", graph=graph,
                              deliver_fn=lambda pid: delivery.collect_observations(pid, read_fn=sess_read))
        assert export.error is None

    def _count(q):
        return session.run(q, p=project).single()["c"]

    # idempotent: one Service, one Endpoint, one AGGREGATES edge, one Observation
    assert _count("MATCH (n:L1Service {project_id:$p}) RETURN count(n) AS c") == 1
    assert _count("MATCH (n:Observation {project_id:$p}) RETURN count(n) AS c") == 1
    assert _count("MATCH (:L1Service {project_id:$p})-[r:AGGREGATES]->(:Endpoint) RETURN count(r) AS c") == 1
