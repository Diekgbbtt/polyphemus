import json
from typing import Any

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from polymerhus.app.config import config
from polymerhus.ingestion.contracts import SourceRecord, SourceStatus

def check() -> bool:
    with psycopg.connect(config.POSTGRES_DSN, connect_timeout=3) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        return cur.fetchone()[0] == 1

async def ensure_checkpoint_tables() -> None:
    """Create LangGraph checkpoint tables (idempotent)."""
    async with AsyncPostgresSaver.from_conn_string(config.POSTGRES_DSN) as saver:
        await saver.setup()


# --- Recon pipeline registry (sync, mirrors check()'s psycopg pattern) -----

_TERMINAL_RUN_STATUSES = {"complete", "failed"}
_TERMINAL_JOB_STATUSES = {"success", "degraded", "failed", "skipped"}

# Out-of-band phase sentinel: a targeted AnalyserReconRequest job (interface
# agreement B) runs OUTSIDE the linear phase plan, so it is stored with a
# negative phase that no pipeline phase index can collide with. The row stays
# uniquely keyed by the existing UNIQUE(run_id, phase, job) via a
# correlation-qualified job name (see record_targeted_job).
TARGETED_PHASE = -1

# Forward, additive migrations applied at runtime so the persistent dev DB and
# CI self-heal without a volume reset (init.sql's docker-entrypoint-initdb.d
# mount only runs on first volume init). Each is idempotent (IF NOT EXISTS) and
# is ALSO present in db/postgres/init.sql as the fresh-clone baseline; keep the
# two in sync. Applied at startup (src/polymerhus/app/main.py) and by test fixtures.
_RECON_SCHEMA_MIGRATIONS = (
    "ALTER TABLE recon_jobs ADD COLUMN IF NOT EXISTS correlation_id TEXT",
    "ALTER TABLE recon_jobs ADD COLUMN IF NOT EXISTS requester_id TEXT",
    "ALTER TABLE recon_jobs ADD COLUMN IF NOT EXISTS origin TEXT",
    "CREATE INDEX IF NOT EXISTS recon_jobs_correlation_idx ON recon_jobs (correlation_id)",
    # #34: run-level analysis stats. The guarantee this design makes is
    # at-least-once OBSERVATION of surface, and `analysis_drained` is decided from
    # what the terminal pass actually read - so the counters must be durable and
    # assertable, not merely logged. Additive JSONB, inert to every existing reader.
    "ALTER TABLE recon_runs ADD COLUMN IF NOT EXISTS stats JSONB NOT NULL DEFAULT '{}'::jsonb",
    # #75: analysis is its own run with its own row, INDEPENDENT of the recon run.
    # A surrogate PK (`analysis_run_id`) with `run_id` as a NON-UNIQUE indexed
    # correlation column (D5): a later relaunch - a fresh analysis attempt over the
    # same recon run after a teardown - must never collide on a key, so run_id is
    # deliberately not UNIQUE. The 1:1 read path (get_analysis_run) is a convention
    # over this shape (latest attempt wins), not a hard uniqueness constraint.
    "CREATE TABLE IF NOT EXISTS analysis_runs ("
    "  analysis_run_id TEXT PRIMARY KEY,"
    "  run_id          TEXT NOT NULL,"
    "  project_id      TEXT NOT NULL,"
    "  status          TEXT NOT NULL,"
    "  started_at      TIMESTAMPTZ,"
    "  finished_at     TIMESTAMPTZ,"
    "  stats           JSONB NOT NULL DEFAULT '{}'::jsonb"
    ")",
    "CREATE INDEX IF NOT EXISTS analysis_runs_run_idx ON analysis_runs (run_id)",
)

# Analysis-run statuses (#75). `draining` is the only live state; the rest are
# terminal. `withheld` = the terminal marker was consumed but non-vacuity failed
# (no pass entered a dispatch), `stopped` = a graceful operator stop left the
# queue non-empty, `interrupted` = the process died mid-drain (startup reconcile,
# D10). Kept here so every writer agrees on the vocabulary.
_TERMINAL_ANALYSIS_STATUSES = {"drained", "withheld", "stopped", "interrupted"}

