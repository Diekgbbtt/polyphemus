# LightRAG MethodologyBundle Runtime

Status: implemented on branch `lightrag` as of 2026-08-04.

Purpose: document the current LightRAG methodology retrieval path after the
structured-output refactor and the WSTG plus writeup benchmark run.

## Runtime Boundary

LightRAG is now treated as a retrieval engine, not as the final answer writer.
The repository-owned pipeline is:

```text
KnowledgeQuery
  -> RoutedMethodologyRetriever
  -> LightRAG /query with only_need_context=true
  -> raw retrieved context
  -> methodology_formatter LLM call
  -> validated MethodologyBundle
  -> methodology_bundles audit table
```

The LightRAG containers still expose their native `/query` endpoints. Those
endpoints return LightRAG context or raw LightRAG answers depending on request
parameters. Attack-engineering agents should not consume those native endpoints
directly when they need methodology guidance. They should consume a
repository-owned service boundary that returns `MethodologyBundle`.

The current Python service boundary is:

```python
from agent.lightrag.service import retrieve_methodology
```

The pending HTTP boundary is documented by
`tests/lightrag/test_methodology_http_contract.py`:

```text
POST /methodology/query
request:  {"run_id": "...", "query": KnowledgeQuery}
response: MethodologyBundle
```

That HTTP test is marked `xfail(strict=True)` until the route is wired. Once
the route exists, the test should pass as `XPASS`; remove the marker in the
same change that exposes the endpoint.

## Structured Output Contract

The public runtime response is `MethodologyBundle`. The formatter asks the LLM
for a compact schema first, then converts it into the richer public bundle.

Hard constraints:

- at most 3 candidates;
- compact summary and rationale fields;
- no meta text such as "I need to" or "Based on the provided context";
- no long procedural exploit walkthroughs;
- `satisfied_conditions` and `missing_conditions` are separate;
- candidates require evidence references;
- empty candidate output is allowed only with `knowledge_gaps`.

The formatter validates output with Pydantic. If the formatter call fails,
returns invalid JSON, references missing evidence, or produces unsupported
content, the service returns an empty candidate bundle with explicit
`knowledge_gaps` instead of free-form prose.

Key implementation files:

```text
agent/lightrag/types.py       KnowledgeQuery, CompactMethodologyBundle, MethodologyBundle
agent/lightrag/formatter.py   strict formatter prompt, validation, fallback
agent/lightrag/retriever.py   base-first retrieval and writeup overlay routing
agent/lightrag/service.py     KnowledgeQuery -> MethodologyBundle -> artifact persistence
agent/lightrag/packager.py    compatibility packaging for retriever outputs
```

## Source Routing

Two LightRAG workspaces are used:

```text
validated WSTG base
  compose service: lightrag
  compose url: http://lightrag:9621
  host url: http://127.0.0.1:9621
  storage: data/lightrag/rag_storage
  source_tier: validated_base

0xdf writeup overlay
  compose service: lightrag-writeups
  compose url: http://lightrag-writeups:9621
  host url: http://127.0.0.1:9622
  storage: data/lightrag/writeups_rag_storage
  workspace: writeups_0xdf
  source_tier: review_overlay
```

`RoutedMethodologyRetriever` queries the WSTG base first. It queries the
writeup overlay only when one of these routing gates fires:

- query pattern is `bypass` or `chaining`;
- symptoms, objective, context, or taxonomy tags match overlay concepts such as
  SQLi, SSRF, JWT, Active Directory, Git exposure, or deserialization;
- the base result has fewer candidates than the configured minimum.

Merged results preserve base precedence and cap the final candidate list at
three.

## Benchmark Added

The WSTG plus writeup benchmark runner lives at:

```text
agent/lightrag/benchmark_wstg_writeup_generation.py
tests/lightrag/test_benchmark_wstg_writeup_generation.py
```

It evaluates four use cases:

- Broken Access Control, including horizontal and vertical escalation;
- OAuth2 / OIDC authorization-code flow flaws;
- Session Management and Fixation;
- BOLA / IDOR in APIs.

Each use case is run against both datasets:

```text
wstg
wstg+writeup
```

The benchmark keeps the LightRAG parameters constant across every query:

```json
{
  "mode": "mix",
  "top_k": 20,
  "chunk_size": 1200,
  "chunk_top_k": 10,
  "max_total_tokens": 20000,
  "max_entity_tokens": 12000,
  "max_relation_tokens": 12000,
  "only_need_context": true,
  "include_references": true,
  "include_chunk_content": true,
  "stream": false
}
```

Each execution writes exactly these five sections:

```text
Executed Query
Parameters Used
Context Retrieved from LightRAG
Complete Input Passed to LLM (Final Prompt)
Output Returned by LLM
```

The latest live artifact is:

```text
data/lightrag/benchmarks/wstg_writeup_generation_benchmark_live.json
```

The last live run produced 8 executions, 4 use cases times 2 datasets, with
`error_count: 0`.

## Pre-Indexed Storage

The branch is intended to ship ready-to-query LightRAG stores so a developer can
start the two LightRAG containers without rebuilding both indexes.

Tracked storage directories:

```text
data/lightrag/rag_storage/
data/lightrag/writeups_rag_storage/
```

These directories are mounted by `docker-compose.yml` into the two LightRAG
services. Backups remain ignored:

```text
data/lightrag/rag_storage.bak.*/
```

Operational notes:

- do not change embedding model, embedding dimension, LightRAG version, or
  workspace name without treating it as a re-index event;
- `lightrag-writeups` must keep `WORKSPACE=writeups_0xdf`;
- the pre-indexed stores are source artifacts, not runtime logs;
- `kv_store_llm_response_cache.json` is included with the store snapshot so the
  mounted workspace matches the validated local state;
- if a store is rebuilt, re-run the graph/query gates and benchmark before
  committing the new snapshot.

To start the ready-to-query stores:

```bash
docker compose --profile lightrag up -d lightrag lightrag-writeups
```

Host endpoints:

```text
http://127.0.0.1:9621/query
http://127.0.0.1:9622/query
```

Inside Docker network endpoints:

```text
http://lightrag:9621/query
http://lightrag-writeups:9621/query
```

Remember: those are native LightRAG endpoints. The attack-engineering agent
should use the repository-owned methodology endpoint once wired so it receives
validated `MethodologyBundle` JSON instead of raw prose or raw context.
