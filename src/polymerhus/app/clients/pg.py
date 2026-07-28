import json

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from polymerhus.app.config import config

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
)


def ensure_recon_schema() -> None:
    """Apply the idempotent recon-registry migrations. Mirrors
    neo4j_client.ensure_schema (runtime schema application) for the Postgres
    side, so an already-initialised DB gains the interface-B columns without a
    destructive volume reset. Safe to call repeatedly."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        for stmt in _RECON_SCHEMA_MIGRATIONS:
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
