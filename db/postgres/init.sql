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
ALTER TABLE recon_runs ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS recon_runs_status_idx ON recon_runs (status);
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
