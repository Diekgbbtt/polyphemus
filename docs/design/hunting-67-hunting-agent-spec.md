# Hunting agent spec: hunting agent

Part of [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (per-agent specs), middle of the agent hierarchy.
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`; it holds the inter-agent logic (walkthrough S0-S7, domain data contracts D1-D11, interface agreements IA-1..IA-8, failure-handling canon, agent-attribute compliance).
This document disambiguates the hunting agent from the combined spec: everything below is the hunting agent's contract alone, written to the depth an implementation session can build from without re-reading the parent.
Decisions cited as D67-n live in `docs/design/hunting-67-per-agent-specs-decisions.md`.

*Status: spec (contract), NOT implementation.*

## 1. Identity

The hunting agent is the test-DESIGN side of the Q8 design/execution partition: a typed agent with a parametrised prompt template over a declarative `HuntConfig`, authoring rich `TestImplementationSpec`s and driving the hypothesis evaluation loop through the pod.

### 1.1 Role

One hunting agent per dispatched hunt (N = 1 in phase 1; per-symptom in phase 2), in the hunting bounded context.
It is dispatched by the hunt-orchestrator (IA-2) and is the pod's parent (IA-3/IA-4).

### 1.2 Goal

Author, for its dispatched `HuntConfig`, a `TestImplementationSpec` that a test-executor pod can meaningfully execute, covering the low-level techniques grounded in the retrieved symptom-technique KB entries and the concrete surface evidence; then verify hypotheses through the pod and evaluate the three-valued hypothesis verdicts (D67-02, D67-12).

### 1.3 Workflow

1. Consume the `HuntConfig` (D3): the parametrised prompt template (rationale + extension points, assumptions, supposed payload vectors, L0 fault-applicability evidence), the wide surface context (adapted index-card), the target caveats, the prior-hunt insights, and the fault-targeting tool registry.
2. Query the symptom-technique KB (the `fault KB` handle) for symptoms and probing-techniques on the join key `(fault-class, unit technological-axis)` (IA-8).
3. Author the `TestImplementationSpec` (D4, merged spec section 7): the core NL over the fundamental typed base.
4. Yield the spec plus feedback to the orchestrator (IA-5).
5. Run the hypothesis-evaluation loop: dispatch the pod (IA-3) on the spec, consume `{verdict, evidence}` (IA-4), derive the three-valued hypothesis verdict (D67-02), and either confirm success, land unsuccessful, or pursue `insufficient-evidence` via a narrow tool exec or an inline back-edge need surfaced through feedback (D67-14, IA-5 -> IA-6).
6. Worst case and failure state per D67-12 (section 4 below).

### 1.4 Tools

The fault-targeting tool registry (from `HuntConfig`); the symptom-technique KB query interface.
The read-only graph view is NOT a direct tool: the orchestrator's view stays the sole graph access; the agent consumes projections.
There is NO recon tool: the back-edge seam belongs to the orchestrator (D67-04); inline needs are surfaced through IA-5 feedback and executed by the orchestrator.

### 1.5 Context

The `HuntConfig` parameter set verbatim; the symptom-technique KB retrieval results (D10); the adapted index-card surface context.
The index-card projection is a live re-derive at authoring time, never a pipeline snapshot.

### 1.6 Output template

- The `TestImplementationSpec` (D4): typed base (target identity, verification symptom(s), testing pattern, assumptions list, payload vector space) over the NL core (rationale, interpretation guidance).
- The hypothesis verdict (D7): `{verdict: successful | unsuccessful | insufficient-evidence, evidence_mapping, revival_key}`.
- Orchestrator feedback (D11): NL feedback text plus any hypothesis verdict already derived.

### 1.7 Produced outcome

The spec lands in the hunt store, wired to its hunt; the orchestrator receives the feedback; the hypothesis verdict is recorded; nothing is written to L0/L1.

### 1.8 Observability

The shared recipe (merged spec section 8): one Langfuse trace per spec-authoring turn, spans per step (KB retrieval, spec composition) named after the step, session = run id, Langfuse optional and fail-open; verdicts measured via hunt-store records and the eval harness, never Langfuse score identifiers.

### 1.9 Honour clauses

- Sole-writer: never writes L0/L1; persists only through the hunt store.
- Sequential hypothesis dispatch: one hypothesis evaluation at a time (one model turn at a time).
- Fail-open: section 5.
- `insufficient-evidence` NEVER exists as a HuntingAgent state: the agent always yields at least one test-execution and always terminates its hunt with a verdict, never a pending state (Q8, three-level verdict model).

## 2. Domain peculiarities

- The hypothesis-evaluation loop: this is the agent's second core activity after spec authoring.
  Per hypothesis: dispatch the pod (IA-3), consume `{verdict, evidence}` (IA-4), map the binary pod outcome to the three-valued hypothesis verdict (D67-02): a pod-`successful` maps to hypothesis-`successful`; a pod-`unsuccessful` carrying a clean symptom-absent maps to hypothesis-`unsuccessful`; a pod-`unsuccessful` carrying infeasibility or noise in the trail maps to hypothesis-`insufficient-evidence`.
- The inline re-evaluation loop (D67-14): hypothesis-`insufficient-evidence` triggers a narrow tool exec or an inline back-edge need (surfaced via IA-5; the orchestrator executes IA-6 and routes the result back).
  Re-evaluation is unbounded while each response yields meaningful insights; a no-meaningful-insight response ends the evaluation (the D67-12 failure state).
  The termination guard is the meaningfulness test on the returned evidence, not a depth count.
- The worst case is NOT a failure mode (D67-12): a hostile `(fault-class, testable-unit)` pair - one hypothesis verified, yielding one test - results in something technically unfeasible or a state with a strong blocking assertion, even after many variants have been executed.
  This is graceful degradation: the hunt still feeds evidence-backed insights to the orchestrator.
- The failure state (D67-12): no hypothesis could be successfully verified AND further back-edged narrow recon requests provided no meaningful insights.
  The hunt degrades to `unsuccessful` with the attempted hypotheses' evidence trail; the feedback still flows.
- No authoring-failure fallback template: the at-least-one-execution guarantee is a design property of the agent's operation, not a fallback mechanism (D67-12's rejected alternative: there is no uncontrolled authoring failure to fall back from).
- The join key `(fault-class, unit technological-axis)` is the KB retrieval contract (D10, IA-8); the technological axis is never a facet of the typed predicate (#66 non-conflation) - it is only a retrieval key here.
- The agent declines/refines spec attributes into variants (D67-03, D67-08) when the pod's evidence suggests it; the variant mechanics themselves live in the pod's experiment log, the agent decides the declines.

## 3. What this build builds vs stubs vs reuses

Builds:

- The agent itself: the spec-authoring turn (one LLM call over the parametrised prompt template) and the hypothesis-evaluation loop.
- The KB query interface against the symptom-technique KB (IA-8), with an in-memory fixture KB for tests.
- The typed handoff of the `TestImplementationSpec` to the pod (IA-3) and the `{verdict, evidence}` consumption (IA-4).
- The hypothesis verdict derivation and the feedback emission (D11).
- The inline back-edge need surfacing (IA-5, D67-14).

Stubs (owned by sibling tickets, minimal fixture in this build):

- The symptom-technique KB itself: operator-built external (glossary), never built here; the fixture KB serves the tests.
- The pod (IA-3/IA-4 target): a fixture pod for the contract tier; the real pod arrives with its own ticket.
- The fault-targeting tool registry (#71): the registry content from the `HuntConfig`.
- The hunt store (#68): the same append-only markdown stub as the orchestrator's build.
- The orchestrator (dispatch): the `HuntConfig` arrives as a typed fixture.

Reuses:

- The index-card projection (`analysis/index_card.py`) for the surface-context budget rule.
- The `TestImplementationSpec` schema as declared in merged spec section 7 (the typed base over the NL core).
- The hunt-record and evidence-record patterns from the store stub.

## 4. Happy paths and outliers

### 4.1 Happy paths

H1 - Confirmed: the `HuntConfig` covers a normal pair; the KB returns symptoms and probing-techniques; the spec is authored with a full typed base and NL core; the pod returns `{successful, symptom-confirmed}`; the hypothesis verdict is `successful`; the hunt lands successful with the spec and feedback in the store.
H2 - Clean absent: the pod returns `{unsuccessful, space-exhausted}` with a clean trail; the hypothesis verdict is `unsuccessful`.
H3 - Insufficiency resolved: the pod returns `{unsuccessful, infeasibility in trail}`; the hypothesis verdict is `insufficient-evidence`; a narrow tool exec (or an inline back-edge returning a meaningful insight) revises the evaluation to a verdict.
H4 - Worst case (D67-12): the hostile pair yields one test that is technically unfeasible or strongly blocked after many variants; graceful degradation: the hunt lands unsuccessful and the feedback carries the evidence-backed insights.
H5 - Failure state (D67-12): no hypothesis verifiable and the inline back-edge returns no meaningful insights; the hunt lands unsuccessful with the attempted hypotheses' evidence trail.

### 4.2 Outliers

O1 - KB returns empty: the agent authors from the `HuntConfig` alone (degraded grounding, fail-open IA-8).
O2 - KB unavailable (raises): the same degrade; nothing raises.
O3 - Malformed `HuntConfig` (a part missing): the agent authors from the present parts and flags the gap in the feedback; nothing raises.
O4 - Index-card projection unavailable: the agent authors without the surface context (degraded).
O5 - Pod raises at IA-3: the agent treats the run as unsuccessful with the error in the evidence and continues the evaluation or enters the failure state; nothing raises.
O6 - Pod rejects the spec at INIT: the agent re-authors (declining attributes per D67-03) or lands unsuccessful with the validation evidence; the re-authoring is bounded by the evaluation loop's budget.
O7 - Duplicate hypothesis: an identical spec is not re-dispatched to the pod (idempotent; the experiment log records one execution).
O8 - Inline back-edge returns `error`/`degraded` status: the result is folded into the evidence trail (IA-6 vocabulary) and the evaluation continues or ends.
O9 - Inline back-edge keeps returning non-meaningful results: the meaningfulness guard ends the evaluation (D67-14); the hunt enters the failure state; no unbounded loop escapes the guard.
O10 - Spec-authoring turn LLM exhaustion: the hunt degrades to unsuccessful with the partial authoring evidence in the feedback; there is no fallback template (D67-12); the guarantee is a design property, not a fallback.

## 5. Delivery semantics and failure handling

Delivery canon (merged spec section 3): all delivery is synchronous and in-process in phase 1.

- IA-3 (agent -> pod): synchronous typed handoff of D4.
  A spec failing INIT validation is rejected; the pod lands `unsuccessful` with the validation evidence; the agent re-authors or lands unsuccessful; no silent hang.
- IA-4 (pod -> agent): synchronous typed return of D5 + D6.
  A raising pod degrades to `unsuccessful` with the error in the evidence (the pod's own contract; the agent handles the double's raise defensively too); nothing raises.
- IA-5 (agent -> orchestrator): synchronous best-effort feedback.
  A lost feedback does not block; the orchestrator continues from the store records.
- IA-8 (agent -> KB): query on the join key; an unavailable KB degrades the grounding; the agent authors from the `HuntConfig` alone.
- Inline back-edge (D67-14): the agent surfaces the need via IA-5; the orchestrator executes IA-6 and routes the result back on the `correlation_id`; the meaningfulness guard terminates the re-evaluation loop.

## 6. Assertion catalogue - work-item "hunting agent (per-agent spec from #67)"

**Source:** `docs/design/hunting-67-hunting-agent-spec.md` (this doc); parent `docs/design/hunting-67-per-agent-specs-spec.md` section 5.
**Seams under assertion:** IA-3 (spec handoff), IA-4 (verdict return), IA-8 (KB query), D67-02 (verdict mapping), D67-12 (worst case/failure state), D67-14 (inline re-evaluation), D4 (spec schema).

### 6.1 Contract predicates (integration tier)

C1 - Spec schema at D4: given a complete `HuntConfig` and a fixture KB, exercising success, the authored spec's typed base validates against merged spec section 7 (target identity, verification symptom(s), testing pattern, assumptions list, payload vector space present) and both NL fields are present.
Yields: `tests/integration/test_hunting_agent_contracts.py::test_spec_validates_against_typed_base`.
C2 - Empty KB at IA-8: given the KB returning zero entries, exercising empty-valid, the spec is authored from the `HuntConfig` alone and no raise occurs.
Yields: `...::test_empty_kb_degrades_to_config_grounding`.
C3 - KB raise at IA-8: given the KB raising, exercising degradation, the same degrade as C2; nothing raises.
Yields: `...::test_kb_unavailable_degrades`.
C4 - Malformed config at IA-3: given a `HuntConfig` missing one part, exercising malformed, the agent authors from the present parts and the feedback flags the gap.
Yields: `...::test_malformed_huntconfig_flags_gap`.
C5 - Pod success mapping at IA-4 (D67-02): given `{successful, symptom-confirmed}`, exercising success, the hypothesis verdict is `successful`.
Yields: `...::test_pod_success_maps_to_hypothesis_success`.
C6 - Clean-absent mapping at IA-4 (D67-02): given `{unsuccessful, space-exhausted}` with a clean trail, exercising success, the hypothesis verdict is `unsuccessful`.
Yields: `...::test_clean_absent_maps_to_hypothesis_unsuccessful`.
C7 - Infeasibility mapping at IA-4 (D67-02): given `{unsuccessful, infeasibility-asserted}` with the infeasibility in the trail, exercising success, the hypothesis verdict is `insufficient-evidence`.
Yields: `...::test_infeasibility_maps_to_insufficient_evidence`.
C8 - Pod reject at IA-3: given the pod rejecting the spec at INIT, exercising malformed, the agent re-authors once and lands a verdict or unsuccessful with the validation evidence; nothing raises.
Yields: `...::test_pod_init_rejection_triggers_reauthoring`.
C9 - Duplicate hypothesis at IA-3: given an identical spec already dispatched, exercising duplicate-idempotent, no second dispatch occurs.
Yields: `...::test_duplicate_hypothesis_not_redispatched`.
C10 - Inline no-meaningful-insight at IA-5 (D67-14): given an inline back-edge result that yields no meaningful insight, exercising ordering, the evaluation ends and the hunt enters the D67-12 failure state (no unbounded loop).
Yields: `...::test_no_meaningful_insight_ends_evaluation`.
C11 - Pod raise at IA-3: given the pod raising, exercising degradation, the agent treats the run as unsuccessful with the error in the evidence and continues or enters the failure state; nothing raises.
Yields: `...::test_raising_pod_degrades`.
C12 - Worst case at IA-4 (D67-12): given a hostile pair whose single test is technically unfeasible, exercising degradation, the hunt lands unsuccessful and the feedback carries the evidence-backed insights (never an empty feedback).
Yields: `...::test_worst_case_graceful_degradation_feeds_back`.

### 6.2 Walkthrough predicates (e2e tier)

The hunting agent's full-chain walkthroughs substitute nothing inside the live edge, so they are mechanisable only when the pod exists; they are carried as blocked until the pod ticket lands.

E1 - Confirmed hypothesis: grounds H1 and D67-02.
Entry seam: the `HuntConfig` dispatch (IA-2).
Input: a fixture `HuntConfig` with the five parts set to stated values: prompt template (rationale "fault-x applies to slug-a because ...", assumptions [...], supposed payload vectors [...], L0 evidence [...]), adapted index-card (spine + one-hop DFS of unit "kind:slug:a"), target caveats [...], prior-hunt insights [], tool registry [].
Live edge: none (self-contained; the pod is the real one).
Path: agent queries the fixture KB on `(fault-x, slug-a-technological-axis)` -> authors the spec -> pod executes -> `{successful, symptom-confirmed}` -> hypothesis-`successful` -> S7 persistence.
Terminal: the store holds the spec record with a full typed base, the hypothesis verdict `successful`, and the feedback record; exactly one pod execution recorded.
Observed: the hunt record read back from the store shows spec_ref, hypothesis verdict, and the pod result ref.
Yields: `tests/e2e/test_hunting_agent_walkthrough.py::test_confirmed_hypothesis`. Blocked by the pod ticket.
E2 - Inline back-edge re-evaluation: grounds H3 and D67-14.
Entry seam: the `HuntConfig` dispatch (IA-2).
Input: a fixture `HuntConfig` for a pair whose pod runs land `{unsuccessful, infeasibility-asserted}`.
Path: hypothesis-`insufficient-evidence` -> inline need surfaced via feedback -> orchestrator executes the recon -> meaningful insight routes back -> revised verdict.
Terminal: the hypothesis verdict is revised (not `insufficient-evidence`); the evidence trail contains the recon result.
Observed: the store's hunt record and the back-edge record on the `correlation_id`.
Yields: `...::test_inline_back_edge_revision`. Blocked by the pod ticket (and the real orchestrator).

## 7. Out of scope

The pod (its own spec doc), the orchestrator (its own spec doc), the symptom-technique KB content (operator-built external), the fault-targeting tool registry content (#71), and the closed-enum pattern engine (#81).
The merged spec's inter-agent logic (sections 10-14) governs the seams this document references.