# #110: the hunting-run lifecycle status table. One row per hunting run with a
# surrogate `hunting_run_id` PK (`running` is the only live state; the rest are
# terminal). The graph engine is an in-memory actor per run, so the row is the
# durable footprint of that lifecycle. Mirrored in db/postgres/init.sql; applied
# at boot by ensure_hunting_schema() (the same self-heal discipline as the
# recon migrations).
_HUNTING_SCHEMA_MIGRATIONS = (
    "CREATE TABLE IF NOT EXISTS hunting_runs ("
    "  hunting_run_id TEXT PRIMARY KEY,"
    "  project_id     TEXT NOT NULL,"
    "  status         TEXT NOT NULL,"
    "  started_at     TIMESTAMPTZ,"
    "  finished_at    TIMESTAMPTZ"
    ")",
    "CREATE INDEX IF NOT EXISTS hunting_runs_project_idx ON hunting_runs (project_id)",
)

# Hunting-run statuses (#110). `running` is the only live state; the rest are
# terminal: `complete` = orchestration persisted its terminal report, `stopped` =
# phase-1 operator stop, `failed` = the run errored but persisted (fail-open),
# `interrupted` = the process died mid-run (startup reconcile). Kept here so
# every writer agrees on the vocabulary.
_TERMINAL_HUNTING_STATUSES = {"complete", "stopped", "failed", "interrupted"}


def ensure_recon_schema() -> None:
    """Apply the idempotent recon-registry migrations. Mirrors
    neo4j_client.ensure_schema (runtime schema application) for the Postgres
    side, so an already-initialised DB gains the interface-B columns without a
    destructive volume reset. Safe to call repeatedly."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        for stmt in _RECON_SCHEMA_MIGRATIONS:
            cur.execute(stmt)


def ensure_hunting_schema() -> None:
    """Apply the idempotent hunting-runs migrations (#110). Mirrored in
    db/postgres/init.sql; applied at boot so the persistent dev DB and CI
    self-heal without a volume reset. Safe to call repeatedly."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        for stmt in _HUNTING_SCHEMA_MIGRATIONS:
            cur.execute(stmt)


def set_run_stats(run_id: str, stats: dict) -> None:
    """Merge run-level stats onto the run row (#34). Additive and idempotent: the
    JSONB concatenation overwrites only the keys supplied, so a later writer of a
    different key cannot clobber an earlier one."""
    import json

    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recon_runs SET stats = COALESCE(stats, '{}'::jsonb) || %s::jsonb "
            "WHERE run_id = %s",
            (json.dumps(stats or {}), run_id),
        )


# --- analysis runs (#75): analysis is its own run, decoupled from the recon run ---

def create_analysis_run(analysis_run_id: str, run_id: str, project_id: str) -> None:
    """Open an analysis-run row in the live `draining` state. Idempotent on the
    surrogate PK. `run_id` correlates it to its recon run but is NOT unique, so a
    relaunch (a fresh analysis_run_id over the same run_id) inserts cleanly (D5)."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO analysis_runs (analysis_run_id, run_id, project_id, status, started_at) "
            "VALUES (%s, %s, %s, 'draining', now()) "
            "ON CONFLICT (analysis_run_id) DO NOTHING",
            (analysis_run_id, run_id, project_id),
        )


def set_analysis_run_status(analysis_run_id: str, status: str, stats: dict | None = None) -> None:
    """Set an analysis run's status, stamping finished_at on a terminal status and
    merging any stats (additive JSONB, same discipline as set_run_stats)."""
    finished = "finished_at = now(), " if status in _TERMINAL_ANALYSIS_STATUSES else ""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE analysis_runs SET status = %s, {finished}"
            "stats = COALESCE(stats, '{}'::jsonb) || %s::jsonb "
            "WHERE analysis_run_id = %s",
            (status, json.dumps(stats or {}), analysis_run_id),
        )


def get_analysis_run(run_id: str) -> dict | None:
    """The 1:1 read path (D5): the LATEST analysis attempt for a recon run_id.
    Latest-attempt-wins is a convention over the non-unique run_id, so an observer
    that launched recon with a run_id finds the analysis result by that same id."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT analysis_run_id, run_id, project_id, status, started_at, finished_at, "
            "COALESCE(stats, '{}'::jsonb) FROM analysis_runs WHERE run_id = %s "
            "ORDER BY started_at DESC NULLS LAST LIMIT 1",
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "analysis_run_id": row[0], "run_id": row[1], "project_id": row[2],
            "status": row[3], "started_at": row[4], "finished_at": row[5], "stats": row[6],
        }


