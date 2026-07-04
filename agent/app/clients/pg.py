import json

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agent.app.config import config

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
    """Upsert the project's `settings.recon` JSONB blob."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO settings (project_id, recon) VALUES (%s, %s) "
            "ON CONFLICT (project_id) DO UPDATE SET recon = EXCLUDED.recon",
            (project_id, json.dumps(recon)),
        )


def create_run(run_id: str, project_id: str) -> None:
    """Insert a recon_runs row. Idempotent: the REST route creates the run
    synchronously so a poll right after launch sees it, and `run_pipeline`
    also calls this - the ON CONFLICT DO NOTHING makes the second call a
    harmless no-op (run_id is the PK)."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recon_runs (run_id, project_id, status, started_at) "
            "VALUES (%s, %s, %s, now()) "
            "ON CONFLICT (run_id) DO NOTHING",
            (run_id, project_id, "running"),
        )


def set_run_status(run_id: str, status: str, current_phase: int | None = None) -> None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        if status in _TERMINAL_RUN_STATUSES:
            cur.execute(
                "UPDATE recon_runs SET status = %s, "
                "current_phase = COALESCE(%s, current_phase), "
                "finished_at = now() WHERE run_id = %s",
                (status, current_phase, run_id),
            )
        else:
            cur.execute(
                "UPDATE recon_runs SET status = %s, "
                "current_phase = COALESCE(%s, current_phase) WHERE run_id = %s",
                (status, current_phase, run_id),
            )


def get_run(run_id: str) -> dict | None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, project_id, status, current_phase, started_at, finished_at "
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
