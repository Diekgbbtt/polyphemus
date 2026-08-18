# tests/test_pipeline_registry.py
"""Sync Postgres registry helpers for the recon pipeline orchestrator.

Fully mocked - `psycopg.connect` is monkeypatched to a fake connection/cursor
pair that records every executed statement, mirroring the sync
`with psycopg.connect(...) as conn, conn.cursor() as cur:` pattern already
used by `polymerhus.app.clients.pg.check()`. No live Postgres involved.
"""
import json

from polymerhus.app.clients import pg


class FakeCursor:
    def __init__(self, fetch_result=None):
        self.executed: list[tuple[str, tuple]] = []
        self._fetch_result = fetch_result

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetch_result

    def fetchall(self):
        return self._fetch_result if self._fetch_result is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def patch_connect(monkeypatch, cursor):
    monkeypatch.setattr(pg.psycopg, "connect", lambda *a, **kw: FakeConn(cursor))
    return cursor


def test_create_project_inserts_parameterised(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.create_project("proj1", "Project One")

    query, params = cur.executed[0]
    assert "INSERT INTO projects" in query
    assert "%s" in query
    assert params == ("proj1", "Project One")


def test_project_exists_true(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=(1,)))
    assert pg.project_exists("proj1") is True
    query, params = cur.executed[0]
    assert "SELECT 1 FROM projects" in query
    assert params == ("proj1",)


def test_project_exists_false(monkeypatch):
    patch_connect(monkeypatch, FakeCursor(fetch_result=None))
    assert pg.project_exists("proj1") is False


def test_load_settings_returns_recon_jsonb(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=({"auth_context": {"cookies": []}},)))
    result = pg.load_settings("proj1")
    assert result == {"auth_context": {"cookies": []}}
    query, params = cur.executed[0]
    assert "SELECT recon FROM settings" in query
    assert params == ("proj1",)


def test_load_settings_missing_row_returns_empty_dict(monkeypatch):
    patch_connect(monkeypatch, FakeCursor(fetch_result=None))
    assert pg.load_settings("proj1") == {}


def test_create_run_inserts_running_status(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.create_run("run1", "proj1")

    query, params = cur.executed[0]
    assert "INSERT INTO recon_runs" in query
    assert "ON CONFLICT (run_id) DO NOTHING" in query
    assert params[0] == "run1"
    assert params[1] == "proj1"
    assert "running" in params


def test_set_run_status_terminal_sets_finished_at(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.set_run_status("run1", "complete", current_phase=3)

    query, params = cur.executed[0]
    assert "finished_at = now()" in query
    assert "run1" in params
    assert "complete" in params
    assert 3 in params


def test_set_run_status_nonterminal_leaves_finished_at(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.set_run_status("run1", "running", current_phase=2)

    query, params = cur.executed[0]
    assert "finished_at = now()" not in query
    assert "run1" in params
    assert "running" in params
    assert 2 in params


def test_get_run_found(monkeypatch):
    # #34: `stats` rides the run row. It was written by `set_run_stats` from the
    # first commit but never selected, so the feed's report - including whether
    # analysis drained - could not be read back by anything.
    row = ("run1", "proj1", "running", 2, "t1", None, {"mode": "queued"})
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=row))
    result = pg.get_run("run1")

    assert result == {
        "run_id": "run1",
        "project_id": "proj1",
        "status": "running",
        "current_phase": 2,
        "started_at": "t1",
        "finished_at": None,
        "stats": {"mode": "queued"},
    }
    query, params = cur.executed[0]
    assert params == ("run1",)


def test_get_run_missing_returns_none(monkeypatch):
    patch_connect(monkeypatch, FakeCursor(fetch_result=None))
    assert pg.get_run("run1") is None


def test_get_run_jobs_returns_list_of_dicts(monkeypatch):
    rows = [
        (1, "run1", 0, "subfinder", "success", "t1", "t2", {"pods": 1}, None),
        (2, "run1", 1, "dnsx", "degraded", "t3", "t4", {"pods": 0}, "boom"),
    ]
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=rows))
    result = pg.get_run_jobs("run1")

    assert len(result) == 2
    assert result[0]["job"] == "subfinder"
    assert result[0]["status"] == "success"
    assert result[1]["job"] == "dnsx"
    assert result[1]["error"] == "boom"
    query, params = cur.executed[0]
    assert params == ("run1",)