def reconcile_orphaned_analysis_runs() -> int:
    """Startup reconcile (D10): the in-memory queue dies with the process, so any
    analysis run left `draining` at boot has no live queue behind it. Flip it to
    `interrupted` - an honest terminal state - stamping why. Idempotent: a second
    boot finds nothing `draining`. Queue persistence (#88) later upgrades this to a
    true resume. Returns the number reconciled."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE analysis_runs SET status='interrupted', finished_at=now(), "
            "stats = COALESCE(stats, '{}'::jsonb) || jsonb_build_object("
            "  'interrupted', true,"
            "  'interrupted_at', to_char(now() AT TIME ZONE 'UTC', "
            "                            'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),"
            "  'interrupt_reason', 'process ended mid-drain: the in-memory chunk queue "
            "did not survive the restart (queue persistence is deferred to #88)'"
            ") WHERE status='draining'",
        )
        return cur.rowcount


# --- hunting runs (#110): the orchestration lifecycle's status row -------------

def create_hunting_run(project_id: str) -> str:
    """Open a hunting-run row in the live `running` state and return its surrogate
    `hunting_run_id` (generated here, not caller-supplied - the engine owns the
    lifecycle the row records). Idempotent on the surrogate PK."""
    import uuid

    hunting_run_id = str(uuid.uuid4())
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO hunting_runs (hunting_run_id, project_id, status, started_at) "
            "VALUES (%s, %s, 'running', now()) "
            "ON CONFLICT (hunting_run_id) DO NOTHING",
            (hunting_run_id, project_id),
        )
    return hunting_run_id


def set_hunting_run_status(hunting_run_id: str, status: str) -> None:
    """Set a hunting run's status, stamping finished_at on a terminal status."""
    finished = "finished_at = now(), " if status in _TERMINAL_HUNTING_STATUSES else ""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE hunting_runs SET status = %s, {finished}"
            " WHERE hunting_run_id = %s",
            (status, hunting_run_id),
        )


def get_hunting_run(hunting_run_id: str) -> dict | None:
    """The 1:1 read path for a hunting run's lifecycle row."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT hunting_run_id, project_id, status, started_at, finished_at "
            "FROM hunting_runs WHERE hunting_run_id = %s",
            (hunting_run_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "hunting_run_id": row[0], "project_id": row[1], "status": row[2],
            "started_at": row[3], "finished_at": row[4],
        }


def list_hunting_runs(project_id: str) -> list[dict]:
    """All of a project's hunting runs, oldest first."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT hunting_run_id, project_id, status, started_at, finished_at "
            "FROM hunting_runs WHERE project_id = %s ORDER BY started_at NULLS LAST",
            (project_id,),
        )
        return [
            {
                "hunting_run_id": r[0], "project_id": r[1], "status": r[2],
                "started_at": r[3], "finished_at": r[4],
            }
            for r in cur.fetchall()
        ]


def reconcile_orphaned_hunting_runs() -> int:
    """Startup reconcile (#110): the per-run orchestration actor is in-memory and
    dies with the process, so any hunting run left `running` at boot has no live
    engine behind it. Flip it to `interrupted` - an honest terminal state -
    stamping when. Idempotent: a second boot finds nothing `running`. Returns the
    number reconciled."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE hunting_runs SET status='interrupted', finished_at=now() "
            "WHERE status='running'",
        )
        return cur.rowcount


def create_project(project_id: str, name: str) -> None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (project_id, name) VALUES (%s, %s) "
            "ON CONFLICT (project_id) DO NOTHING",
            (project_id, name),
        )


def project_exists(project_id: str) -> bool:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE project_id = %s", (project_id,))
        return cur.fetchone() is not None


def load_settings(project_id: str) -> dict:
    """Return the project's `settings.recon` JSONB dict, or {} if no row."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT recon FROM settings WHERE project_id = %s", (project_id,))
        row = cur.fetchone()
        return row[0] if row else {}


