"""#75: the `analysis_runs` persistence contract - analysis as its own run,
decoupled from the recon run. Live-PG gated (mirrors test_reaper.py)."""
import uuid

import psycopg
import pytest

from polymerhus.app.clients import pg
from tests.conftest import pg_live_dsn

DSN = pg_live_dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="live PG not reachable")


def _seed_project() -> tuple[str, str]:
    pid, rid = str(uuid.uuid4()), str(uuid.uuid4())
    pg.create_project(pid, "analysis-run-test")
    return pid, rid


def test_create_and_read_the_1to1_analysis_run():
    """The 1:1 read path (D5): get_analysis_run returns the run keyed by recon run_id."""
    pid, rid = _seed_project()
    arid = f"{rid}:aaa"
    pg.create_analysis_run(arid, rid, pid)
    row = pg.get_analysis_run(rid)
    assert row is not None
    assert row["analysis_run_id"] == arid
    assert row["run_id"] == rid
    assert row["status"] == "draining"       # opens live
    assert row["finished_at"] is None


def test_terminal_status_stamps_finished_and_merges_stats():
    pid, rid = _seed_project()
    arid = f"{rid}:bbb"
    pg.create_analysis_run(arid, rid, pid)
    pg.set_analysis_run_status(arid, "drained", {"mode": "queued", "passes": 4})
    row = pg.get_analysis_run(rid)
    assert row["status"] == "drained"
    assert row["finished_at"] is not None
    assert row["stats"]["mode"] == "queued" and row["stats"]["passes"] == 4


def test_relaunch_over_the_same_run_id_does_not_collide(monkeypatch):
    """D5 forward constraint: a fresh analysis attempt over the SAME recon run_id
    (a relaunch after teardown) must INSERT cleanly - run_id is a non-unique indexed
    correlation column, not a UNIQUE key. Both rows exist; the 1:1 read returns the
    latest attempt."""
    pid, rid = _seed_project()
    first, second = f"{rid}:001", f"{rid}:002"
    pg.create_analysis_run(first, rid, pid)
    pg.set_analysis_run_status(first, "stopped")
    # a relaunch: same run_id, new surrogate id - must not raise a unique violation
    pg.create_analysis_run(second, rid, pid)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM analysis_runs WHERE run_id=%s", (rid,))
        assert cur.fetchone()[0] == 2               # both attempts persisted
    latest = pg.get_analysis_run(rid)
    assert latest["analysis_run_id"] == second      # latest-attempt-wins convention


def test_startup_reconcile_flips_orphaned_draining_to_interrupted():
    """D10: a run left `draining` by a prior crash has no live in-memory queue, so
    the boot sweep flips it to `interrupted` - idempotently, and without touching a
    row that already reached a terminal status."""
    pid, rid = _seed_project()
    pid2, rid2 = _seed_project()
    orphan, done = f"{rid}:orphan", f"{rid2}:done"
    pg.create_analysis_run(orphan, rid, pid)                       # left draining
    pg.create_analysis_run(done, rid2, pid2)
    pg.set_analysis_run_status(done, "drained")                    # already terminal

    n = pg.reconcile_orphaned_analysis_runs()
    assert n >= 1
    assert pg.get_analysis_run(rid)["status"] == "interrupted"
    assert pg.get_analysis_run(rid)["stats"]["interrupted"] is True
    assert pg.get_analysis_run(rid2)["status"] == "drained"        # untouched

    # idempotent: a second sweep finds nothing draining and does not re-touch it
    fin = pg.get_analysis_run(rid)["finished_at"]
    assert pg.reconcile_orphaned_analysis_runs() == 0
    assert pg.get_analysis_run(rid)["finished_at"] == fin