def test_upsert_job_terminal_sets_finished_at_and_stats(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.upsert_job("run1", 0, "subfinder", "success", stats={"pods": 1, "success": 1, "failed": 0})

    query, params = cur.executed[0]
    assert "INSERT INTO recon_jobs" in query
    assert "now()" in query
    assert "ON CONFLICT (run_id, phase, job) DO UPDATE" in query
    assert "run1" in params
    assert 0 in params
    assert "subfinder" in params
    assert "success" in params
    stats_param = [p for p in params if isinstance(p, str) and "pods" in p]
    assert stats_param and json.loads(stats_param[0]) == {"pods": 1, "success": 1, "failed": 0}


def test_upsert_job_in_progress_leaves_finished_at_null(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.upsert_job("run1", 0, "subfinder", "in_progress")

    query, params = cur.executed[0]
    assert "INSERT INTO recon_jobs" in query
    assert "NULL" in query
    assert "ON CONFLICT (run_id, phase, job) DO UPDATE" in query


def test_upsert_job_second_call_same_key_uses_conflict_update_path(monkeypatch):
    """The terminal upsert for a (run, phase, job) already seeded as
    in_progress advances status/finished_at/stats/error via the conflict
    branch while preserving the original started_at (the first insert's
    now())."""
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.upsert_job("run1", 0, "subfinder", "in_progress")
    pg.upsert_job("run1", 0, "subfinder", "success", stats={"pods": 1})

    # upsert_job also fires a separate `UPDATE recon_runs SET last_heartbeat_at`
    # query; scope these assertions to the recon_jobs upsert only.
    job_upserts = [q for q, _ in cur.executed if "INTO recon_jobs" in q]
    assert job_upserts
    for query in job_upserts:
        assert "ON CONFLICT (run_id, phase, job) DO UPDATE" in query
        assert "status = EXCLUDED.status" in query
        assert "finished_at = EXCLUDED.finished_at" in query
        assert "stats = EXCLUDED.stats" in query
        assert "error = EXCLUDED.error" in query
        # started_at is only ever the INSERT's now() - never in the UPDATE SET.
        assert "started_at = EXCLUDED" not in query


def test_upsert_job_with_error(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.upsert_job("run1", 0, "subfinder", "failed", error="boom")

    query, params = cur.executed[0]
    assert "boom" in params


def test_save_settings_merges_rather_than_replaces(monkeypatch):
    """A partial settings PUT (e.g. adding auth_context) must MERGE into the
    stored recon, not replace it - otherwise it silently wipes target_domain
    and the run falls back to the example.com placeholder. The merge must be
    RECURSIVE so nested items are independent: setting auth_context.credentials
    must not wipe a previously-stored auth_context.cookies (and vice versa)."""
    cur = patch_connect(monkeypatch, FakeCursor())
    pg.save_settings("proj1", {"auth_context": {"cookies": []}})

    query, params = cur.executed[0]
    assert "INSERT INTO settings" in query
    # deep JSONB merge: nested objects merge key-by-key rather than the incoming
    # auth_context replacing the stored one wholesale.
    assert "jsonb_deep_merge(settings.recon, EXCLUDED.recon)" in query
    assert "settings.recon || EXCLUDED.recon" not in query
    assert params[0] == "proj1"


def test_save_methodology_bundle_inserts_append_only_json(monkeypatch):
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=(42,)))
    artifact_id = pg.save_methodology_bundle(
        "run1",
        {"query_id": "q1", "pattern": "target_state"},
        {"query_id": "q1", "summary": "Retrieved methodology"},
    )

    query, params = cur.executed[0]
    assert artifact_id == 42
    assert "INSERT INTO methodology_bundles" in query
    assert "ON CONFLICT" not in query
    assert "RETURNING id" in query
    assert params[0] == "run1"
    assert params[1] == "q1"
    assert json.loads(params[2]) == {"query_id": "q1", "pattern": "target_state"}
    assert json.loads(params[3]) == {"query_id": "q1", "summary": "Retrieved methodology"}


def test_get_methodology_bundles_returns_rows_for_run(monkeypatch):
    rows = [
        (
            7,
            "run1",
            "q1",
            {"query_id": "q1", "pattern": "target_state"},
            {"query_id": "q1", "summary": "Retrieved methodology"},
            "t1",
        )
    ]
    cur = patch_connect(monkeypatch, FakeCursor(fetch_result=rows))
    result = pg.get_methodology_bundles("run1")

    assert result == [
        {
            "id": 7,
            "run_id": "run1",
            "query_id": "q1",
            "query": {"query_id": "q1", "pattern": "target_state"},
            "bundle": {"query_id": "q1", "summary": "Retrieved methodology"},
            "created_at": "t1",
        }
    ]
    query, params = cur.executed[0]
    assert "FROM methodology_bundles WHERE run_id = %s ORDER BY id" in query
    assert params == ("run1",)
