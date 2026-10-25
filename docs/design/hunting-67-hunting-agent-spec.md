# Hunting agent spec: hunting agent

Part of [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (per-agent specs), middle of the agent hierarchy.
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`; it holds the inter-agent logic (walkthrough S0-S7, domain data contracts D1-D11, interface agreements IA-1..IA-8, failure-handling canon, agent-attribute compliance).
This document disambiguates the hunting agent from the combined spec: everything below is the hunting agent's contract alone, written to the depth an implementation session can build from without re-reading the parent.
Decisions cited as D67-n live in `docs/design/hunting-67-per-agent-specs-decisions.md`.

*Status: spec (contract), NOT implementation.*

**Redesign 2026-10-18.** Section 8 supersedes the workflow, input, tool, output, and typed-surface clauses of this document for the production hunter.
The superseded clauses are 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7-1.9, section 2, section 3, section 4, section 5, and the D4-dependent assertions in section 6.
Those sections retain the older contract for history and are not current.
The old text is retained for history.
The redesigned hunter consumes a loop payload, not a `HuntConfig`.
The production prompt is implemented in a dedicated work phase with refine-and-adversarial-review iterations.
The harness FSM is S4; the pod contract is S5; the impact map is `docs/design/unit-threat-model-spec-impact-map.md`.

## 1. Identity

The hunting agent is the test-DESIGN side of the Q8 design/execution partition: a typed agent with a parametrised prompt template over a declarative `HuntConfig`, authoring rich `TestImplementationSpec`s and driving the hypothesis evaluation loop through the pod.

### 1.1 Role

One hunting agent per dispatched hunt (N = 1 in phase 1; per-symptom in phase 2), in the hunting bounded context.
It is dispatched by the hunt-orchestrator (IA-2) and is the pod's parent (IA-3/IA-4).

### 1.2 Goal

Author, for its dispatched `HuntConfig`, a `TestImplementationSpec` that a test-executor pod can meaningfully execute, covering the low-level techniques grounded in the retrieved symptom-technique KB entries and the concrete surface evidence; then verify hypotheses through the pod and evaluate the four-valued hypothesis verdicts (D67-02, D67-12, Q3-amended).

### 1.3 Workflow

**SUPERSEDED by 8.4 and 8.5 (2026-10-18).** The hunter no longer consumes a `HuntConfig` and no longer runs the fault-hypothesis workflow below.

1. Consume the `HuntConfig` (D3): the parametrised prompt template (rationale + extension points, assumptions, supposed payload vectors, L0 fault-applicability evidence), the wide surface context (adapted index-card), the target caveats, the prior-hunt insights, and the fault-targeting tool registry.
2. Query the symptom-technique KB (the `fault KB` handle) for symptoms and probing-techniques on the join key `(fault-class, unit technological-axis)` (IA-8).
3. Author the `TestImplementationSpec` (D4, merged spec section 7): the core NL over the fundamental typed base.
4. Yield the spec plus feedback to the orchestrator (IA-5).
5. Run the hypothesis-evaluation loop: dispatch the pod (IA-3) on the spec, consume `{verdict, evidence}` (IA-4), derive the four-valued hypothesis verdict by the harness's deterministic trail-driven function (D67-02, Q3-amended), and either confirm success, land unsuccessful, or pursue `insufficient-evidence` via a narrow tool exec or an inline back-edge need surfaced through feedback (D67-14, IA-5 -> IA-6).
6. Worst case and failure state per D67-12 (section 4 below).

### 1.4 Tools

**SUPERSEDED by 8.7 (2026-10-18).**

The fault-targeting tool registry (from `HuntConfig`); the symptom-technique KB query interface.
The read-only graph view is NOT a direct tool: the orchestrator's view stays the sole graph access; the agent consumes projections.
There is NO recon tool: the back-edge seam belongs to the orchestrator (D67-04); inline needs are surfaced through IA-5 feedback and executed by the orchestrator.

### 1.5 Context

The `HuntConfig` parameter set verbatim; the symptom-technique KB retrieval results (D10); the adapted index-card surface context.
The index-card projection is a live re-derive at authoring time, never a pipeline snapshot.

### 1.6 Output template

**SUPERSEDED by 8.6 (2026-10-18).** The D4 surface no longer carries `testing_pattern`, `payload_vector_space`, or `interpretation_guidance`.

- The `TestImplementationSpec` (D4): typed base (target identity, verification symptom(s), testing pattern, assumptions list, payload vector space) over the NL core (rationale, interpretation guidance).
- The hypothesis verdict (D7): `{verdict: successful | unsuccessful | insufficient-evidence | underspecified-spec, evidence_mapping, revival_key}`.
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

**SUPERSEDED by 8.4-8.6 (2026-10-18).**

- The hypothesis-evaluation loop: this is the agent's second core activity after spec authoring.
  Per hypothesis: dispatch the pod (IA-3), consume `{verdict, evidence}` (IA-4), and derive the D7 hypothesis verdict (D67-02, Q3-amended): the verdict is a four-valued enum `{successful, unsuccessful, insufficient-evidence, underspecified-spec}`, derived by a PURE deterministic trail-driven harness function of the binary pod outcome plus the evidence trail - never LLM-judged.
  The ratified map: `{successful, symptom-confirmed}` -> `successful`; `{unsuccessful, space-exhausted}` with a clean trail -> `unsuccessful`; `{unsuccessful, technical-infeasibility}` -> `unsuccessful` (a structural blocker); `{unsuccessful, specific-defence-prevention}` -> `unsuccessful`; `{unsuccessful, no-symptom-evidence}` -> `insufficient-evidence` or `unsuccessful` (trail-driven); `{unsuccessful, budget-timeout}` -> `insufficient-evidence` or `unsuccessful` (trail-driven); a pod rejection at INIT carrying the validation evidence -> `underspecified-spec`.
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
H3 - Insufficiency resolved: the pod returns `{unsuccessful, no-symptom-evidence}` with a non-clean envelope (the single `clean` flag False: blocked or unreachable observations); the hypothesis verdict is `insufficient-evidence`; a narrow tool exec (or an inline back-edge returning a meaningful insight) revises the evaluation to a verdict. (Q3-amended: a `technical-infeasibility` terminal derives `unsuccessful`, never `insufficient-evidence`.)
H4 - Worst case (D67-12): the hostile pair yields one test that is technically unfeasible or strongly blocked after many variants; graceful degradation: the hunt lands unsuccessful and the feedback carries the evidence-backed insights.
H5 - Failure state (D67-12): no hypothesis verifiable and the inline back-edge returns no meaningful insights; the hunt lands unsuccessful with the attempted hypotheses' evidence trail.

### 4.2 Outliers

O1 - KB returns empty: the agent authors from the `HuntConfig` alone (degraded grounding, fail-open IA-8).
O2 - KB unavailable (raises): the same degrade; nothing raises.
O3 - Malformed `HuntConfig` (a part missing): the agent authors from the present parts and flags the gap in the feedback; nothing raises.
O4 - Index-card projection unavailable: the agent authors without the surface context (degraded).
O5 - Pod raises at IA-3: the agent treats the run as unsuccessful with the error in the evidence and continues the evaluation or enters the failure state; nothing raises.
O6 - Pod rejects the spec at INIT: the agent re-authors exactly once (declining attributes per D67-03); a second rejection lands the verdict `underspecified-spec` with the validation evidence; the re-authoring is bounded by the evaluation loop's budget and there is no third attempt.
O7 - Duplicate hypothesis: an identical spec is not re-dispatched to the pod (idempotent; the experiment log records one execution).
O8 - Inline back-edge returns `error`/`degraded` status: the result is folded into the evidence trail (IA-6 vocabulary) and the evaluation continues or ends.
O9 - Inline back-edge keeps returning non-meaningful results: the meaningfulness guard ends the evaluation (D67-14); the hunt enters the failure state; no unbounded loop escapes the guard.
O10 - Spec-authoring turn LLM exhaustion: the hunt degrades to unsuccessful with the partial authoring evidence in the feedback; there is no fallback template (D67-12); the guarantee is a design property, not a fallback.

## 5. Delivery semantics and failure handling

Delivery canon (merged spec section 3): all delivery is synchronous and in-process in phase 1.

- IA-3 (agent -> pod): synchronous typed handoff of D4.
  A spec failing INIT validation is rejected; the pod lands `unsuccessful` with the validation evidence; the agent re-authors exactly once, or lands `underspecified-spec` with the validation evidence; no silent hang.
- IA-4 (pod -> agent): synchronous typed return of D5 + D6.
  A raising pod degrades to `unsuccessful` with the error in the evidence (the pod's own contract; the agent handles the double's raise defensively too); nothing raises.
- IA-5 (agent -> orchestrator): synchronous best-effort feedback.
  A lost feedback does not block; the orchestrator continues from the store records.
- IA-8 (agent -> KB): query on the join key; an unavailable KB degrades the grounding; the agent authors from the `HuntConfig` alone.
- Inline back-edge (D67-14): the agent surfaces the need via IA-5; the orchestrator executes IA-6 and routes the result back on the `correlation_id`; the meaningfulness guard terminates the re-evaluation loop.

## 6. Assertion catalogue - work-item "hunting agent (per-agent spec from #67)"

**SUPERSEDED by 8.10 (2026-10-18) for the redesigned hunter.** The old assertions remain as history.

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
C7 - Infeasibility mapping at IA-4 (D67-02, Q3-amended): given `{unsuccessful, technical-infeasibility}` with the infeasibility in the trail, exercising success, the hypothesis verdict is `unsuccessful` (a structural blocker, never `insufficient-evidence`).
Yields: `...::test_infeasibility_maps_to_unsuccessful`.
C8 - Pod reject at IA-3 (Q3/Q5): given the pod rejecting the spec at INIT, exercising malformed, the agent re-authors exactly once; a second rejection lands the verdict `underspecified-spec` with the validation evidence; nothing raises.
Yields: `...::test_pod_init_rejection_lands_underspecified_spec`.
C9 - Duplicate hypothesis at IA-3: given an identical spec already dispatched, exercising duplicate-idempotent, no second dispatch occurs.
Yields: `...::test_duplicate_hypothesis_not_redispatched`.
C10 - Inline no-meaningful-insight at IA-5 (D67-14): given an inline back-edge result that yields no meaningful insight, exercising ordering, the evaluation ends and the hunt enters the D67-12 failure state (no unbounded loop).
Yields: `...::test_no_meaningful_insight_ends_evaluation`.
C11 - Pod raise at IA-3: given the pod raising, exercising degradation, the agent treats the run as unsuccessful with the error in the evidence and continues or enters the failure state; nothing raises.
Yields: `...::test_raising_pod_degrades`.
C12 - Worst case at IA-4 (D67-12): given a hostile pair whose single test is technically unfeasible, exercising degradation, the hunt lands unsuccessful and the feedback carries the evidence-backed insights (never an empty feedback).
Yields: `...::test_worst_case_graceful_degradation_feeds_back`.
C13 - Defence-prevention mapping at IA-4 (D67-02, Q3-amended): given `{unsuccessful, specific-defence-prevention}` with the blocking defence in the trail, exercising success, the hypothesis verdict is `unsuccessful` (never `insufficient-evidence`).
Yields: `...::test_defence_prevention_maps_to_unsuccessful`.
C14 - Trail-driven insufficiency at IA-4 (D67-02, Q3-amended): given `{unsuccessful, no-symptom-evidence}` with a non-clean envelope (`clean` False: blocked or unreachable observations), exercising success, the hypothesis verdict is `insufficient-evidence`.
Yields: `...::test_no_symptom_evidence_blocked_maps_to_insufficient_evidence`.
C15 - Trail-driven clean absence at IA-4 (D67-02, Q3-amended): given `{unsuccessful, no-symptom-evidence}` with a clean envelope (`clean` True: clean completed observations), exercising success, the hypothesis verdict is `unsuccessful`.
Yields: `...::test_no_symptom_evidence_clean_maps_to_unsuccessful`.
C16 - Budget-timeout partial trail at IA-4 (D67-02, Q3-amended): given `{unsuccessful, budget-timeout}` with a non-clean envelope (`clean` False: the loop cut mid-flight), exercising success, the hypothesis verdict is `insufficient-evidence`.
Yields: `...::test_budget_timeout_partial_maps_to_insufficient_evidence`.
C17 - Budget-timeout clean trail at IA-4 (D67-02, Q3-amended): given `{unsuccessful, budget-timeout}` with a clean envelope (`clean` True), exercising success, the hypothesis verdict is `unsuccessful`.
Yields: `...::test_budget_timeout_clean_maps_to_unsuccessful`.

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
Input: a fixture `HuntConfig` for a pair whose pod runs land `{unsuccessful, no-symptom-evidence}` with blocked observations in the trail (Q3-amended: `technical-infeasibility` would derive `unsuccessful`, never `insufficient-evidence`).
Path: hypothesis-`insufficient-evidence` -> inline need surfaced via feedback -> orchestrator executes the recon -> meaningful insight routes back -> revised verdict.
Terminal: the hypothesis verdict is revised (not `insufficient-evidence`); the evidence trail contains the recon result.
Observed: the store's hunt record and the back-edge record on the `correlation_id`.
Yields: `...::test_inline_back_edge_revision`. Blocked by the pod ticket (and the real orchestrator).

### 6.3 Isolated predicates (e2e tier, added 2026-08-05)

The isolated tier walks the REAL hunting agent end-to-end through its REAL infrastructure seams - the append-only markdown hunt-store files (S7), the stable system prompt resolved from the repo skill (implementation doc 4.10, embedded ahead of every LLM turn), the automated technological-axis derivation forming the IA-8 join key, and the tracing seam against the configured observability stack - with only the un-built collaborators as fixtures at their contract boundaries: the pod (#84), the spec-authoring and continuation-judgment LLM turns, and the symptom-technique KB content (operator-built external). That is the fixture-agent contract spec section 3 sanctions; the REAL pod chain remains the blocked E1/E2 walkthrough's live edge, never substituted here.

E3 - Ratified verbatims reach every LLM turn (implementation doc 4.10): the authored and judged turns both embed the REAL repo skill ahead of the per-invocation user prompt; the pass markers (`GROUND` / `DECOMPOSE` / `SPEC-WRITE` / `VERIFY-CLAIMS` / `RANK`) and the section headings are present, the fallback is not substituted.
Yields: `tests/e2e/test_hunting_agent_isolated_e2e.py::test_E3_real_skill_reaches_authoring_and_judgment_turns`.
E4 - S7 persistence is real files with provenance: the `spec.md` and `evidence.md` files exist under the run dir and carry the records; `_seq`/`_ref` carry run, kind, and store-wide ordering; the result's `spec_ref`/`pod_result_ref` equal the file records' `_ref`; the spec record is the flattened D4 typed base plus the hunt identity; the evidence record carries `derived_verdict` and the terminal reason.
Yields: `...::test_E4_real_file_persistence_with_provenance`.
E5 - Automated KB join key, once per hunt (IA-8/D10): across a Service and a System hunt, exactly one query per hunt, on `(fault_class, axis)` with the axis derived deterministically per card (`api_paradigm` preferred, then `navigation_model`, then the kind).
Yields: `...::test_E5_kb_join_key_derived_per_unit_kind`.
E6 - KB raise degrades over the real files (O2/C3): the agent authors from the HuntConfig alone, flags the gap in the feedback, and the spec still persists.
Yields: `...::test_E6_kb_raise_degrades_and_still_persists`.
E7 - Inline re-entry dedups over the real files (D67-14/C9): a routed back-edge re-enters the SAME candidate - one pod dispatch, one `spec.md` and one `evidence.md` record, stable refs, and the routed result reaches the judgment turn.
Yields: `...::test_E7_reentry_dedup_over_real_files`.
E8 - INIT-rejection lineage over the real files (Q3/Q5): two spec records with `parent_spec_ref` lineage, the re-authoring turn embeds the skill and the INIT validation evidence, and the second rejection lands `underspecified-spec` with the validation evidence on the evidence record.
Yields: `...::test_E8_init_rejection_lineage_over_real_files`.
E9 - Tracing seam against the observability stack: with the env configured, the hunting span is really open (trace id present) and flush completes without raising; with the client raising, a dispatch completes identically - tracing is best-effort and never perturbs a hunt.
Yields: `...::test_E9_tracing_seam_live_and_fail_open`.
E10 - Re-entry after an INIT re-author judges the LATEST committed spec (D67-08, added 2026-08-05): a hunt whose spec was rejected at INIT is re-authored, run, and returns insufficient-evidence; a routed back-edge then re-enters the candidate and the judgment turn consumes the re-authored spec's evidence trail (its interpretations), never the superseded original's - the latest experiment-log entry stands.
Yields: `...::test_E10_reentry_after_reauth_uses_latest_spec`.

## 7. Out of scope

The pod (its own spec doc), the orchestrator (its own spec doc), the symptom-technique KB content (operator-built external), the fault-targeting tool registry content (#71), and the closed-enum pattern engine (#81).
The merged spec's inter-agent logic (sections 10-14) governs the seams this document references.

## 8. Redesign 2026-10-18: the loop-driven hunter

### 8.1 Problem statement

The hunter is dispatched a `HuntConfig` that names a fault class.
It must invent the unit's trust agreements from a projection and a research direction.
Its workflow is a fault-hypothesis tree: DECOMPOSE into specific faults, GENERATE candidates, DISCRIMINATE, VERIFY-CLAIMS, RANK, dispatch each candidate.
The spec surface carries a testing pattern, a payload vector space, and interpretation guidance.
The testing pattern duplicates the class skill's procedural knowledge.
The payload vector space pre-narrows the attack before the hunter has grounded.
The fault-hypothesis vocabulary no longer matches the modeller, which produces trust-model loops, not faults.

The measured costs are:

- The hunter spends turns re-deriving the unit's trust model.
- The fault-hypothesis set is not the trust-model set; the hunter can miss the agreement the loop names.
- The payload vector space constrains the procedure before the evidence is collected.
- The old prompt's EVALUATE, CONCLUDE, and [G] nodes assume a pod map-back that does not exist.

### 8.2 Solution

The hunter consumes one loop payload.
It grounds on the technical failure modes of the trust agreement or the dynamic-state transition that yielded the loop.
It slices the failure-modes space the loop opens.
It collects discrimination-axis instances.
It discriminates and generates a spec set combinatorially.
It checks the set's well-formedness.
It verifies the load-bearing assumptions with falsification-only probes.
It writes the surviving specs as `ratified` and declasses the unfeasible ones as `dropped`.

The original decision tree's navigation is kept.
The new passes integrate into the tree; they do not replace it with a pipeline.
The production prompt is implemented in a dedicated work phase.
That phase runs multiple refine-and-adversarial-review iterations.
The prompt's gate hints are the hunter loop drivers; they need strong trajectory-keeping guarantees and surgical quality.

### 8.3 User stories

1. As an operator, I want the hunter to receive one loop, so that one dispatch has one research direction.
2. As an operator, I want the hunter to ground on the trust agreement's technical failure modes, so that the test follows the unit's actual interface or state transition.
3. As an operator, I want the hunter to load the class skill by the loop's suite class, so that the procedure is grounded in the class methodology.
4. As an operator, I want the hunter to collect discrimination-axis instances before it generates specs, so that the spec set covers the slice instead of a single guess.
5. As an operator, I want the encoding scheme excluded from the discrimination axis, so that the hunter does not mistake encoding variants for distinct directions.
6. As an operator, I want the spec set checked for overlap and exhaustive coverage, so that duplicate or missing regions are visible.
7. As an operator, I want the exhaustiveness check documented as a structural limitation, so that no one claims a mechanical guarantee that does not exist.
8. As an operator, I want the surviving specs marked `ratified` and the unfeasible ones `dropped`, so that the state vocabulary is consistent across the hunting artifacts.
9. As an operator, I want the falsification probes scoped to the spec's assumptions, so that the hunter verifies technical requirements without narrowing the attack vectors.
10. As an operator, I want payload vectors excluded from the falsification probes, so that vector probing stays a pod activity.
11. As an operator, I want the second DISCRIMINATE phase removed, so that the tree has one discrimination pass and an on-the-fly likelihood ranking.
12. As an operator, I want EVALUATE, CONCLUDE, and [G] removed, so that the prompt contains no dead pod map-back.
13. As an operator, I want the `supports`, `conflicts`, and `test` attributes removed, so that the spec carries only the execution-relevant content.
14. As an operator, I want the typed surface reduced to target identity, verification symptoms, assumptions, rationale, and lineage, so that the pod receives a simple execution contract.
15. As an operator, I want `payload_vector_space`, `interpretation_guidance`, and `testing_pattern` retired, so that the spec cannot pre-narrow the procedure.
16. As an operator, I want `verification_symptoms` to mean the concrete observable failure modes of the trust agreement, so that the pod's manifestation check is unambiguous.
17. As an operator, I want `assumptions` to mean the technical requirements the pod may falsify, so that the hunter and the pod share one semantics.
18. As an operator, I want the rationale to stay vulnerability-level, so that the hunter keeps the room to engineer its own procedure.
19. As an operator, I want the hunter's store key to be the loop dispatch id, so that one loop has one spec folder.
20. As an operator, I want the spec status vocabulary to be exactly `{hypothesised, ratified, dropped}`, so that no artifact uses `verified` or `specified`.
21. As an operator, I want the phase-summary notes to carry the pass exits, so that the harness can track the pass sequence without a status write.
22. As an operator, I want the grounding note rewritten on a grounding re-entry, so that the latest summary wins.
23. As an operator, I want the hunter-side materialisation retired, so that no KB materialisation block reaches the prompt.
24. As an operator, I want the dead verdict surfaces removed, so that no code path pretends to derive a hypothesis verdict.
25. As an operator, I want the pod dispatch path kept, so that ratified specs still reach the test-executor pod.
26. As the hunter, I want the loop ontology in one prompt paragraph, so that I can reason over the unit, the sharpening, the trust model, the abduction chain, the confidence degree, and the failure-modes slice.
27. As the hunter, I want the grounding pass to start on the target surfaces, so that the frame comes from the live unit, not from a class checklist.
28. As the hunter, I want the hacking KB used only for target technology configurations in grounding, so that instance mining happens in collection.
29. As the hunter, I want the collection pass to mine advanced techniques, chaining prerequisites, technology-specific failure modes, and payload-vector classes, so that the discrimination has real instances.
30. As the hunter, I want the well-formedness pass to loop in the reasoning while the harness state stays put, so that the trajectory shows one pass, not inner-loop transitions.
31. As the hunter, I want the verify-claims pass to probe only falsifiable technical requirements, so that a failed probe lowers confidence without erasing the direction.
32. As a reviewer, I want the prompt work phase to have its own adversarial review, so that the loop drivers are surgically specified.
33. As a reviewer, I want the old fault-hypothesis assertions superseded, so that the test suite does not pin a retired workflow.
34. As a runtime operator, I want the hunter's session id to name the unit and the loop, so that the dispatch is traceable.
35. As a runtime operator, I want the pod session to name the loop dispatch and the spec, so that the execution lineage is traceable.

### 8.4 The pass sequence

The hunter's reasoning passes are:

| Pass | Input | Work | Exit signal | Done when |
|---|---|---|---|---|
| `GROUNDING` | The loop payload, the unit projection, the live target, the class skill, the methodology KB, the HTTP history, the notes, the hunt store, the auth context | Establish the frame, the hard constraints, and the assumptions. Ground on the trust agreement's technical failure modes. Explore the sources; exploit means exit. | `notes` write: `kind=phase_summary`, `note_name=phase:grounding` | The frame is explicit, the technical failure modes are identified, and the load-bearing claims are verified, revised, or marked with visible uncertainty. |
| `SLICE` | The grounding output | Define the region of the failure-modes space the loop opens. | `phase:slice` note | The slice definition is explicit, with the boundary and the variables that delimit it. |
| `COLLECT` | The slice | Query the methodology KB, the previous hunt stores, and the notes for as many instances as possible of the discrimination axis. | `phase:collect` note | The instance set covers the axis broadly enough to discriminate. |
| `DISCRIMINATE` | The slice and the instances | Split the slice over the axis instances. Choose the discriminating variables. Resolve the narrow/broad trade-off. | `phase:discriminate` note | The axis instances and the discrimination are explicit; each spec slot is distinguishable from its nearest alternative. |
| `GENERATE` | The discrimination | Generate the spec set combinatorially over the axis instances. Write one spec per `hunts_store` call, each with `status=hypothesised`. | One `hunts_store` write per spec | The spec set is written. |
| `WELL-FORMEDNESS` | The spec set | Check no overlap and exhaustive coverage over the slice. Merge or drop. A new iteration re-enters COLLECT or GENERATE in the reasoning. | `phase:well_formedness` note | The set is well formed, or the iteration has a recorded remaining gap. |
| `VERIFY-CLAIMS` | The surviving specs | Probe the load-bearing technical requirements with falsification-only probes. Loop until the requirement is resolved or the meaningfulness guard ends it. | One `hunts_store` write per survivor to `ratified`, then `finalize`; declass unfeasible specs to `dropped` | The terminal set is persisted. |
| `COMPLETE` | The final spec set | No model work. The surfer dispatches the pod. | Terminal | The hunt ends. |

The harness tracks the pass sequence passively.
A pass exit advances the tracked state.
An earlier pass's signal appends to the trail and never moves the state back.
A later pass's signal advances as a reality-restoring forward jump and records the skipped states.
Loops exist at GROUNDING, WELL-FORMEDNESS, and VERIFY-CLAIMS.
The harness stays in the looping pass until that pass's exit signal fires.
Inner-loop calls are trail material, not transitions.
The full state and signal contract is S4 14.

### 8.5 The prompt and the tree

The original decision tree's navigation is kept.
The new passes integrate into it.
The hunter may revisit a decision point when evidence justifies it.
The production prompt work phase writes the final prose.

The prompt must carry:

**Discipline.**
The mock prompt's end-discipline paragraph extends the wider discipline paragraph already present in the current system prompt.
The prompt must carry the discipline section with the evidence-before-assertion, no-bulldozing, attempt-cap, meaningful-insight-guard, fail-open, target-front availability, and graceful-degradation clauses.

**Role framing.**
The agent is aware of its role in the hunting process only.
The role is "engineering web vulnerability tests".
The prompt mentions no wider codebase position and no hunter system versions.

**Loop ontology.**
One dedicated paragraph defines the loop's entities:

- The unit and its technical sharpening.
- The trust model: the trust agreement or the dynamic-state transition.
- The abduction chain: the programming fault and the vulnerability that characterises the application if the fault is implemented.
- The confidence degree.
- The failure-modes-space slice.
- The reasoning from the loop to engineered attacks.

**Decision tree.**
The tree's nodes are:

```
GROUND
  -> [D1] frame and technical failure modes established?
  -> SLICE -> COLLECT -> DISCRIMINATE -> GENERATE
  -> WELL-FORMEDNESS --[D2: new instances or specs]--> COLLECT or GENERATE
  -> VERIFY-CLAIMS -> COMPLETE
```

The [D2] re-entry is a reasoning iteration.
The tracked state stays WELL-FORMEDNESS until the exit note.
The second DISCRIMINATE phase is removed.
An on-the-fly likelihood ranking replaces it.

**Grounding.**
Ground on the target surfaces first.
Then load the class skill.
Then consult the other sources: the methodology KB for target technology configurations only, the HTTP history, the notes, the hunt store, and the auth context.
The class-exhaustiveness question over "specific faults of this class" is removed.
The grounding target is the technical failure modes of the trust agreements in an interface or in a state transition.
The grounding is an explore/exploit pass.
The in-loop retrieval-gap check is a rider on a grounding KB query; it is not a transition.

**SLICE.**
The pass yields the slice definition: the region of the failure-modes space the loop opens.
The slice is prose reasoning.
It ends in no spec and no store write.

**COLLECT.**
The pass mines as many instances as possible of the axis the hunter will discriminate on:

- Advanced techniques: proxies that ease attack complexity or yield an execution mode that could manifest a symptom.
- Chaining with other low-hanging vulnerabilities: whether a prior vulnerability must be exploited to gain a capability; which vulnerability can be exploited beforehand.
- Technology-specific failure modes: for example configured failover when the default configuration is used.
- Payload-vector classes: discriminated on the effective request item that carries the vector, the communication protocol, and behaviours such as redirects or indirect deliveries.
- The encoding scheme is not a discrimination variable.

**DISCRIMINATE.**
The pass splits the slice over the collected axis instances.
It chooses the variables that separate the specs.
It records the narrow/broad trade-off.

**GENERATE.**
The pass is the combinatorial function over the axis instances.
The `supports`, `conflicts`, and `test` attributes are removed.
They are structural from the threat model.
The spec set is written with `status=hypothesised`.

**WELL-FORMEDNESS.**
The pass checks the spec set for no overlap and exhaustive coverage of the slice.
It may merge entries or drop them.
The pass records the merge and drop decisions in the `phase:well_formedness` note.
It does not write `dropped` statuses; the terminal write at VERIFY-CLAIMS applies them.
A new iteration re-enters the reasoning.
Systematically verifying exhaustiveness is a structural limitation of the contract; the prompt does not claim a mechanical guarantee.
The check absorbs the removed class-exhaustiveness question in its new form.

**VERIFY-CLAIMS.**
The pass stays scoped to assumption-falsification probes.
A strong technical requirement that comes from a broad assumption is a probe target: advanced-technique feasibility, chained preliminary-vulnerability feasibility, technology-configuration evidence.
Payload vectors may not yield these probes.
The posture stays fail-open and loose.
When a probe yields no meaningful insight, the evaluation ends.
The probe iterations do not move the tracked state.

**Removals.**
EVALUATE, CONCLUDE, and the [G] decision node are removed completely.
No pod map-back exists today.
The second DISCRIMINATE phase is removed.
The fault-hypothesis vocabulary is removed from the hunter prompt.

**Phase hints.**
The workflow injects a `<phase-transition-hint>` only when a pass exits.
The ending tool response of the pass carries the hint.
The hint names the next pass.
The hint is guidance, never a gate.
No call is refused for the pass the tracked state is in.

**Examples.**
The worked examples are rewritten for the new passes and the reduced spec surface.
They imitate the reasoning shape, not the old domain.

### 8.6 The typed surface and the spec-set lifecycle

The D4 surface is reduced:

- `target_identity`: `{url, unit_id}`.
  `url` is the base URL the pod probes.
  `unit_id` is the kind-qualified L1 identity.
- `verification_symptoms`: a non-empty list of the concrete observable failure modes of the trust agreement over an interface or a state transition.
  This is the manifestation ground truth for the pod.
- `assumptions`: the technical requirements the pod may falsify.
  They are not the modeller's trust assumptions.
- `rationale`: the vulnerability-level rationale.
  It carries no failure-mode detail and no narrowed vector.
- `parent_spec_ref`: the variant lineage, when the spec is derived.
- `provenance`: the dispatch context.
  It carries `run_id` (bound by the tool, never authored), `loop_id`, `unit_id`, `canonical_class`, `web_vulnerability_class`, `baseline_ref` (optional), `source_recon_refs`, `assumption_ref`, `playbook`, and the bounded `skill_procedure` for the pod's triager.
- `skills`: the optional flat pod-runner skill list.
  Each name is a skill the runner may carry.
  It is never a path and never a meta-skill.

The write surface adds three fields to the canonical `TestImplementationSpec`:

- `status`: `hypothesised`, `ratified`, or `dropped`;
- `fault_keyword` and `strategy_keyword`: the two words the store derives the identity from.

`spec_id` is derived as `<fault_keyword>_<strategy_keyword>`.
It is never authored.

The prompt's `## The spec body` is a generated projection of `SpecWrite`, `SpecProvenance`, `TargetIdentity`, and `SkillProcedure`.
It names every writable field, its type, and its requiredness.
A hand-written partial field list is not allowed to drift from the models.

The retired fields are `payload_vector_space`, `interpretation_guidance`, and `testing_pattern`.
The pod's variant machinery is S5.
`variants` is a pod-side concept: the pod's `VariantSpec` is a combination of a subset of the skills-ontology entities.
The hunter's spec set is not a variant set.
This is the recorded reading of R8-1's `variants` bullet: the pod's variant machinery is unchanged in concept; the hunter's spec set is not a variant set.

The `skill_procedure` is typed:

```
SkillProcedure:
  recon_action: str
  bypass_technique: str
  technology_grounding: str
  pro_tips: str
  advanced_technique: str
  preliminary_chaining: str
  interpretation_pitfalls: str
```

The hunter authors it from the loaded class skill.
Each field carries the skill's text for that procedure section.
The total excerpt is bounded to 4000 characters.
The field names are the seven gap classes of S5 8.6.
The triager maps each gap class to its field.

The spec-set lifecycle is:

- `hypothesised`: the spec written at GENERATE.
- `ratified`: the surviving spec at the terminal write.
- `dropped`: the declassed spec at the terminal write.

A WELL-FORMEDNESS "merge" is a descriptive judgement, not a fourth status.
The merged-away spec is written `dropped`; the surviving spec is `ratified`
(possibly rewritten first). The store and the mover read only the three
literals above.

The spec body is the typed spec at every status.
There is no separate `FaultItem` draft.
The spec identity is the file-name stem `<fault_keyword>_<strategy_keyword>`.
The store derives it from the payload's keywords.
The payload carries no `spec_id` field.
The `verified` and `specified` values are retired.

The spec set is well formed when:

- No two specs overlap.
- The set covers the slice exhaustively.
- Every spec is falsifiable: it states what symptom-absent means.

The exhaustiveness verification is a documented structural limitation.
The contract does not claim a mechanical check.
The prompt does not add a payload-completeness rule.

### 8.7 Tools, store, and dispatch

The hunter's tool surface is:

- `hunts_store`: read/write over the loop's spec folder.
  - The hunt key is the loop dispatch id `<unit_name>__<loop_id>`.
  - The key is bound at tool construction; it is never a request field.
  - The write carries exactly ONE `spec` object, never a list.
  - The required fields are `status`, `fault_keyword`, `strategy_keyword`, and `target_identity.url`.
  - A rejected write is a coded `hunts_store_write_rejected` naming the field.
  - The GENERATE write persists one spec with `status=hypothesised`.
  - The terminal write closes the set after the surviving specs are `ratified` and the unfeasible specs are `dropped`.
  - A zero-spec hunt is a valid terminal set.
  - A write after `finalize` is rejected.
  - The store derives the file name `<fault_keyword>_<strategy_keyword>.yaml` and the folder `test-specs/<hunt_key>/`.
  - The `hypothesised` write creates; a later status upserts in place.
  - A duplicate identity is a dedup signal; a re-author updates in place.
- `notes`: read/write over the hunter notes store.
  - The note key is bound to the hunt key.
  - The existing kinds are available.
  - The `phase_summary` kind is added.
  - The phase note name is `phase:<phase>`; a re-iteration updates the same note.
  - The note body states the pass's output and the rationale, within the conciseness cap.
- `graph_view`: the read-only L0/L1 view.
- `kb_query`: the methodology KB, always bound.
  - In grounding it grounds on the target technology configurations.
  - In collection it mines the axis instances.
- `exec`: the Kali exec tool, unbounded at the harness level.
  - The target-front availability directive applies.
- `skill_list` / `skill_load`: the web-vulnerability suite.
  - `skill_list` requires a case-insensitive name regex.
  - A parent match includes its class leaves; a leaf match includes its class parent.
  - The loop's suite class selects the class skill.
- `search_http_history` / `get_http_artifact`: the project's recorded HTTP traffic.
  - Search returns sanitized candidate rows.
  - Get inspects one artifact and its capture state.
  - The record's artifact id becomes the spec's `provenance.baseline_ref`.
  - Replay is the pod's act, never the hunter's.
- `load_skill`: the project skill catalogue.
- `record_skill_lesson`: the skill-usage lesson recorder.
- `auth_store`: the project authentication context, in READ-ONLY mode.
  - The hunter reads the view.
  - The hunter never writes the store.

The request tool definition is the full tool surface.
The loop tool surface is removed.
The prompt's `## The tools` is a complete human summary of the bound surface.
It names every tool above and carries no second description body.
The request schemas remain the machine contract.
The top-level descriptions carry purpose, operation, constraints, the coded error envelope, and the critical usage clauses.

The hunter's first human message is ONE instance-context message.
It carries the application overview, the loop grounding, the current state, and the step protocol.
It carries no loop tool surface.
The compaction pin preserves this message for the whole hunt.

The technical sharpening in the loop grounding is projected to `id`, `statement`, and `confidence`.
The agreement evidence entries stay out of the projection; the loop evidence carries the references.

The pod dispatch path stays:

- The terminal write produces ratified specs.
- The surfer moves a ratified spec to `consumed/` and dispatches one pod session.
- The pod session id is `hunting:<run_id>:pod:<unit_name>__<loop_id>:<spec_id>`.
- The hunter derives no hypothesis verdict.
- The pod exports its result; the verdict-consumption workflow remains out of scope.

The hunter's store key, folder, and session id no longer use a `fault_key` or a `HuntConfig`.
The old per-config memory layout is superseded.

### 8.8 Removals and supersessions

The hunter-side materialisation is retired fully:

- The prompt-builder render `_render_materialisation`.
- The `HuntConfig.materialisation` slot.
- The symptom-seam fallback consumption.

The dead verdict and pod-result surfaces are removed:

- `derive_verdict`.
- `SpecItem.experiment_ref`.
- The dead verdict and pod-result residue the implementation enumerates.
- The old `HuntState` fault lists, `current_fault`, the four-value `FaultStatus`, `FAULT_STATUSES`, `HuntPhase`, the status detector and push functions over the fault lifecycle.
- The old hint constants `D2_HINT`, `COMMIT_SPECIFICATION_HINT`, `NEXT_FAULT_HINT`, `NEXT_ITERATION_HINT`, and `D3_HINT`.
- The old `FaultItem` draft body and the `specified` body distinction.
- The old prompt nodes EVALUATE, CONCLUDE, and [G], and the old fault-hypothesis examples.

The pod dispatch path stays.
The `hunts_store`, `notes`, `graph_view`, `kb_query`, and `exec` tool names stay.
The `skill_list`, `skill_load`, `search_http_history`, `get_http_artifact`, `load_skill`, `record_skill_lesson`, and `auth_store` tools are added.
The loop tool surface is removed.
The request tool definitions are the full surface.

### 8.9 Implementation decisions

- The hunter is dispatched with a loop payload, not a `HuntConfig`.
- The loop payload fields are S2 8.2.
- The hunter's session id is `hunting:<run_id>:hunt:<unit_name>__<loop_id>`.
- The hunter's store key is `<unit_name>__<loop_id>`.
- The hunter's spec folder is `test-specs/<hunt_key>/`.
- The spec body is the reduced D4 surface at every status.
- The status values are `{hypothesised, ratified, dropped}`.
- The GENERATE write persists one spec per call.
- The terminal write closes the set and applies the promotes and declasses.
- The `skills` field carries the flat pod-runner skill list.
- The `run_id` is bound and never authored.
- The `spec_id` is derived and never authored.
- The `skill_procedure` is the typed seven-field excerpt above.
- The `baseline_ref` rides the provenance when the hunter has a recorded baseline.
- The prompt's spec body is generated from the typed models.
- The first human context is pinned through compaction.
- The auth store is bound read-only.
- The `variants` concept stays pod-side; the spec set is not a variant set.
- The prompt's discipline paragraph extends the existing wider discipline paragraph.
- The phase-summary notes carry the pass exits.
- The harness stays in the looping pass until its exit signal.
- The production prompt is a dedicated work phase with adversarial review.
- The prompt's role framing excludes codebase position and versions.
- The prompt's grounding uses the methodology KB only for target technology configurations.
- The prompt's collection mines the discrimination-axis instances.
- The prompt's verify-claims probes only the assumptions.
- The `skill_procedure` excerpt rides the spec provenance for the pod triager.

The implementation follows the patterns recorded in `src/polymerhus/attack/hunting/CONTEXT.md`: the state-graph hunter's passive detect-and-push machine, the hunter memory store's derived-symbol and move-aware write, the shared notes tool base, the atomic store writes (#340), and the phase-transition verbatims.
The hunter replicates the similar component and keeps the single-writer discipline.

### 8.10 Testing decisions

Test external behaviour: the persisted specs, the store folder, the statuses, the note exits, and the prompt's required clauses.

Seams:

- The pure pass tracker: signal detection, monotonic state, forward jump, trail-only backward signal, loop discipline.
- The graph: injected observations drive the state moves and the hint injection.
- The store: bound key, derived file name, status lifecycle, move-aware write.
- The notes: `phase_summary` kind, `phase:<phase>` names, update-on-re-iteration.
- The prompt: the eight passes, the four axis families, the removed nodes, the reduced D4 fields, the role framing, the grounding KB scope.
- The dispatch: one pod per ratified spec; the session id shape.
- The materialisation removal: no render path remains.
- The verdict removal: no `derive_verdict` path remains.

Prior art:

- The state-graph hunter tests.
- The hunter memory and store tests.
- The spec-set quality measurement (`docs/experiments/unit-threat-model-testimplspecs-qa.md`) as the prompt-quality baseline.
- The isolated end-to-end harness with fake tools and the real skill file.

### 8.11 Out of scope

- The harness FSM (S4).
- The pod contract (S5).
- The modeller and the artifact (S1, S2).
- The closed-enum pattern engine (`#81`).
- The fault-targeting tool registry (`#71`).
- The verdict-consumption workflow.
- The TBSG exploration (`#371`).

### 8.12 Further notes

The workbench R8-1 carries the prompt decisions.
The workbench R8-2 and R8-3 carry the harness and pod decisions.
The impact map carries the supersession ledger.
The production prompt work phase is the only place the final prose is written.
The prompt work phase must run through multiple refine-and-adversarial-review iterations.

### 8.13 Context dedup amendment (2026-10-23)

The shared decision record is `docs/design/hunting-context-dedup-2026-10-23-adr.md`.
The impact map is `docs/design/hunting-context-dedup-impact-map.md`.

The hunter changes are:

- The loop tool surface is removed.
  It duplicated the request descriptions inside the first human message.
- The first human message is one instance-context message.
  It carries the application overview and the loop grounding together.
- The compaction pass pins that first human message.
- The `## The spec body` is generated from `SpecWrite`, `SpecProvenance`, `TargetIdentity`, and `SkillProcedure`.
- The `skills` field is documented as the flat pod-runner skill list.
- The `run_id` is documented as bound and the `spec_id` as derived.
- The technical sharpening is projected to `id`, `statement`, and `confidence`.
- The phase hint is described as a transition signal.
- The tool descriptions are dense usage projections under an 8,500-char ceiling.
  The schemas remain the machine contract.
- The auth store is bound read-only.

The tool-list completion and the description budget are covered by `tests/attack/test_hunting_agent_prompt.py` and `tests/attack/test_tool_description_budget.py`.
