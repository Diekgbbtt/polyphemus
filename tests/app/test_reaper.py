import os, uuid, psycopg, pytest
from agent.app.clients import pg

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set (live PG)")


def test_reap_flips_stale_running_to_failed():
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "reap-test")
    pg.create_run(rid, pid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,))
        conn.commit()
    reaped = pg.reap_stale_runs(30)
    assert reaped >= 1
    assert pg.get_run(rid)["status"] == "failed"
    assert pg.get_run(rid)["finished_at"] is not None


def test_reap_leaves_fresh_running_alone():
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "reap-test")
    pg.create_run(rid, pid)  # heartbeat = now()
    pg.reap_stale_runs(30)
    assert pg.get_run(rid)["status"] == "running"
