import os
import uuid
import psycopg
import pytest

from agent.app.clients import pg

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set (live PG)")


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
