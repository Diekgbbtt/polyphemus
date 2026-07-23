import os
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import pg_live_dsn

DSN = pg_live_dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="live PG not reachable")


@pytest.fixture(scope="module")
def client():
    from polymerhus.app.main import app
    return TestClient(app)


def test_get_projects_lists_created_project(client):
    from polymerhus.app.clients import pg
    pid = str(uuid.uuid4())
    pg.create_project(pid, "list-test")
    r = client.get("/projects")
    assert r.status_code == 200
    ids = [p["project_id"] for p in r.json()["projects"]]
    assert pid in ids


def test_get_runs_requires_running_status(client):
    assert client.get("/runs?status=complete").status_code == 400
    assert client.get("/runs").status_code == 400


def test_get_runs_marks_stalled(client):
    import psycopg
    from polymerhus.app.clients import pg
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "live-test")
    pg.create_run(rid, pid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,))
        conn.commit()
    body = client.get("/runs?status=running").json()
    assert body["liveness_ttl_seconds"] == 30
    row = next(r for r in body["runs"] if r["run_id"] == rid)
    assert row["liveness"] == "stalled"


def test_get_runs_marks_live(client):
    from polymerhus.app.clients import pg
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "live-test")
    pg.create_run(rid, pid)  # heartbeat now()
    row = next(r for r in client.get("/runs?status=running").json()["runs"] if r["run_id"] == rid)
    assert row["liveness"] == "live"


def test_graph_404_unknown_project(client):
    assert client.get("/projects/does-not-exist/graph").status_code == 404


def test_graph_shape_for_known_project(client):
    from polymerhus.app.clients import pg
    pid = str(uuid.uuid4())
    pg.create_project(pid, "graph-shape")
    r = client.get(f"/projects/{pid}/graph")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert isinstance(body["nodes"], list) and isinstance(body["links"], list)
