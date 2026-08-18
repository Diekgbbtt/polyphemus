CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
    project_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS settings (
    project_id  TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    recon       JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Recursive JSONB merge: like the `||` operator but descends into nested
-- objects instead of replacing them wholesale. Used by save_settings so a
-- partial PUT that touches one nested item (e.g. auth_context.credentials)
-- preserves its independent siblings (e.g. auth_context.cookies). Non-object
-- values (scalars, arrays like the cookies list) are replaced by the incoming
-- side, so setting cookies still overwrites the whole cookie list as expected.
CREATE OR REPLACE FUNCTION jsonb_deep_merge(a jsonb, b jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN jsonb_typeof(a) = 'object' AND jsonb_typeof(b) = 'object' THEN
            COALESCE(
                (SELECT jsonb_object_agg(
                    k,
                    CASE
                        WHEN a ? k AND b ? k THEN jsonb_deep_merge(a -> k, b -> k)
                        WHEN b ? k THEN b -> k
                        ELSE a -> k
                    END)
                 FROM (
                    SELECT jsonb_object_keys(a) AS k
                    UNION
                    SELECT jsonb_object_keys(b)
                 ) keys),
                '{}'::jsonb)
        ELSE b
    END
$$;
CREATE TABLE IF NOT EXISTS recon_runs (
    run_id        TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    status        TEXT NOT NULL,
    current_phase INT,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS recon_jobs (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    phase       INT,
    job         TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    stats       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error       TEXT,
    CONSTRAINT recon_jobs_run_phase_job_key UNIQUE (run_id, phase, job)
);
-- #75: analysis is its own run, decoupled from the recon run. Surrogate PK with
-- run_id a NON-UNIQUE indexed correlation column so a relaunch never collides (D5).
CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_run_id TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    stats           JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS analysis_runs_run_idx ON analysis_runs (run_id);
-- #110: the hunting-run lifecycle status row. `running` is the only live state;
-- the rest are terminal (complete | stopped | failed | interrupted). Also applied
-- at runtime by app/clients/pg.py::ensure_hunting_schema so the persistent dev
-- DB and CI self-heal without a volume reset.
CREATE TABLE IF NOT EXISTS hunting_runs (
    hunting_run_id TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL,
    status         TEXT NOT NULL,
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS hunting_runs_project_idx ON hunting_runs (project_id);
ALTER TABLE recon_runs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS recon_runs_status_idx ON recon_runs (status);
-- Interface agreement B (L1D-26): a targeted AnalyserReconRequest job carries a
-- correlation_id (result routed back by it), a requester_id (…to this agent
-- instance), and an origin (analyser|anatomy_skill). Idempotent, mirroring the
-- last_heartbeat_at ALTER above. Also applied at runtime by
-- agent/app/clients/pg.py::ensure_recon_schema so the persistent dev DB and CI
-- self-heal without a volume reset (init.sql only runs on first volume init).
-- #34: run-level analysis stats (analysis_drained + the terminal pass's census).
ALTER TABLE recon_runs ADD COLUMN IF NOT EXISTS stats JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE recon_jobs ADD COLUMN IF NOT EXISTS correlation_id TEXT;
ALTER TABLE recon_jobs ADD COLUMN IF NOT EXISTS requester_id   TEXT;
ALTER TABLE recon_jobs ADD COLUMN IF NOT EXISTS origin         TEXT;
CREATE INDEX IF NOT EXISTS recon_jobs_correlation_idx ON recon_jobs (correlation_id);
CREATE TABLE IF NOT EXISTS ingest_runs (
    ingest_id   TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    status      TEXT NOT NULL,
    per_source  JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieval   TEXT NOT NULL DEFAULT 'deferred',
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS doc_chunks (
    id          BIGSERIAL PRIMARY KEY,
    doc_ref     TEXT NOT NULL,
    source_type TEXT NOT NULL,
    anchor      JSONB NOT NULL,
    chunk_text  TEXT NOT NULL,
    ordinal     INT NOT NULL,
    embedding   vector(1024) NOT NULL,
    provenance  JSONB NOT NULL,
    project_id  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS doc_chunks_hnsw    ON doc_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS doc_chunks_doc_ref ON doc_chunks (doc_ref);
CREATE INDEX IF NOT EXISTS doc_chunks_anchor  ON doc_chunks USING gin (anchor);
CREATE TABLE IF NOT EXISTS methodology_bundles (
    id         BIGSERIAL PRIMARY KEY,
    run_id     TEXT NOT NULL,
    query_id   TEXT NOT NULL,
    query      JSONB NOT NULL,
    bundle     JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS methodology_bundles_run_id_idx ON methodology_bundles (run_id);
CREATE INDEX IF NOT EXISTS methodology_bundles_query_id_idx ON methodology_bundles (query_id);

CREATE TABLE IF NOT EXISTS ingestion_sources (
    source_key TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('file', 'url')),
    source_uri TEXT NOT NULL,
    content_hash TEXT,
    status TEXT NOT NULL,
    source_metadata JSONB NOT NULL DEFAULT '{}',
    parser TEXT,
    parser_version TEXT,
    normalization_version TEXT,
    lightrag_document_id TEXT,
    normalized_markdown_path TEXT,
    normalized_json_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error_code TEXT,
    last_error_message TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id UUID PRIMARY KEY,
    source_key TEXT NOT NULL REFERENCES ingestion_sources(source_key) ON DELETE CASCADE,
    status TEXT NOT NULL,
    audit JSONB,
    error JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_source_key_idx ON ingestion_jobs (source_key);
