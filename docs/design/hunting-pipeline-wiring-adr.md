# ADR: Hunting pipeline wiring - grilling dispositions (2026-08-23/24)

Status: decided (grilling round for the hunting pipeline wiring, 2026-08-23 resolved
EOD 2026-08-24; operator rulings recorded verbatim where they amend).
Ticket: spec #169; the wiring tickets are #170-#175.
Base: `dev` at `8ef14c5` (the fork point of `feat/hunting-pipeline-wiring`).

This ADR records the grilling dispositions that produced the wiring spec
(`hunting-pipeline-wiring-spec.md`, published as spec #169) and the ticket
breakdown (#170-#175). It is the durable answer to the grey points the wiring faced:
branch divergence, surfer topology, delivery semantics, singular vs whole launch,
type ownership, and actor granularity.

## Context

The hunting pipeline is fragmented across refactor branches. The hunt-orchestrator
produces `HuntConfig`s (consumed by hunting agents), hunting agents produce
`TestImplementationSpec`s (consumed by test-executor pods). Each component is an
actor with a mailbox. The end-to-end wiring is missing: a message-passing engine and
the app REST surface to trigger the pipeline as a whole or one component at a time.

The authoritative seams: the sealed `hunting-module-runtime-seam.md` contract
(ratified 2026-08-11, single shared worker loop 2026-08-12, sequential-pipeline
premise 2026-08-13), the actors + inbox machinery in `app/llm/actor.py`, the typed
session addresses in `app/llm/session_address.py`, the run-time manager in
`app/runtime.py`, and `start_hunting`/`stop_hunting` in `attack/hunting/runtime.py`.

The memory substrate is the operator-locked `hunting-memory-system-spec.md`
(2026-08-23): per-project, produced/consumed config store + notes file, replicated
across every memory system ("its pattern will be replicated"). The inbox surfer's
produced->consumed movement is G13, explicitly another workstream's scope - THIS
workstream.

## Branch-state evidence (2026-08-23)

- `dev` (`8ef14c5` at inspection) holds the shared runtime, session addressing, and
  the base hunting seams, but not the fragmented component work.
- `feat/hunting-84-test-executor-pod` (`6209016`): 22 commits; owns
  `attack/hunting/pod/*` (`TestImplementationSpec`, `arun_pod`, `PodMemoryStore`),
  modifies `session_address.HuntSession` docstring. Spec id was the canonical hash
  (sha256) - RECONCILED by this workstream (below).
- `feat/hunting-orchestrator-candidates-rewrite` (`aadb68b` at inspection, working
  tree later at `20c7e4f`): 15+ commits; owns the per-fault REASON rework, the
  `HuntConfig` extension, `unit_projection.py`, `hunt_store` KINDS changes, and the
  memory-system + memory-workflow ADR docs.
- `#164` hunter state-graph content: a WIP commit (`4c5fa48` at inspection; the
  branch worktree was being re-updated by the agent) holding `hunter_graph.py`,
  `hunter_state.py`, `hunter_tools.py`, `actors.py` hosting, and the 14-grey-point
  ADR. Its spec now defines the spec identifier and the produced/consumed topology
  for the hunter domain.

## Dispositions (the closed frontier)

### Q1 - Integration branch strategy

Create a dedicated integration worktree `feat/hunting-pipeline-wiring` branched from
`dev`; merge the component branches in sequence, the wiring commits authoritative
there. Rebase would rewrite the feature branches' history while review is open; `dev`
is the only branch tracking the control-plane workstream.

### Q2a - Surfer hosting and lifecycle

A run-scoped surfer coroutine, spawned by the run bootstrap and reaped at the run's
terminal path - NOT a module-global daemon and not one surfer per component. Runs on
the one shared worker loop under `module_context("hunting")`.

### Q2b - Concurrency model (operator regrounding)

There can be MULTIPLE hunters and test-execution pods concurrently running. Only ONE
hunt-orchestrator, which is one-time-dispatch and does not consume messages so far.
New hunters and pods can be dispatched anytime; multiple can run simultaneously. The
only constraint is the shared thread pool size. Idle-state gating for DISPATCH is not
needed.

### Q3 - Delivery and consumption semantics

At-least-once. The produced/consumed directories ARE the handoff; the move IS the
at-least-once marker (the memory-topology pattern, G13). A dispatch refused by
admission leaves the item in produced for the next tick - never dropped. The crash
window between dispatch and move (R3) is accepted as negligible by operator ruling.
The file-name novelty gates (config id, spec id) defend double-dispatch content-wise.
The old per-run kind files and `_seq`/`_ref` bookkeeping are replaced by the topology.

### Q4 - Memory-items ownership map (operator)

orchestrator : huntConfig; hunter : testImplementationSpec; pod : experimentLog.
The experimentLog is in the pod tree. The hunter's testImplementationSpec family is
still to be implemented (#164 owns it).

### Q6 - REST surface

Extend the existing `project_management/api.py` HTTP adapter using its established
patterns (the launcher seam, repository + gateway, error mapping). At-most-once on
launch: track created run ids server-side and refuse replayed triggers with the
appropriate semantics; a dedicated idempotency header is rejected as over-engineering.

**Amended by the identity-based refactor (2026-08-25, operator ruling):** the
singular POD launch no longer enqueues a fabricated `specified` spec into produced/
(that fabricated dispatch input was the ambiguity the reviewer flagged). A pod-only
launch resumes ONE stored/paused pod session by posting its coroutine id, never
fabricating a `specified` status; the whole-pod-component path remains the
whole-pipeline run.

### Q9-Q11 - Sequencing, seams, and the surfer's role

- Q9/A: the memory-migrated topology lands FIRST; this workstream operates on it.
- Q10: start/stop seam shapes stay the same; the memory system has been specced and
  the wiring bases off it; pending #164 work is irrelevant as a gate.
- Q11: the inbox surfer ONLY owns checking inboxes for messages, communicating to the
  runtime control plane to dispatch the correct new agents, and moving the message to
  the consumed directory once the component returns correct dispatch feedback.

### Q12 - The control plane (operator)

Extend the SHARED runtime manager to per-session lifecycle on its run registry - not
a new module control-plane component. Through the shared manager, all coroutine
lifecycle management must be wired; it already holds similar logic partially, so one
lifecycle home. Session id = coroutine id = registry run name.

### Q13 - Session ids and spec identity (operator)

- Orchestrator session: `hunting:<run_id>:orchestrator`.
- Hunter session: `hunting:<run_id>:hunt:<config_id>`.
- Pod session: `hunting:<run_id>:pod:<config_id>:<spec_id>`.
- `config_id` = semantic config file name `<unit_id>_<CWE_ID>_<fault_class(vulnerability)>`
  (memory-system G4) - the `_`-joined fault_key.
- **Canonical identity (amended by the identity-based surfer refactor, 2026-08-25):**
  the ONE logical join key is the semantic `config_key` (`<unit_id>::<CWE_ID>::<vulnerability>`
  round-tripped by `HuntStore.semantic_key` / the `test-specs` folder's recovering
  parser). A produced spec's parent hunter is resolved by converting its `fault_key`
  folder to the `config_key` form - never by using the raw folder name as a hash key.
  `hunter_inboxes` is keyed by `config_key` on BOTH the register side (hunter
  dispatch) and the lookup side (pod dispatch): the two sides of one cross-family
  join must agree on the SAME canonical key, or every pod dispatch misses its parent.
- **The model-facing `fault_key` contract (amended by #199):** the model-emitted
  `fault_key` is validated by a harness-owned gate in the typed layer of the
  `hunts_store` / `notes` tools (writes AND reads) against the persisted config
  ids in the `HuntStore` - the naming convention (a well-formed 3-part config key,
  canonical `_`-joined `<unit_id>_<CWE_ID>_<vulnerability_class>` with the class's
  spaces preserved, or its `::`-semantic twin) plus a literal `:`-split match of
  the parts against a persisted config identity, with no cross-form resolution.
  A violation returns the denoted `fault_key_mismatch` error (never a raise, never
  a fabricated folder); the model reflects and corrects, mirroring the G4 dedup
  signal's interpretation.
- `spec_id` = semantic spec file name `<fault>_<strategy>` (164 state-graph spec 6).
  This REPLACES the pod branch's canonical-hash spec id everywhere it was identity
  (session-address spec discriminator, pod memory keys) - a reconciliation item for
  the pod leg.

### Q14 - Per-session pause granularity

Per-session pause stops the NEXT unit (idle-loop inbox read / graph-node boundary)
after the in-flight one, mirroring the sealed seam's pause semantics, but per session.

### Q15 - Dispatch gate width

A configurable width, default 20, per project. Effectively single-project execution
in practice, so one width.

### Q16 - Verdict-processing stub

(a) `arun_pod` is still dispatched; the experiment-log family is still
produced/consumed; but the hunter's idle-loop handling of a `PodExport` is a STUB
(consume and record, no re-evaluation). The verdict-processing workflow is not yet
clear and is not wired.

**Amended by the identity-based surfer refactor (2026-08-25):** the durable
parent-keyed record is written at POD COMPLETION, keyed by the parent's `config_key`
- independent of whether any live hunter inbox exists. The idle-loop inbox delivery
is a within-run LIVE FEED (a notification the co-running hunter may consume for the
future verdict-processing node, D67-02/D11/D67-14), never a dispatch gate: a
produced `specified` spec is dispatchable on ITS OWN persisted status, even when its
parent config was consumed by an earlier run (no live parent in this run). The export
is never lost to a crash between dispatch and an in-memory inbox consumption.

**The durable-record note key (amended by #199):** the durable pod-export note is
keyed `<config_key>:pod-export:<spec_id>` (the parent's canonical `config_key` +
the `pod-export:` marker + the semantic `<fault>_<strategy>` spec id) with action
`update` - one current record per (config, spec), since one TestImplementationSpec
yields at most one PodExport. The pod session id lives ONLY in `provenance["source"]`,
never in the note key, so the key stays round-trippable (`config_key_from_fault_key`
and the parent-read filters line up on the canonical config identity).

### Q17 - Session lifecycle surface

(a) Session pause/resume/cancel are exposed on the REST surface in this workstream,
including per-session addressing.

### Q18 - Sequencing

(A) Strict: the wiring branch is held off until the memory-produced/consumed topology
lands; then it operates on it.

## The inbox surfer protocol (from Q11 + Q3)

1. Surfer input surfaces: the memory families' `produced/` directories for the run's
   project (hunt configs, test specs, experiment logs).
2. Dispatch protocol: for each produced item not yet dispatched, ask the runtime
   control plane to dispatch the agent for its session id. On success feedback, move
   produced -> consumed. On refusal (gate full, module paused, run draining), leave in
   produced and retry next tick - at-least-once, never dropped.
3. The mover deduction is extracted as a pure function:
   `(produced set, session registry state, dispatch feedback) ->
   (to dispatch, to move, to retry)`; the impure shell applies the moves and drives
   the control plane.
4. The produced->consumed move IS the at-least-once marker.

**Dispatch gate (amended by the identity-based refactor, 2026-08-25):** an item's
dispatchability is decided by ITS OWN persisted status (`ratified` config -> hunter,
`specified` spec -> pod), never by the liveness of a chain-adjacent agent. A produced
spec whose parent hunter is absent from the current run (parent config consumed by an
earlier run) still dispatches and its export is recorded durably under the parent's
`config_key`. This makes the quiesce pending-work predicate and the dispatch decision
agree by construction - the `run_work_remaining`/`build_run_dispatch` "can never
disagree" claim RESTORED (previously violated: a spec was counted as work but could
never dispatch without a live parent inbox, wedging the run's quiesce).

## Agent idle state (from R7 + Q16)

After an agent's workflow graph ends, the agent enters the idle state: a simple loop
iteratively reading its inbox - reusing the existing mailbox loop machinery, NOT
checkpoint-resume mechanisation. The pod->hunter verdict handling in the idle loop is
a stub for now.

## Run lifecycle (from R1/R2 resolutions)

- The run reaches a terminal status only when all its component sessions have settled.
- Stop cancels every session of the run through the shared control plane (per-session
  cancel by id); the run-scoped surfer is itself a session and is cancelled with the
  rest. A coroutine returning while the run is still mid-flight must never silently
  `interrupt` the run - that is a defect in the control plane layer, not in this work.
- Start/stop seam shapes unchanged.
- **Quiesce/dispatch contract (restored by the identity-based refactor, 2026-08-25):**
  the pending-work predicate and the dispatch decision gate on the SAME thing - an
  item's own persisted status. No produced `specified` spec can wedge the quiesce:
  it is always dispatchable on its own status. The run reaches terminal only when no
  dispatchable produced item remains and all dispatched sessions have settled.

## Consequences

- The wiring operates on the memory topology (hunt configs, which the orchestrator
  produces; test specs, which the hunter produces; experiment logs, which the pod
  produces) via the produced/consumed pattern.
- The shared runtime manager gains per-session lifecycle and the hunting dispatch
  width - a shared-runtime change agreed by ruling (Q12).
- The pod's spec identity moves from the canonical hash to `<fault>_<strategy>`; the
  pod reconciliation is a wiring ticket item.
- #164's verdict-consumption detail (a hunter's idle handling of a PodExport) is
  stubbed; a future ticket owns the real verdict processing workflow. The refactor
  makes the durable export record parent-keyed and crash-safe (Q16 amendment).
- The refactor CONVERGES identity on the semantic `config_key` (Q13): the `fault_key`
  folder stays the physical address; the `config_key` is the JOIN key across the
  hunter/pod families. One round-trip helper, no dual-key drift.

## Alternatives rejected

- A bespoke polling `hunting/surfer.py` scanner: rejected - the runtime owns
  scheduling; the surfer is a mover, not a loop owner.
- A second module control-plane component: rejected (Q12) - lifecycle logic stays in
  the shared runtime manager.
- Idle-state gating for dispatch: rejected (Q2b) - dispatch of new hunters and pods is
  unconstrained up to the shared executor.
- An `Idempotency-Key` header: rejected (Q6) - server-side run-row tracking suffices.
- Checkpoint-resume mechanisation for late messages: rejected (R7) - agents idle-loop
  over their inbox.
- Per-ref consumption marker files beyond the produced/consumed move: rejected (Q3) -
  the move IS the marker; R3 negligible by ruling.

## References

- `hunting-orchestrator-memory-workflow-adr.md` (grill dispositions G1-G14 + operator
  corrections; the produced/consumed topology and HuntConfig rework).
- `hunting-memory-system-spec.md` (the replicated memory topology; G4 config naming,
  G5 status lifecycle, G11 `_seq`/`_ref` removal).
- `hunting-164-state-graph-spec.md` / `hunting-164-state-graph-adr.md` (the hunter
  StateGraph, spec identity `<fault>_<strategy>`, produced/consumed test-spec topology,
  `pending_verdicts` channel).
- `hunting-module-runtime-seam.md` (the sealed seam the wiring consumes).
- `hunting-pipeline-wiring-spec.md` (this workstream's spec, published as #169).