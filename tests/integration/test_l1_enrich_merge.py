"""FR-ENRICH integration tier — Service->System edges written through l1_curator
into live Neo4j. The DataItem / SURFACES_AT / data-flow / data-relationship writers
were removed with the data plane (`docs/design/drop-data-modeller.md`).
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.analysis import l1_curator
from polymerhus.analysis.l1_types import (
    Provenance,
    ServiceDelta,
    SystemEdgeDelta,
)
from tests.conftest import wait_for

from tests.conftest import neo4j_target

# Single source of truth (tests/conftest.py::neo4j_target): env-driven so this
# file works BOTH in-network (bolt://neo4j:7687) and from the host against the
# published port. Was a hardcoded localhost constant, which cannot resolve
# inside the Docker network.
URI, AUTH = neo4j_target()
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


# --- systems as edges, not strings (L1D-18) ---

def test_system_edge_written_as_typed_edge(session, project):
    mf = _mf(session)
    l1_curator.l1_curate([ServiceDelta(business_function_slug="sales-analysis", provenance=PROV)], [], project, merge_fn=mf)
    l1_curator.enrich(
        project,
        system_edges=[SystemEdgeDelta(service_slug="sales-analysis", kind="RESTApi", rel="EXPOSED_VIA", provenance=PROV),
                      SystemEdgeDelta(service_slug="sales-analysis", kind="AuthorizationSystem", rel="AUTHORIZED_BY", role="seller", provenance=PROV)],
        merge_fn=mf,
    )
    exposed = session.run(
        "MATCH (:L1Service {project_id: $p, business_function_slug: 'sales-analysis'})-[:EXPOSED_VIA]->(:L1System {kind: 'RESTApi'}) RETURN count(*) AS c", p=project,
    ).single()["c"]
    authz = session.run(
        "MATCH (:L1Service {project_id: $p})-[r:AUTHORIZED_BY {role: 'seller'}]->(:L1System {kind: 'AuthorizationSystem'}) RETURN count(r) AS c", p=project,
    ).single()["c"]
    assert exposed == 1 and authz == 1