def save_settings(project_id: str, recon: dict) -> None:
    """Upsert the project's `settings.recon` JSONB blob, MERGING the incoming
    keys into any existing settings (RECURSIVE JSONB merge, jsonb_deep_merge).

    A partial update must not wipe siblings it did not mention - at any depth:
    - a PUT that only adds `auth_context` must NOT drop `target_domain`
      (otherwise the run falls back to the example.com placeholder), and
    - a PUT that only sets `auth_context.credentials` must NOT drop a
      previously-stored `auth_context.cookies` (they are independent items).
    A plain `||` merges only the top level, so the nested auth_context would be
    replaced wholesale; jsonb_deep_merge descends into nested objects. Scalars
    and arrays (e.g. the cookies list) are still replaced by the incoming
    value, so setting cookies overwrites the whole list as expected."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO settings (project_id, recon) VALUES (%s, %s) "
            "ON CONFLICT (project_id) DO UPDATE SET "
            "recon = jsonb_deep_merge(settings.recon, EXCLUDED.recon)",
            (project_id, json.dumps(recon)),
        )


def create_run(run_id: str, project_id: str) -> None:
    """Insert a recon_runs row. Idempotent: the REST route creates the run
    synchronously so a poll right after launch sees it, and `run_pipeline`
    also calls this - the ON CONFLICT DO NOTHING makes the second call a
    harmless no-op (run_id is the PK)."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recon_runs (run_id, project_id, status, started_at, last_heartbeat_at) "
            "VALUES (%s, %s, %s, now(), now()) "
            "ON CONFLICT (run_id) DO NOTHING",
            (run_id, project_id, "running"),
        )


def set_run_status(run_id: str, status: str, current_phase: int | None = None) -> None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        if status in _TERMINAL_RUN_STATUSES:
            cur.execute(
                "UPDATE recon_runs SET status = %s, "
                "current_phase = COALESCE(%s, current_phase), "
                "finished_at = now(), last_heartbeat_at = now() WHERE run_id = %s",
                (status, current_phase, run_id),
            )
        else:
            cur.execute(
                "UPDATE recon_runs SET status = %s, "
                "current_phase = COALESCE(%s, current_phase), "
                "last_heartbeat_at = now() WHERE run_id = %s",
                (status, current_phase, run_id),
            )


def get_run(run_id: str) -> dict | None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, project_id, status, current_phase, started_at, finished_at, "
            "COALESCE(stats, '{}'::jsonb) "
            "FROM recon_runs WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "project_id": row[1],
            "status": row[2],
            "current_phase": row[3],
            "started_at": row[4],
            "finished_at": row[5],
            # `set_run_stats` wrote this from the run's first commit but nothing read
            # it back, so the feed's own report - including whether analysis drained -
            # was invisible to every consumer of a run. A write-only column is not a
            # record.
            "stats": row[6],
        }


def get_run_jobs(run_id: str) -> list[dict]:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, run_id, phase, job, status, started_at, finished_at, stats, error "
            "FROM recon_jobs WHERE run_id = %s ORDER BY id",
            (run_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "run_id": r[1],
                "phase": r[2],
                "job": r[3],
                "status": r[4],
                "started_at": r[5],
                "finished_at": r[6],
                "stats": r[7],
                "error": r[8],
            }
            for r in rows
        ]


def upsert_job(
    run_id: str,
    phase: int,
    job: str,
    status: str,
    stats: dict | None = None,
    error: str | None = None,
) -> None:
    """Insert a recon_jobs row. `finished_at` is set to now() when `status`
    is terminal (success/degraded/failed/skipped); left NULL otherwise
    (e.g. "in_progress")."""
    finished_at_expr = "now()" if status in _TERMINAL_JOB_STATUSES else "NULL"
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recon_jobs (run_id, phase, job, status, started_at, "
            f"finished_at, stats, error) VALUES (%s, %s, %s, %s, now(), {finished_at_expr}, %s, %s) "
            "ON CONFLICT (run_id, phase, job) DO UPDATE SET "
            "status = EXCLUDED.status, finished_at = EXCLUDED.finished_at, "
            "stats = EXCLUDED.stats, error = EXCLUDED.error",
            (run_id, phase, job, status, json.dumps(stats or {}), error),
        )
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() WHERE run_id = %s", (run_id,))


