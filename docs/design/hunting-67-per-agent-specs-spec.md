# Hunting spec: per-agent specs (hunt-orchestrator, hunting agent, stub test-executor pod)

Part of [#54](https://github.com/Diekgbbtt/polyphemus/issues/54) (hunting wayfinder map, Phase-2+ concretisation).
Resolves [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (enhancement, the graduated per-agent spec ticket).

*Status: spec (decision record + contract), NOT implementation. This is the phase-2 map convention: one spec per graduated ticket. The cooperative-team execution logic of the pod beyond the scaffold is deferred (D67-01; decision record section 4); the closed-enum testing-pattern engine is deferred (D67-07; decision record section 4); the hunt-store persistence is owned by [#68](https://github.com/Diekgbbtt/polyphemus/issues/68); the control-plane dispatch graph by [#69](https://github.com/Diekgbbtt/polyphemus/issues/69); the orchestrator memory by [#70](https://github.com/Diekgbbtt/polyphemus/issues/70); the deterministic components by [#71](https://github.com/Diekgbbtt/polyphemus/issues/71). This spec owns the per-agent contracts only.*

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

## 4. The hunt-orchestrator (planner)

The planner selects candidates, configures hunts, dispatches, and holds memory + budget.

### 4.1 Role

A single planner agent, peer of the phase-2 orchestrator, in the hunting bounded context.

### 4.2 Goal

Select `HuntCandidate`s, configure and dispatch hunts so that every dispatched hunting agent yields at least one test-execution, and hold the orchestration state (memory, budget, back-edge needs) across the run.

### 4.3 Workflow

1. Consume the `FaultSource` output: `{(unit, fault, symptom, applies-witnesses)}` with the deterministic prune applied (the #63 typed predicate; the three-valued `match verdict` is the prune signal, Q8 level 1).
2. Run the in-turn reasoning gate (Q8): per fault-class, reason over the evidences plus the fault-class's concrete requirements (retrieved KB), producing rationale, assumptions, and envisioned test primitives.
   Directions it is not sufficiently confident on are pruned in-turn (pure LLM heuristic, no confidence score); there is no distinct gating phase.
3. For each carried-forward direction, mint a `HuntConfig` and dispatch one hunting agent (N = 1 in phase 1).
4. Handle the back-edge: a yellow `insufficient-evidence` match verdict raises a targeted-recon need via the hunt back-edge (`request_targeted_recon`, `origin="hunting"`, #64-wired); park/resume and inline modes per Q8.
5. Collect hunts' outcomes and evidence trails, persist via the hunt store (#68) and orchestrator memory (#70), and advance the run.

### 4.4 Tools (D67-04)

The orchestrator's tool surface is: the hunt back-edge (targeted-recon requests, `recon/control/targeted.py::request_targeted_recon` with `origin="hunting"`), the hunt-store reads (candidates, configs, hunts, results, memory), AND a read-only view over the live L0/L1 graph.
The graph view is read-only: the orchestrator never writes L0/L1.

### 4.5 Context

The `FaultSource` outputs; the retrieved KB evidences (rationale, assumptions, envisioned test primitives); the hunt store reads; the read-only graph view; prior-hunt insights by revival key (#70); budget state (Q7 accounting).

### 4.6 Output

- A dispatched `HuntConfig` per carried-forward direction (the declarative config the hunting agent consumes).
- A back-edge need where a yellow verdict raised it.
- Orchestration state transitions persisted to the hunt store (#68) and memory (#70).

### 4.7 Environment outcome

The hunt store reflects the orchestration lifecycle (candidates -> configs -> hunts -> results), the back-edge needs are recorded, and the run advances without blocking on any agent.

### 4.8 Observability

The shared recipe (section 8): one Langfuse trace per orchestration turn, spans per step, score identifiers for verdicts.

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
5. Worst case: the execution is ephemeral and meaningless, exploration degrades gracefully, and the agent yields feedback; `insufficient-evidence` never exists as a HuntingAgent state (Q8).

### 5.4 Tools

The fault-targeting tool registry (from `HuntConfig`); the symptom-technique KB query interface; the read-only graph view is NOT a direct tool (the orchestrator's view stays the sole graph access; the hunting agent consumes projections).

### 5.5 Context

The `HuntConfig` parameter set verbatim; the symptom-technique KB retrieval results; the adapted index-card surface context.

### 5.6 Output

A `TestImplementationSpec` (the executor-pod input) and orchestrator feedback.

### 5.7 Environment outcome

The spec lands in the hunt store, wired to its hunt; the orchestrator receives the feedback; nothing is written to L0/L1.

### 5.8 Observability

The shared recipe (section 8): one Langfuse trace per spec-authoring turn, spans per step (KB retrieval, spec composition), score identifiers for the authored spec's completeness.

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
INIT -> (validate spec + environment contract) 
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

### 6.9 Output

`{verdict, evidence}` where `verdict` is binary and `evidence` is the full experiment log (D67-02, D67-08).

### 6.10 Environment outcome

The verdict and evidence land in the hunt store, wired to the hunt; the parent HuntingAgent consumes them for the hypothesis-level evaluation; nothing is written to L0/L1.

### 6.11 Observability

The shared recipe (section 8): one Langfuse trace per pod run, spans per loop iteration (probe, execute, observe, interpret), score identifiers for the binary verdict.

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
Recipe elements: one trace per agent turn/run, spans per step (orchestrator steps, spec-authoring steps, pod loop iterations), and score identifiers for the emitted verdicts (match verdict, hypothesis verdict, pod verdict).

## 9. Coordination with sibling tickets

- #68 (hunt store): owns persistence of candidates, configs, hunts, results, and memory; this spec only declares what each agent reads/writes.
- #69 (control plane): owns the dispatch graph, implicit-coverage rule, gating wiring, back-edge modes, budget/ranker hooks; this spec fixes the orchestrator's tool surface (D67-04) as its input contract.
- #70 (memory): owns revival keys, fault-evidence records, the reuse gate; this spec consumes prior-hunt insights via the `HuntConfig`.
- #71 (deterministic components): owns the FaultSource prefilter engine, tool registry, budget governor; the typed `applies-if` predicate (#63) is its input contract.
- #64 (yellow back-edge wiring): owns the full trigger + wiring of the hunt back-edge; stubbed in this effort.
- The deferred closed-enum pattern engine (D67-07) opens as its own ticket with an exhaustive description after the specs finish.
