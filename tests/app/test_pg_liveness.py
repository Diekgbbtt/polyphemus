import os
import uuid
import psycopg
import pytest

from agent.app.clients import pg

from tests.conftest import pg_live_dsn

DSN = pg_live_dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="live PG not reachable")


def _mk_project_and_run():
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "hb-test")
    pg.create_run(rid, pid)
    return pid, rid


def test_recon_runs_has_heartbeat_column_and_status_index():
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='recon_runs' AND column_name='last_heartbeat_at'"
        )
        assert cur.fetchone() is not None, "last_heartbeat_at column missing"
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='recon_runs_status_idx'")
        assert cur.fetchone() is not None, "recon_runs_status_idx missing"


def test_create_run_sets_heartbeat():
    _, rid = _mk_project_and_run()
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT last_heartbeat_at FROM recon_runs WHERE run_id=%s", (rid,))
        assert cur.fetchone()[0] is not None


def test_touch_run_heartbeat_advances_it():
    _, rid = _mk_project_and_run()
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recon_runs SET last_heartbeat_at = now() - interval '5 minutes' "
            "WHERE run_id=%s", (rid,))
        conn.commit()
    pg.touch_run_heartbeat(rid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT now() - last_heartbeat_at FROM recon_runs WHERE run_id=%s", (rid,))
        assert cur.fetchone()[0].total_seconds() < 10


def test_list_running_runs_includes_job_counts():
    pid, rid = _mk_project_and_run()
    pg.upsert_job(rid, 0, "subfinder", "success")
    pg.upsert_job(rid, 0, "amass", "in_progress")
    rows = [r for r in pg.list_running_runs() if r["run_id"] == rid]
    assert len(rows) == 1
    r = rows[0]
    assert r["project_name"] == "hb-test"
    assert r["jobs"]["success"] == 1 and r["jobs"]["in_progress"] == 1
    assert r["jobs"]["total"] == 2


def test_list_running_runs_excludes_terminal():
    pid, rid = _mk_project_and_run()
    pg.set_run_status(rid, "complete")
    assert all(r["run_id"] != rid for r in pg.list_running_runs())
