# LightRAG Ingestion Pipeline - Milestone 1

This document describes the local Milestone 1 pipeline for automatic Markdown ingestion into a single LightRAG server.

## Current Result

The local stack supports this workflow:

```text
data/ingestion/inbox/
  -> n8n Local File Trigger
  -> FastAPI POST /v1/ingestions
  -> lightrag_docprep normalization
  -> document.md + document.json
  -> LightRAG document upload
  -> LightRAG status polling
  -> minimal post-ingestion audit record
  -> n8n moves original file to processed/ or failed/
```

The first Markdown copy is ingested into LightRAG. A second file with identical content but a different filename is classified as `SKIPPED_DUPLICATE`, reuses the existing LightRAG document id, and is not uploaded to LightRAG again.

## Runtime Layout

The host repository uses:

```text
data/ingestion/
├── inbox/
├── processed/
├── failed/
└── normalized/
```

The containers mount the same tree at:

```text
/data/ingestion/
```

Only `.gitkeep` files are versioned under `data/ingestion/`. Runtime documents and normalized artifacts are ignored by Git.

## Services

Milestone 1 uses one LightRAG service and one LightRAG storage directory:

```text
postgres   registry and job state
neo4j      existing project graph dependency
lightrag   single LightRAG API server
ingestion  FastAPI ingestion service
n8n        watched-folder orchestrator
```

`lightrag-writeups` is intentionally not part of this pipeline.

## Environment

Create and edit `.env` in the worktree:

```bash
cd /home/alelxsalc03/Desktop/polyphemus/.worktrees/lightrag-ingestion-m1
nano .env
```

Do not commit `.env`.

Required LightRAG embedding settings for Nemotron via OpenRouter:

```env
EMBEDDING_BINDING=openai
EMBEDDING_BINDING_HOST=https://openrouter.ai/api/v1
EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b:free
EMBEDDING_DIM=2048
EMBEDDING_USE_BASE64=false
EMBEDDING_BINDING_API_KEY=...
```

`EMBEDDING_USE_BASE64=false` is required because the OpenRouter/NVIDIA endpoint rejects base64 embeddings for this model.

Role-specific LightRAG LLM settings:

```env
EXTRACT_LLM_BINDING=openai
EXTRACT_LLM_BINDING_HOST=https://api.swissai.svc.cscs.ch/v1
EXTRACT_LLM_MODEL=RCP-AIaaS/Qwen/Qwen3-VL-30B-A3B-Instruct
EXTRACT_LLM_BINDING_API_KEY=...

KEYWORD_LLM_BINDING=openai
KEYWORD_LLM_BINDING_HOST=https://api.swissai.svc.cscs.ch/v1
KEYWORD_LLM_MODEL=RCP-AIaaS/Qwen/Qwen3-VL-30B-A3B-Instruct
KEYWORD_LLM_BINDING_API_KEY=...

QUERY_LLM_BINDING=openai
QUERY_LLM_BINDING_HOST=https://api.swissai.svc.cscs.ch/v1
QUERY_LLM_MODEL=<deepseek-swissai-model-slug>
QUERY_LLM_BINDING_API_KEY=...
```

n8n also requires a stable encryption key:

```env
N8N_ENCRYPTION_KEY=<stable-local-secret>
```

If the `n8n-data` Docker volume already exists, this key must match the key stored in the volume. Otherwise n8n exits with a mismatching encryption key error.

## Start The Stack

```bash
docker compose --env-file .env --profile lightrag up -d --build --remove-orphans lightrag ingestion n8n postgres neo4j
```

Check health:

```bash
docker compose --env-file .env --profile lightrag ps
```

Expected services:

```text
lightrag    healthy
ingestion   healthy
n8n         healthy
postgres    healthy
neo4j       healthy
```

## n8n Workflow

The workflow is versioned at:

```text
workflows/n8n/lightrag-file-ingestion.json
```

Import it:

```bash
docker compose --env-file .env --profile lightrag exec -T n8n \
  n8n import:workflow --input=/workflows/n8n/lightrag-file-ingestion.json
```

Activate it:

```bash
docker compose --env-file .env --profile lightrag exec -T n8n \
  n8n update:workflow --all --active=true
docker compose --env-file .env --profile lightrag restart n8n
```

The workflow nodes are:

```text
Inbox File Trigger
  -> Filter temp and hidden files
  -> Stabilization wait
  -> POST ingestion job
  -> Polling wait
  -> GET job status
  -> Terminal state?
      no -> Polling wait
      yes -> Success or duplicate?
          yes -> Move to processed
          no  -> Move to failed
```

The final move is done by n8n `Execute Command` nodes using `mv`. Domain parsing, hashing, deduplication, LightRAG API calls, and audit state remain in Python.

## FastAPI Contract

Submit a file:

```http
POST /v1/ingestions
Content-Type: application/json

{
  "source_kind": "file",
  "source_uri": "/data/ingestion/inbox/example.md"
}
```

Get status:

```http
GET /v1/ingestions/{job_id}
```

Terminal statuses:

```text
PROCESSED
SKIPPED_DUPLICATE
FAILED
```

## Registry

The registry tables are:

```text
ingestion_sources
ingestion_jobs
```

Inspect recent jobs:

