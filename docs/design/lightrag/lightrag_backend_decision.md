# LightRAG Backend Decision

Status: P0 decision for the first real indexing run.

## Decision

Reuse the same OpenRouter backend already used by the existing reconnaissance phases.

The existing `triager` and `job_orchestrator` roles are configured with DeepSeek via
OpenRouter:

```env
LLM_MODEL_TRIAGER=openrouter:deepseek/deepseek-v4-flash
LLM_MODEL_JOB_ORCHESTRATOR=openrouter:deepseek/deepseek-v4-flash
```

For zero-cost LightRAG indexing, use a current specific free route rather than the paid
`deepseek/deepseek-v4-flash` slug. As of 2026-07-18, the tested DeepSeek free variants
are not reliable for this run: OpenRouter reports both `deepseek/deepseek-v4-flash:free`
and `deepseek/deepseek-chat-v3.1:free` as unavailable for free and points to paid slugs.
Use `tencent/hy3:free` for the first run.

LightRAG does not consume the repository's `LLM_MODEL_<ROLE>` convention directly. Map
the same OpenRouter backend to LightRAG's API-server variables:

```env
LLM_BINDING=openai
LLM_BINDING_HOST=https://openrouter.ai/api/v1
LLM_MODEL=tencent/hy3:free
LLM_BINDING_API_KEY=<same value as API_KEY_OPENROUTER>
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

For the current OpenRouter `tencent/hy3:free` route, set:

```env
ENTITY_EXTRACTION_USE_JSON=false
```

This keeps the test moving without changing the LLM backend. If a later model is
chosen that supports OpenAI-compatible `response_format=json_object`, JSON
extraction can be re-enabled and should be re-tested from an empty
`data/lightrag/rag_storage`.

The tradeoff is practical: non-JSON extraction is less strict, but the WSTG
preprocessor now gives LightRAG a deterministic, source-grounded composite
document, reducing extraction chaos enough for the first validation pass.

Fallback free LLMs for indexing experiments:

```env
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
LLM_MODEL=openrouter/free
```

Prefer specific `:free` slugs for repeatable indexing. Use `openrouter/free` only as an
availability fallback because it may route to different models between runs.

## Embeddings

Embeddings are not covered by the existing agent LLM roles. For a zero-cost first run,
use OpenRouter's free NVIDIA embedding model:

```env
EMBEDDING_BINDING=openai
EMBEDDING_BINDING_HOST=https://openrouter.ai/api/v1
EMBEDDING_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free
EMBEDDING_DIM=2048
EMBEDDING_BINDING_API_KEY=<same value as API_KEY_OPENROUTER>
EMBEDDING_SEND_DIM=false
EMBEDDING_USE_BASE64=false
```

Keep the embedding model and dimension stable after the first successful insert; changing
them requires clearing `data/lightrag/rag_storage` and re-indexing.

The next practical step remains the controlled offline corpus in `data/lightrag/inputs/`.
