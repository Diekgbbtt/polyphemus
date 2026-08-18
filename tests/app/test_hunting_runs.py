"""#110: the `hunting_runs` lifecycle persistence contract - one status row per
hunting run (`running` live -> `complete | stopped | failed | interrupted`
terminal), with the startup orphan reconcile. Live-PG gated (mirrors
test_analysis_runs.py / test_reaper.py)."""
import uuid

import pytest

from polymerhus.app.clients import pg
from tests.conftest import pg_live_dsn

DSN = pg_live_dsn()
pytestmark = pytest.mark.skipif(not DSN, reason="live PG not reachable")


def _seed_project() -> str:
    pid = str(uuid.uuid4())
    pg.create_project(pid, "hunting-run-test")
    return pid


def test_create_opens_running_and_reads_back():
    """create_hunting_run returns the surrogate id and opens the row `running`."""
    pid = _seed_project()
    hid = pg.create_hunting_run(pid)
    row = pg.get_hunting_run(hid)
    assert row is not None
    assert row["hunting_run_id"] == hid
    assert row["project_id"] == pid
    assert row["status"] == "running"
    assert row["finished_at"] is None


def test_surrogate_ids_are_distinct():
    """The engine owns the id - every create is a fresh surrogate, never a caller
    collision."""
    pid = _seed_project()
    assert pg.create_hunting_run(pid) != pg.create_hunting_run(pid)


def test_terminal_status_stamps_finished():
    pid = _seed_project()
    hid = pg.create_hunting_run(pid)
    pg.set_hunting_run_status(hid, "complete")
    row = pg.get_hunting_run(hid)
    assert row["status"] == "complete"
    assert row["finished_at"] is not None


def test_list_hunting_runs_is_project_scoped():
    p1, p2 = _seed_project(), _seed_project()
    h1 = pg.create_hunting_run(p1)
    pg.create_hunting_run(p2)
    runs = pg.list_hunting_runs(p1)
    assert [r["hunting_run_id"] for r in runs] == [h1]


def test_startup_reconcile_flips_orphaned_running_to_interrupted():
    """#110: a run left `running` by a prior crash has no live in-memory actor, so
    the boot sweep flips it to `interrupted` - idempotently, and without touching
    a row that already reached a terminal status."""
    pid, pid2 = _seed_project(), _seed_project()
    orphan, done = pg.create_hunting_run(pid), pg.create_hunting_run(pid2)
    pg.set_hunting_run_status(done, "complete")

    n = pg.reconcile_orphaned_hunting_runs()
    assert n >= 1
    assert pg.get_hunting_run(orphan)["status"] == "interrupted"
    assert pg.get_hunting_run(orphan)["finished_at"] is not None
    assert pg.get_hunting_run(done)["status"] == "complete"  # untouched

    # idempotent: a second sweep finds nothing running and does not re-touch it
    fin = pg.get_hunting_run(orphan)["finished_at"]
    assert pg.reconcile_orphaned_hunting_runs() == 0
    assert pg.get_hunting_run(orphan)["finished_at"] == fin