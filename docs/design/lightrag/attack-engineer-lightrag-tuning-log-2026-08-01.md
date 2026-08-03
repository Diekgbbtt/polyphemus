# Attack Engineer LightRAG Tuning Log - 2026-08-01

Scope: evaluate the current LightRAG WSTG methodology KB and identify a query
shape and retrieval configuration for Attack Engineer Knowledge Pack generation.

## Architecture Findings

LightRAG is used as methodology memory only. Recon Layer 0/Layer 1 target facts
remain outside the KB and are projected into the query as typed methodology
anchors.

The useful query structure is:

```text
Phase 2 target profile JSON
+ ontology projection:
  TechnologyStack
  PreconditionEnvironment
  Artifact
  ObservableSignal
  DefensiveControl
  VulnerabilityClass
-> ask LightRAG to resolve:
  target anchors
  -> VulnerabilityClass
  -> AttackTechnique / PayloadPattern / DefensiveControl
  -> WSTG scenario anchors
  -> WSTG ID, title, methodology, probes, evidence, negative controls
```

Production queries must not include benchmark-only `expected_wstg_ids`.

## Recommended Strategy

Default broad Attack Engineer retrieval:

```json
{
  "mode": "naive",
  "top_k": 20,
  "max_total_tokens": 20000,
  "only_need_context": true,
  "template": "ontology_feature_to_wstg"
}
```

Use this for target-state queries from an abstracted Phase 2 profile. Generate
the final Knowledge Pack only after the context pass selects and anchors the
candidate methodology.

Fallback or diagnostic retrieval:

```json
{
  "mode": "hybrid",
  "top_k": 80,
  "chunk_top_k": 10,
  "max_total_tokens": 30000,
  "max_entity_tokens": 12000,
  "max_relation_tokens": 12000,
  "only_need_context": true,
  "hl_keywords": ["high-level target / method terms"],
  "ll_keywords": ["source file, WSTG ID, concrete payload or technique terms"]
}
```

Use this when the question is a targeted lookup, an exact WSTG/source-file
diagnostic, or a bypass query with known technique/control names.

Avoid `global` and `mix` as the first broad profile query: they returned richer
graph context but drifted into adjacent WSTG cases more often. `local` is useful
as a precision cross-check, especially for GraphQL/API cases, but had lower
average recall than `naive` in the answer-generation sample.

Server-side ranking thresholds are currently not active query levers:
`enable_rerank=false`, `cosine_threshold=0.2`, `min_rerank_score=0.0`.
Rerank threshold tuning requires enabling/configuring a reranker in the
LightRAG service, not just changing per-query payloads.

## Test Log

### [LR-AE-001] Repository and contract inspection

Configuration / Query: static read of `agent/lightrag`, `tests/lightrag`, and
`docs/design/lightrag`.

OK: The repo already has a benchmark harness, an experiment tracker, graph audit
tooling, WSTG smoke gates, and an ontology projection builder for Phase 2
profiles.

FAIL: `KnowledgeQuery.retrieval.mode` accepted `vector/graph/keyword`, while
the LightRAG API and benchmark use `naive/local/global/hybrid/mix`.

NOTE: The retrieval mode contract needed a small TDD fix so production queries
can express the empirically best mode.

### [LR-AE-002] Baseline unit tests

Configuration / Query:

```bash
.venv/bin/python -m pytest tests/lightrag/test_types.py tests/lightrag/test_benchmark_wstg.py tests/lightrag/test_client.py -q
```

OK: 24 tests passed before changes.

FAIL: No failing baseline behavior, but the suite did not cover API mode
alignment.

NOTE: Added a focused regression test in [LR-AE-010].

### [LR-AE-003] LightRAG service and graph audit

Configuration / Query: `LightRAGHttpClient.health()`,
`status_counts()`, and graph audit against
`data/lightrag/rag_storage/graph_chunk_entity_relation.graphml`.

OK: Service healthy, 119 processed documents, 0 failed. Graph audit: 3,977
entities, 2,925 relations, 0 unknown type entities, 0 non-canonical type
entities, 0 noise entities, no blocking issues.

FAIL: The graph contains many diagnostic "missing_expected_entities", but the
gate reports them as non-blocking because required aliases/source checks pass.

NOTE: The KB is queryable and suitable for retrieval experiments.

### [LR-AE-004] Sandbox behavior

Configuration / Query: benchmark to `http://127.0.0.1:9621` without escalation.

OK: The failed run clearly isolated environment access as the issue.

FAIL: All local HTTP calls failed with `ConnectError: [Errno 1] Operation not
permitted`.

NOTE: Valid LightRAG experiments must run with explicit local-network
permission in this sandbox.

### [LR-AE-005] Mode sweep, broad ontology query

Configuration / Query: 8 WSTG benchmark cases, template
`ontology_feature_to_wstg`, `only_need_context=true`, `top_k=40`,
`max_total_tokens=12000`.

