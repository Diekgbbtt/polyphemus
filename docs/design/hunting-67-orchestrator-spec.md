# Hunting agent spec: hunt-orchestrator (planner)

Part of [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (per-agent specs), top of the agent hierarchy.
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`; it holds the inter-agent logic (walkthrough S0-S7, domain data contracts D1-D11, interface agreements IA-1..IA-8, failure-handling canon, agent-attribute compliance).
This document disambiguates the orchestration agent from the combined spec: everything below is the hunt-orchestrator's contract alone, written to the depth an implementation session can build from without re-reading the parent.
Decisions cited as D67-n live in `docs/design/hunting-67-per-agent-specs-decisions.md`.

*Status: spec (contract), NOT implementation.*

## 1. Identity

The hunt-orchestrator is the planner: a single agent instance per hunting run, peer of the phase-2 orchestrator, in the hunting bounded context.
It selects candidates, configures hunts, dispatches, and holds the orchestration state (memory, budget, back-edge needs) across the run.

### 1.1 Role

One planner agent per run.
It is the only agent with graph access (a read-only L0/L1 view) and the sole owner of the hunt back-edge seam (IA-6, D67-04).

### 1.2 Goal

Select `HuntCandidate`s, configure and dispatch hunts so that every dispatched hunting agent yields at least one test-execution, and hold the orchestration state (memory, budget, back-edge needs) across the run.

### 1.3 Workflow

1. Consume the `FaultSource` output: the candidate set `{(unit, fault, symptom, applies-witnesses)}` with the deterministic prune applied (#63).
   The three-valued `match verdict` is the prune signal (Q8 level 1).
2. Run the in-turn reasoning gate (Q8): per fault-class, reason over the evidences plus the fault-class's concrete requirements (retrieved KB), producing the rationale, assumptions, and envisioned test primitives.
   A KB-retrieval failure degrades the reasoning to the evidences alone (D67-11); it never prunes a direction by itself.
   Directions it is not sufficiently confident on are pruned in-turn (pure LLM heuristic, no confidence score); there is no distinct gating phase.
3. Feed the carried-forward directions to the ranker (S2; the ranker body is #71's, the hooks #69's; stubbed in this build).
4. For each carried-forward direction that survives ranking and the budget governor, mint one `HuntConfig` (D3) and dispatch one hunting agent (N = 1 in phase 1).
5. Handle the back-edge: a yellow `insufficient-evidence` match verdict raises a targeted-recon need via the hunt back-edge (`request_targeted_recon`, `origin="hunting"`); park/resume and inline modes per IA-6.
6. Collect hunts' outcomes and evidence trails, persist via the hunt store (#68; a minimal markdown stub in this build) and the orchestrator memory (#70; stubbed), and advance the run.

### 1.4 Tools (D67-04)

The admitted tool surface is exactly three tools:

1. The hunt back-edge: targeted-recon requests through `recon/control/targeted.py::request_targeted_recon` with `origin="hunting"` (IA-6).
2. The hunt-store reads: candidates, configs, hunts, results, memory.
3. A read-only view over the live L0/L1 graph.

The graph view is read-only: a write attempt through the view is rejected (assertion C5).
The orchestrator never writes L0/L1.

### 1.5 Context

The `FaultSource` outputs (D1, D2); the retrieved KB evidences (rationale, assumptions, envisioned test primitives); the hunt store reads; the read-only graph view; prior-hunt insights by revival key (#70); budget state (Q7 accounting).
The graph view and the hunt-store reads are live re-derives at orchestration time, never a pipeline snapshot (merged spec section 3).

### 1.6 Output template

- A dispatched `HuntConfig` per carried-forward direction (record D3).
- A back-edge need where a yellow verdict raised it (record D9, interface IA-6).
- Orchestration state transitions persisted to the hunt store (hunt records D8) and memory (#70).

### 1.7 Produced outcome

The hunt store reflects the orchestration lifecycle (candidates -> configs -> hunts -> results), the back-edge needs are recorded, and the run advances without blocking on any agent.
Nothing is written to L0/L1.

### 1.8 Observability

The shared recipe (merged spec section 8): one Langfuse trace per orchestration turn, spans per step named after the step, session = run id, Langfuse optional and fail-open, verdicts measured via hunt-store records and the eval harness, never Langfuse score identifiers.

### 1.9 Honour clauses

- Sole-writer: never writes L0/L1; persists only through the hunt store.
- Sequential dispatch: one model turn at a time; N = 1 hunts in phase 1.
- Fail-open: section 5.
- Live reads: context is re-derived, never a pipeline snapshot.

## 2. Domain peculiarities

- The gate is EMBEDDED in the single reasoning turn: no distinct gating phase, no confidence scores, pure LLM-heuristic pruning (Q8).
- Sole graph-adjacent agent: the hunting agent consumes projections, never the graph (merged spec 5.4).
- Sole back-edge seam owner: BOTH back-edge modes route through the orchestrator (IA-6).
  In the inline mode the hunting agent surfaces the gap through its feedback (IA-5); the orchestrator executes the targeted-recon request and routes the result back on the `correlation_id`; the hunting agent never calls recon directly.
- Dispatch-guarantee holder: the "every dispatched hunting agent yields at least one test-execution" property is the dispatch contract (IA-2); the orchestrator records what the agent delivers, it does not fabricate executions.
- Back-edge modes: park/resume (S3) is bounded by the depth-1 cap (a re-match still `insufficient-evidence` terminates the candidate as `unresolved` with the residual gap on the revival key); the inline mode (S6) allows unbounded re-evaluation (D67-14) but the orchestrator only executes and routes - the re-evaluation loop itself lives in the hunting agent.
- Candidate identity: a candidate is `(unit, fault)` with a kind-qualified unit identity (`"<kind>:<key>"`); dedup and revival keys are bound to this identity.

## 3. What this build builds vs stubs vs reuses

Builds:

- The orchestrator agent itself: the single reasoning turn (one LLM call) that produces the rationale/assumptions/envisioned test primitives, the in-turn pruning decision, and the per-direction `HuntConfig` minting.
- The dispatch invocation of the hunting agent (synchronous, in-process; IA-2).
- The back-edge need recording (park/resume) and the inline back-edge execution + result routing (IA-6).
- The hunt record writing (D8) to the hunt-store stub.
- The tool-surface enforcement: exactly the three tools of 1.4, graph view read-only.

Stubs (owned by sibling tickets, minimal fixture in this build):

- `FaultSource` (S0; #66/#71): the candidate set is fed as a typed fixture.
- The ranker (S2; #69/#71): a pass-through or fixed-order fixture.
- The budget governor (#71): an open-budget or fixed-limit fixture.
- The hunt store (#68): append-only markdown files, indexed by path/name (the Q8 persistence decision), enough for the catalogue's reads and writes.
- Orchestrator memory (#70): revival-key/insight records in the store stub.
- The hunting agent (IA-2 target): a fixture agent for the contract tier; the real agent arrives with its own ticket.

Reuses:

- Interface agreement B, `recon/control/targeted.py`: `AnalyserReconRequest`, `request_targeted_recon`, `TargetedReconResult`, `ReconScope` - verbatim, `origin="hunting"`, unit_id kind-qualified.
- The index-card projection (`analysis/index_card.py`) as the graph-view surface budget rule.
- The recon job registry pattern (`recon/control/jobs.py::JobSpec`) as the tool-registry pattern.

## 4. Happy paths and outliers

### 4.1 Happy paths

H1 - Full run: the fixture delivers two candidates (a Service and a System, both `applies`).
The gate carries both; the ranker orders; two `HuntConfig`s are minted and two hunts dispatched; both hunts return verdicts; the store ends with exactly two hunt records, each carrying its config/spec/result references; no back-edge need; the run advances.
H2 - Deterministic prune: one candidate `applies`, one `does-not-apply` (deterministic clause FALSE with the violated-clause witness).
Only one direction survives; one dispatch; one hunt record.
H3 - Park/resume: one candidate `applies`, one yellow `insufficient-evidence`.
The yellow candidate is parked with a back-edge need recorded (no hunt dispatched for it); after the recon lands and the re-match flips to `applies`, the second hunt is dispatched.
Terminal: two hunt records and one back-edge record.
H4 - KB degradation: the KB retrieval fails at the gate (D67-11).
The direction is kept, reasoned over the evidences alone; the dispatch still happens.

### 4.2 Outliers

O1 - Empty candidate set: FaultSource delivers zero candidates (all pruned, or LLM match exhaustion per fault).
The run performs an empty orchestration pass: zero dispatches, the store records the empty pass, the run terminates normally; this is a valid result, not an error.
O2 - Partial LLM-match exhaustion: the match for one fault exhausts.
That fault contributes an empty candidate set, the exhaustion is counted, the other faults proceed.
O3 - Store write failure at S7: the hunt-record write fails.
A warning is logged, the run continues, the record is re-flushed on the next opportunity; the run never blocks on a store failure.
O4 - Store read failure at orchestration time.
The orchestrator proceeds without the prior-hunt insights (degraded grounding).
O5 - Graph-view query failure.
The gate degrades to the candidate set and KB evidences alone (same fail-open spirit as D67-11).
O6 - Dispatch target failure: the hunting agent raises or times out.
The orchestrator records the hunt as unsuccessful/degraded in the store with whatever feedback arrived, and the run continues; the at-least-one-execution guarantee is the agent's design property, not a fabricable effect.
O7 - Duplicate candidate delivery: FaultSource delivers the same `(unit, fault)` twice.
The second delivery mints no second hunt; dedup is by the candidate identity (assertion C3).
O8 - Park/resume re-match still `insufficient-evidence`.
The candidate terminates as `unresolved` with the residual gap on its revival key (depth-1 cap); no within-run probe loop.
O9 - Budget cut at ranking: the governor cuts dispatch mid-way.
Fewer hunts than carried-forward directions; the run records the cut and the un-dispatched directions.
O10 - Malformed candidate record: missing witness or unknown fault class.
The record is dropped with a counted warning; nothing raises.

## 5. Delivery semantics and failure handling

Delivery canon (merged spec section 3): all delivery is synchronous and in-process in phase 1.

- IA-1 (FaultSource -> orchestrator): synchronous at run start.
  A fault whose LLM match exhausts yields an empty candidate set for that fault, counted; nothing raises.
- IA-2 (orchestrator -> hunting agent): synchronous in-process dispatch, one per carried-forward direction.
  A failing agent yields the recorded degraded outcome; the run never blocks and no call raises.
- IA-6 (orchestrator <-> recon): `request_targeted_recon`, synchronous MVP, fail-open, never raises.
  Status vocabulary `success`/`degraded`/`skipped`/`error`; a degraded or errored result is folded into the evidence trail.
  Park/resume: depth-1 cap. Inline: executed on demand, routed on the `correlation_id`.
- IA-7 (orchestrator <-> hunt store): reads at orchestration time, writes at S7.
  Write failures degrade to warnings; the run never blocks.

## 6. Assertion catalogue - work-item "hunt-orchestrator (per-agent spec from #67)"

**Source:** `docs/design/hunting-67-orchestrator-spec.md` (this doc); parent `docs/design/hunting-67-per-agent-specs-spec.md` section 4.
**Seams under assertion:** IA-1 (candidate delivery), IA-2 (dispatch), IA-6 (back-edge), IA-7 (store), the D67-04 tool surface, D67-11 KB degradation.

### 6.1 Contract predicates (integration tier)

C1 - Empty candidate set at IA-1: given zero candidates, exercising empty-valid, the run performs an empty pass: zero dispatches, the store records the pass, no raise.
Yields: `tests/integration/test_hunt_orchestrator_contracts.py::test_empty_candidate_set_is_an_empty_pass`.
C2 - Partial match exhaustion at IA-1: given one fault whose LLM match exhausts and one healthy fault, exercising degradation, the exhausted fault contributes zero candidates (counted) and the healthy fault dispatches normally.
Yields: `...::test_partial_match_exhaustion_degrades_per_fault`.
C3 - Duplicate candidate at IA-1: given the same `(unit, fault)` delivered twice, exercising duplicate-idempotent, exactly one hunt is minted; dispatch count stays one.
Yields: `...::test_duplicate_candidate_mints_one_hunt`.
C4 - Malformed candidate at IA-1: given a record with a missing witness and an unknown fault class, exercising malformed, the record is dropped with a counted warning and the valid records proceed.
Yields: `...::test_malformed_candidate_is_dropped_counted`.
C5 - Tool surface at the graph view (D67-04): given a write-shaped call through the read-only view, exercising malformed, the view rejects the write; no L0/L1 mutation occurs.
Yields: `...::test_graph_view_rejects_writes`.
C6 - Dispatch target failure at IA-2: given a hunting agent that raises, exercising degradation, the hunt is recorded unsuccessful/degraded with the partial feedback, the run continues, no raise propagates.
Yields: `...::test_dispatch_target_failure_degrades_the_hunt`.
C7 - KB failure at IA-2 (D67-11): given the KB retrieval failing at the gate, exercising degradation, the direction is kept and a `HuntConfig` is still minted.
Yields: `...::test_kb_failure_degrades_the_gate`.
C8 - Park/resume at IA-6: given a yellow verdict whose re-match is still `insufficient-evidence`, exercising degradation, the candidate terminates `unresolved` with the residual gap on its revival key; dispatch count for it is zero.
Yields: `...::test_park_resume_depth_one_cap`.
C9 - Inline back-edge at IA-6: given an inline need surfaced via IA-5 feedback, exercising success, the orchestrator executes the targeted-recon request with `origin="hunting"` and the result routes back on the `correlation_id`.
Yields: `...::test_inline_back_edge_routes_on_correlation_id`.
C10 - Store write failure at IA-7: given a failing store write at S7, exercising degradation, a warning is logged, the run completes, no raise.
Yields: `...::test_store_write_failure_degrades_to_warning`.
C11 - Record ordering at IA-7: given a dispatched hunt, exercising ordering, the store shows config -> dispatch -> result in order before the run advances.
Yields: `...::test_hunt_record_ordering`.
C12 - Empty dispatch record at IA-2 (ordering): given a carried-forward direction that the budget cuts (O9), exercising ordering, no hunt is minted and the cut is recorded.
Yields: `...::test_budget_cut_records_undispatched_direction`.

### 6.2 Walkthrough predicates (e2e tier)

The orchestrator's full-chain walkthroughs substitute nothing inside the live edge, so they are mechanisable only when the hunting agent (and the chain) exist; they are carried as blocked until the hunting-agent ticket lands.

E1 - Full run, two candidates: grounds merged spec 10.2-10.4, 10.8 and H1.
Entry seam: the candidate-set delivery at IA-1.
Input: the fixture candidate set `{(service:"kind:slug:a", fault_class:"fault-x", symptom:null, applies-witnesses:{deterministic:"", llm:"clause x holds"}), (system:"kind:key:b", fault_class:"fault-y", ...)}`.
Live edge: none (self-contained; the hunting agent is the real one, the pod the real one).
Path: gate carries both -> ranker orders -> two `HuntConfig`s minted -> two dispatches -> two hunting agents -> two pod runs -> two verdicts -> S7 persistence.
Terminal: exactly two hunt records in the store, each with config_ref, spec_ref, pod_result_ref and a hypothesis verdict; zero back-edge records.
Observed: the store listing queried by run id returns the two records with their field values.
Yields: `tests/e2e/test_hunt_orchestrator_walkthrough.py::test_full_run_two_candidates`. Blocked by the hunting-agent ticket.
E2 - Yellow park/resume: grounds merged spec 10.4/10.7 and H3.
Entry seam: the candidate-set delivery at IA-1.
Input: `{(unit:"kind:slug:a", fault:"fault-x", applies), (unit:"kind:key:b", fault:"fault-y", insufficient-evidence)}`.
Path: gate -> dispatch for a -> park for b with a back-edge record -> recon lands -> re-match applies -> second dispatch.
Terminal: two hunt records, one back-edge record, one `unresolved`-free run; the depth-1 cap is not hit.
Observed: the store's back-edge records and both hunt records.
Yields: `...::test_yellow_park_resume`. Blocked by the hunting-agent ticket.

### 6.3 Orchestrator-in-isolation predicates (e2e tier)

The orchestrator's OWN infrastructure seams are exercised for real here - a live L0/L1 graph the read-only view grounds on, and a real append-only markdown hunt store on the filesystem - while the agent-side collaborators (reason turn Q8, dispatch IA-2, re-match, KB retrieval, back-edge) are the spec-sanctioned fixture agents (section 3). This closes the coverage hole left by C1-C12 (which mock the graph view empty) and the blocked E1/E2 (which need the real hunting agent): nothing else asserts the orchestrator grounds in real index-cards, never writes L0/L1, or persists the full lifecycle into real store files. Every happy path H1-H4 and every outlier O1-O10 takes its orchestrator shape here.

E3 - Full run against the real graph (H1 + D67-04): given two applies candidates over a live project carrying a Service and a System with edges, exercising success, the gate's surface is the REAL index-cards (typed spine + per-family edge degrees), both `HuntConfig`s carry that surface and the KB's tool registry, the store ends with run/config/hunt/dispatch/result records chained by `config_ref`, and the L0/L1 graph is byte-identical before and after the run.
Yields: `tests/e2e/test_hunt_orchestrator_isolated_e2e.py::test_E3_full_run_grounds_in_real_graph_and_never_writes`.
E4 - Park/resume unresolved at the depth cap (O8, IA-6): given a yellow candidate whose re-match is still `insufficient-evidence`, exercising degradation, the candidate terminates `unresolved` with its revival key and a `back_edge` record; the back-edge path writes nothing to the graph.
Yields: `...::test_E4_park_resume_unresolved_at_depth_cap`.
E5 - Park/resume re-match applies (H3, IA-6): given a yellow candidate whose re-match flips to `applies`, exercising success, the second hunt dispatches and its `HuntConfig` carries the back-edge caveat; the store has two hunt records and one back-edge record.
Yields: `...::test_E5_park_resume_rematch_applies_dispatches`.
E6 - Deterministic prune before the gate (H2, Q8 level 1): given an applies and a does-not-apply candidate, exercising success, only one direction survives to dispatch, `pruned_by_verdict` counts one, and the gate still grounds in the real graph.
Yields: `...::test_E6_deterministic_prune_before_the_gate`.
E7 - Empty candidate set (O1): given zero candidates, exercising empty-valid, the run records the empty pass with `candidates_received == 0` and dispatches nothing.
Yields: `...::test_E7_empty_candidate_set_is_an_empty_pass`.
E8 - Duplicate + malformed intake (O7/O10): given a duplicate identity and a missing-witness candidate, exercising malformed, both are dropped counted and one hunt proceeds.
Yields: `...::test_E8_duplicate_and_malformed_dropped_counted`.
E9 - KB degradation at the gate (H4/D67-11): given a failing KB retrieval, exercising degradation, the gate reasons degraded (`kb_degraded`), the direction is kept, the minted config's tool registry is empty, and the dispatch still happens.
Yields: `...::test_E9_kb_failure_degrades_the_gate_never_prunes`.
E10 - Store write failure (O3, IA-7): given failing store writes at S7, exercising degradation, warnings are logged, the run completes, and the failure count is reported.
Yields: `...::test_E10_store_write_failure_degrades_to_warning`.
E11 - Store read failure (O4, IA-7): given a failing store read, exercising degradation, the hunt proceeds with empty prior-hunt insights.
Yields: `...::test_E11_store_read_failure_degrades_prior_insights`.
E12 - Graph-view query failure (O5): given a failing graph read, exercising degradation, the gate degrades to the candidate set + KB evidences alone and the hunt still dispatches.
Yields: `...::test_E12_graph_view_failure_degrades_the_gate`.
E13 - Dispatch target failure (O6, IA-2): given a hunting agent that raises, exercising degradation, the hunt record is `degraded` with the error, the run continues.
Yields: `...::test_E13_dispatch_failure_degrades_the_hunt`.
E14 - Budget cut (O9): given a budget governor that cuts one of two directions, exercising ordering, the cut direction is recorded, not dispatched, and one config/hunt pair results.
Yields: `...::test_E14_budget_cut_records_undispatched_direction`.
E15 - Cross-run memory by revival key (#70, E1): given a completed first pass, exercising persistence, the first pass's feedback becomes the second pass's prior-hunt insight, read back out of the real cross-run `memory.md`. (As of the #137 memory workstream the cross-run `memory.md` is superseded by the **per-project** hunt-config + note memory store; the revive-keyed prior-hunt insight persists there via the note + config reading tool - see the memory system.)
Yields: `...::test_E15_cross_run_memory_by_revival_key`.
E16 - The read-only view over the live graph (D67-04): given a write-shaped call through the real view, exercising malformed, the view rejects the write and still serves reads against the live graph.
Yields: `...::test_read_only_view_rejects_writes`.

## 7. Out of scope

The ranker body (#71), the budget governor (#71), the `FaultSource` engine (#66/#71), the hunt-store persistence design (#68), the memory system (#70), the back-edge trigger wiring (#64), and the hunting agent itself (its own spec doc).
The merged spec's inter-agent logic (sections 10-14) governs the seams this document references.
