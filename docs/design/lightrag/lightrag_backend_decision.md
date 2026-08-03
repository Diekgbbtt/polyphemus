# LightRAG Backend Decision

Status: updated after the validated WSTG indexing run on 2026-07-28 and the
2026-07-30 WSTG corpus/benchmark preparation pass.

## Decision

Use LightRAG's OpenAI-compatible binding, but keep the LightRAG indexing backend
separate from the repository's `LLM_MODEL_<ROLE>` agent roles.

The existing `triager` and `job_orchestrator` roles are configured with DeepSeek via
OpenRouter:

```env
LLM_MODEL_TRIAGER=openrouter:deepseek/deepseek-v4-flash
LLM_MODEL_JOB_ORCHESTRATOR=openrouter:deepseek/deepseek-v4-flash
```

The first stable WSTG KB was produced with SwissAI as the LLM provider and
`apertus-ai/Apertus-v1.5-70B` as the concrete model. LightRAG does not consume
the repository's `LLM_MODEL_<ROLE>` convention directly; configure the API
server variables explicitly:

```env
LLM_BINDING=openai
LLM_BINDING_HOST=https://api.swissai.svc.cscs.ch/v1
LLM_MODEL=apertus-ai/Apertus-v1.5-70B
LLM_BINDING_API_KEY=<SwissAI API key>
```

### JSON extraction caveat

The first WSTG indexing attempt on 2026-07-18 failed with:

```text
Model 'tencent/hy3' does not support 'json_object' response format.
Supported formats: json_schema.
```

LightRAG had been configured with:

```env
ENTITY_EXTRACTION_USE_JSON=true
```

For the validated WSTG run, keep:

```env
ENTITY_EXTRACTION_USE_JSON=false
```

This keeps indexing compatible with the known route behavior and avoids
changing extraction format during KB stabilization. If a later model is chosen
that supports OpenAI-compatible `response_format=json_object`, JSON extraction
can be re-enabled only after re-testing from an empty `data/lightrag/rag_storage`.

The tradeoff is practical: non-JSON extraction is less strict, but the WSTG
preprocessor now gives LightRAG a deterministic, source-grounded composite
document, reducing extraction chaos enough for the first validation pass.

### Insert concurrency during rebuild

For the first clean rebuild of the 2026-07-30 WSTG corpus, use conservative
indexing:

```env
MAX_PARALLEL_INSERT=1
```

The previous batch testing showed worker execution timeouts during document
extraction. Lowering insert concurrency does not improve semantic retrieval by
itself, but it reduces pressure on the remote LLM route and makes failures more
isolated. Pair it with staged upload batches of five documents and ingestion
history logging. After a full clean rebuild has completed with zero failed
documents, concurrency can be re-tested as an indexing-speed optimization.

If indexing is stuck, prefer LightRAG's cancel endpoint before stopping the
container:

```text
POST /documents/cancel_pipeline
```

Stopping the container interrupts active workers, but pending/failed document
state may remain and must be cleaned before retrying the batch.

Historical or fallback OpenRouter LLMs for indexing experiments:

```env
LLM_MODEL=tencent/hy3:free
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
LLM_MODEL=openrouter/free
```

Prefer concrete model slugs for repeatable indexing. Use provider-level
fallbacks such as `openrouter/free` only for throwaway experiments because they
may route to different models between runs. `503 - No provider found for the
requested service` means the selected provider/model route is unavailable; keep
the provider if required, but switch to a concrete model that is available and
retry the failed batch.

## Embeddings

Embeddings are not covered by the existing agent LLM roles. The validated local
WSTG run used an OpenAI-compatible embedding route with 2,048 dimensions:

```env
EMBEDDING_BINDING=openai
EMBEDDING_BINDING_HOST=https://openrouter.ai/api/v1
EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b:free
EMBEDDING_DIM=2048
EMBEDDING_BINDING_API_KEY=<embedding provider API key>
EMBEDDING_SEND_DIM=false
EMBEDDING_USE_BASE64=false
```

Keep the embedding model and dimension stable after the first successful insert;
changing them requires clearing `data/lightrag/rag_storage` and re-indexing.

The current practical baseline is the validated 119-document WSTG KB under
`data/lightrag/rag_storage`. Treat backend changes as a re-indexing event, not
as a runtime-only configuration change.
