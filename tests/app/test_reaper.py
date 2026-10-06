import os, uuid, psycopg, pytest
from polymerhus.app.clients import pg
from tests.conftest import pg_live_dsn

DSN = pg_live_dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="live PG not reachable")


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


def test_reap_records_why_the_run_was_reaped():
    """A reaped run's process stopped without saying anything, so the reaper is the
    only witness. A bare `failed` cannot be told apart from a run that failed on its
    own terms - diagnosing run 6b9358a0 meant hand-correlating a frozen heartbeat
    against a container's StartedAt, which the row should have carried itself."""
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "reap-test")
    pg.create_run(rid, pid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,))
        conn.commit()

    pg.reap_stale_runs(30)

    stats = pg.get_run(rid)["stats"]
    assert stats["reaped"] is True
    assert "heartbeat stale" in stats["reap_reason"]
    assert stats["heartbeat_age_s"] >= 600      # the 10 minutes we set
    assert stats["reaped_at"]


def test_reap_preserves_stats_a_run_already_wrote():
    """The feed writes `analysis_drained` and the timing census into the same column.
    A reaper that clobbered them would destroy the evidence it exists to preserve."""
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "reap-test")
    pg.create_run(rid, pid)
    pg.set_run_stats(rid, {"mode": "queued", "passes": 3, "advance_blocked_s_max": 0.01})
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() - interval '10 minutes' "
                    "WHERE run_id=%s", (rid,))
        conn.commit()

    pg.reap_stale_runs(30)

    stats = pg.get_run(rid)["stats"]
    assert stats["reaped"] is True          # the reaper's own keys are added...
    assert stats["mode"] == "queued"        # ...and the feed's survive
    assert stats["passes"] == 3
