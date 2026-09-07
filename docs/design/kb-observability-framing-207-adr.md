# ADR: #207 - single-source KB description + per-stage query observability

*Status: RATIFIED by the operator grilling (2026-09-07), implemented in this change.*

## Context

Two defects on the same seam (`kb_query` / `query_lightrag`):

1. **Wrong "fault KB" framing.** The tool was framed as a "fault knowledge base"
   and its descriptions drifted between the three sites (the real tool in
   `lightrag/tool.py`, the pod wrapper in `pod/tools.py`, the hunter wrapper in
   `hunter_tools.py`): the pod promised "one ontology entity" while bundles
   return 3-7, and the hunter listed config fields. The framing misdirected a
   pod into using the KB as a confirmation oracle for canonical HTTP semantics
   (a 404-with-shell misread as a possible auth signal). The KB is a
   testing-**methodology** KB (WSTG + writeup overlays), not a fault KB.
2. **Observability black-box.** The pipeline's inner three stages (retrieval,
   generation, validation) were plain httpx with zero Langfuse/OTel integration;
   only the tool boundary appeared as TOOL observations. Provenance
   (`provenance_references` indices into an in-memory `ReferenceRegistryV1`)
   was unverifiable, grounding-vs-enrichment was indistinguishable, author-lane
   reads left no artifact, `PROV []` was accepted silently, and the entity-count
   contract drift was unmeasured.

## Decision

### 1. Single canonical tool description (framing)

- `QUERY_LIGHTRAG_DESCRIPTION` lives in `lightrag/tool.py` and is imported
  verbatim by the pod and hunter wrappers - the description cannot drift.
- The description frames the KB **positively**: retrieve the ontology's
  methodology concepts when missing (technology stack, attack technique, payload
  pattern, artifact, observable signal, vulnerability class, attack goal,
  attacker capability, precondition environment, defensive control - the real
  `ENTITY_TYPES`), never "verify or adjudicate a bug".
- The pod `{KB_TOOL}` prompt bullet (both Runner + Triager sites) is the same
  neutral pointer + one-trigger-line signature, zero overlap with the
  description.
- The genuinely fault-scoped CWE catalogue (`data/fault-kb.yaml`, #66) is a
  different artifact and keeps its own framing.

### 2. Per-stage observability seam

- `lightrag/observability.py` opens one OTel child span per pipeline stage via
  the `opentelemetry.trace` API, riding the Langfuse OTLP span processor already
  wired by `app/observability/langfuse_tracing.py` (grey pt 6: reuse the
  processor, no new exporter infrastructure).
- **Retrieval span**: query, mode, top_k, chunk ids + best-effort scores, and
  the persisted `ReferenceRegistryV1` mapping (index -> reference_id ->
  file_path) so a cited provenance index is resolvable post-hoc (grey pt 7:
  span metadata on the retrieval span).
- **Generation span**: prompt + raw output.
- **Validation span**: accepted/degraded, errors, rejected citations, resolved
  provenance, plus `metric.provenance_empty` (the `PROV []` soft-ack signal) and
  `metric.entity_count` (the contract-drift counter) (grey pt 9).
- **Author lane** (grey pt 8): the hunter has no D6 log, so each `kb_query`
  records a `kb_observation` span with the query, scenario id, entity names, and
  provenance as metadata - never a filesystem artifact. The pod lane keeps its
  D6-log `KbObservation` recording.
- **Fail-open** (CODING_STANDARD section 12): absent opentelemetry or Langfuse,
  every span degrades to a silent no-op; observability never crashes or perturbs
  the query pipeline.

## Consequences

- A `query_lightrag` call is now auditable end-to-end: per-stage spans, a
  resolvable registry mapping, and structured validation outcomes.
- Agents are no longer steered toward "fault KB" questions; the positive framing
  emphasises methodology retrieval. (No spec-side 404 branch was added - the
  operator ruled the operative change is the framing, not widening the spec's
  binary symptom model.)
- The unit tier exercises the mechanics with the real OTel SDK behind an
  in-memory exporter and mocked LLM/gateway; a live walkthrough lives in e2e.