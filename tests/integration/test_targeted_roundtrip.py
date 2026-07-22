"""FR-RECONREQ integration tier — request_targeted_recon against the REAL
Postgres registry and (for idempotent ingest) the REAL Neo4j via the sanctioned
L0 curator. A fake run_job stands in for the kali/LLM pod so the SEAM (registry
persistence, in-process routing, idempotent ingest) is exercised without live
tool execution — the same dependency-injection discipline run_pipeline uses.

Encodes AST-RECONREQ-01/02/03 (docs/design/L1-MVP-plan.md §5).
"""
import asyncio
import uuid

import psycopg
import pytest
from neo4j import GraphDatabase

from agent.app.clients import pg
from agent.recon import curator
from agent.recon.targeted import AnalyserReconRequest, ReconScope, request_targeted_recon
from agent.recon.types import AssetDelta, PodExport
from db.neo4j.init_schema import init_schema
from tests.conftest import pg_live_dsn, wait_for

DSN = pg_live_dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="live PG not reachable")

from tests.conftest import neo4j_target

NEO4J_URI, NEO4J_AUTH = neo4j_target()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module", autouse=True)
def _recon_schema():
    pg.ensure_recon_schema()  # self-heal the interface-B columns on the live DB


@pytest.fixture
def run_ctx():
    pid, rid = "trq_" + uuid.uuid4().hex[:8], "trqrun_" + uuid.uuid4().hex[:8]
    pg.create_project(pid, "targeted-recon-it")
    pg.create_run(rid, pid)
    yield pid, rid
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM recon_jobs WHERE run_id = %s", (rid,))
        cur.execute("DELETE FROM recon_runs WHERE run_id = %s", (rid,))
        cur.execute("DELETE FROM settings WHERE project_id = %s", (pid,))
        cur.execute("DELETE FROM projects WHERE project_id = %s", (pid,))


# --- AST-RECONREQ-02: registry persists correlation/requester/origin, retrievable by correlation_id ---

def test_registry_carries_correlation_and_is_retrievable(run_ctx):
    pid, rid = run_ctx
    cid = "corr_" + uuid.uuid4().hex[:8]

    async def fake_run_job(job, input_assets, *, run_id, phase, extra):
        assert phase == pg.TARGETED_PHASE  # ran outside the linear phase plan
        return [PodExport(input_asset=input_assets[0] if input_assets else {}, verdict="success",
                          assets_merged=2, observations_merged=1)]

    req = AnalyserReconRequest(
        job="graphql-cop", requester_id="analyser-42", origin="analyser", correlation_id=cid,
        scope=ReconScope(service_id="sales-analysis", targets=["https://a/graphql"]),
    )
    result = _run(request_targeted_recon(req, rid, pid, run_job=fake_run_job))
    assert result.status == "success"

    row = pg.get_job_by_correlation(cid)
    assert row is not None
    assert row["correlation_id"] == cid
    assert row["requester_id"] == "analyser-42"
    assert row["origin"] == "analyser"
    assert row["run_id"] == rid
    assert row["phase"] == pg.TARGETED_PHASE
    assert row["status"] == "success"


def test_registry_status_upserts_on_same_correlation(run_ctx):
    pid, rid = run_ctx
    cid = "corr_" + uuid.uuid4().hex[:8]
    # first: a degraded run; then: re-record success for the SAME correlation_id
    pg.record_targeted_job(rid, "graphql-cop", "degraded", correlation_id=cid,
                           requester_id="r", origin="analyser", error="transient")
    pg.record_targeted_job(rid, "graphql-cop", "success", correlation_id=cid,
                           requester_id="r", origin="analyser", stats={"pods": 1})
    row = pg.get_job_by_correlation(cid)
    assert row["status"] == "success"  # upsert, not a duplicate row
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM recon_jobs WHERE correlation_id = %s", (cid,))
        assert cur.fetchone()[0] == 1


# --- AST-RECONREQ-03: ingest is idempotent and flows only through the sanctioned curator ---

def test_idempotent_ingest_via_curator_no_duplicate_on_replay(run_ctx):
    pid, rid = run_ctx
    endpoint_id = {"path": "/targeted-probe", "method": "GET", "baseurl": "https://trq"}

    driver = wait_for(lambda: _connected_driver(), timeout=30)
    try:
        with driver.session() as s:
            init_schema(s)
            s.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid).consume()

        async def fake_run_job(job, input_assets, *, run_id, phase, extra):
            # the pod's real work: curate canned deltas through the SANCTIONED L0
            # curator (the only L0 write path) into the real graph.
            merged, _ = curator.curate(
                [AssetDelta(type="Endpoint", identity=dict(endpoint_id), props={"status_code": 200})],
                [], pid,
            )
            return [PodExport(input_asset={}, verdict="success", assets_merged=merged, observations_merged=0)]

        req = AnalyserReconRequest(job="graphql-cop", requester_id="r",
                                   scope=ReconScope(targets=["https://trq/targeted-probe"]))
        for _ in range(2):  # replay the same targeted job
            _run(request_targeted_recon(req, rid, pid, run_job=fake_run_job))

        with driver.session() as s:
            c = s.run(
                "MATCH (e:Endpoint {project_id: $p, path: '/targeted-probe'}) RETURN count(e) AS c",
                p=pid,
            ).single()["c"]
            assert c == 1  # idempotent MERGE via the sanctioned curator: no duplicate
            s.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid).consume()
    finally:
        driver.close()


def _connected_driver():
    d = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    d.verify_connectivity()
    return d
