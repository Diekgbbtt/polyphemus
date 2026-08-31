# Documentation Ingestion Subsystem — Design (rev 1)

*Status: design consolidation, validated in brainstorming. Companion to `recon-mvp-design.md` (which specifies it at a high level in §6) and `evolution-paradigm.md` (Foundation 2b — bound documentation + sparse vector store). Scope: **iteration 1 of phase 1 — the operator-initiated documentation-ingestion write path only**. Retrieval, Layer-1 binding semantics, and code-source ingestion are deferred with explicit forward-compat seams (§8).*

---

## 1. Scope

**In (MVP).** An operator-initiated subsystem that, per requested source:

1. **Extracts** documentation for a target (tier-1 deterministic path first, bounded fallback),
2. **Chunks + embeds** it,
3. **Stores** chunks + vectors in a single **pgvector** corpus (`doc_chunks`), and
4. **Binds** the corpus to the Neo4j Layer-0 node it describes, by **node identity** (never a locator string).

Two source types are live in the MVP: **`openapi`/`graphql`** (target API contract) and **`web_map`** (target documentation site). The subsystem is **write-only**: it builds and binds the corpus; it does **not** query it.

**Out (deferred, with seams — §8).**
- **Retrieval** — reranking, MMR, hybrid full-text, `query()` — consumed by iteration-2 analysis. Vectors are nonetheless computed and stored now (the durable seam).
- **Code-source extractors** — `oss_codebase`, `target_codebase` — deferred to **iteration 2 (attack-surface analysis + Layer 1)**, where white-box source is actually consumed. The pipeline is unchanged when they land (extractor registry, §8).
- Multi-tenancy, scope/RoE enforcement (inherited from recon-mvp scope).

---

## 2. Technologies & dependencies