def touch_run_heartbeat(run_id: str) -> None:
    """Bump last_heartbeat_at to now() to prove the run's process is alive."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() WHERE run_id = %s", (run_id,))


def record_targeted_job(
    run_id: str,
    tool: str,
    status: str,
    *,
    correlation_id: str,
    requester_id: str,
    origin: str,
    stats: dict | None = None,
    error: str | None = None,
) -> None:
    """Persist a targeted AnalyserReconRequest job (interface agreement B) into
    recon_jobs, carrying correlation_id/requester_id/origin so the result is
    retrievable by correlation_id (get_job_by_correlation) and routable back to
    requester_id.

    Stored at the out-of-band TARGETED_PHASE with a correlation-qualified job
    name so it never collides with a linear-phase job of the same tool under the
    existing UNIQUE(run_id, phase, job); re-recording the same correlation_id is
    an idempotent upsert of its status/stats."""
    finished_at_expr = "now()" if status in _TERMINAL_JOB_STATUSES else "NULL"
    job_name = f"targeted:{tool}:{correlation_id}"
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recon_jobs (run_id, phase, job, status, started_at, "
            f"finished_at, stats, error, correlation_id, requester_id, origin) "
            f"VALUES (%s, %s, %s, %s, now(), {finished_at_expr}, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, phase, job) DO UPDATE SET "
            "status = EXCLUDED.status, finished_at = EXCLUDED.finished_at, "
            "stats = EXCLUDED.stats, error = EXCLUDED.error, "
            "correlation_id = EXCLUDED.correlation_id, "
            "requester_id = EXCLUDED.requester_id, origin = EXCLUDED.origin",
            (run_id, TARGETED_PHASE, job_name, status, json.dumps(stats or {}),
             error, correlation_id, requester_id, origin),
        )
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() WHERE run_id = %s", (run_id,))


def get_job_by_correlation(correlation_id: str) -> dict | None:
    """Return the targeted-recon registry row for a correlation_id, or None.
    The reader half of interface agreement B's routed-result contract."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, run_id, phase, job, status, stats, error, "
            "correlation_id, requester_id, origin "
            "FROM recon_jobs WHERE correlation_id = %s ORDER BY id DESC LIMIT 1",
            (correlation_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "run_id": row[1], "phase": row[2], "job": row[3],
            "status": row[4], "stats": row[5], "error": row[6],
            "correlation_id": row[7], "requester_id": row[8], "origin": row[9],
        }


_JOB_COUNT_KEYS = ("in_progress", "success", "degraded", "skipped", "failed")