| Mode | Recall | Precision | Relevance | Anchor | Avg latency |
|---|---:|---:|---:|---:|---:|
| naive | 0.6375 | 0.5122 | 0.7114 | 0.7823 | 319 ms |
| local | 0.4521 | 0.6146 | 0.5879 | 0.6714 | 5784 ms |
| global | 0.3625 | 0.2812 | 0.4805 | 0.6109 | 2141 ms |
| hybrid | 0.2188 | 0.2208 | 0.4362 | 0.4844 | 1894 ms |
| mix | 0.1875 | 0.2158 | 0.3955 | 0.4479 | 3177 ms |

OK: `naive` produced the best broad-profile recall and relevance with the
lowest latency.

FAIL: `global`, `hybrid`, and `mix` drifted into adjacent scenario IDs. `local`
had better precision but weaker recall.

NOTE: Use `naive` as the first pass for broad target-state Knowledge Pack
retrieval.

### [LR-AE-006] `top_k` and token budget sweep

Configuration / Query: 8 cases, template `ontology_feature_to_wstg`,
`only_need_context=true`, modes `naive/local`, `top_k=20/60/100`,
`max_total_tokens=20000`.

| Mode/top_k | Recall | Precision | Relevance | Anchor | Avg tokens |
|---|---:|---:|---:|---:|---:|
| naive/20 | 0.7458 | 0.3533 | 0.7989 | 0.8521 | 9471 |
| naive/60 | 0.7458 | 0.3533 | 0.7989 | 0.8521 | 9471 |
| naive/100 | 0.7458 | 0.3533 | 0.7989 | 0.8521 | 9471 |
| local/20 | 0.6792 | 0.3949 | 0.7584 | 0.8109 | 9685 |
| local/60 | 0.5854 | 0.4613 | 0.6928 | 0.7562 | 9931 |
| local/100 | 0.5646 | 0.5333 | 0.6783 | 0.7380 | 10175 |

OK: Raising `max_total_tokens` from 12000 to 20000 improved broad-context
recall. `naive` was stable across `top_k`; `local/top_k=20` was the best local
variant.

FAIL: Larger `local` top_k increased precision but reduced recall/relevance,
which is bad for first-pass hypothesis generation.

NOTE: `top_k=20` is enough for both candidates; spend budget on context tokens,
not higher top_k.

### [LR-AE-007] Generated answer sample

Configuration / Query: template `ontology_feature_to_wstg`, modes
`naive/local`, `top_k=20`, `max_total_tokens=20000`, generation enabled.
Interrupted after 6 completed records because the full 16-query run exceeded
the exploratory time budget.

| Mode | N | Recall | Precision | Relevance | Anchor | Avg latency |
|---|---:|---:|---:|---:|---:|---:|
| naive | 3 | 0.8056 | 0.3501 | 0.8353 | 0.8681 | 44373 ms |
| local | 3 | 0.6111 | 0.3571 | 0.6992 | 0.7708 | 49723 ms |

OK: `naive` preserved better recall and relevance when LightRAG generated a
short answer.

FAIL: Generation latency is too high for matrix tuning. Precision stays modest
because generated answers mention adjacent but valid WSTG IDs.

NOTE: Tune with context-only runs; generate the final Knowledge Pack once per
selected query at `temperature=0`.

### [LR-AE-008] Keyword-guided hybrid functional gate

Configuration / Query: existing smoke query cases, `hybrid`, `top_k=80`,
`chunk_top_k=10`, `max_total_tokens=30000`, `max_entity_tokens=12000`,
`max_relation_tokens=12000`, `only_need_context=true`, seeded
`hl_keywords/ll_keywords`.

OK: 9/9 blocking WSTG targeted query cases passed.

FAIL: This configuration is not a broad target-profile strategy; it depends on
known source files, WSTG-oriented names, or explicit technique/control terms.

NOTE: Keep keyword-guided hybrid as a second-stage diagnostic and bypass lookup
path.

### [LR-AE-009] Query template sweep

Configuration / Query: 8 cases, `naive`, `top_k=20`,
`max_total_tokens=20000`, `only_need_context=true`.

| Template | Recall | Precision | Relevance | Anchor | Avg tokens |
|---|---:|---:|---:|---:|---:|
| ontology_feature_to_wstg | 0.7458 | 0.3533 | 0.7989 | 0.8521 | 9471 |
| wstg_category_oriented | 0.7458 | 0.3200 | 0.7989 | 0.8677 | 9774 |
| step_by_step_methodology | 0.7146 | 0.3367 | 0.7770 | 0.8286 | 9683 |
| feature_to_threat | 0.6833 | 0.3366 | 0.7551 | 0.8208 | 9650 |

OK: `ontology_feature_to_wstg` ties best recall/relevance and has better
precision than the category template.

FAIL: Category-oriented retrieval anchors well but mentions more unrelated WSTG
IDs.

NOTE: Prefer ontology projection query structure for Attack Engineer
target-state packs.

### [LR-AE-010] TDD contract fix

Configuration / Query: added `test_retrieval_mode_matches_lightrag_api_modes`.

OK: The test first failed because `naive` was rejected. After updating
`RetrievalMode` to `naive/local/global/hybrid/mix`, the full LightRAG test
suite passed:

```bash
.venv/bin/python -m pytest tests/lightrag -q
# 112 passed
```

FAIL: No remaining failure in the touched LightRAG test suite.

NOTE: The production `KnowledgeQuery` contract can now represent the selected
retrieval strategy.
