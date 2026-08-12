# LightRAG Ingestion Pipeline - Milestone 2

This document describes the safe update path added after Milestone 1.

## Current Result

Milestone 2 keeps the same visible n8n pipeline:

```text
inbox file
  -> n8n Local File Trigger
  -> FastAPI POST /v1/ingestions
  -> FastAPI processing and LightRAG control
  -> n8n polling
  -> processed/ or failed/
```

No parsing or LightRAG logic was moved into n8n.

The new behavior is for the same `source_key` with changed bytes:

```text
known source_key + same hash      -> SKIPPED_DUPLICATE
known source_key + different hash -> update job
new source_key                    -> new ingestion
```

## Update Strategy

For an update, the service preserves the active `PROCESSED` source record until the replacement is complete.

```text
active source remains PROCESSED
  -> parse and normalize new file
  -> if parsing fails, fail only the job
  -> delete previous LightRAG document contribution
  -> ingest new normalized document.md
  -> if new ingestion succeeds, replace registry hash/doc/artifact paths
  -> if new ingestion fails after delete, re-ingest previous normalized document.md
```

This avoids marking the source as updated before the new version is actually indexed.

## Files Changed

```text
agent/ingestion/contracts.py
agent/ingestion/lightrag_adapter.py
agent/ingestion/service.py
data/lightrag/preprocessing_pipeline/src/lightrag_docprep/parsers/__init__.py
data/lightrag/preprocessing_pipeline/src/lightrag_docprep/router.py
tests/conftest.py
tests/ingestion/test_contracts.py
tests/ingestion/test_lightrag_adapter.py
tests/ingestion/test_service.py
scripts/smoke_lightrag_update.sh
```

## LightRAG Delete API

The existing LightRAG HTTP client already exposes:

```text
DELETE /documents/delete_document
```

The ingestion adapter now wraps it as:

```python
delete_document(document_id, delete_llm_cache=True)
```

The adapter maps 4xx delete errors to non-retryable `LIGHTRAG_DELETE_FAILED` and connectivity/timeouts to retryable errors.

## Registry Behavior

The existing Postgres tables are still used:

```text
ingestion_sources
ingestion_jobs
```

No schema migration was added for Milestone 2.

During update submit, the service creates a new job but does not overwrite the existing `ingestion_sources` row. The source row is updated only after the new LightRAG ingestion succeeds, or after rollback restores the previous normalized artifact.

## Tests

Run the Milestone 2 non-credit test set:

```bash
/home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest \
  tests/ingestion/test_contracts.py \
  tests/ingestion/test_lightrag_adapter.py \
  tests/ingestion/test_service.py \
  -q
```

Run all ingestion tests:

```bash
/home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest tests/ingestion -q
```

Validate the update smoke script syntax without calling LightRAG:

```bash
sh -n scripts/smoke_lightrag_update.sh
```

Validate Compose without printing resolved secrets:

```bash
docker compose --env-file .env.example --profile lightrag config --quiet
```

## Manual Credit-Consuming Update Smoke

Run this only when you intentionally want to spend model/API credits:

```bash
ENV_FILE=.env scripts/smoke_lightrag_update.sh
```

The script:

1. writes `update-smoke-<timestamp>.md` to `data/ingestion/inbox/`;
2. waits for n8n and LightRAG to process v1;
3. writes a changed v2 file with the same filename back to `inbox/`;
4. waits for the latest job to become `PROCESSED` with a changed content hash;
5. verifies the final file is under `data/ingestion/processed/`.

Expected final line:

```text
update smoke ok: file:inbox/update-smoke-...md hash <old> -> <new>
```

## Inspect The Final Record

After the manual smoke, inspect the source and latest jobs:

```bash
docker compose --env-file .env --profile lightrag exec -T postgres \
  psql -U polymerhus -d polymerhus \
  -c "select source_key, status, content_hash, lightrag_document_id, normalized_markdown_path, normalized_json_path, last_error_code from ingestion_sources where source_key like 'file:inbox/update-smoke-%' order by updated_at desc limit 5;"
```

```bash
docker compose --env-file .env --profile lightrag exec -T postgres \
  psql -U polymerhus -d polymerhus \
  -c "select job_id, source_key, status, error, audit, created_at, updated_at from ingestion_jobs where source_key like 'file:inbox/update-smoke-%' order by created_at desc limit 10;"
```

## Known Limits

Milestone 2 does not implement deep graph audit. The audit object is still the Milestone 1 minimal placeholder:

```json
{
  "critical_issues": 0,
  "warnings": 0
}
```

Milestone 3 must replace that placeholder with real non-destructive graph/vector/KV/document-status checks.

The full repository test suite may still require optional dependencies outside this milestone, including HTML parser dependencies and recon agent dependencies. The relevant ingestion suite is the authoritative Milestone 2 verification.
