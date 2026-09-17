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

- `lightrag/observability.py` opens one Langfuse child observation per pipeline
  stage via the SDK primitives (`start_as_current_observation` /
  `span.update` / `score_current_span`), following the client-layer canon
  (`docs/design/observability-recipe.md`) - grey pt 6 (reuse the SDK wiring,
  no new exporter infrastructure). Raw OTel tracer scopes were tried first and
  REJECTED after live verification proved the SDK processor's export filter
  silently drops them (verified 2026-09-09, see the recipe caveat).
- **Retrieval observation**: input = query, mode, top_k; metadata = status,
  chunk ids + best-effort scores, and the persisted `ReferenceRegistryV1`
  mapping (index -> reference_id -> file_path) so a cited provenance index is
  resolvable post-hoc (grey pt 7: observation metadata on the retrieval
  observation).
- **Generation observation**: input = the prompt; output = the raw output;
  metadata = the generator's `reasoning_content` (`DeepSeekClient.stream`
  surfaces the reasoning deltas as `reasoning` events; the tool records them
  on the observation but does not forward them into its own `delta`/`answer`
  stream contract).
- **Validation observation**: metadata = accepted/degraded, errors, rejected
  citations, resolved provenance; scores = `provenance_empty` (the `PROV []`
  soft-ack signal) and `entity_count` (the contract-drift counter) via
  `score_current_span` (grey pt 9).
- **Author lane** (grey pt 8): the hunter has no D6 log, so each `kb_query`
  records a `kb_observation` observation with the query + scenario id as input
  and entity names + provenance as metadata - never a filesystem artifact. The
  pod lane keeps its D6-log `KbObservation` recording.
- **Fail-open** (CODING_STANDARD section 12): absent `langfuse`, every
  observation degrades to a silent no-op; observability never crashes or
  perturbs the query pipeline.

## Consequences

- A `query_lightrag` call is now auditable end-to-end: per-stage observations, a
  resolvable registry mapping, and structured validation outcomes.
- Agents are no longer steered toward "fault KB" questions; the positive framing
  emphasises methodology retrieval. (No spec-side 404 branch was added - the
  operator ruled the operative change is the framing, not widening the spec's
  binary symptom model.)
- The unit tier exercises the mechanics with a faked `langfuse` module (the
  `test_analyser_tracing.py` recipe); live export is verified against
  Langfuse Cloud via the sibling-container scaffold.