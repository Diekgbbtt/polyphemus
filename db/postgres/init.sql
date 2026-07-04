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
