# Hunting agent spec: test-executor pod (stub)

Part of [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (per-agent specs), bottom of the agent hierarchy.
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`; it holds the inter-agent logic (walkthrough S0-S7, domain data contracts D1-D11, interface agreements IA-1..IA-8, failure-handling canon, agent-attribute compliance).
This document disambiguates the test-executor pod from the combined spec: everything below is the pod's contract alone, written to the depth an implementation session can build from without re-reading the parent.
Decisions cited as D67-n live in `docs/design/hunting-67-per-agent-specs-decisions.md`.

*Status: spec (contract), NOT implementation.*
*This build ships the minimal LangGraph scaffold only (D67-01); the cooperative-team execution logic beyond the scaffold is deferred.*

## 1. Identity

The test-executor pod is the test-EXECUTION side of the Q8 design/execution partition: a small cooperative agent team that executes a spec against the live target and returns `{verdict, evidence}`.
It is the only agent that touches the live target.

### 1.1 Role (D67-01)

A cooperative team of agents, analogous to the recon job-executor pod but with a different topology.
This implementation turn delivers the minimal LangGraph scaffold: general-purpose tool-calling capability (the minimal tool surface below), memory, Langfuse observability stubs, the communication interface with the parent HuntingAgent, and a helper symbolic layer used for specific testing-verification use-cases.
The pod is a sub-module within the hunting module, following the DDD approach.

### 1.2 Goal

Execute the `TestImplementationSpec` against the live target, drive the feedback-based testing loop, and return the binary verdict with the full experiment log as evidence (D67-02, D67-08).

### 1.3 Workflow (the looped state machine, D67-06)

```
INIT -> (validate spec + environment contract; an invalid spec is rejected here, landing `unsuccessful` with the validation evidence in the trail - the pod never silently executes a malformed spec)
     -> PROBE (derive the next probe from the current spec variant, the testing pattern, and the interpreted evidence)
     -> EXECUTE (tool call against the live target)
     -> OBSERVE (capture the raw output)
     -> INTERPRET (classify: symptom-confirmed / symptom-absent / noise / infeasibility-signal; baseline comparison where the pattern is differential)
     -> DECIDE (update the evidence; then either emit a verdict, decline an attribute into a variant, or stop)
     -> TERMINAL {successful, unsuccessful}
```

Interpretation generates the next probe: the executor may decline any attribute of the spec into a different variant (D67-03, D67-08).

### 1.4 Tools (the minimal scaffold surface)

- The HTTP probe tool: requests against the live target, bounded by the exec timeout.
- The exec tool: mirrors the recon pod's exec surface (non-zero exit retried up to `MAX_POD_ITERS`).

The specialised fault-targeting tool registry is #71's future home.
The tool calls are the only place the live target is touched.

### 1.5 Context

The `TestImplementationSpec` (D4); the communication interface with the parent HuntingAgent (the typed handoff: D4 in, D5 + D6 out); the memory and observability stubs; the helper symbolic layer.
The pod has no graph access and no store access: everything it knows arrives through the spec and the communication interface, and everything it produces leaves through the same interface.

### 1.6 Output template

- The pod verdict record (D5): `{verdict: successful | unsuccessful, terminal_reason: symptom-confirmed | space-exhausted | infeasibility-asserted | budget-timeout, iterations}`.
- The experiment log record (D6): `{variant_specs, raw_observations, interpretations}` - the full evidence trail (D67-08).

### 1.7 Produced outcome

The verdict and evidence land in the hunt store, wired to the hunt; the parent HuntingAgent consumes them for the hypothesis-level evaluation; nothing is written to L0/L1.

### 1.8 Observability

The shared recipe (merged spec section 8): one Langfuse trace per pod run, spans per loop iteration (probe, execute, observe, interpret) named after the step, session = run id, Langfuse stubs in this build and fail-open; the binary verdict is measured through the hunt-store records and the eval harness, never Langfuse score identifiers.

### 1.9 Honour clauses

- Sole-writer: never writes L0/L1; persists only through the parent's hunt-store write.
- Binary terminal invariant: the state machine ends in exactly `successful` or `unsuccessful`, never a third state (D67-02).
- Fail-open: section 5.
- Fixed internal caps: budget and timeout are pod-internal (D67-09), set by the pod, env-overridable, never carried in the spec.

## 2. Domain peculiarities

- The four-way termination (D67-06), each landing a binary end with the distinguishing evidence in the trail:
  1. Symptom confirmed via the verification symptom(s) -> `successful`, terminal_reason `symptom-confirmed`.
  2. Pattern/probe space exhausted without symptom -> `unsuccessful`, terminal_reason `space-exhausted`.
  3. A strong technical infeasibility assertion (unreachable target, missing tool, everything WAF-blocked) -> `unsuccessful`, terminal_reason `infeasibility-asserted`, infeasibility in the trail.
  4. Budget/timeout reached -> `unsuccessful`, terminal_reason `budget-timeout`, partial evidence.
- The fixed caps (D67-09): tool calls retry up to `MAX_POD_ITERS = 3` on non-zero exit; each exec is bounded by `EXEC_TIMEOUT_S = 300`; both env-overridable, both pod-internal, never spec fields.
- The testing pattern is an OPEN NL pattern inside the typed envelope (D67-07): the engine treats it as guidance over the generic loop.
  The closed-enum pattern engine is deferred to [#81](https://github.com/Diekgbbtt/polyphemus/issues/81).
- Variants (D67-08): a declined/refined attribute yields a derived variant spec instance, recorded with provenance; the exported evidence is the full experiment log (variant specs, raw observations, interpretations).
- INIT validation is a hard gate: a spec failing the typed base schema or the environment contract is rejected and lands `unsuccessful` with the validation evidence in the trail.
- An empty payload vector does NOT zero the loop: the pattern's default probe still runs once; if no probe can be derived at all, the loop lands `space-exhausted` with the (possibly empty) log.
- Identical variant + payload executions are deduplicated: one execution, recorded once.
- The helper symbolic layer: minimal testing-verification helpers (e.g. payload construction, baseline comparison) - the specific use-cases the scaffold's later builds extend.

## 3. What this build builds vs stubs vs reuses

Builds:

- The minimal LangGraph scaffold: the looped state machine (INIT -> PROBE -> EXECUTE -> OBSERVE -> INTERPRET -> DECIDE -> TERMINAL), general tool-calling, memory, Langfuse observability stubs, the communication interface with the parent HuntingAgent, and the helper symbolic layer.
- The two tools (HTTP probe, exec) with the retry and timeout enforcement.
- INIT validation against the D4 typed base schema.
- Variant derivation with provenance and the experiment log (D6).
- The four-way termination with the `terminal_reason` vocabulary (D5).

Stubs (owned by sibling tickets, minimal fixture in this build):

- The cooperative-team execution logic beyond the scaffold (D67-01; deferred).
- The closed-enum pattern engine (#81).
- The fault-targeting tool registry (#71).
- The hunt store (#68): the same append-only markdown stub as the other builds.
- Langfuse SDK: the observability stubs.

Reuses:

- The recon pod's execution patterns: `MAX_POD_ITERS`/`EXEC_TIMEOUT_S` semantics (`recon/config.py`), the degrade-to-failed-export fail-open (`recon/control/job_agent.py`), the synchronous bridge (`recon/control/async_bridge.py`).
- The `TestImplementationSpec` schema from merged spec section 7 (D4).

## 4. Happy paths and outliers

### 4.1 Happy paths

H1 - Confirmed: the spec's verification symptom is observed -> `{successful, symptom-confirmed}`, iterations = N, the log holds the variant spec, the raw observation, and the interpretation.
H2 - Absent: the pattern/probe space exhausts without the symptom -> `{unsuccessful, space-exhausted}`.
H3 - Infeasible: unreachable target or all tools blocked -> `{unsuccessful, infeasibility-asserted}` with the infeasibility in the trail.
H4 - Capped: budget/timeout reached -> `{unsuccessful, budget-timeout}` with partial evidence.
H5 - Variant: a declined attribute yields a derived variant spec with provenance; the loop continues; the log records both variants.

### 4.2 Outliers

O1 - Invalid spec at INIT: rejected, `unsuccessful` with the validation evidence; never executed.
O2 - Non-zero exit: retried up to `MAX_POD_ITERS = 3`, then lands a binary end with the evidence.
O3 - Exec timeout: `EXEC_TIMEOUT_S` enforced; the run lands `budget-timeout` (or the feasible alternative) with partial evidence.
O4 - Exec tool unavailable: the infeasibility-asserted path.
O5 - Target unreachable (DNS/connection refused): the infeasibility-asserted path.
O6 - Empty observation (empty body): interpreted as noise, preserved raw, the loop continues.
O7 - Duplicate probe: an identical variant + payload is executed once and recorded once.
O8 - Unclassifiable output: treated as noise with the raw output preserved; the loop continues.
O9 - Langfuse stub failure: the run completes unaffected (fail-open).
O10 - Memory stub failure: the run completes unaffected.
O11 - Variant count blow-up: bounded by the pod's internal caps (D67-09); the loop always lands a binary end.
O12 - Empty payload vector: the pattern's default probe runs once; if no probe is derivable, `space-exhausted` with the log.

## 5. Delivery semantics and failure handling

Delivery canon (merged spec section 3): all delivery is synchronous and in-process in phase 1.

- IA-3 (parent -> pod): synchronous typed handoff of D4.
  INIT rejection is a first-class outcome (unsuccessful + validation evidence), never a silent hang.
- IA-4 (pod -> parent): synchronous typed return of D5 + D6.
  A run that raises degrades to `unsuccessful` with the error in the evidence trail; the pod never raises into the parent (mirrors the recon degrade-to-failed-export pattern).
- Failure canon (merged spec section 13): fail-open everywhere; retries bounded by the fixed caps; Langfuse never a gate; terminality always holds.

## 6. Assertion catalogue - work-item "test-executor pod (per-agent spec from #67)"

**Source:** `docs/design/hunting-67-test-executor-pod-spec.md` (this doc); parent `docs/design/hunting-67-per-agent-specs-spec.md` section 6.
**Seams under assertion:** INIT (validation), the looped state machine (D67-06), the four-way termination (D67-06), the fixed caps (D67-09), variants + experiment log (D67-08), IA-3/IA-4, and the system walkthroughs of the merged spec (section 10).

### 6.1 Contract predicates (integration tier)

C1 - INIT rejection: given a spec violating the typed base schema, exercising malformed, the pod lands `unsuccessful` with the validation evidence in the trail and executes no tool call.
Yields: `tests/integration/test_test_executor_pod_contracts.py::test_init_rejects_invalid_spec`.
C2 - Binary terminal invariant: given any spec and any tool behaviour, exercising ordering, every run terminates in exactly one of `{successful, unsuccessful}` and carries a `terminal_reason` from the D5 vocabulary.
Yields: `...::test_binary_terminal_invariant`.
C3 - Symptom confirmed: given a spec whose symptom a scripted tool output satisfies, exercising success, the pod lands `{successful, symptom-confirmed}` with iterations = N and the log populated.
Yields: `...::test_symptom_confirmed_lands_successful`.
C4 - Space exhausted: given a spec whose symptom never appears across the whole probe space, exercising empty-valid, the pod lands `{unsuccessful, space-exhausted}`.
Yields: `...::test_space_exhausted_lands_unsuccessful`.
C5 - Infeasibility: given an unreachable target (connection refused), exercising degradation, the pod lands `{unsuccessful, infeasibility-asserted}` with the infeasibility in the trail.
Yields: `...::test_infeasibility_asserted_with_evidence`.
C6 - Budget/timeout: given tool calls exceeding the fixed caps, exercising degradation, the pod lands `{unsuccessful, budget-timeout}` with partial evidence.
Yields: `...::test_budget_timeout_lands_unsuccessful`.
C7 - Retry: given a tool call failing with non-zero exit twice then succeeding, exercising degradation, the retries converge at `MAX_POD_ITERS = 3` and the run lands a binary end.
Yields: `...::test_non_zero_exit_retries_to_converge`.
C8 - Timeout enforcement: given a tool call hanging past `EXEC_TIMEOUT_S`, exercising degradation, the exec is aborted and the run lands a binary end within the caps.
Yields: `...::test_exec_timeout_enforced`.
C9 - Variant provenance: given a declined attribute, exercising success, the experiment log contains the derived variant spec with provenance and the raw observation and interpretation entries (D6 shape).
Yields: `...::test_variant_derivation_with_provenance`.
C10 - Duplicate probe: given the same variant + payload re-decided, exercising duplicate-idempotent, exactly one execution is recorded in the log.
Yields: `...::test_duplicate_probe_recorded_once`.
C11 - Empty payload vector: given a spec with an empty payload vector space, exercising empty-valid, the pattern's default probe still runs once (or the run lands `space-exhausted` when no probe is derivable).
Yields: `...::test_empty_payload_vector_still_probes`.
C12 - Langfuse stub failure: given the observability stub raising, exercising degradation, the run completes unaffected.
Yields: `...::test_langfuse_failure_is_fail_open`.

### 6.2 Walkthrough predicates (e2e tier)

E1 - One trivial real run: grounds merged spec 6.12 and H1.
Entry seam: the IA-3 handoff (a fixture `TestImplementationSpec`).
Input: a spec with target identity `"service:web:soupmarket"`, verification symptom "HTTP 200 with a non-empty body on GET /", testing pattern (open NL) "blind-boolean", assumptions ["network egress allowed"], payload vector space `{method: GET, path: "/"}`, rationale + interpretation guidance set.
Live edge: the eval target `soupmarket.shop` (the `juice-shop-remote` target in `tests/e2e/fixtures/eval-targets.yaml`), live HTTP mode.
Path: INIT validates -> PROBE derives the GET probe -> EXECUTE issues GET / -> OBSERVE captures the response -> INTERPRET classifies symptom-confirmed -> DECIDE emits the verdict -> TERMINAL.
Terminal: exactly one verdict `{successful, symptom-confirmed, iterations >= 1}` and an experiment log with at least one raw observation.
Observed: the hunt-store stub record and the response status read back from the tool call log.
Yields: `tests/e2e/test_test_executor_pod_walkthrough.py::test_trivial_real_run`. Mechanisable in this ticket (the pod and the target are both real).

E2 - Full chain, two candidates: grounds merged spec 10.1-10.8 and the orchestrator E1.
Entry seam: the candidate-set delivery at IA-1.
Input: the fixture candidate set of orchestrator E1.
Live edge: the eval target `soupmarket.shop`, live HTTP mode.
Path: FaultSource fixture -> gate -> ranker -> two `HuntConfig`s -> two hunting agents -> two pod runs -> two verdicts -> S7.
Terminal: exactly two hunt records with spec/result refs and hypothesis verdicts.
Observed: the store listing by run id.
Yields: `tests/e2e/test_hunting_chain_walkthrough.py::test_full_chain_two_candidates`. Mechanisable when all three agents exist (this ticket is last, so its e2e tier completes the chain).
E3 - Yellow park/resume: grounds merged spec 10.4/10.7 and the orchestrator E2.
Entry seam: the candidate-set delivery at IA-1.
Input: `{(service applies), (system yellow)}` per orchestrator E2.
Path: dispatch for the service; park for the system; recon lands; re-match applies; second dispatch.
Terminal: two hunt records, one back-edge record.
Observed: the store's back-edge and hunt records.
Yields: `...::test_yellow_park_resume`. Mechanisable when the chain is complete (this ticket is last).
E4 - Zero-candidate run: grounds merged spec 10.1 and the orchestrator E1-empty.
Entry seam: the candidate-set delivery at IA-1.
Input: the empty candidate set.
Path: gate on nothing -> no dispatch -> S7.
Terminal: zero hunt records, run complete.
Observed: the store shows the empty pass.
Yields: `...::test_zero_candidate_run`. Mechanisable when the chain is complete (this ticket is last).

## 7. Out of scope

The cooperative-team execution logic beyond the scaffold (D67-01), the closed-enum pattern engine (#81), the fault-targeting tool registry content (#71), the hunt-store persistence design (#68), the orchestrator and the hunting agent (their own spec docs).
The merged spec's inter-agent logic (sections 10-14) governs the seams this document references.