def list_running_runs() -> list[dict]:
    """Return running runs joined to project name, each with per-status job counts.
    Liveness is NOT derived here (the endpoint does that with the TTL)."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT r.run_id, r.project_id, p.name, r.status, r.current_phase, "
            "r.started_at, r.last_heartbeat_at "
            "FROM recon_runs r JOIN projects p ON p.project_id = r.project_id "
            "WHERE r.status = 'running' ORDER BY r.started_at DESC NULLS LAST"
        )
        runs = cur.fetchall()
        cur.execute(
            "SELECT run_id, status, count(*) FROM recon_jobs "
            "WHERE run_id IN (SELECT run_id FROM recon_runs WHERE status='running') "
            "GROUP BY run_id, status"
        )
        counts: dict[str, dict[str, int]] = {}
        for run_id, status, n in cur.fetchall():
            counts.setdefault(run_id, {})[status] = n
    out = []
    for run_id, project_id, name, status, phase, started, hb in runs:
        c = counts.get(run_id, {})
        jobs = {k: int(c.get(k, 0)) for k in _JOB_COUNT_KEYS}
        jobs["total"] = sum(jobs.values())
        out.append({
            "run_id": run_id, "project_id": project_id, "project_name": name,
            "status": status, "current_phase": phase,
            "started_at": started, "last_heartbeat_at": hb, "jobs": jobs,
        })
    return out


def reap_stale_runs(ttl_seconds: int) -> int:
    """Flip running runs whose heartbeat is older than ttl_seconds (or NULL)
    to failed, stamping finished_at. Returns the number reaped.

    Records WHY into the run's stats. A reaped run is one whose process stopped
    without saying anything - it was killed, its container was recreated
    underneath it, or the host went away - so the reaper is the only witness that
    exists, and a bare `failed` makes that indistinguishable from a run that
    failed on its own terms. Diagnosing run 6b9358a0 meant hand-correlating a
    frozen `last_heartbeat_at` against a container's `StartedAt`; `reaped_at` plus
    the heartbeat age puts that correlation in the row itself."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recon_runs SET status='failed', finished_at=now(), "
            "stats = COALESCE(stats, '{}'::jsonb) || jsonb_build_object("
            "  'reaped', true,"
            "  'reaped_at', to_char(now() AT TIME ZONE 'UTC', "
            "                       'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),"
            "  'reap_reason', 'heartbeat stale: the run process stopped without "
            "reaching a terminal status (killed, container recreated, or host lost)',"
            "  'heartbeat_age_s', "
            "     round(EXTRACT(EPOCH FROM (now() - last_heartbeat_at))::numeric, 1)"
            ") "
            "WHERE status='running' AND "
            "(last_heartbeat_at IS NULL OR last_heartbeat_at <= now() - make_interval(secs => %s))",
            (ttl_seconds,),
        )
        return cur.rowcount


def list_projects() -> list[dict]:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id, name, created_at FROM projects ORDER BY created_at DESC")
        return [{"project_id": r[0], "name": r[1], "created_at": r[2]} for r in cur.fetchall()]
def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


def save_methodology_bundle(run_id: str, query, bundle) -> int | None:
    query_payload = _jsonable(query)
    bundle_payload = _jsonable(bundle)
    query_id = query_payload.get("query_id") or bundle_payload.get("query_id")
    if not query_id:
        raise ValueError("methodology bundle persistence requires query_id")
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO methodology_bundles (run_id, query_id, query, bundle) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (run_id, query_id, json.dumps(query_payload), json.dumps(bundle_payload)),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_methodology_bundles(run_id: str) -> list[dict]:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, run_id, query_id, query, bundle, created_at "
            "FROM methodology_bundles WHERE run_id = %s ORDER BY id",
            (run_id,),
        )
        return [
            {
                "id": r[0],
                "run_id": r[1],
                "query_id": r[2],
                "query": r[3],
                "bundle": r[4],
                "created_at": r[5],
            }
            for r in cur.fetchall()
        ]


# --- LightRAG document ingestion registry -----------------------------------

_TERMINAL_INGESTION_STATUSES = {
    SourceStatus.PROCESSED,
    SourceStatus.FAILED,
    SourceStatus.SKIPPED_DUPLICATE,
    SourceStatus.FAILED_AUDIT,
}


def _source_select_columns() -> str:
    return (
        "source_key, source_kind, source_uri, content_hash, status, source_metadata, "
        "parser, parser_version, normalization_version, lightrag_document_id, "
        "normalized_markdown_path, normalized_json_path, "
        "last_error_code, last_error_message"
    )