```bash
docker compose --env-file .env --profile lightrag exec -T postgres \
  psql -U polymerhus -d polymerhus \
  -c "select j.job_id, j.source_key, j.status as job_status, s.status as source_status, s.content_hash, s.lightrag_document_id, j.audit, j.error from ingestion_jobs j join ingestion_sources s on s.source_key=j.source_key order by j.created_at desc limit 10;"
```

## Manual End-To-End Test

Create a Markdown file:

```bash
cat > data/ingestion/inbox/manual-test.md <<'EOF'
# Manual Ingestion Test

```http
GET /manual-test HTTP/1.1
Host: example.test
```

This document mentions SQL injection methodology and authentication bypass.
EOF
```

Do not call the parser manually. n8n should detect the file.

Verify processing:

```bash
docker compose --env-file .env --profile lightrag exec -T postgres \
  psql -U polymerhus -d polymerhus \
  -c "select j.source_key, j.status, s.lightrag_document_id, j.audit, j.error from ingestion_jobs j join ingestion_sources s on s.source_key=j.source_key where j.source_key='file:inbox/manual-test.md' order by j.created_at desc limit 1;"
```

Verify final move:

```bash
find data/ingestion/inbox data/ingestion/processed data/ingestion/failed \
  -maxdepth 1 -type f -name 'manual-test.md' -print
```

Expected:

```text
data/ingestion/processed/manual-test.md
```

## Automated Smoke Test

Run:

```bash
ENV_FILE=.env scripts/smoke_lightrag_ingestion.sh
```

Expected output:

```text
smoke ok: file:inbox/smoke-...md processed and file:inbox/smoke-...-duplicate.md skipped duplicate
```

The script:

1. writes a unique Markdown file to `inbox/`;
2. waits for `PROCESSED`;
3. waits for n8n to move it to `processed/`;
4. copies the same content under a different filename;
5. waits for `SKIPPED_DUPLICATE`;
6. waits for n8n to move the duplicate to `processed/`.

## Verification Commands

Local tests:

```bash
PYTHONPATH=data/lightrag/preprocessing_pipeline/src:/home/alelxsalc03/Desktop/polyphemus/data/lightrag/preprocessing_pipeline/.venv/lib/python3.12/site-packages \
/home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest \
  tests/ingestion \
  tests/test_pipeline_registry.py \
  tests/lightrag/test_client.py \
  tests/lightrag/test_ingest.py \
  -q
```

Compose validation:

```bash
docker compose --env-file .env --profile lightrag config --quiet
```

Service status:

```bash
docker compose --env-file .env --profile lightrag ps
```

## Current Audit Scope

Milestone 1 writes a minimal audit object after LightRAG ingestion reaches a processed terminal status:

```json
{
  "critical_issues": 0,
  "warnings": 0
}
```

This is enough to prove the pipeline control flow and persistence contract. Deep graph checks are intentionally deferred to Milestone 3, including:

- allowed entity type enforcement;
- relations with both endpoints;
- provenance checks for nodes and relations;
- graph/vector/KV/document-status consistency;
- non-destructive merge candidate reporting.

## Troubleshooting

If LightRAG exits with:

```text
embedding binding 'nvidia_openai' not supported
```

use:

```env
EMBEDDING_BINDING=openai
EMBEDDING_USE_BASE64=false
```

If embedding fails with:

```text
Nvidia embeddings do not support base64 encoding_format
```

confirm `EMBEDDING_USE_BASE64=false` is present in `.env` and passed through `docker-compose.yml`.

If n8n exits with a mismatching encryption key error, either:

1. restore the previous `N8N_ENCRYPTION_KEY` used by the existing `n8n-data` volume; or
2. reset the local n8n volume if no credentials/workflows need preserving.

If n8n logs:

```text
node execution output incorrect data
```

check that only one workflow named `LightRAG watched folder ingestion` is active, and that the active workflow uses `Execute Command` for file moves rather than `Read/Write Files from Disk` with `operation=move`.

List workflows:

```bash
docker compose --env-file .env --profile lightrag exec -T n8n n8n list:workflow
```

Deactivate an old duplicate:

```bash
docker compose --env-file .env --profile lightrag exec -T n8n \
  n8n update:workflow --id=<old-id> --active=false
docker compose --env-file .env --profile lightrag restart n8n
```

## Working With A Web LLM

When asking a web LLM to continue this work, provide this context:

```text
Repository: polyphemus
Worktree: /home/alelxsalc03/Desktop/polyphemus/.worktrees/lightrag-ingestion-m1
Goal: complete the local Milestone 1 watched-folder ingestion pipeline.

Architecture:
- n8n Local File Trigger watches /data/ingestion/inbox
- n8n calls FastAPI ingestion service
- FastAPI uses lightrag_docprep for parsing and normalization
- FastAPI uploads normalized document.md to a single LightRAG server
- FastAPI records job/source state in Postgres
- n8n polls job status and moves files to processed/ or failed/

Constraints:
- do not commit .env or runtime data
- do not reintroduce lightrag-writeups
- do not modify ontology in Milestone 1
- do not duplicate parsing/chunking in n8n
- keep n8n visible as trigger/orchestrator
```

Ask it to reason from the files and commands in this document rather than inventing a different architecture.
