# Hunting agent spec: test-executor pod

Part of [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (per-agent specs), bottom of the agent hierarchy.
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`; it holds the inter-agent logic (walkthrough S0-S7, domain data contracts D1-D11, interface agreements IA-1..IA-8, failure-handling canon, agent-attribute compliance).
This document disambiguates the test-executor pod from the combined spec: everything below is the pod's contract alone, written to the depth an implementation session can build from without re-reading the parent.

*T10b (#397) note.*
The pre-redesign E2 full-chain walkthrough (candidate set -> `HuntConfig` -> hunting agents) is historical.
The live chain is a produced loop file -> the hunter spec set -> the pod; the pod's D4 contract below is current.

*Status: spec (contract), being re-specified by the #84 regrounding.
Implementation decisions from the 2026-08-21 grilling live in `docs/design/hunting-84-regrounding-decisions.md` (D84-1..D84-25) and are authoritative over this document where they clash; this document is corrected so no clash remains.
The regrounding reconciled the pod onto the shared session abstractions (`HuntSession`, `stateful_turn`, the #95 compaction middleware, async-native entry) and superseded the pre-regrounding scaffold's stateless seams and symbolic runner.

**Pod contract redesign 2026-10-18.** Section 8 supersedes the D4 typed base, the testing-pattern clause, the empty-payload-vector outlier, and the variant-minting clauses.
The old text is retained for history.
Sections 1.7, 2, 4.1, and 6 also retain the older contract for history and are not current.
The redesigned D4 surface carries `target_identity`, `verification_symptoms`, `assumptions`, `rationale`, and lineage only.
The triager mints variants from a procedure diff, not from a declined spec attribute.
The impact map is `docs/design/unit-threat-model-spec-impact-map.md`.

## 1. Identity

The test-executor pod is the test-EXECUTION side of the Q8 design/execution partition: a small cooperative agent team that executes a spec against the live target and returns `{verdict, evidence}`.
It is the only agent that touches the live target.

### 1.1 Role (D67-01, D84-16)

A cooperative team of two agents with a different topology from the recon pod: the **Runner** (actor) and the **Triager** (critic).
The Runner is the probe stretch's control plane - a **pure plan designer** running as a `create_agent` ReAct loop over one `stateful_turn` per stretch (D84-17), perceiving each tool result, interpreting, and reasoning on the next step on repetition.
The Triager is the critic - a `stateful_turn` session that reads the note + the filtered experiment-log slice and emits a binary verdict or mines a third-party variant (D84-16, D84-23).

### 1.2 Goal

Execute the `TestImplementationSpec` against the live target, drive the feedback-based testing loop, and return the binary verdict with the full experiment log as evidence (D67-02, D67-08).

### 1.3 Workflow (D67-06, D84-16/17)

```
INIT -> (validate spec + environment contract; an invalid spec is rejected here, landing `unsuccessful` with the validation evidence in the trail - the pod never silently executes a malformed spec)
     -> RUNNER STRETCH (ONE `stateful_turn`: a `create_agent` ReAct loop over the probe phase)
          * plan: the kill-chain's probe phase - feasibility validation (P0), concretization (P1), execute (P2), confirm exhaustion (P3)
          * tools bound: `exec`, `note`, the always-bound `query_lightrag` KB tool, and the shared `graph_view` L0/L1 tool (#197)
          * bounded by `HUNT_POD_MAX_TOOL_CALLS` (default 200, inner cap) and the compaction barrier
          * on P3 exhaustion, uses the `note` tool (writes ONE consolidated experiment-summary NOTE to the pod experiment-memory store) as its FINAL tool call
     -> TRIAGER (reads the note + `triager_context`; classify + terminate or mine a variant)
     -> decide -> {terminal | mint variant -> [POD-BUDGET CHECK] -> RUNNER STRETCH}
     -> TERMINAL {successful, unsuccessful}
```

The workflow graph is a HIGH-LEVEL MAP only (D84-16/18).
The plan itself lives in the Runner's ReAct session thread, preserved across laps by the compaction running summary (D84-18); the graph-state plan tool is ticket #136's control-plane, out of scope (D84-18).

### 1.4 Tools

- **`exec`** - the general-purpose terminal (curl, package managers, any tool the pod lacks), bounded by `EXEC_TIMEOUT_S`, non-zero exit retried up to `MAX_POD_ITERS = 3` (O2/C7).
- **`query_lightrag` (`KbQueryTool`)** - the single knowledge-base tool from the `lightrag` branch, **always-bound as of #197** (the `HUNTING_LIGHTRAG_TOOL` opt-in gate is REMOVED; D84-26, resolved when the `lightrag` merge landed). Bound as a LangChain `BaseTool` into the Runner's `create_agent` `tools=[...]` - the SAME pattern the hunting agent's author lane uses. The former `kb_retrieve` symptom-technique typed seam (surface B) is **retired**; the pod binds `KbQueryTool`, which wraps the real `query_lightrag` and - T3/#179 - records every KB response as a first-class `KbObservation` into the variant's experiment-log file (distinct from the exec `RawObservation`). Fail-open (empty/raising -> a denoted degraded bundle, O13).
- **`graph_view` (#197)** - the shared read-only L0/L1 tool (`graph_view_tool.py::build_graph_view_tool`, the SAME single-source contract the orchestrator and hunter bind), riding `ReadOnlyGraphView(project_id).read` and bound into the Runner's AND the Triager's `tools=[...]` - always-on, never gated.
- **`note_tool`** - the note write/read tool (D84-17/20/27): the Runner writes ONE consolidated experiment-summary note at P3 exhaustion (prompt-verbatim); the Triager reads it per lap as its primary reasoning artifact. Bound into the respective agents' `tools=[...]` (Runner: write; Triager: read).
- **`auth_store`** - the shared per-project auth view, bound READ-ONLY into the Runner and the Triager. The pod reads the login overview and the account records to type an authenticated request. It never writes the store and never replays a secret.
- **`load_skill` / `record_skill_lesson`** - the project skill loader and the skill-usage lesson recorder, bound into the Runner and the Triager through the shared auth-capable binding.
- **Tool-call validation is the tool's own contract** (D84-22): a wrong parameter fails as a tool-call request REJECTED with an error message + code describing the semantic explicitly - the harness does not re-validate arguments, it only enforces the cap, raw recording (G4), and dedup (O7).

The request tool definitions are the full tool surface.
The system prompts carry a complete human tool summary, not a second description body.
The top-level descriptions carry purpose, operation, constraints, the coded error envelope, and the critical usage clauses.
The schemas remain the machine contract.

The first human context is pinned through compaction for both pod roles.
The pinned message carries the spec and the target context.

The specialised fault-targeting tool registry is #71's future home.
The tool calls are the only place the live target is touched.

### 1.5 Context (D84-20)

The `TestImplementationSpec` (D4); the communication interface with the parent HuntingAgent (the typed handoff: D4 in, D5 + D6 out); the memory and observability seams; and the pod experiment-memory store.

The pod has **no graph write access**.
It binds the read-only `graph_view` tool for the target surface.
It OWNS a pod experiment-memory store (D84-33 through D84-38, adapted as of T1/#177 and re-scoped 2026-08-24): a per-project, deterministic-key store at `data/<project_id>/test-executor-pod/` with three bodies under the per-spec directory `<fault>_<strategy>/` - `variants/<variant-ref>.yaml` (the minted TestImplementationSpec variants, `v0`/`v1`/...), `experiment-log/<order>.yaml` (one file per variant - the D6 slice with the `executed` dedup ledger and the `experiment_summary` terminal record, overwritten idempotently) and the per-project `notes.yaml` keyed `<fault>_<strategy>:<order>:<note_name>`. The variant ref `vN` and the order `N` are the SAME ordinal in two spellings, easily mappable. The spec identifier is the #164 hunter's `<fault>_<strategy>` (D84-34), NOT a content-addressed hash; the order number is the variant ordinal. There is NO `_seq`/`_ref` (D84-36): the deterministic key plus the natural list order disambiguate every artifact; reads are latest-first. The note tool reads/writes this store; the `experiment_summary` write sinks into the variant's experiment-log file as its terminal record (D84-35), `kb_insight`/`freeform` accumulate in `notes.yaml`. The authoritative build spec for the store is `docs/design/hunting-84-pod-memory-system-spec.md`.
The pod prompts embed an INDEXABLE LIST of the pod memory's keys (notes by key + the experiment-log identifiers, spec id + orders on file) plus note-reading guidance, mirroring the hunt-orchestrator's prior-config key-list + reading-tool pattern, so the Runner/Triager can index into the store when required (D84-27).

### 1.6 Output template

- The pod verdict record (D5, Q3-amended): `{verdict: successful | unsuccessful, terminal_reason: <6-value>, clean: bool, init_validation: [str], iterations}`.
- The experiment log record (D6): `{variant_specs, raw_observations, interpretations}` - the full evidence trail (D67-08), plus the pod notes (D84-17/20).

### 1.7 Produced outcome

The verdict and evidence land in the hunt store, wired to the hunt; the parent HuntingAgent consumes them for the hypothesis-level evaluation; nothing is written to L0/L1. **As of T7/#183 (GP3): the pod ALSO persists its OWN terminal `PodExport` envelope to its pod memory store at `<spec_id>/<run_id>.yaml` (the pod store is the source of truth; the parent reads from it).**

### 1.8 Observability (D84-21)

The shared recipe: **one Langfuse trace per pod run, session = thread id** (`HuntSession` thread), spans per `stateful_turn`, and **the trace MUST showcase the whole tool-call/reason graph** - each ReAct model step, each tool call, each reasoning span (D84-21).
If the observability seam does not already surface the tool-call/reason graph, it is refactored to do so.
Langfuse is fail-open and never a gate (C12).

### 1.9 Honour clauses

- Sole-writer: never writes L0/L1; persists only through the parent's hunt-store write and the pod-owned experiment-memory store - including the pod's OWN terminal `PodExport` envelope (T7/#183: `<spec_id>/<run_id>.yaml`).
- Binary terminal invariant: the state machine ends in exactly `successful` or `unsuccessful`, never a third state (D67-02).
- Fail-open: section 5.
- Fixed internal caps: budget and timeout are pod-internal (D67-09), set by the pod, env-overridable, never carried in the spec.
  `HUNT_POD_MAX_TOOL_CALLS` defaults to **200** (D84-22), `HUNT_POD_MAX_ITERS` defaults to 8, `MAX_POD_ITERS = 3`, `EXEC_TIMEOUT_S = 300`.

## 2. Domain peculiarities

- The six-way termination (Q3-amended, ratified 2026-08-04; supersedes the four-way D67-06), each landing a binary end with the distinguishing evidence in the trail:
  1. Symptom confirmed via the verification symptom(s) -> `successful`, terminal_reason `symptom-confirmed`.
  2. Pattern/probe space exhausted without symptom AND every knowledge-base query relied on returned a real answer -> `unsuccessful`, terminal_reason `space-exhausted`. A degraded/unavailable KB result is UNAVAILABLE evidence, never absence: a `space-exhausted` claim over degraded KB coverage is downgraded to `no-symptom-evidence` with `clean=false` (#304).
  3. A strong technical infeasibility assertion (unreachable target, missing tool, everything WAF-blocked) -> `unsuccessful`, terminal_reason `technical-infeasibility`, infeasibility in the trail.
  4. A specific active defence prevented the probes (a WAF/filter soft-block) -> `unsuccessful`, terminal_reason `specific-defence-prevention`.
  5. Symptom absent but coverage partial or observations impaired (including a degraded/unavailable knowledge-base result) -> `unsuccessful`, terminal_reason `no-symptom-evidence`.
  6. Budget/timeout reached -> `unsuccessful`, terminal_reason `budget-timeout`, partial evidence.
  `clean` True = clean completed observations; False = blocked/unreachable or a mid-flight cut. `init_validation` present only on an INIT rejection.
  **As of #209 - presentation rule**: the triager prompt presents `verdict` and `terminal_reason` as SEPARATE
  outputs (e.g. "verdict successful, terminal_reason symptom-confirmed"), NEVER slash-joined shorthand
  (`successful / symptom-confirmed`). A slash-joined string is copied verbatim by the model into `verdict`, fails
  the `validate_decision` binary guard, and the degradation then mis-records a confirmed symptom as
  `unsuccessful`.
- The fixed caps (D67-09): `MAX_POD_ITERS = 3`, `EXEC_TIMEOUT_S = 300`, `HUNT_POD_MAX_TOOL_CALLS = 200`, `HUNT_POD_MAX_ITERS = 8`; all env-overridable, all pod-internal, never spec fields.
- **SUPERSEDED by 8.4 (2026-10-18).** The testing pattern is an OPEN NL pattern inside the typed envelope (D67-07): the engine treats it as guidance over the generic loop.
  The closed-enum pattern engine is deferred to [#81](https://github.com/Diekgbbtt/polyphemus/issues/81).
- **SUPERSEDED by 8.6 (2026-10-18).** Variants (D67-08): a declined/refined attribute yields a derived variant spec instance, recorded with provenance; the exported evidence is the full experiment log (variant specs, raw observations, interpretations).
- INIT validation is a hard gate: a spec failing the typed base schema or the environment contract is rejected and lands `unsuccessful` with the validation evidence in the trail.
- An empty payload vector does NOT zero the loop: the Runner's first ReAct turn still issues the default probe once; if no probe can be derived at all, the loop lands `space-exhausted` with the (possibly empty) log (O12/C11).
- Identical variant + payload executions are deduplicated: one execution, recorded once (O7/C10).
- **The note final step (D84-17/20)**: once the Runner reaches P3 space exhaustion, it writes ONE consolidated experiment-summary note to the pod experiment-memory store - a plain prompt-verbatim final step in the workflow, summarising the experiments from all the stretch's logs.
  The Triager reads the note from a third-party perspective before deciding.

## 3. What this build builds vs stubs vs reuses

Builds:

- The minimal LangGraph scaffold: the HIGH-LEVEL workflow map (`INIT -> RUNNER STRETCH -> TRIAGER -> decide -> TERMINAL`), general tool-calling (`create_agent` ReAct), the pod experiment-memory store + note tool, Langfuse observability with the full tool-call/reason graph, the communication interface with the parent HuntingAgent, the `build_harness_middleware` (cap G1, raw recording G4, dedup O7) and the compaction middleware on the agent.
- The tools (`exec`, `note`, the always-bound `query_lightrag` KB tool, and the shared `graph_view` tool) with retry and timeout enforcement and the tool-contract validation semantics (D84-22).
- INIT validation against the D4 typed base schema.
- Variant derivation with provenance and the experiment log (D6).
- The six-way termination with the `terminal_reason` vocabulary (D5) + `clean` + `init_validation`.

Stubs (owned by sibling tickets, minimal fixture in this build):

- The cooperative-team execution logic beyond the scaffold (D67-01; deferred).
- The closed-enum pattern engine (#81).
- The fault-targeting tool registry (#71).
- The hunt store (#68): the same append-only markdown stub as the other builds.
- Langfuse SDK: the observability stubs fail-open.
- The plan-control tool / DAG harness control-plane (#136; deliberately out of scope).

Reuses:

- The recon pod's execution patterns: `MAX_POD_ITERS`/`EXEC_TIMEOUT_S` semantics (`recon/config.py`) and the degrade-to-failed-export fail-open (`recon/control/job_agent.py`).
- The `TestImplementationSpec` schema from merged spec section 7 (D4).
- The shared session abstractions (`HuntSession`, `stateful_turn`, `run_session_turn`/`arun_session_turn`, `create_agent`, the `app/llm/compaction.py` middleware building blocks) - D84-2, D84-6, D84-17.
- The per-project memory store's indexing/retrieval/data-model patterns (as a PATTERN to replicate, NOT to import) - D84-20.
- No sync bridge is reused: the pod is async-ONLY (D84-15), so `run_pod`/`run_coro_blocking`/`async_bridge.py` are deliberately NOT used.

## 4. Happy paths and outliers

### 4.1 Happy paths

H1 - Confirmed: the spec's verification symptom is observed -> `{successful, symptom-confirmed}`, iterations = N, the log holds the variant spec, the raw observation, and the interpretation.
H2 - Absent: the pattern/probe space exhausts without the symptom on an AVAILABLE knowledge base -> `{unsuccessful, space-exhausted}`, with the P3 note written. Over a degraded KB the same shape lands `{unsuccessful, no-symptom-evidence, clean=false}` (#304).
H3 - Infeasible: unreachable target or all tools blocked -> `{unsuccessful, technical-infeasibility}` with the infeasibility in the trail.
H4 - Capped: budget/timeout reached -> `{unsuccessful, budget-timeout}` with partial evidence.
H5 - Variant: a variant basis yields a derived variant spec with provenance; the loop continues; the log records both variants.
H6 - Note: on P3 exhaustion the consolidated experiment summary is written to the pod experiment-memory store and the Triager reads it.

### 4.2 Outliers

O1 - Invalid spec at INIT: rejected, `unsuccessful` with the validation evidence; never executed.
O2 - Non-zero exit: retried up to `MAX_POD_ITERS = 3`, then lands a binary end with the evidence.
O3 - Exec timeout: `EXEC_TIMEOUT_S` enforced; the run lands `budget-timeout` (or the feasible alternative) with partial evidence.
O4 - Exec tool unavailable: the technical-infeasibility path.
O5 - Target unreachable (DNS/connection refused): the technical-infeasibility path.
O6 - Empty observation (empty body): interpreted as noise, preserved raw, the loop continues.
O7 - Duplicate probe: an identical variant + payload is executed once and recorded once.
O8 - Unclassifiable output: treated as noise with the raw output preserved; the loop continues.
O9 - Langfuse stub failure: the run completes unaffected (fail-open).
O10 - Memory stub failure: the run completes unaffected.
O11 - Variant count blow-up: bounded by the pod's internal caps (D67-09); the loop always lands a binary end.
O12 - **SUPERSEDED by 8.5 (2026-10-18).** Empty payload vector: the Runner's first ReAct turn still probes once; if no probe is derivable, `space-exhausted` with the log.
O13 - KB query failure (`query_lightrag` raising or empty): fail-open - the Runner degrades to the spec's own primitives. The empty/degraded bundle is RECORDED as a `KbObservation` (T3/#179) when a log is bound, marked `degraded=true` (#304). A degraded KB is UNAVAILABLE evidence: it can never license a clean `space-exhausted` (the graph downgrades to `no-symptom-evidence`/`clean=false`, #304) - only a real answer returning the same set as init confirms exhaustion (D84-16).
O14 - A tool-call with wrong parameters: the tool REJECTS it with an error message + code (tool contract semantics, D84-22); the ReAct loop sees the rejection as a tool result and adjusts.

## 5. Delivery semantics and failure handling

Delivery canon (merged spec section 3): all delivery is synchronous-threaded and in-process in phase 1.

- IA-3 (parent -> pod): the parent dispatches the pod via `arun_pod` (the async seam, awaited natively by the parent's `_await_seam(pod, spec)`); `run_pod` is REMOVED (D84-15).
  INIT rejection is a first-class outcome (unsuccessful + validation evidence), never a silent hang.
- IA-4 (pod -> parent): the async entry returns the D5 + D6 envelope.
  A run that raises degrades to `unsuccessful` with the error in the evidence trail; the pod never raises into the parent (mirrors the recon degrade-to-failed-export pattern).
- Failure canon (merged spec section 13): fail-open everywhere; retries bounded by the fixed caps; Langfuse never a gate; terminality always holds.

## 6. Assertion catalogue - test-executor pod

**Source:** this document; parent `docs/design/hunting-67-per-agent-specs-spec.md` section 6; the grilling records `docs/design/hunting-84-regrounding-decisions.md` (D84-1..D84-25).
**Seams under assertion:** the `arun_pod` async entry (IA-3/IA-4), the HIGH-LEVEL workflow map, the six-way termination, the fixed caps, variants + experiment log (D67-08), the pod experiment-memory store + note tool (D84-17/20), the KB tool binding (D84-16), and the system walkthroughs of the merged spec (section 10).

### 6.1 Contract predicates (integration tier)

C1 - INIT rejection: given a spec violating the typed base schema, exercising malformed, the pod lands `unsuccessful` with the validation evidence in the trail and executes no tool call.
C2 - Binary terminal invariant: given any spec and any tool behaviour, exercising ordering, every run terminates in exactly one of `{successful, unsuccessful}` and carries a `terminal_reason` from the Q3-amended vocabulary.
C3 - Symptom confirmed: given a spec whose symptom a scripted tool output satisfies, exercising success, the pod lands `{successful, symptom-confirmed}` with iterations = N and the log populated.
C4 - Space exhausted: given a spec whose symptom never appears across the whole probe space over an AVAILABLE KB (no degraded observation), exercising empty-valid, the pod lands `{unsuccessful, space-exhausted}`. Over a DEGRADED KB the same run lands `{unsuccessful, no-symptom-evidence, clean=false}` (#304).
C5 - Infeasibility: given an unreachable target (connection refused), exercising degradation, the pod lands `{unsuccessful, technical-infeasibility}` with the infeasibility in the trail.
C6 - Budget/timeout: given tool calls exceeding the fixed caps, exercising degradation, the pod lands `{unsuccessful, budget-timeout}` with partial evidence.
C7 - Retry: given a tool call failing with non-zero exit twice then succeeding, exercising degradation, the retries converge at `MAX_POD_ITERS = 3` and the run lands a binary end.
C8 - Timeout enforcement: given a tool call hanging past `EXEC_TIMEOUT_S`, exercising degradation, the exec is aborted and the run lands a binary end within the caps.
C9 - Variant provenance: given a variant basis, exercising success, the experiment log contains the derived variant spec with provenance and the raw observation and interpretation entries (D6 shape).
C10 - Duplicate probe: given the same variant + payload re-decided, exercising duplicate-idempotent, exactly one execution is recorded in the log.
C11 - Empty payload vector: given a spec with an empty payload vector space, exercising empty-valid, the Runner still probes once (or the run lands `space-exhausted` when no probe is derivable).
C12 - Langfuse stub failure: given the observability stub raising, exercising degradation, the run completes unaffected.
C13 - Tool surface bound: given a spec whose concretization needs a KB query, exercising tool-surface, the Runner's `create_agent` is bound with `exec` + `note` + the always-bound `query_lightrag` tool + the shared `graph_view` tool + the read-only `auth_store` + `load_skill` + `record_skill_lesson`, and a query returns through the seam fail-open. The KB tool's fail-open + `KbObservation` recording (T3/#179) is asserted at the unit tier (`tests/attack/pod/test_tools.py`).
C14 - Note written on P3: given a space-exhausted run, exercising success, the pod experiment-memory store holds ONE consolidated experiment-summary note keyed by the spec id + variant, and the Triager reads it.
C15 - Tool-contract validation: given a tool call with a wrong parameter, exercising degradation, the call is REJECTED with an error message + code (never executed, never harness-revalidated).

### 6.2 Walkthrough predicates (e2e tier)

E1 - One trivial real run: grounds merged spec 6.12 and H1.
Entry seam: the IA-3 handoff (a fixture `TestImplementationSpec`).
Input: a spec with `target_identity = {url: "https://soupmarket.shop/", unit_id: "service:web:soupmarket"}`, `verification_symptoms = ["HTTP 200 with a non-empty body on GET /"]`, `assumptions = ["network egress allowed"]`, and a rationale set - the REDUCED D4 (S5 8.4), with no retired testing-pattern/vector/interpretation fields.
Live edge: the eval target `soupmarket.shop` (the `juice-shop-remote` target in `tests/e2e/fixtures/eval-targets.yaml`), live HTTP mode.
Path: INIT validates -> RUNNER STRETCH (ReAct; the Runner's first turn issues the default probe -> EXECUTE -> OBSERVE) -> symbolic symptomatic classification OR the Triager -> TERMINAL.
Terminal: exactly one verdict `{successful, symptom-confirmed, iterations >= 1}` and an experiment log with at least one raw observation.
Observed: the hunter spec-set record and the response status read back from the tool call log.
E1 is a REAL pod run via `arun_pod` (D84-24): it exercises the ReAct runner, the KB tool binding, and the `exec` tool against the live target. The pre-regrounding symbolic runner is removed.
Yields: `tests/e2e/test_test_executor_pod_walkthrough.py::test_trivial_real_run`. Mechanisable in this ticket segment (the pod and the target are both real; the pod LLM is wired in the in-network e2e stack).
Living-doc caveat: `tests/e2e/fixtures/eval-targets.yaml` does NOT exist in the repo yet - E1 is currently hermetically mechanised (the production lane over a fake model/exec/KB, #158), with the live edge pending a wired in-network target.

E2 - Full chain, two candidates: grounds merged spec 10.1-10.8 and the orchestrator E1.
Entry seam: the candidate-set delivery at IA-1.
Live edge: the eval target `soupmarket.shop`, live HTTP mode.
Path: FaultSource fixture -> gate -> ranker -> two `HuntConfig`s -> two hunting agents -> two pod runs -> two verdicts -> S7.
Terminal: exactly two hunt records with spec/result refs and hypothesis verdicts.
Yields: `tests/e2e/test_hunting_chain_walkthrough.py::test_full_chain_two_candidates`. Mechanisable when all three agents exist (this ticket segment is last, so its e2e tier completes the chain).

E3 - Yellow park/resume: grounds merged spec 10.4/10.7 and the orchestrator E2.
Entry seam: the candidate-set delivery at IA-1.
Input: `{(service applies), (system yellow)}` per orchestrator E2.
Path: dispatch for the service; park for the system; recon lands; re-match applies; second dispatch.
Terminal: two hunt records, one back-edge record.
Yields: `...::test_yellow_park_resume`. Mechanisable when the chain is complete (this ticket segment is last).

E4 - Zero-candidate run: grounds merged spec 10.1 and the orchestrator E1-empty.
Entry seam: the candidate-set delivery at IA-1.
Input: the empty candidate set.
Path: gate on nothing -> no dispatch -> S7.
Terminal: zero hunt records, run complete.
Yields: `...::test_zero_candidate_run`. Mechanisable when the chain is complete (this ticket segment is last).

## 7. Out of scope

The cooperative-team execution logic beyond the scaffold (D67-01), the closed-enum pattern engine (#81), the fault-targeting tool registry content (#71), the hunt-store persistence design (#68), the orchestrator and the hunting agent (their own spec docs).
The merged spec's inter-agent logic (sections 10-14) governs the seams this document references.
The plan-control tool / DAG workflow control-plane (#136) is recorded and deferred.
The per-project memory store (#137/#140) is never imported into the pod - its patterns are replicated, its namespace is not (D84-20).

## 8. Contract redesign 2026-10-18: the reduced D4 and the procedure-diff triager

### 8.1 Problem statement

The pre-redesign D4 surface carried `testing_pattern`, `payload_vector_space`, and `interpretation_guidance`.
The testing pattern duplicates the class skill's procedural knowledge.
The payload vector space pre-narrows the attack before the runner has grounded on the target.
The interpretation guidance duplicates the rationale and the verification symptoms.
The three fields make the spec heavier without adding execution semantics.

The triager mints a variant by declining a spec attribute.
That mechanism assumes the spec's attributes are the discrimination space.
The redesigned hunter discriminates on the skills-ontology entities, not on spec attributes.
A variant basis no longer names a meaningful variant.

### 8.2 Solution

The D4 surface is reduced.
The INIT gate ranges over the reduced base.
The runner authors probes from the spec's rationale, symptoms, assumptions, and target identity.
The triager mints a variant by diffing the skill's procedure against the executed procedure.
The pod memory variant record keeps its shape.
The `declined_attribute` storage field carries the variant basis.

### 8.3 User stories

1. As the hunter, I want the spec to carry only target identity, verification symptoms, assumptions, rationale, and lineage, so that the pod receives a simple execution contract.
2. As the hunter, I want `verification_symptoms` to mean the concrete observable failure modes of the trust agreement, so that the pod's manifestation check follows the trust model.
3. As the hunter, I want `assumptions` to carry the technical requirements the pod may falsify, so that the pod knows what to challenge.
4. As the hunter, I want the rationale to stay vulnerability-level, so that I do not pre-narrow the pod's procedure.
5. As the hunter, I want the payload vector space retired, so that the pod authors its probes from the evidence.
6. As the hunter, I want the testing pattern retired, so that the class skill is the single procedural source.
7. As the hunter, I want the interpretation guidance retired, so that the verification symptoms define symptom-absent.
8. As the pod, I want the INIT gate to require only a base URL and a non-empty symptom list, so that a well-formed spec is never rejected for a retired field.
9. As the pod, I want the gate to collect all violations in one rejection, so that the hunter can correct the spec in one pass.
10. As the pod, I want the runner to author at least one probe from the reduced spec, so that an empty vector no longer lands a false absence.
11. As the pod, I want a non-derivable probe to land `no-symptom-evidence` with `clean=false`, so that an authoring gap is not recorded as target absence.
12. As the pod, I want the replay capability to stay available, so that a recorded baseline can still be executed when the hunter names it.
13. As the triager, I want the skill procedure in my context, so that I can diff it against the executed procedure.
14. As the triager, I want a fixed gap-class vocabulary, so that every variant basis is named consistently.
15. As the triager, I want the first uncovered gap class to be the basis, so that the mining order is deterministic.
16. As the triager, I want a failure-mode fallback, so that a fully covered procedure can still yield a variant.
17. As the triager, I want runner-failure and runner-divergence triggers, so that a broken execution yields a recovery variant.
18. As the triager, I want the experiment log in my context, so that I never mint a duplicate variant.
19. As the triager, I want the terminal decision vocabulary unchanged, so that the binary verdict and the six terminal reasons stay stable.
20. As an operator, I want the variant record shape unchanged, so that the pod memory and the parent reads do not migrate.
21. As an operator, I want `declined_attribute` to carry the basis, so that the stored lineage names the real reason.
22. As an operator, I want the seven procedure gaps named after the skill's procedure, so that the triager and the hunter use the same entities.
23. As an operator, I want the skill procedure excerpt bounded, so that the pod context does not grow with the whole skill.
24. As an operator, I want the pod to fall back to the failure-mode reasoning when the excerpt is absent, so that a missing provenance field degrades rather than blocks.
25. As a reviewer, I want the INIT gate's mandatory set fixed, so that no implementation invents a third requirement.
26. As a reviewer, I want the retired fields absent from every fixture and prompt, so that no stale `testing_pattern` path survives.
27. As a reviewer, I want the variant basis persisted, so that a later audit can reconstruct why the variant was mined.
28. As a runtime operator, I want the pod's binary terminal invariant unchanged, so that the parent's verdict derivation stays valid.

### 8.4 The reduced D4 surface and the INIT gate

The D4 surface is:

```
TargetIdentity:
  url: str
  unit_id: str

TestImplementationSpec:
  target_identity: TargetIdentity
  verification_symptoms: list[str]
  assumptions: list[str]
  rationale: str
  parent_spec_ref: str | None
  provenance: SpecProvenance
  skills: list[str]

SpecProvenance:
  run_id: str
  loop_id: str
  unit_id: str
  canonical_class: str
  web_vulnerability_class: str
  baseline_ref: str | None
  source_recon_refs: list[str]
  assumption_ref: str | None
  playbook: str | None
  skill_procedure: SkillProcedure | None
```

The semantics are:

- `target_identity.url` is the base URL the pod probes.
  The hunter authors it from the projected L0 surface and the unit context.
- `target_identity.unit_id` is the kind-qualified L1 identity.
  It is carried for provenance; it is not INIT-gated.
- `verification_symptoms` are the concrete observable failure modes of the trust agreement over an interface or a state transition.
  They stay the ground truth for whether the vulnerability has manifested.
- `assumptions` are the technical requirements the pod may falsify.
  They are not the modeller's trust assumptions.
- `rationale` is the vulnerability-level rationale.
  It carries no failure-mode detail and no narrowed vector.
- `parent_spec_ref` is the variant lineage.
- `provenance` carries `run_id` (bound by the store, never authored), `loop_id`, `unit_id`, `canonical_class`, `web_vulnerability_class`, `baseline_ref` (optional), `source_recon_refs`, `assumption_ref`, `playbook`, and the bounded `skill_procedure`.
- `skills` is the optional flat pod-runner skill list.
  Each name is a skill the runner may carry.
  It is never a path and never a meta-skill.

The hunter write adds `status`, `fault_keyword`, and `strategy_keyword`.
`spec_id` is derived as `<fault_keyword>_<strategy_keyword>`.
It is never authored.

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

The hunter authors it from the loaded class skill; the total excerpt is bounded to 4000 characters.
The seven fields map one-to-one to the seven procedure gap bases in 8.6.
The pod triager reads the excerpt from the spec provenance.

The retired fields are `testing_pattern`, `payload_vector_space`, and `interpretation_guidance`.

The INIT gate's mandatory set is exactly:

- `target_identity.url` is a non-empty string.
- `verification_symptoms` contains at least one non-blank string.

Every other field is optional.
The gate collects all violations in one rejection.
The rejection lands `unsuccessful` with the validation evidence in the trail and zero tool calls.
The gate does not probe the URL.
An unreachable URL lands `technical-infeasibility` at execution, not a rejection.

The INIT gate keeps the hunter's responsibility for the base URL.
A symbolic loader that would inject the configured target URL is rejected.
It risks misleading the pod on targets that expose assets through multiple URLs.

### 8.5 Runner probe authoring

The runner authors a `ProbeChain` from:

- The spec's rationale.
- The verification symptoms.
- The assumptions.
- The target identity.
- The target surface.
- The methodology KB.

The chain keeps its shape: ordered dependency steps plus exactly one core payload-carrying step.

The `payload_vector_space` is retired.
The runner's first ReAct turn still authors at least one probe.
No probe is pre-authored by the hunter.

The `ProbeStep.request_ref` and the pod's `replay` tool stay available.
When `provenance.baseline_ref` is present, the runner may use `replay` with that artifact id.
Otherwise the runner authors the requests from scratch.
The D4 carries no structured payload vector; `baseline_ref` is a single optional artifact pointer.

If no probe is derivable, the run lands `no-symptom-evidence` with `clean=false`.
The authoring gap is impaired coverage, not target absence.
The old `space-exhausted` on an empty vector is retired.

### 8.6 Variant minting

The triager's decision stays either terminal or variant.
The terminal decision vocabulary is unchanged.

On a variant decision, the decision carries:

- `declined_attribute`: the variant basis.
- `variant_spec`: the derived spec.
- `feedback`: the runner-facing explanation.

The `VariantSpec` storage record keeps its shape:

```
ref: str
parent_ref: str | None
declined_attribute: str
spec: dict
```

`declined_attribute` carries the variant basis literal.

The variant basis vocabulary is:

| Basis | Meaning |
|---|---|
| `recon-action` | A different vulnerability-specific recon action was available and untried. |
| `bypass-technique` | An untried bypass technique was in the skill procedure. |
| `technology-grounding` | The target technology was insufficiently grounded; no sharp payloads or vectors were attempted for it. |
| `pro-tips` | A pro tip in the skill procedure was not executed. |
| `advanced-technique` | An advanced technique was not leveraged. |
| `preliminary-chaining` | A preliminary vulnerability that could grant the required capability was not exploited. |
| `interpretation-pitfall` | The interpretation failed in a common pitfall named by the skill. |
| `failure-mode` | No procedure gap exists; an additional observable failure mode is plausible. |
| `runner-failure` | The runner execution failed. |
| `runner-divergence` | The execution diverged completely from the spec. |

The first seven are procedure gaps.
The `failure-mode` basis is the fallback.
The last two are execution triggers.

The minting algorithm is:

1. Read the typed `SkillProcedure` from `spec.provenance["skill_procedure"]`.
   The seven fields map to the seven procedure gap bases in table order.
   When the excerpt is absent, record the gap and go to step 5.
   A section is covered when the executed procedure in the D6 trail contains the action, technique, or check that the section names.
   The triager judges coverage from the trail; the mapping is one-to-one.
   An EMPTY section is a skipped class, not a coverage gap: there is no authored procedure to execute or cover, so the diff passes over it (T10 H1).
   Treating an empty section as a gap would re-mint the same basis every lap and loop to the budget cap without a new prediction.
2. Read the executed procedure from the D6 trail: the variant specs, the probe chains, the raw observations, the interpretations, and the pod notes.
3. Test the execution triggers first.
   When the runner failed, the basis is `runner-failure`; when it diverged completely from the spec, the basis is `runner-divergence`.
   A failed or diverged execution has no meaningful procedure coverage, so these triggers outrank the diff (T10 H3).
4. Test the seven populated gap classes in the table order.
   The first gap class that the executed procedure does not cover is the basis.
   The variant changes the spec to cover it.
5. If every populated gap class is covered, reason on the additional observable failure modes the spec's `verification_symptoms` and `assumptions` could yield.
   If a new observable failure mode is plausible, mint a `failure-mode` variant.
   The fallback uses only the material the pod holds; it does not read the modeller's failure-mode space.
6. Never mint a duplicate of a basis and detail already present in the experiment log.
   The triager reads the log before deciding.
   The detail comparison is exact text over the canonical key-sorted JSON of the derived spec: a changed field is a new variant, a re-worded but semantically identical spec is not caught (T10 H7).
7. Record the variant with the basis in `declined_attribute`, the parent ref, and the derived spec.
   The derived spec keeps the base `provenance`, including the typed skill procedure; the graph enforces the field (T10 H6).

The triager's context carries the note, the filtered experiment log, the base spec, and the bounded skill procedure excerpt.
The triager prompt's mining section is rewritten to the algorithm above.
The terminal decision output is unchanged.

The `space-exhausted` exhaustion rule is prompt-level, not symbolically enforced (T10 H2).
The harness cannot decide whether a knowledge-base answer carried a precise new variant; that judgment is the triager's, and the terminal decision keeps its six-way binary vocabulary.
The rule is stated in the triager prompt and reviewed there.

The 4000-character skill-procedure bound is the HUNTER authoring seam (S3 8.6): the hunter-store write rejects an over-long excerpt.
A spec that reaches the pod directly (a pre-mined artifact or a test fixture) is not re-validated by the pod; the diff reads only whether a field is empty and the triager's coverage claim, so the bound is documented rather than re-enforced at the pod seam (T10 H5).

A HARD runner exception (an internal error, not a failed execution the triager observed) degrades the pod to `technical-infeasibility` at the run wrapper, not `runner-failure` (T10 H8).
`runner-failure` is the triager's decision on an executed-but-failed stretch; the wrapper's fail-open terminal is an execution impossibility and never mints a variant.

The pod memory variant records keep their shape.
The `declined_attribute` field's semantics change from a declined spec attribute to the variant basis.

### 8.7 Implementation decisions

- The D4 surface is the reduced shape in 8.4.
- The INIT gate's mandatory set is exactly the URL and the symptom list.
- The runner authors probes from the reduced spec.
- The replay capability stays; the structured vector does not.
- A non-derivable probe lands `no-symptom-evidence` with `clean=false`.
- The variant basis vocabulary is the table in 8.6.
- The triager reads the typed `SkillProcedure` from the spec provenance.
- The baseline is `provenance.baseline_ref` when present.
- The first uncovered gap class is the basis.
- The `variants` concept stays pod-side: a variant is a combination of a subset of the skills-ontology entities.
- The failure-mode fallback and the runner triggers are explicit.
- The variant record shape is unchanged.
- The triager prompt's mining section is rewritten.
- The retired fields are removed from the model, the gate, the prompts, the fixtures, and the tests.

The implementation follows the patterns recorded in `src/polymerhus/attack/hunting/CONTEXT.md`: the `validate_spec` INIT gate, the pod memory store's deterministic-key pattern, the `VariantSpec` record shape, the semantic `spec_id` (`spec_identifier`), and the triager's binary decision presentation.
The pod replicates the pattern and keeps the binary terminal invariant.

### 8.8 Testing decisions

Test the INIT gate, the runner probe authoring, the variant minting, and the prompt contract.
Drive the graph with a scripted triager decision and a scripted experiment log.
Assert the persisted variant records and the terminal envelope.

Seams:

- The D4 schema: the reduced fields parse; the retired fields are rejected as unknown.
- The INIT gate: URL missing, symptoms empty, both missing, the all-violations collection, the zero-tool-call rejection.
- The runner: a first probe authored from the reduced spec; a non-derivable probe landing `no-symptom-evidence` with `clean=false`; a replay ref when the hunter names one.
- The variant basis: each of the ten literals.
- The procedure diff: the first uncovered class wins; the order is fixed.
- The fallback: a fully covered procedure mints a `failure-mode` variant.
- The execution triggers: runner failure and runner divergence.
- The duplicate guard: a basis and detail already in the log is not re-minted.
- The storage: the variant record shape; `declined_attribute` carries the basis.
- The prompt: the mining algorithm and the ten bases.

Prior art:

- The pod graph and verification tests.
- The pod memory variant tests.
- The triager decision tests.

### 8.9 Out of scope

- The hunter workflow and the spec authoring (S3).
- The harness FSM (S4).
- The modeller and artifact (S1, S2).
- The cooperative-team execution logic beyond the scaffold.
- The closed-enum pattern engine (`#81`).
- The fault-targeting tool registry (`#71`).

### 8.10 Further notes

The workbench R8-3 and Q48 are the decision authority.
The reduced D4 surface is shared with S3 8.6.
The variant basis is the only new decision object.
The pod's binary terminal invariant, six-way termination, fixed caps, and experiment-log shape stay.
### 8.11 Context dedup amendment (2026-10-23)

The shared decision record is `docs/design/hunting-context-dedup-2026-10-23-adr.md`.
The impact map is `docs/design/hunting-context-dedup-impact-map.md`.

The pod changes are:

- The Runner and the Triager name their full bound tool surfaces.
  The Runner names `auth_store`.
  The Triager names `graph_view` and `auth_store`.
- The auth store is read-only on both roles.
  The full write contract is not bound.
- The request tool definitions are the full surface.
  The prompt tool lists are complete human summaries.
- The tool descriptions are shared constants.
  The runner surface falls from 12,979 to 5,101 chars.
  The triager surface falls from 12,715 to 4,837 chars.
  The 4,649-char auth-mode cut is included in both totals.
- The shared conciseness directive is shortened and embedded once.
- The first human context is pinned through compaction for both roles.
- The spec paragraph names `skills`.
- The variant bases and the critic's five terminal reasons are pinned by tests.

The full spec, variant, and terminal generation remains a follow-up.
