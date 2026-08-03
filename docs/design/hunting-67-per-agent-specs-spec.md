# Hunting spec: per-agent specs (hunt-orchestrator, hunting agent, stub test-executor pod)

Part of [#54](https://github.com/Diekgbbtt/polyphemus/issues/54) (hunting wayfinder map, Phase-2+ concretisation).
Resolves [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (enhancement, the graduated per-agent spec ticket).

*Status: spec (decision record + contract), NOT implementation. This is the phase-2 map convention: one spec per graduated ticket. The cooperative-team execution logic of the pod beyond the scaffold is deferred (D67-01; decision record section 4); the closed-enum testing-pattern engine is deferred (D67-07; decision record section 4); the hunt-store persistence is owned by [#68](https://github.com/Diekgbbtt/polyphemus/issues/68); the control-plane dispatch graph by [#69](https://github.com/Diekgbbtt/polyphemus/issues/69); the orchestrator memory by [#70](https://github.com/Diekgbbtt/polyphemus/issues/70); the deterministic components by [#71](https://github.com/Diekgbbtt/polyphemus/issues/71). This spec owns the per-agent contracts only. Mined on 2026-08-03 per the operator's request: sections 10-14 add the end-to-end walkthrough, the domain-data contracts, the interface agreements with delivery semantics and failure handling, and the agent-attribute compliance against the #9 agent-spec precedent.*

## 0. Provenance and decision record

- The decision record is `docs/design/hunting-67-per-agent-specs-decisions.md`, ratified through two direct grilling passes (2026-08-03).
- Every decision below carries its D67 number; the operator's verbatim answers, and the rejected alternatives, are in the record.

## 1. Problem statement

The Q8 walking skeleton (Q8, #62) fixes the three-tier hierarchy and the design/execution partition, but the per-agent contracts themselves are unspecified.
Each agent's tools, context, output, environment outcome, observability, and verifiability are open, and the executor pod's composition, state machine, stop conditions, and spec structure were explicitly deferred as grilling material by the ticket.

Three gaps follow:

1. The orchestrator's tool surface is undefined: it needs the back-edge and hunt-store reads, but whether it may ground in the live L0/L1 graph is open (D67-04).
2. The `TestImplementationSpec` is named but unstructured: the hunting agent does not know the shape to author, and the pod does not know the shape to consume (D67-03, D67-10).
3. The pod is a name without a machine: its composition, its loop, its terminal states, and its stop conditions are unspecified, so no build can start and no contract can be verified (D67-01, D67-02, D67-06).

## 2. Scope and boundaries

In scope:

- The per-agent contract of the hunt-orchestrator (planner).
- The per-agent contract of the hunting agent (typed, parametrised prompt template).
- The per-agent contract of the stub test-executor pod, including its minimal LangGraph scaffold (D67-01), its binary terminal states (D67-02), its four-way termination (D67-06), its variant mechanics (D67-08), and its internal fixed caps (D67-09).
- The `TestImplementationSpec` structure: a core NL body over a fundamental typed base (D67-03, D67-10).
- The shared observability recipe (D67-05).

Out of scope:

- The cooperative-team execution logic of the pod beyond the scaffold (ticket-boundary; the scaffold is the future build-on point, D67-01).
- The closed-enum testing-pattern engine (D67-07; deferred to a dedicated ticket after the specs finish).
- Hunt-store persistence (#68), control-plane dispatch (#69), orchestrator memory (#70), deterministic components (#71), fault-KB content (#66), yellow back-edge wiring (#64).
- The `exploit` submodule and phase-2 abduction / verification-pod roll-up (map out-of-scope list).

## 3. Shared principles

- **Ubiquitous language.** Terms from `src/polymerhus/attack/hunting/CONTEXT.md` are used verbatim; provisional terms stay marked provisional until ratified.
- **Sole-writer discipline.** No agent writes L0/L1; the pod and agents never mint graph nodes or edges (the fault-hypothesis is a phase-3 primitive, never a graph node - `domain-model.md` §2.6).
- **Fail-open.** Every agent degrades gracefully; exploration degrades, feedback flows, and no agent blocks a run.
- **DDD module conventions.** The pod is a sub-module within the hunting module and may use any construct the project's domain modules have (D67-01).
- **Token minimisation (DD-4).** Context is projected and bounded; the index-card projection is the surface-context budget rule.
- **Live reads.** Context that reflects the graph or the hunt store is re-derived at dispatch time from the live L0/L1 graph and the live hunt store, never taken from a pipeline snapshot (mirrors the [#9](https://github.com/Diekgbbtt/polyphemus/issues/9) agent-spec precedent).
- **Delivery canon.** All inter-agent delivery in this spec is synchronous and in-process in phase 1 (matching the recon interface-B MVP, `recon/control/targeted.py`); async promotion is a later concern, not a phase-1 contract.

## 4. The hunt-orchestrator (planner)

The planner selects candidates, configures hunts, dispatches, and holds memory + budget.

### 4.1 Role

A single planner agent, peer of the phase-2 orchestrator, in the hunting bounded context.

### 4.2 Goal

Select `HuntCandidate`s, configure and dispatch hunts so that every dispatched hunting agent yields at least one test-execution, and hold the orchestration state (memory, budget, back-edge needs) across the run.

### 4.3 Workflow

1. Consume the `FaultSource` output: `{(unit, fault, symptom, applies-witnesses)}` with the deterministic prune applied (the #63 typed predicate; the three-valued `match verdict` is the prune signal, Q8 level 1).
2. Run the in-turn reasoning gate (Q8): per fault-class, reason over the evidences plus the fault-class's concrete requirements (retrieved KB), producing rationale, assumptions, and envisioned test primitives.
   A KB-retrieval failure degrades the reasoning to the evidences alone (D67-11); it never prunes a direction by itself.
   Directions it is not sufficiently confident on are pruned in-turn (pure LLM heuristic, no confidence score); there is no distinct gating phase.
3. For each carried-forward direction, mint a `HuntConfig` and dispatch one hunting agent (N = 1 in phase 1).
4. Handle the back-edge: a yellow `insufficient-evidence` match verdict raises a targeted-recon need via the hunt back-edge (`request_targeted_recon`, `origin="hunting"`, #64-wired); park/resume and inline modes per Q8.
5. Collect hunts' outcomes and evidence trails, persist via the hunt store (#68) and orchestrator memory (#70), and advance the run.

### 4.4 Tools (D67-04)

The orchestrator's tool surface is: the hunt back-edge (targeted-recon requests, `recon/control/targeted.py::request_targeted_recon` with `origin="hunting"`), the hunt-store reads (candidates, configs, hunts, results, memory), AND a read-only view over the live L0/L1 graph.
The graph view is read-only: the orchestrator never writes L0/L1.

### 4.5 Context

The `FaultSource` outputs; the retrieved KB evidences (rationale, assumptions, envisioned test primitives); the hunt store reads; the read-only graph view; prior-hunt insights by revival key (#70); budget state (Q7 accounting).
The graph view and the hunt-store reads are live re-derives at orchestration time, never a pipeline snapshot (section 3).

### 4.6 Output

- A dispatched `HuntConfig` per carried-forward direction (the declarative config the hunting agent consumes; record D3).
- A back-edge need where a yellow verdict raised it (record D9, interface IA-6).
- Orchestration state transitions persisted to the hunt store (#68) and memory (#70).

### 4.7 Environment outcome

The hunt store reflects the orchestration lifecycle (candidates -> configs -> hunts -> results), the back-edge needs are recorded, and the run advances without blocking on any agent.

### 4.8 Observability

The shared recipe (section 8): one Langfuse trace per orchestration turn, spans per step named after the step; verdicts are measured through the hunt-store records and the eval harness, not through Langfuse score identifiers.

### 4.9 Verifiability

- Unit tier: orchestrator logic exercised with the graph view mocked and the hunt store mocked (no live Neo4j, per `docs/design/testing-strategy.md` §2; no live LLM, per the repo test-tier convention).
- Integration tier: `tests/integration/test_hunt_orchestrator_contracts.py` - the tool surface admits exactly the back-edge, hunt-store reads, and the read-only graph view; a write attempt through the view is rejected.
- E2E tier: `tests/e2e/test_hunt_orchestrator_walkthrough.py` - a full orchestration walkthrough against the eval target with the stub pod.

## 5. The hunting agent

The test-DESIGN side of the Q8 partition: a typed agent with a parametrised prompt template over a declarative `HuntConfig`; writes rich `TestImplementationSpec`s.

### 5.1 Role

One hunting agent per dispatched hunt (N = 1 in phase 1; per-symptom in phase 2), in the hunting bounded context.

### 5.2 Goal

Author, for its dispatched `HuntConfig`, a `TestImplementationSpec` that a test-executor pod can meaningfully execute, covering the low-level techniques grounded in the retrieved symptom-technique KB entries and the concrete surface evidence.

### 5.3 Workflow

1. Consume the `HuntConfig`: parametrised prompt template (rationale + extension points, assumptions, supposed payload vectors, L0 fault-applicability evidence), wide surface context (adapted index-card), target caveats, prior-hunt insights, fault-targeting tool registry.
2. Query the symptom-technique KB (the `fault KB` handle) for symptoms and probing-techniques on the join key `(fault-class, unit technological-axis)`.
3. Author the `TestImplementationSpec` (section 7): core NL over the fundamental typed base.
4. Yield the spec plus feedback to the orchestrator.
5. Worst case (D67-12): a hostile (fault-class, testable-unit) pair - one hypothesis verified, yielding one test - results in something technically unfeasible or a state with a strong blocking assertion, even after many variants have been executed.
   This is graceful degradation, not failure: the hunt still feeds evidence-backed insights to the orchestrator.
6. The actual HuntingAgent failure state (D67-12): no hypothesis could be successfully verified, AND further back-edged narrow recon requests provided no meaningful insights.
   The hunt degrades to `unsuccessful` with the attempted hypotheses' evidence trail, and the feedback still flows.
   `insufficient-evidence` never exists as a HuntingAgent state (Q8).

### 5.4 Tools

The fault-targeting tool registry (from `HuntConfig`); the symptom-technique KB query interface; the read-only graph view is NOT a direct tool (the orchestrator's view stays the sole graph access; the hunting agent consumes projections).

### 5.5 Context

The `HuntConfig` parameter set verbatim; the symptom-technique KB retrieval results (record D10); the adapted index-card surface context.
The index-card projection is a live re-derive at authoring time, never a pipeline snapshot (section 3).

### 5.6 Output

A `TestImplementationSpec` (the executor-pod input) and orchestrator feedback.

### 5.7 Environment outcome

The spec lands in the hunt store, wired to its hunt; the orchestrator receives the feedback; nothing is written to L0/L1.

### 5.8 Observability

The shared recipe (section 8): one Langfuse trace per spec-authoring turn, spans per step (KB retrieval, spec composition) named after the step; spec completeness is measured through the hunt-store records and the eval harness, not through Langfuse score identifiers.

### 5.9 Verifiability

- Unit tier: prompt-template parametrisation exercised with mocked KB and registry.
- Integration tier: `tests/integration/test_hunting_agent_contracts.py` - a `HuntConfig` maps to a `TestImplementationSpec` whose typed base validates against section 7's schema.
- E2E tier: the walkthrough covers spec authoring for the eval target and its consumption by the stub pod.

## 6. The stub test-executor pod

The test-EXECUTION side of the Q8 partition: a small cooperative agent team that executes a spec against the live target and returns `{verdict, evidence}`.
This turn ships the minimal scaffold only (D67-01).

### 6.1 Role (D67-01)

A cooperative team of agents, analogous to the recon job-executor pod but with a different topology.
In this implementation turn the in-scope deliverable is the minimal LangGraph scaffold that later builds can extend: general-purpose tool-calling capability, memory, Langfuse observability stubs, the communication interface with the parent HuntingAgent, and a helper symbolic layer used for specific testing-verification use-cases.
The pod is a sub-module within the hunting module, following the DDD approach.

### 6.2 Goal

Execute the `TestImplementationSpec` against the live target, drive the feedback-based testing loop, and return the binary verdict with the full experiment log as evidence (D67-02, D67-08).

### 6.3 Terminal states (D67-02)

The pod's state machine ends in exactly two terminal states: `successful` and `unsuccessful`.
The three-valued hypothesis verdicts `{successful, unsuccessful, insufficient-evidence}` are NOT pod states: they are the HuntingAgent's hypothesis-level evaluation, one level up, derived from the pod's binary outcome plus its evidence trail.
A pod-`unsuccessful` carrying infeasibility or noise in the trail can map to hypothesis-`insufficient-evidence`; a clean symptom-absent maps to hypothesis-`unsuccessful`.

### 6.4 The looped state machine (D67-06)

The pod's core is a looped, feedback-driven state machine, not a linear execution:

```
INIT -> (validate spec + environment contract; an invalid spec is rejected here, landing `unsuccessful` with the validation evidence in the trail - the pod never silently executes a malformed spec)
     -> PROBE (derive next probe from the current spec variant, the testing pattern, and the interpreted evidence)
     -> EXECUTE (tool call against the live target)
     -> OBSERVE (capture raw output)
     -> INTERPRET (classify: symptom-confirmed / symptom-absent / noise / infeasibility-signal; baseline comparison where the pattern is differential)
     -> DECIDE (update evidence; then either emit a verdict, decline an attribute into a variant, or stop)
     -> TERMINAL {successful, unsuccessful}
```

Interpretation generates the next probe: the executor may decline any attribute of the spec into a different variant (D67-03, D67-08).

### 6.5 Termination (D67-06)

The loop stops on exactly four conditions, all landing on the binary ends with the distinguishing evidence in the trail:

1. Symptom confirmed via the verification symptom(s) -> `successful`.
2. Pattern/probe space exhausted without symptom -> `unsuccessful`.
3. A strong technical infeasibility assertion (unreachable target, missing tool, everything WAF-blocked) -> `unsuccessful` with the infeasibility in the evidence trail.
4. Budget/timeout reached -> `unsuccessful` with partial evidence.

Budget and timeout are pod-internal fixed caps (D67-09): set by the pod itself, not carried as spec fields, not overridable by the spec.

### 6.6 The testing pattern (D67-07)

The testing pattern is an open NL pattern inside the typed envelope, treated by the engine as guidance over the generic loop.
The closed-enum pattern engine (replay-differential, fuzz-differential, oracle-based, blind-boolean, timing, composite) is deferred to a dedicated ticket with an exhaustive description, opened after the Phase-2+ specs finish.

### 6.7 Variants and the evidence trail (D67-08)

When the executor declines or refines an attribute of the spec, the result is a derived variant spec instance, recorded with provenance.
The pod exports the full experiment log as its evidence trail: the variant specs, the raw observations, and the interpretations.

### 6.8 Context

The `TestImplementationSpec`; the communication interface with the parent HuntingAgent; the memory and observability stubs; the helper symbolic layer.
The scaffold's tool surface is minimal: an HTTP probe tool (requests against the live target, bounded by the exec timeout) and an exec tool mirroring the recon pod's exec surface; the specialised fault-targeting tool registry is #71's future home.
The communication interface with the parent HuntingAgent is the typed handoff of the `TestImplementationSpec` (in) and `{verdict, evidence}` (out): records D4, D5, D6 (section 11), interfaces IA-3/IA-4 (section 12).

### 6.9 Output

`{verdict, evidence}` where `verdict` is binary and `evidence` is the full experiment log (D67-02, D67-08).

### 6.10 Environment outcome

The verdict and evidence land in the hunt store, wired to the hunt; the parent HuntingAgent consumes them for the hypothesis-level evaluation; nothing is written to L0/L1.

### 6.11 Observability

The shared recipe (section 8): one Langfuse trace per pod run, spans per loop iteration (probe, execute, observe, interpret) named after the step; the binary verdict is measured through the hunt-store records and the eval harness, not through Langfuse score identifiers.

### 6.12 Verifiability

- Unit tier: the looped state machine exercised with the tool calls mocked; each of the four termination conditions unit-tested to its binary end.
- Integration tier: `tests/integration/test_test_executor_pod_contracts.py` - the binary terminal invariant (never a third terminal state), the variant derivation rule (a declined attribute yields a derived variant spec with provenance), the infeasibility evidence in the trail.
- E2E tier: `tests/e2e/test_test_executor_pod_walkthrough.py` - one trivial real run against the eval target executing a spec and returning the binary verdict.

## 7. The TestImplementationSpec structure (D67-03, D67-10)

Core NL body inside a fundamental typed base.
The typed base covers everything except two NL fields: the rationale and the interpretation guidance.

### 7.1 Typed fields

- **Target identity** - the attack-surface element(s) to probe (service/system/endpoint identity, channel), bound to clear L0 evidences where present.
- **Verification symptom(s)** - the observable predicate(s) that would confirm the fault if observed; the load-bearing part of the spec.
- **Testing pattern** - the abstract strategy, open NL inside the typed envelope (D67-07).
- **Assumptions list** - the environment contract, brought over from the hunt-orchestrator prompt.
- **Payload vector space** - the parameterized input space, not a single literal.

Budget and timeout are NOT spec fields: they are pod-internal fixed caps (D67-09).

### 7.2 NL fields

- **Rationale** - why this test discriminates this hypothesis.
- **Interpretation guidance** - how the executor maps observations to evidence; the flexibility to interpret any unsuccessful output meaningfully and drive the feedback loop.

### 7.3 Composition (D67-03)

The spec carries: the attack-surface context, the rationale and the verification symptom(s), the assumptions (brought over from the hunt-orchestrator prompt), the relevant previous test findings (likewise passed on from the hunt-orchestrator prompt), the payload vector, and the testing pattern.
All of it is described at a high level as a baseline; where there are relevant clear evidences in the L0 surface, the description must reference them, so the test-executor core agent can interpret any unsuccessful output meaningfully and drive a feedback-based testing loop, which may involve declining any attribute of the spec into a different variant.

## 8. The shared observability recipe (D67-05)

The same Langfuse observability recipe applies to all three agents: hunt-orchestrator, hunting agent, and test-executor pod.
The pod's internals are observable to the same degree as the parent agents, not boundary-only.
The recipe is the repo's ratified v4 recipe (`docs/design/dataplane-A1-decisions.md` DPL-DEC-20, AST-DEC-09), applied verbatim:

- Langfuse is optional and fail-open: tracing failures drop span batches and never gate, block, or raise into a run (AST-DEC-09).
- One trace per agent turn/run; the session identifier is the run id (no `stream-` prefix on hunting run ids, so no stripping applies).
- Spans per step (orchestrator steps, spec-authoring steps, pod loop iterations), each span named after its step's node (span name = node name, DPL-DEC-20).
- Verdicts are NOT Langfuse score identifiers: `create_score` has no call sites and scores are designed-not-built (DPL-DEC-20). The authoritative verdict measurement is the hunt-store records (section 11) plus the eval-harness assertions (section 14, leg 9).
- Tags carry the verdict markers for localisation.

## 9. Coordination with sibling tickets

- #68 (hunt store): owns persistence of candidates, configs, hunts, results, and memory; this spec only declares what each agent reads/writes.
- #69 (control plane): owns the dispatch graph, implicit-coverage rule, gating wiring, back-edge modes, budget/ranker hooks; this spec fixes the orchestrator's tool surface (D67-04) as its input contract.
- #70 (memory): owns revival keys, fault-evidence records, the reuse gate; this spec consumes prior-hunt insights via the `HuntConfig`.
- #71 (deterministic components): owns the FaultSource prefilter engine, tool registry, budget governor; the typed `applies-if` predicate (#63) is its input contract.
- #64 (yellow back-edge wiring): owns the full trigger + wiring of the hunt back-edge; stubbed in this effort.
- The deferred closed-enum pattern engine (D67-07) opens as its own ticket with an exhaustive description after the specs finish.

## 10. The end-to-end walkthrough

This section traces one candidate through the whole flow; it is the reference path every contract in sections 11-14 must support.
Stages S0 and S2 are owned by sibling tickets (#66, #71); this spec fixes the contracts they feed into and consume.

### 10.1 S0 - Candidate production (FaultSource, #66/#71)

1. The FaultSource prefilter engine evaluates the typed `applies-if` predicates (#63) against the L1 model; each predicate that evaluates FALSE emits its violated clause as the deterministic half of the witness (the deterministic `does-not-apply`, a prune); TRUE/UNKNOWN evaluations pass without a witness.
2. An LLM match step evaluates the fault's applicability to the unit and returns the three-valued `match verdict` (`applies`, `does-not-apply`, `insufficient-evidence`) with the LLM half of the witness.
3. The candidate set `{(unit, fault, symptom, applies-witnesses)}` is delivered to the hunt-orchestrator; `symptom` is phase-2-populated and empty in phase 1.
4. Yellow `insufficient-evidence` verdicts are not dropped: they raise a back-edge need (S3, S6).

### 10.2 S1 - Orchestrator in-turn reasoning gate (this spec, 4.3)

1. The orchestrator consumes the candidate set plus the retrieved KB evidences.
2. Per fault-class, one reasoning turn produces the rationale, assumptions, and envisioned test primitives.
3. Directions it is not sufficiently confident on are pruned in-turn; there is no distinct gating phase and no confidence score.
4. Carried-forward directions proceed to ranking.

### 10.3 S2 - Ranking (Q7, #69/#71)

1. A multi-facet LLM risk ranker orders the carried-forward directions; the clear-L0-Observation facet is the most important one (Q7).
2. The budget governor (#71) may cut dispatch at the budget boundary; the phase-1 rule is N = 1 hunt per carried-forward direction.

### 10.4 S3 - Dispatch (this spec, 4.3, IA-2)

1. The orchestrator mints one `HuntConfig` (D3) per dispatched direction.
2. The hunting agent is dispatched with the `HuntConfig`; delivery is synchronous and in-process (IA-2).
3. Where yellow verdicts are present, the back-edge need is recorded for park/resume after the targeted recon lands (S6, IA-6).

### 10.5 S4 - Spec authoring (this spec, 5.3, IA-8)

1. The hunting agent queries the symptom-technique KB on the join key `(fault-class, unit technological-axis)` (IA-8).
2. The agent authors the `TestImplementationSpec` (D4): the typed base over the NL core.
3. Worst case: the authored spec is ephemeral and meaningless; the guarantee is at least one test-execution (5.3 step 5).

### 10.6 S5 - Pod execution (this spec, 6.4-6.7, IA-3/IA-4)

1. INIT validates the spec against the typed base schema and the environment contract; an invalid spec is rejected and lands `unsuccessful` with the validation evidence in the trail.
2. The loop runs PROBE -> EXECUTE -> OBSERVE -> INTERPRET -> DECIDE until one of the four terminations (6.5); tool calls hit the live target via the scaffold's HTTP probe and exec tools.
3. The pod returns `{verdict, evidence}` to the parent HuntingAgent (IA-4).

### 10.7 S6 - Hypothesis evaluation and the inline back-edge (this spec, 6.3, IA-6)

1. The HuntingAgent derives the three-valued hypothesis verdict from the pod's binary outcome plus the evidence trail.
2. Hypothesis-`insufficient-evidence` triggers either a narrow tool exec or a back-edged targeted-recon request (inline request-response mode, IA-6).
3. The inline mode allows unbounded re-evaluation (D67-14): each returned response may revise the hypothesis verdict; the evaluation continues while responses yield meaningful insights.
4. When an inline response yields no meaningful insight, the evaluation ends: the hunt either lands a verdict or enters the failure state (D67-12) - no hypothesis verifiable and recon no longer meaningful - degrading to `unsuccessful` with the evidence trail.
5. The back-edge is fault-agnostic on the wire; the `correlation_id` routes the result back.
   The depth-1 cap applies to park/resume only, not to the inline mode.

### 10.8 S7 - Persistence and advancement (this spec, 4.3, IA-7)

1. The orchestrator persists the hunt records (D8) and the revival key to the hunt store.
2. Memory (#70) records the fault-evidence records and the reuse gate.
3. Unresolved candidates terminate as `unresolved` with the residual gap carried on the revival key.
4. The run advances; no stage blocks on any agent (failure canon, section 13).

## 11. Domain data contracts

Every record this flow moves is declared here with its producer, consumer, and shape.
Records that already exist in the codebase are referenced, not redefined; records this spec introduces are type-now seams for the implementer.
D1-D11 are ratified contracts (D67-13): the hunt store (#68) may add persistence-specific fields when it implements, but must not remove fields the agents depend on.

### 11.1 D1 - Candidate record

- Shape: `{(unit_id, fault_class, symptom?, applies_witnesses)}`.
- Witness halves: the deterministic half (the violated clause emitted by the #63 typed predicate) and the LLM half (the match reasoning).
- Producer: FaultSource (S0).
- Consumer: hunt-orchestrator.

### 11.2 D2 - Match verdict record

- Shape: `{unit_id, fault_class, verdict: applies | does-not-apply | insufficient-evidence, witness}`.
- Producer: FaultSource LLM match (S0).
- Consumers: the orchestrator's prune signal (S1) and the back-edge trigger (S3/S6).

### 11.3 D3 - HuntConfig record

- Shape: the five-part parameter set: the parametrised prompt template (rationale + extension points, assumptions, supposed payload vectors, L0 fault-applicability evidence), the wide surface context (adapted index-card), the target caveats, the prior-hunt insights (by revival key, #70), and the fault-targeting tool registry.
- Producer: hunt-orchestrator (S3).
- Consumer: hunting agent.
- Reuses the existing index-card surface handle (`analysis/index_card.py`) and the L0 evidences (recon types).

### 11.4 D4 - TestImplementationSpec record

- Shape: the typed base (target identity, verification symptom(s), testing pattern, assumptions list, payload vector space) over the NL core (rationale, interpretation guidance) - section 7.
- Producer: hunting agent (S4).
- Consumer: test-executor pod.

### 11.5 D5 - Pod verdict record

- Shape: `{verdict: successful | unsuccessful, terminal_reason: symptom-confirmed | space-exhausted | infeasibility-asserted | budget-timeout, iterations}`.
- Producer: test-executor pod (S5).
- Consumer: HuntingAgent (hypothesis evaluation).

### 11.6 D6 - Experiment log record

- Shape: `{variant_specs, raw_observations, interpretations}` - the full evidence trail (D67-08).
- Producer: test-executor pod (S5).
- Consumers: HuntingAgent, hunt store.

### 11.7 D7 - Hypothesis verdict record

- Shape: `{verdict: successful | unsuccessful | insufficient-evidence, evidence_mapping, revival_key}`.
- Producer: HuntingAgent (S6).
- Consumers: hunt-orchestrator, hunt store, memory (#70).

### 11.8 D8 - Hunt record

- Shape: `{hunt_id, candidate_ref, config_ref, spec_ref, pod_result_ref, hypothesis_verdict, revival_key}`.
- Producer: hunt-orchestrator (S7).
- Consumers: hunt store (#68), memory (#70).

### 11.9 D9 - Back-edge request and response

- Shape: `AnalyserReconRequest` -> `TargetedReconResult` (existing models in `recon/control/targeted.py`), with `origin="hunting"`, the `correlation_id`, and the unit_id kind-qualified (`ReconScope.unit_id`).
- Producer: hunt-orchestrator (S3/S6).
- Consumer: recon; the result routes back on the `correlation_id`.
- Never redefined: the existing models are reused verbatim (interface agreement B, L1D-26).

### 11.10 D10 - KB retrieval record

- Shape: `{join_key, symptoms, probing_techniques}` for the key `(fault-class, unit technological-axis)`.
- Producer: symptom-technique KB.
- Consumer: hunting agent (S4).

### 11.11 D11 - Orchestrator feedback record

- Shape: NL feedback text plus any hypothesis verdict already derived (D7).
- Producer: hunting agent (S4/S6).
- Consumer: hunt-orchestrator (next-round reasoning).

## 12. Interface agreements

Each interface states its delivery semantics and its failure handling.
The delivery canon (section 3) holds: synchronous, in-process, phase 1.

### 12.1 IA-1 FaultSource -> hunt-orchestrator (candidate set)

- Delivery: synchronous, in-process, at run start.
- Failure: a fault whose LLM match exhausts yields an empty candidate set for that fault (fail-open, high recall); the exhaustion is counted; nothing raises into the orchestrator.

### 12.2 IA-2 hunt-orchestrator -> hunting agent (HuntConfig dispatch)

- Delivery: synchronous, in-process, one dispatch per carried-forward direction.
- Failure: an agent turn that exhausts yields the ephemeral meaningless spec (5.3 step 5); the run never blocks and no parent call raises.

### 12.3 IA-3 hunting agent -> test-executor pod (TestImplementationSpec handoff)

- Delivery: synchronous, in-process, typed handoff of D4.
- Failure: a spec failing INIT validation is rejected; the pod lands `unsuccessful` with the validation evidence in the trail (6.4); feedback flows to the orchestrator (D11); no silent hang.

### 12.4 IA-4 test-executor pod -> HuntingAgent ({verdict, evidence} return)

- Delivery: synchronous, in-process, typed return of D5 + D6.
- Failure: a pod run that raises degrades to `unsuccessful` with the error in the evidence trail; the pod never raises into the parent (mirrors the recon degrade-to-failed-export pattern, `recon/control/job_agent.py`).

### 12.5 IA-5 hunting agent -> hunt-orchestrator (feedback)

- Delivery: synchronous, best-effort.
- Failure: a lost feedback does not block the run; the orchestrator continues from what landed in the hunt store.

### 12.6 IA-6 hunt-orchestrator <-> recon (hunt back-edge)

- Delivery: `request_targeted_recon` with `origin="hunting"`; synchronous in-process MVP (interface agreement B, L1D-26); the `correlation_id` routes the result; fault-agnostic on the wire.
- Inline mode (S6): unbounded re-evaluation (D67-14); each response may revise the hypothesis verdict while it yields meaningful insights; a no-meaningful-insight response ends the evaluation (possibly entering the D67-12 failure state).
- Park/resume mode (S3): the depth-1 cap applies (a re-match still `insufficient-evidence` terminates the candidate as `unresolved`).
- Status vocabulary: `success`, `degraded`, `skipped`, `error` (`TargetedReconResult`).
- Failure: fail-open, never raises (`targeted.py`); a degraded or errored result is folded into the evidence trail.

### 12.7 IA-7 hunt-orchestrator <-> hunt store

- Delivery: reads at orchestration time, writes at S7; record shapes per section 11.
- Failure: a store write failure degrades to a logged warning; the run never blocks on a store failure (mirrors the recon registry-write fail-open).

### 12.8 IA-8 hunting agent -> symptom-technique KB

- Delivery: query on the join key `(fault-class, unit technological-axis)`.
- Failure: an unavailable KB degrades the grounding; the agent authors from the `HuntConfig` alone (fail-open).

## 13. Failure-handling canon

The mechanisms below are the repo's ratified patterns, applied to every agent of this spec.

- Fail-open: every step degrades, never raises into the caller, never blocks a run (precedent: `recon/control/pipeline.py` best-effort with the always-terminal `complete` run status; `recon/control/targeted.py` never raising).
- Retry: pod tool calls retry up to `MAX_POD_ITERS = 3` on non-zero exit; each exec is bounded by `EXEC_TIMEOUT_S = 300`; both are pod-internal fixed caps (D67-09), set by the pod, env-overridable, never carried in the spec.
- LLM exhaustion: bounded retry yields an empty result, counted (dataplane-A1 workflow precedent); the hunting agent's guarantee is the ephemeral meaningless spec, never nothing.
- Langfuse: optional and fail-open; tracing failures drop batches and never gate or block a run (AST-DEC-09).
- Store and registry writes: failures are logged and degraded, never crash the caller.
- Terminality: every pod run lands exactly one of the two binary terminals with the distinguishing evidence in the trail (6.5).

## 14. Agent-attribute compliance (comparison to the #9 agent-spec precedent)

The [#9](https://github.com/Diekgbbtt/polyphemus/issues/9) agent spec and the dataplane-A1 nine-leg schema define the attribute set an agent spec must pin: role, workflow, goal, tools, context, output template, produced outcome, observability, verifiability, plus the honour clauses.
This section maps every attribute to each agent of this spec and records what the mining closed.

### 14.1 The leg-by-leg map

- Role: #9 pins the role in the supervisory graph.
  Orchestrator: single planner, peer of the phase-2 orchestrator (4.1).
  Hunting agent: one per dispatched hunt (5.1).
  Pod: cooperative team with the minimal scaffold (6.1).
- Workflow: #9 pins the ordered steps.
  Orchestrator 4.3, hunting agent 5.3, pod 6.4-6.7.
- Goal: 4.2, 5.2, 6.2.
- Tools: #9 pins the named tool surface.
  Orchestrator: the admitted surface is exactly the back-edge, the hunt-store reads, and the read-only graph view; a write attempt is rejected (4.9).
  Hunting agent: the fault-targeting tool registry plus the KB query (5.4).
  Pod: the minimal scaffold surface of the HTTP probe tool and the exec tool (6.8); the specialised registry is #71's future home.
  Mining closed: the pod's tool surface was previously unspecified.
- Context: #9 pins live reads re-derived from the graph, never a pipeline snapshot.
  Mining closed: section 3's live-reads principle pins the orchestrator's graph view, the index-card projections, and the hunt-store reads as dispatch-time re-derives.
- Output template: #9 reuses existing typed shapes (L1DeltaBatch/AnatomyResult).
  Mining closed: section 11 reuses the existing models verbatim where they exist (D9, D3's index-card handle, the L0 evidences) and declares the missing records (D3, D4, D5, D6, D7, D8) as typed seams.
- Produced outcome: #9 pins the environment change.
  4.7, 5.7, 6.10: the hunt store reflects the lifecycle; nothing is ever written to L0/L1.
- Observability: #9 pins trace, span, and score identifiers.
  Mining corrected: the repo's ratified recipe (DPL-DEC-20, AST-DEC-09) has no Langfuse score identifiers (`create_score` has no call sites); span names equal node names; the authoritative verdict measurement is the hunt-store records plus the eval-harness assertions (section 8).
- Verifiability: #9 pins e2e assertions over outlier inputs and a unit tier with mocks.
  4.9, 5.9, 6.12 pin the files; the assertion families are the binary terminal invariant, the tool-surface admission, and the walkthroughs - the #63 assertion-catalogue pattern (C-series) is the template.

### 14.2 Honour clauses

- Sole-writer discipline: no agent writes L0/L1; agents persist only through the hunt store (section 3; 4.7, 5.7, 6.10).
- Sequential dispatch: one model turn at a time; N = 1 hunts in phase 1 (4.3).
- Fail-open: section 13.
- DDD disciplines: the pod is a sub-module of the hunting module; the glossary is the source of terms (6.1; section 3).
