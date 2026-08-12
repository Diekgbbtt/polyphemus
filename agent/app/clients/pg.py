import json
from typing import Any

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agent.app.config import config
from agent.ingestion.contracts import SourceRecord, SourceStatus

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
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() WHERE run_id = %s", (run_id,))


def touch_run_heartbeat(run_id: str) -> None:
    """Bump last_heartbeat_at to now() to prove the run's process is alive."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE recon_runs SET last_heartbeat_at = now() WHERE run_id = %s", (run_id,))


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
    to failed, stamping finished_at. Returns the number reaped."""
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recon_runs SET status='failed', finished_at=now() "
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
}


def get_ingestion_source(source_key: str) -> SourceRecord | None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT source_key, source_kind, source_uri, content_hash, status, "
            "parser, normalization_version, lightrag_document_id, "
            "normalized_markdown_path, normalized_json_path, "
            "last_error_code, last_error_message "
            "FROM ingestion_sources WHERE source_key = %s",
            (source_key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return SourceRecord(
            source_key=row[0],
            source_kind=row[1],
            source_uri=row[2],
            content_hash=row[3],
            status=SourceStatus(row[4]),
            parser=row[5],
            normalization_version=row[6],
            lightrag_document_id=row[7],
            normalized_markdown_path=row[8],
            normalized_json_path=row[9],
            last_error_code=row[10],
            last_error_message=row[11],
        )


def upsert_ingestion_source(record: SourceRecord) -> None:
    with psycopg.connect(config.POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_sources ("
            "source_key, source_kind, source_uri, content_hash, status, parser, "
            "parser_version, normalization_version, lightrag_document_id, "
            "normalized_markdown_path, normalized_json_path, last_error_code, last_error_message"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (source_key) DO UPDATE SET "
            "source_kind = EXCLUDED.source_kind, "
            "source_uri = EXCLUDED.source_uri, "
            "content_hash = EXCLUDED.content_hash, "
            "status = EXCLUDED.status, "
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
            "SELECT j.job_id, j.source_key, j.status, s.content_hash, "
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
            "status": row[2],
            "content_hash": row[3],
            "lightrag_document_id": row[4],
            "audit": row[5],
            "error": row[6],
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
