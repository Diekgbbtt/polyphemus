# Hunting agent spec: test-executor pod

Part of [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (per-agent specs), bottom of the agent hierarchy.
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`; it holds the inter-agent logic (walkthrough S0-S7, domain data contracts D1-D11, interface agreements IA-1..IA-8, failure-handling canon, agent-attribute compliance).
This document disambiguates the test-executor pod from the combined spec: everything below is the pod's contract alone, written to the depth an implementation session can build from without re-reading the parent.

*Status: spec (contract), being re-specified by the #84 regrounding.
Implementation decisions from the 2026-08-21 grilling live in `docs/design/hunting-84-regrounding-decisions.md` (D84-1..D84-25) and are authoritative over this document where they clash; this document is corrected so no clash remains.
The regrounding reconciled the pod onto the shared session abstractions (`HuntSession`, `stateful_turn`, the #95 compaction middleware, async-native entry) and superseded the pre-regrounding scaffold's stateless seams and symbolic runner.*

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
          * tools bound: `exec`, `kb_retrieve`, `note`
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
- **`kb_retrieve`** - the bound knowledge-base retrieval tool (D84-16 KB-wiring fix; the pre-regrounding scaffold declared the tool in the prompt but never bound it).
  Wired as a LangChain `BaseTool` into the Runner's `create_agent` `tools=[...]` - the SAME pattern the hunting agent's author lane uses (`actors.py:356-360` `build_lightrag_tool()`) and the canonical `bind_tools` ReAct loop (`crawl_agentic.py`) (D84-26).
  The real tool is the `query_lightrag` tool + its loadable skill + the KB artifact from the `lightrag` workstream (not merged to dev; #84 consumes the seam once merged - D84-26).
- **`note_tool`** - the note write/read tool (D84-17/20/27): the Runner writes ONE consolidated experiment-summary note at P3 exhaustion (prompt-verbatim); the Triager reads it per lap as its primary reasoning artifact. Bound into the respective agents' `tools=[...]` (Runner: write; Triager: read).
- **Tool-call validation is the tool's own contract** (D84-22): a wrong parameter fails as a tool-call request REJECTED with an error message + code describing the semantic explicitly - the harness does not re-validate arguments, it only enforces the cap, raw recording (G4), and dedup (O7).

The specialised fault-targeting tool registry is #71's future home.
The tool calls are the only place the live target is touched.

### 1.5 Context (D84-20)

The `TestImplementationSpec` (D4); the communication interface with the parent HuntingAgent (the typed handoff: D4 in, D5 + D6 out); the memory and observability seams; and the pod experiment-memory store.

The pod has **no graph access**.
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
  2. Pattern/probe space exhausted without symptom -> `unsuccessful`, terminal_reason `space-exhausted`.
  3. A strong technical infeasibility assertion (unreachable target, missing tool, everything WAF-blocked) -> `unsuccessful`, terminal_reason `technical-infeasibility`, infeasibility in the trail.
  4. A specific active defence prevented the probes (a WAF/filter soft-block) -> `unsuccessful`, terminal_reason `specific-defence-prevention`.
  5. Symptom absent but coverage partial or observations impaired -> `unsuccessful`, terminal_reason `no-symptom-evidence`.
  6. Budget/timeout reached -> `unsuccessful`, terminal_reason `budget-timeout`, partial evidence.
  `clean` True = clean completed observations; False = blocked/unreachable or a mid-flight cut. `init_validation` present only on an INIT rejection.
- The fixed caps (D67-09): `MAX_POD_ITERS = 3`, `EXEC_TIMEOUT_S = 300`, `HUNT_POD_MAX_TOOL_CALLS = 200`, `HUNT_POD_MAX_ITERS = 8`; all env-overridable, all pod-internal, never spec fields.
- The testing pattern is an OPEN NL pattern inside the typed envelope (D67-07): the engine treats it as guidance over the generic loop.
  The closed-enum pattern engine is deferred to [#81](https://github.com/Diekgbbtt/polyphemus/issues/81).
- Variants (D67-08): a declined/refined attribute yields a derived variant spec instance, recorded with provenance; the exported evidence is the full experiment log (variant specs, raw observations, interpretations).
- INIT validation is a hard gate: a spec failing the typed base schema or the environment contract is rejected and lands `unsuccessful` with the validation evidence in the trail.
- An empty payload vector does NOT zero the loop: the Runner's first ReAct turn still issues the default probe once; if no probe can be derived at all, the loop lands `space-exhausted` with the (possibly empty) log (O12/C11).
- Identical variant + payload executions are deduplicated: one execution, recorded once (O7/C10).
- **The note final step (D84-17/20)**: once the Runner reaches P3 space exhaustion, it writes ONE consolidated experiment-summary note to the pod experiment-memory store - a plain prompt-verbatim final step in the workflow, summarising the experiments from all the stretch's logs.
  The Triager reads the note from a third-party perspective before deciding.

## 3. What this build builds vs stubs vs reuses

Builds:

- The minimal LangGraph scaffold: the HIGH-LEVEL workflow map (`INIT -> RUNNER STRETCH -> TRIAGER -> decide -> TERMINAL`), general tool-calling (`create_agent` ReAct), the pod experiment-memory store + note tool, Langfuse observability with the full tool-call/reason graph, the communication interface with the parent HuntingAgent, the `build_harness_middleware` (cap G1, raw recording G4, dedup O7) and the compaction middleware on the agent.
- The two tools (`exec`, `kb_retrieve`) with retry and timeout enforcement and the tool-contract validation semantics (D84-22).
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
H2 - Absent: the pattern/probe space exhausts without the symptom -> `{unsuccessful, space-exhausted}`, with the P3 note written.
H3 - Infeasible: unreachable target or all tools blocked -> `{unsuccessful, technical-infeasibility}` with the infeasibility in the trail.
H4 - Capped: budget/timeout reached -> `{unsuccessful, budget-timeout}` with partial evidence.
H5 - Variant: a declined attribute yields a derived variant spec with provenance; the loop continues; the log records both variants.
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
O12 - Empty payload vector: the Runner's first ReAct turn still probes once; if no probe is derivable, `space-exhausted` with the log.
O13 - KB query failure (`kb_retrieve` raising or empty): fail-open - the Runner degrades to the spec's own primitives and the P3 re-query returning the SAME set as init confirms exhaustion (D84-16).
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
C4 - Space exhausted: given a spec whose symptom never appears across the whole probe space, exercising empty-valid, the pod lands `{unsuccessful, space-exhausted}`.
C5 - Infeasibility: given an unreachable target (connection refused), exercising degradation, the pod lands `{unsuccessful, technical-infeasibility}` with the infeasibility in the trail.
C6 - Budget/timeout: given tool calls exceeding the fixed caps, exercising degradation, the pod lands `{unsuccessful, budget-timeout}` with partial evidence.
C7 - Retry: given a tool call failing with non-zero exit twice then succeeding, exercising degradation, the retries converge at `MAX_POD_ITERS = 3` and the run lands a binary end.
C8 - Timeout enforcement: given a tool call hanging past `EXEC_TIMEOUT_S`, exercising degradation, the exec is aborted and the run lands a binary end within the caps.
C9 - Variant provenance: given a declined attribute, exercising success, the experiment log contains the derived variant spec with provenance and the raw observation and interpretation entries (D6 shape).
C10 - Duplicate probe: given the same variant + payload re-decided, exercising duplicate-idempotent, exactly one execution is recorded in the log.
C11 - Empty payload vector: given a spec with an empty payload vector space, exercising empty-valid, the Runner still probes once (or the run lands `space-exhausted` when no probe is derivable).
C12 - Langfuse stub failure: given the observability stub raising, exercising degradation, the run completes unaffected.
C13 - KB tool bound: given a spec whose concretization needs a KB query, exercising tool-surface, the Runner's `create_agent` is bound with `exec` + `kb_retrieve` (assert the tool list), and a query returns through the typed seam fail-open.
C14 - Note written on P3: given a space-exhausted run, exercising success, the pod experiment-memory store holds ONE consolidated experiment-summary note keyed by the spec id + variant, and the Triager reads it.
C15 - Tool-contract validation: given a tool call with a wrong parameter, exercising degradation, the call is REJECTED with an error message + code (never executed, never harness-revalidated).

### 6.2 Walkthrough predicates (e2e tier)

E1 - One trivial real run: grounds merged spec 6.12 and H1.
Entry seam: the IA-3 handoff (a fixture `TestImplementationSpec`).
Input: a spec with target identity `"service:web:soupmarket"`, verification symptom "HTTP 200 with a non-empty body on GET /", testing pattern (open NL) "blind-boolean", assumptions ["network egress allowed"], payload vector space `{method: GET, path: "/"}`, rationale + interpretation guidance set.
Live edge: the eval target `soupmarket.shop` (the `juice-shop-remote` target in `tests/e2e/fixtures/eval-targets.yaml`), live HTTP mode.
Path: INIT validates -> RUNNER STRETCH (ReAct; the Runner's first turn issues the default probe -> EXECUTE -> OBSERVE) -> symbolic symptomatic classification OR the Triager -> TERMINAL.
Terminal: exactly one verdict `{successful, symptom-confirmed, iterations >= 1}` and an experiment log with at least one raw observation.
Observed: the hunt-store stub record and the response status read back from the tool call log.
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