| Concern | Choice | Notes |
|---|---|---|
| Vector store | **pgvector** (`pgvector/pgvector:pg16`, already in the stack for LangGraph checkpoints) | `doc_chunks` table + HNSW index; single stateful backend, **no FAISS** |
| Embedding | The **LightRAG runtime** embeds at insert time (the agent-side `knowledge_base` embedder, local `e5-large-v2`, was never built) | `EMBEDDING_BINDING` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` config, consumed by the `lightrag` container (`.env`) |
| Chunking | Reuse `knowledge_base/chunking.ChunkStrategy` | `chunk_structured()` for OpenAPI/GraphQL JSON; `chunk_markdown()`/text for crawled pages |
| Document loading | Reuse `knowledge_base/document_store.load_document()` | source normalization |
| Static fetch | `execute_command` via `KALI_MCP_URL` (curl/httpx in Kali) | robots.txt, sitemap.xml, OpenAPI URL, GraphQL introspection |
| Agentic crawl | **Steel cloud browser** + reused `tradecraft_crawl` loop logic | JS-rendered doc sites; `STEEL_API_KEY` / `STEEL_BASE_URL` |
| Orchestration | Plain async pipeline (not a LangGraph subgraph) (D-c) | no fan-out/retry-loop; status via `ingest_runs` |

**Modules used (imported narrowly, wrapped):** `knowledge_base/{embedder,api_embedder,chunking,document_store}.py`; the **loop logic** of `agentic/orchestrator_helpers/tradecraft_crawl.py` (canonicalization, same-host/noise filters, LLM frontier-decision, sitemap assembly) — its fetch primitive is replaced by Steel. **Not used:** `faiss_indexer.py`, `reranker.py`, `kb_orchestrator.py`, MMR/full-text config (retrieval side, deferred).

**New dependency:** Steel service (SaaS `STEEL_API_KEY` or self-hosted `STEEL_BASE_URL`), added to the agent container config.

---

## 3. Components & ownership

| # | Component | Owns | Kind |
|---|---|---|---|
| 1 | **Ingest API** (`POST /projects/{id}/ingest`) | request validation, `ingest_id` mint, enqueue | new, thin (FastAPI) |
| 2 | **Ingestion pipeline** | per-source best-effort loop, status transitions, completion-event emission | new (async orchestrator) |
| 3 | **Extractor registry** | `source_type → Extractor` dispatch; unknown-type rejection | new, small |
| 4 | **`api_contract` extractor** | OpenAPI/Swagger fetch+parse, GraphQL introspection, infer-from-graph fallback | new |
| 5 | **`web_map` extractor / crawling agent** | Steel session lifecycle, budgeted doc-site traversal, sitemap assembly | new (reuses `tradecraft_crawl` logic) |
| 6 | **Anchor resolver** | resolve request anchor → Neo4j node identity; default-to-Domain; existence validation | new, small |
| 7 | **Chunker** | text/structured → ordered chunks | **reused** |
| 8 | **Embedder** | chunk → vector; `dimensions` contract | **reused** |
| 9 | **DocStore (pgvector)** | `doc_chunks` writes + HNSW; the deferred `query()` stub | new, thin (replaces `faiss_indexer`) |
| 10 | **Anchor binder** | write `doc_refs` onto the Neo4j node (identity-keyed MERGE) | new, small |
| 11 | **Ingest run registry** | `ingest_runs` state + per-source stats | new (Postgres) |

Each component has one purpose, a typed interface (§5), and a single owner of its side effects. The pipeline (2) is the only component that sequences the others; extractors (4/5) are the only components that touch the live target; the DocStore (9) is the only writer of `doc_chunks`; the anchor binder (10) is the only writer of `doc_refs` on Neo4j.

---

## 4. Data model

### 4.1 pgvector — `doc_chunks` (the corpus)

```sql
CREATE TABLE doc_chunks (
    id          BIGSERIAL PRIMARY KEY,
    doc_ref     TEXT NOT NULL,              -- doc:<source_type>:<anchor_hash>:<ingest_id>
    source_type TEXT NOT NULL,              -- openapi | graphql | web_map
    anchor      JSONB NOT NULL,             -- { node_type, identity{...} } — node IDENTITY, not a locator
    chunk_text  TEXT NOT NULL,
    ordinal     INT  NOT NULL,              -- chunk order within doc_ref
    embedding   vector(D) NOT NULL,         -- D = the embedding dimension
    provenance  JSONB NOT NULL,             -- { source_ref, tool, ingest_id, fetched_at }
    project_id  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX doc_chunks_hnsw ON doc_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX doc_chunks_doc_ref ON doc_chunks (doc_ref);
CREATE INDEX doc_chunks_anchor ON doc_chunks USING gin (anchor);
```

**Immutable / append-only.** Re-ingesting the same `(source_type, anchor)` mints a **new** `doc_ref` (the `<ingest_id>` suffix), so history + provenance are preserved; nothing is mutated or deleted in the MVP.

### 4.2 Neo4j — the graph↔corpus bridge

The anchored Layer-0 node carries a reference attribute (Foundation 2b: "node identity → document handles"), written by the anchor binder:

```cypher
MATCH (n) WHERE <identity predicate for the anchor node>
SET n.doc_refs = coalesce(n.doc_refs, []) + $doc_ref, n.last_seen = datetime()
```

`n.doc_refs` is a string array of `doc_ref`s. This is the `NEO ⇢ doc_ref ⇢ VEC` edge from `recon-mvp-design §2`. Because `doc_chunks.anchor` also stores the node identity, iteration-2 retrieval can traverse **either** direction: graph node → `doc_refs` → chunks, **or** semantic match → `anchor` → node.

### 4.3 Postgres — `ingest_runs` (registry)

```sql
CREATE TABLE ingest_runs (
    ingest_id   TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    status      TEXT NOT NULL,             -- queued | running | completed | partial | failed
    per_source  JSONB NOT NULL DEFAULT '[]',   -- [{ source_type, ref, doc_ref, chunks, anchor, status, error }]
    retrieval   TEXT NOT NULL DEFAULT 'deferred',
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
```

### 4.4 `doc_ref` format

`doc:<source_type>:<anchor_hash>:<ingest_id>` — e.g. `doc:openapi:9f3a…:ing_42`. `<anchor_hash>` = stable hash of the resolved node identity; `<ingest_id>` gives immutability + provenance.

---

## 5. Application & data contracts

### 5.1 REST (extends `recon-mvp-design §10.5`)

| Method + path | Body | Returns |
|---|---|---|
| `POST /projects/{id}/ingest` | `{ sources: [ IngestSource ] }` | `{ ingest_id }` |
| `GET /projects/{id}/ingest/{ingest_id}` | — | `{ status, retrieval:"deferred", per_source:[…] }` |

```jsonc
// IngestSource
{ "type": "openapi | graphql | web_map",
  "ref":  "https://app.example.com/openapi.json",   // URL or introspection endpoint or doc-site root
  "anchor": { "node_type": "BaseURL",               // OPTIONAL; default = project Domain node
              "identity": { "url": "https://app.example.com" } } }
```

**Validation:** unknown `project_id` → 404; `type` not in the extractor registry → 400 (covers deferred code sources); explicit `anchor` whose node is absent in Neo4j → 400; malformed body → 400.

### 5.2 Inter-component contracts

```
Ingest API ──► Pipeline        : IngestRequest{project_id, sources[]}  →  ingest_id
Pipeline ──► Anchor resolver   : (anchor?|None, project_id)  →  AnchorNode{node_type, identity}  (or 400)
Pipeline ──► Extractor         : extract(ref, anchor_node, budget)  →  list[Document]
Document                        = { content:str | entries:list[dict], metadata:dict,
                                    provenance:{source_ref, tool, fetched_at} }
Crawling agent ──► Steel       : render(url, auth_context?)  →  { html, links[], title }
Pipeline ──► Chunker           : chunk(Document)  →  list[Chunk{chunk_text, ordinal, metadata}]
Pipeline ──► Embedder          : embed_documents_batch([chunk_text])  →  list[vector(D)]
Pipeline ──► DocStore          : add_chunks(doc_ref, source_type, anchor, chunks, embeddings, provenance)
Pipeline ──► Anchor binder     : bind(anchor_node, doc_ref)  →  (Cypher MERGE)
Pipeline ──► Registry          : update(ingest_id, per_source_result)
Pipeline ──► (completion event): { ingest_id, per_source:[{doc_ref, chunks, anchor, status}],
                                    retrieval:"deferred" }
```

Sources are processed **isolated and best-effort**: one source failing records `status:"failed"` in `per_source` and does not abort the others; the run is `completed` if all succeed, `partial` if some fail, `failed` if all fail.

### 5.3 Crawling-agent contract (component 5)

- **Inputs:** `base_url`, sitemap.xml seeds (optional), `auth_context` (optional), budget `{max_pages≤30, max_llm_calls≤20, max_seconds≤180, max_depth≤3}`.
- **Loop (budget-bounded):** render next frontier URL in a Steel session → extract readable content + candidate links (emphasis on nav/sidebar/TOC — the structure that reaches every doc section) → canonicalize + dedup, same-host filter, noise filter → **LLM decides** which links are documentation worth following → append `{title, path, content}` to the sitemap → stop on budget or empty frontier.
- **Output:** `[{title, path, content}]` (→ Chunker) plus the assembled sitemap (recorded on the anchor node's provenance).

---

## 6. Control flow

```
operator → POST /ingest {sources:[…]} → {ingest_id}     (returns immediately; runs async)
  registry: ingest_id = queued → running
  for each source (isolated, best-effort):
      anchor_node = AnchorResolver.resolve(source.anchor, project_id)      # 400 on bad explicit anchor
      docs        = EXTRACTORS[source.type].extract(source.ref, anchor_node, budget)   # tier-1 → fallback
      chunks      = Chunker.chunk(docs)
      vectors     = Embedder.embed_documents_batch([c.chunk_text for c in chunks])
      doc_ref     = mint(source.type, anchor_node, ingest_id)
      DocStore.add_chunks(doc_ref, source.type, anchor_node.identity, chunks, vectors, provenance)
      AnchorBinder.bind(anchor_node, doc_ref)
      registry.update(ingest_id, {source, doc_ref, chunks:len, status})
  registry: status = completed | partial | failed ; emit completion event (retrieval:"deferred")
```

### 6.1 Extractor tiering

| source_type | Tier-1 (deterministic, `execute_command`) | Fallback | Anchors to (default) |
|---|---|---|---|
| `openapi` | fetch OpenAPI/Swagger URL, parse | infer from Neo4j Endpoints/Params | `BaseURL` |
| `graphql` | introspection query, parse SDL | infer from observed shapes | `BaseURL` |
| `web_map` | robots.txt + sitemap.xml | **Steel crawling agent** (§5.3) | `BaseURL`/`Domain` |

---

## 7. Constraints (must be respected)

1. **Embeddings are computed at ingest time** — the forward-compat seam; iteration-2 adds a query layer only, never a re-embed (barring model change, R-I2).
2. **Anchors bind to node identity, never to a locator string** (paradigm principle 2). `anchor` is `{node_type, identity}`; the binder MERGEs on the identity predicate.
3. **Provenance is mandatory** on every chunk and every run (paradigm principle 4): `{source_ref, tool, ingest_id, fetched_at}`.
4. **`doc_chunks` is append-only / immutable**; re-ingest versions via a new `doc_ref` (never mutate/delete in the MVP).
5. **The embedding dimension must match** the `doc_chunks.embedding` column and the HNSW index; changing the model requires a coordinated re-ingest.
6. **Single vector backend** — pgvector only; no FAISS artifacts.
7. **Per-source isolation** — one source's failure degrades to a partial corpus, never aborts the run (mirrors recon best-effort semantics).
8. **Steel budgets are enforced** (`max_pages/llm_calls/seconds/depth`); the crawl is bounded, not open-ended.
9. **`source_type` is validated against the extractor registry** — deferred code sources reject cleanly (400), never silently.
10. **Data egress boundary** — local embeddings by default; Steel cloud is used for (typically public) doc sites, and may carry `auth_context` for auth-gated docs; egress of auth-gated/white-box content through third parties must be a conscious operator choice.

---

## 8. Forward-compatibility seams

- **Deferred retrieval.** `DocStore.query(embedding, top_k, anchor_filter?)` is **defined but unimplemented** — a spec'd stub marking exactly where iteration-2 plugs in (and where `reranker`/`kb_orchestrator` re-enter). The completion event's `retrieval:"deferred"` marker + the bound `doc_refs` let iteration-2 orchestration discover "a queryable, node-bound corpus exists, not yet retrieved."
- **Deferred code extractors.** The **extractor registry** (`source_type → Extractor`) makes `oss_codebase`/`target_codebase` a registration change in iteration 2 — the pipeline, schema, and contracts are untouched. Their anchors (Technology, Domain) and tiering (GitHub Trees API / tarball; git clone) are pre-noted in `recon-mvp-design §6`.

---

## 9. Risks

- **R-I1 — Steel dependency.** External SaaS: availability, cost, and egress of auth-gated docs. *Mitigation:* bounded budgets; deterministic sitemap.xml tier-1 union as a partial fallback; conscious egress boundary (§7.10).
- **R-I2 — Embedding-model drift.** Changing the embedding model invalidates stored vectors (dim mismatch / semantic incomparability). *Mitigation:* the dimension pinned to the column/index; model change ⇒ coordinated re-ingest; `doc_ref` versioning makes it clean.
- **R-I3 — Anchor mis-binding.** A doc bound to a wrong/absent node degrades iteration-2 retrieval (the identity-error risk, paradigm R-5). *Mitigation:* existence-validate explicit anchors; default-to-Domain; provenance recorded.
- **R-I4 — Crawl incompleteness (coverage).** The agent may miss doc sections. *Mitigation:* union with sitemap.xml; nav/TOC-oriented traversal; budget tuning; coverage is an accepted MVP soft-edge.
- **R-I5 — Anti-bot / heavy JS on doc sites.** Rare for developer docs, possible for gated portals. *Mitigation:* Steel proxies/stealth (defer to steel-reliability if hit); deterministic fallback.
- **R-I6 — Hidden FAISS/config coupling in reused KB modules.** *Mitigation:* import `embedder/chunking/document_store` narrowly and wrap; do not import `faiss_indexer`/`kb_orchestrator`.
- **R-I7 — Retrieval-deferral drift.** Iteration-2 may change chunking/embedding expectations, requiring re-ingest of the stored corpus. *Accepted;* `doc_ref` versioning enables it.

---

## 10. Decisions log

| Tag | Decision |
|---|---|
| Scope | **Write-only** for the MVP; retrieval deferred to iteration 2 with an explicit seam (§8) |
| Backend | **pgvector-native**; reuse embedder + chunker + document_store; replace `faiss_indexer` with a thin `DocStore` |
| Sources | MVP = `openapi` + `graphql` + `web_map`; **`oss_codebase`/`target_codebase` deferred to iteration 2** (attack-surface analysis + Layer 1) |
| D-a (superseded) | Embedding default = **local `e5-large-v2` (1024-d)**, pluggable to API; local by default to avoid target-doc/code egress. **Superseded:** the agent-side `knowledge_base` embedder was never built; the LightRAG runtime embeds at insert time via the `EMBEDDING_*` binding (`.env`) |
| D-b (rev) | Execution boundary **split**: static fetch via `execute_command` (Kali); **agentic doc crawl via Steel cloud browser** |
| D-c | Ingestion is a **plain async pipeline**, not a LangGraph subgraph; status via `ingest_runs` polling |
| D-d | Anchor = explicit `{node_type, identity}`, **default to project Domain**; resolver validates existence (400 on miss) |
| D-e | Immutability via **versioned `doc_ref`** (`ingest_id` suffix); node accumulates `doc_refs`; provenance mandatory |
