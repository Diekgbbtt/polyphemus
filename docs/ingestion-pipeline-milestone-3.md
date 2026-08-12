# Ingestion Pipeline Milestone 3: Post-Ingestion LightRAG Audit

## Overview

Milestone 3 adds a **static audit** layer to the LightRAG ingestion pipeline. After a source has been processed and its artifacts written to LightRAG storage, the audit inspects a snapshot of that storage for consistency, provenance, and ontology compliance—without making any network, Docker, or external LLM calls.

The audit is designed to be **non-destructive**: it never modifies or deletes storage artifacts. It returns a structured `AuditReport` containing:

- `critical_issues`: list of `AuditIssue` objects that should block acceptance of the ingestion result.
- `warnings`: list of `AuditIssue` objects that indicate non-blocking concerns.
- `merge_candidates`: suggestions for duplicate nodes/edges that may be consolidated later.

## Files Introduced / Modified

- `agent/ingestion/audit.py` — core audit logic.
- `tests/ingestion/test_audit.py` — unit tests for the audit module.
- `scripts/smoke_lightrag_audit_static.sh` — shell script that runs the unit tests without external dependencies.

## Audit Checks

### Critical Checks

| Code | Condition |
|------|-----------|
| `LIGHTRAG_DOCUMENT_ID_MISSING` | Audit was called without a LightRAG document ID. |
| `DOCUMENT_STATUS_MISSING` | No status entry exists for the document ID. |
| `DOCUMENT_STATUS_FAILED` | Status is not in a successful terminal state (`processed`, `completed`, `done`). |
| `DOCUMENT_HAS_NO_CHUNKS` | Successful document has no linked text chunks. |
| `VECTOR_CHUNK_MISSING` | A KV text chunk belonging to the document has no corresponding vector chunk. |
| `KV_VECTOR_CHUNK_MISMATCH` | A vector chunk points to the document but has no KV text chunk. |
| `ENTITY_TYPE_NOT_ALLOWED` | Graph node uses an entity type outside the allowed set. |
| `ORPHAN_RELATION_ENDPOINT` | Graph edge references a source or target node that is not present. |
| `GRAPH_NODE_WITHOUT_PROVENANCE` | Graph node has an entity type but no `source_id`. |
| `GRAPH_EDGE_WITHOUT_PROVENANCE` | Graph edge has no `source_id`. |

### Warnings

| Code | Condition |
|------|-----------|
| `MISSING_STORAGE_FILE` | One or more expected storage files are absent. |
| `ONTOLOGY_DIVERGENCE` | Current LightRAG entity types differ from the previously agreed set. |
| `DOCUMENT_EXPLICIT_ZERO_CHUNKS` | Successful document explicitly reports `chunks_count: 0`. |

### Merge Candidates

- `entity_duplicate`: nodes with identical identity (`entity_type`, `source_id`, `file_path`, `description`, `keywords`).
- `relation_duplicate`: edges with identical identity (`source`, `target`, `source_id`, `description`, `keywords`).

## Storage Snapshot

The audit does not read directly from running services. Instead it uses `LightRAGStorageReader` to load a snapshot from filesystem artifacts:

- JSON files: `kv_store_doc_status.json`, `kv_store_full_docs.json`, `kv_store_text_chunks.json`, `kv_store_full_entities.json`, `kv_store_full_relations.json`, `kv_store_entity_chunks.json`, `kv_store_relation_chunks.json`
- Vector DB JSON files: `vdb_chunks.json`, `vdb_entities.json`, `vdb_relationships.json`
- GraphML file: `graph_chunk_entity_relation.graphml`

Missing files are recorded in `snapshot.missing_files` rather than raising an error. Malformed JSON or GraphML raises `StorageParseError`.

## Usage Example

