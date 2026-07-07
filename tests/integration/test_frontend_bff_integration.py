import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

DSN, NEO = os.environ.get("POSTGRES_DSN"), os.environ.get("NEO4J_URI")
pytestmark = pytest.mark.skipif(not (DSN and NEO), reason="live PG+Neo4j required")


@pytest.fixture(scope="module")
def client():
    from agent.app.main import app
    return TestClient(app)


def _seed_project(client):
    r = client.post("/projects", json={"name": "int-" + uuid.uuid4().hex[:6]})
    return r.json()["project_id"]


# --- GET /projects ---
def test_projects_contract(client):
    pid = _seed_project(client)
    body = client.get("/projects").json()
    assert "projects" in body
    p = next(p for p in body["projects"] if p["project_id"] == pid)
    assert set(p) == {"project_id", "name", "created_at"}


# --- GET /projects/{id}/graph ---
def test_graph_contract_and_isolated_node(client):
    pid = _seed_project(client)
    from agent.app.clients import neo4j_client
    neo4j_client.merge("MERGE (n:Domain {name:$n, project_id:$p})", {"n": "seed.example", "p": pid})
    body = client.get(f"/projects/{pid}/graph").json()
    assert body["project_id"] == pid
    for n in body["nodes"]:
        assert set(n) == {"id", "name", "type", "properties"}
    for l in body["links"]:
        assert set(l) == {"source", "target", "type"}
    assert any(n["type"] == "Domain" and n["name"] == "seed.example" for n in body["nodes"])


def test_graph_unknown_project_404(client):
    assert client.get("/projects/nope/graph").status_code == 404


# --- GET /runs ---
def test_runs_only_running(client):
    assert client.get("/runs").status_code == 400
    assert client.get("/runs?status=complete").status_code == 400
    ok = client.get("/runs?status=running")
    assert ok.status_code == 200 and "liveness_ttl_seconds" in ok.json()


def test_runs_live_then_stalled_then_reaped(client):
    from agent.app.clients import pg
    pid = _seed_project(client)
    rid = str(uuid.uuid4())
    pg.create_run(rid, pid)
    live = next(r for r in client.get("/runs?status=running").json()["runs"] if r["run_id"] == rid)
    assert live["liveness"] == "live"
    assert set(live["jobs"]) == {"total", "in_progress", "success", "degraded", "skipped", "failed"}
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,))
        conn.commit()
    stalled = next(r for r in client.get("/runs?status=running").json()["runs"] if r["run_id"] == rid)
    assert stalled["liveness"] == "stalled"
    assert pg.reap_stale_runs(30) >= 1
    assert all(r["run_id"] != rid for r in client.get("/runs?status=running").json()["runs"])