def get_ingestion_source(source_key: str) -> SourceRecord | None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_source_select_columns()} FROM ingestion_sources WHERE source_key = %s",
            (source_key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _source_record_from_row(row)


def get_processed_ingestion_source_by_hash(content_hash: str | None) -> SourceRecord | None:
    if content_hash is None:
        return None

    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {_source_select_columns()} FROM ingestion_sources "
            "WHERE content_hash = %s AND status = %s AND content_hash IS NOT NULL "
            "ORDER BY updated_at DESC LIMIT 1",
            (content_hash, SourceStatus.PROCESSED.value),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _source_record_from_row(row)


def _source_record_from_row(row) -> SourceRecord:
    return SourceRecord(
        source_key=row[0],
        source_kind=row[1],
        source_uri=row[2],
        content_hash=row[3],
        status=SourceStatus(row[4]),
        source_metadata=row[5] or {},
        parser=row[6],
        parser_version=row[7],
        normalization_version=row[8],
        lightrag_document_id=row[9],
        normalized_markdown_path=row[10],
        normalized_json_path=row[11],
        last_error_code=row[12],
        last_error_message=row[13],
    )


def upsert_ingestion_source(record: SourceRecord) -> None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_sources ("
            "source_key, source_kind, source_uri, content_hash, status, source_metadata, "
            "parser, parser_version, normalization_version, lightrag_document_id, "
            "normalized_markdown_path, normalized_json_path, last_error_code, last_error_message"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (source_key) DO UPDATE SET "
            "source_kind = EXCLUDED.source_kind, "
            "source_uri = EXCLUDED.source_uri, "
            "content_hash = EXCLUDED.content_hash, "
            "status = EXCLUDED.status, "
            "source_metadata = EXCLUDED.source_metadata, "
            "parser = EXCLUDED.parser, "
            "parser_version = EXCLUDED.parser_version, "
            "normalization_version = EXCLUDED.normalization_version, "
            "lightrag_document_id = EXCLUDED.lightrag_document_id, "
            "normalized_markdown_path = EXCLUDED.normalized_markdown_path, "
            "normalized_json_path = EXCLUDED.normalized_json_path, "
            "last_error_code = EXCLUDED.last_error_code, "
            "last_error_message = EXCLUDED.last_error_message, "
            "updated_at = now()",
            (
                record.source_key,
                record.source_kind,
                record.source_uri,
                record.content_hash,
                record.status.value,
                json.dumps(record.source_metadata) if record.source_metadata else "{}",
                record.parser,
                record.parser_version,
                record.normalization_version,
                record.lightrag_document_id,
                record.normalized_markdown_path,
                record.normalized_json_path,
                record.last_error_code,
                record.last_error_message,
            ),
        )


def create_ingestion_job(job_id: str, source_key: str, status: SourceStatus) -> None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_jobs (job_id, source_key, status) VALUES (%s, %s, %s) "
            "ON CONFLICT (job_id) DO NOTHING",
            (job_id, source_key, status.value),
        )


def get_ingestion_job(job_id: str) -> dict | None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT j.job_id, j.source_key, s.source_uri, j.status, s.content_hash, "
            "s.lightrag_document_id, j.audit, j.error, j.finished_at "
            "FROM ingestion_jobs j "
            "JOIN ingestion_sources s ON s.source_key = j.source_key "
            "WHERE j.job_id = %s",
            (job_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "job_id": str(row[0]),
            "source_key": row[1],
            "source_uri": row[2],
            "status": row[3],
            "content_hash": row[4],
            "lightrag_document_id": row[5],
            "audit": row[6],
            "error": row[7],
        }


def set_ingestion_job_status(
    job_id: str,
    status: SourceStatus,
    *,
    error: dict | None = None,
    audit: dict | None = None,
) -> None:
    finished_at_expr = "now()" if status in _TERMINAL_INGESTION_STATUSES else "NULL"
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_jobs SET status = %s, audit = %s, error = %s, "
            f"updated_at = now(), finished_at = {finished_at_expr} WHERE job_id = %s",
            (
                status.value,
                json.dumps(audit) if audit is not None else None,
                json.dumps(error) if error is not None else None,
                job_id,
            ),
        )


# --- Milestone 4 schema migration (explicit, idempotent) --------------------
# Existing pg-data volumes must run this before using URL ingestion.
# init.sql only initializes a *fresh* database; this function is the migration
# path for volumes that already have ingestion_sources without source_metadata
# and with content_hash NOT NULL.

_URL_INGESTION_MIGRATION_SQL = [
    "ALTER TABLE ingestion_sources ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE ingestion_sources ALTER COLUMN content_hash DROP NOT NULL",
]

def apply_url_ingestion_migrations() -> None:
    """Idempotently migrate an existing PostgreSQL volume for Milestone 4.

    Safe to run against a fresh init.sql database; each statement is a no-op
    if the new schema is already present.
    """
    with psycopg.connect(config.POSTGRES_DSN) as conn:
        with conn.cursor() as cur:
            for statement in _URL_INGESTION_MIGRATION_SQL:
                cur.execute(statement)
