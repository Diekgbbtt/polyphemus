# Hunting pipeline wiring: produced/consumed inbox surfer, per-session runtime lifecycle, and the REST launch surface

*Status: spec (contract). Resolved by the 2026-08-23/24 grilling (`hunting-pipeline-wiring-adr.md`), published as spec #169 with wiring tickets #170-#175. Operates on the ratified memory topology (`hunting-memory-system-spec.md`, tickets #165-#168) and the 164 state-graph hunter (#164). Sequencing per Q18-A / ADR: implementation is held off until the produced/consumed topology lands. AMENDED 2026-08-25 by the identity-based surfer refactor: config_key canonical identity, own-status dispatch gate, durable parent-keyed export record, and the pod-only launch resume-by-coroutine-id ruling.*

## Problem Statement

The hunting pipeline is fragmented across refactor branches and un-wired. The hunt-orchestrator produces `HuntConfig`s, hunting agents consume them and produce `TestImplementationSpec`s, and test-executor pods consume those. Each component is an actor with a mailbox, but there is no end-to-end message-passing engine connecting them, no coherent way to launch the pipeline as a whole, and no way to launch a single component on its own. The runtime and session machinery exists (`RuntimeManager`, `AgentInbox`, the typed session addresses); the glue does not.

## Solution

Wire the three components into one coherent pipeline behind a run-scoped **inbox surfer**: a dumb mover that checks each memory family's `produced/` directory, asks the runtime control plane to dispatch the correct new agent session, and on correct dispatch feedback moves the message to `consumed/`. An agent, at the end of its workflow graph, enters an idle state - a simple loop iteratively reading its inbox (NOT checkpoint-resume mechanisation). Whole-pipeline and per-component launch become available over the app REST surface, consistent with the sealed `hunting-module-runtime-seam` contract.

## User Stories

1. As an operator, I want to launch a whole hunting run with one request, so that the orchestrator, its hunters, and their pods execute together under one `hunting_run_id`.
2. As an operator, I want the run's orchestrator to produce ratified hunt configs and dispatch one hunter per config, so that each research direction becomes an independent hunting agent.
3. As an operator, I want each hunter to ratify test-implementation specs and dispatch a test-executor pod per spec, so that testing is parallelised across the fan-out.
4. As an operator, I want each pod's experiment log handed back to its hunter through the same produced/consumed mechanism, so that evidence flows back on the same rails dispatch flows forward.
5. As an operator, I want to launch a single component (orchestrator only, hunter only, pod only) through the same REST surface as the whole pipeline, so that a partial stage can be exercised and debugged alone.
6. As an operator, I want every individual agent session (orchestrator, a specific hunter, a specific pod) individually addressable for pause, resume, and stop, so that one stuck or costly session does not force a whole-run stop.
7. As an operator, I want the shared runtime control plane to hold each session's full lifecycle (its coroutine and registry), keyed by the session id, so that lifecycle logic lives in exactly one place.
8. As an operator, I want the dispatch fan-out bounded by one configurable width, so that the shared executor and provider are never over-run.
9. As an operator, I want the produced->consumed transition to be at-least-once: a dispatch refused by admission is retried, never dropped.
10. As an operator, I want a second hunting run on the same project refused while one is live, so that two runs never race on the same produced/consumed directories.
11. As an operator, I want the run to reach a terminal status only when all its components have settled, so that a `complete` status never masks in-flight work.
12. As an operator, I want stop to cancel every session of the run through the shared control plane, so that a stop leaves no orphaned hunter or pod coroutine.
13. As an operator, I want the server to refuse a replayed launch trigger, so that duplicate requests cannot double-dispatch agents.
14. As a hunter, I want to enter an idle loop reading my inbox after my workflow graph ends, so that I can receive later messages without resume mechanisation.
15. As an operator, I want the pod->hunter verdict processing workflow stubbed for now (consume and record, no re-evaluation), so that the wiring is provable before the verdict semantics are finalised.

## Implementation Decisions

### Architecture

- **One run-scoped inbox surfer per hunting run**, spawned by the run bootstrap and reaped at run terminal. It checks inboxes (the memory families' `produced/` directories), asks the runtime control plane to dispatch agents, and on correct dispatch feedback moves messages `produced -> consumed`. It is a pure mover: it does not reason, it does not own lifecycle, and it never dispatch-gates admission.
- **The shared runtime manager is the control plane** (ADR Q12). The hunting module does NOT build a second control-plane component. The shared `RuntimeManager` is extended with per-session lifecycle on its run registry: an individual registered run may be held (paused), resumed, and cancelled by its session id, in addition to the existing module-level pause/resume/drain. Each session's id equals its coroutine id equals its registry run name.
- **One live hunting run per project**: a second launch against a project with a live run is refused. This makes the per-project produced/consumed directories single-owner.
- **Dispatch gate width**: a configurable width, default 20, bounds the number of concurrently running hunting agent sessions per project. The only further bound is the process's shared executor and worker loop (the operator's ruling: no per-run fan-out cap beyond the gate and the pod-internal caps).

### Session id scheme and addressing

- Orchestrator session id: `hunting:<run_id>:orchestrator`.
- Hunter session id: `hunting:<run_id>:hunt:<config_id>`.
- Pod session id: `hunting:<run_id>:pod:<config_id>:<spec_id>`.
- `config_id` is the semantic hunt-config file name `<unit_id>_<CWE_ID>_<fault_class(vulnerability)>` (memory-system G4) - the `_`-joined fault_key folder.
- **Canonical identity (identity-based refactor, 2026-08-25):** the ONE cross-family join key is the semantic `config_key` (`<unit_id>::<CWE_ID>::<vulnerability>`, round-tripped by `HuntStore.semantic_key` and the `test-specs` folder's recovering parser). `hunter_inboxes` is keyed by `config_key` on BOTH register (hunter dispatch) and lookup (pod dispatch) - the two sides of one join agree on the same canonical key.
- `spec_id` is the semantic spec file name `<fault>_<strategy>` (164 state-graph spec 6). This REPLACES the pod branch's `canonical_spec_id` canonical hash everywhere it was used for identity (hunt-session address spec discriminator, pod memory keying) - the pod implementation must be reconciled to the semantic spec id in this work.
- Session addresses derive from the memory-item keys (the config file name yields the hunter's hunt-id; the spec file name yields the pod's spec discriminator), so the surfer can construct them on the fly.
- Runtime registry lifecycles key on these same ids (session id = coroutine id).

### The inbox surfer semantics

- Surfer input surfaces: the memory families' `produced/` directories for the run's project (hunt configs, test specs, experiment logs).
- Dispatch protocol: for each produced item not yet dispatched, ask the control plane to dispatch the agent for its session id. On success feedback, move `produced -> consumed`. On refusal (gate full, module paused, run draining), leave the item in `produced/` and retry on the next tick - never dropped, at-least-once.
- **Dispatch gate (identity-based refactor, 2026-08-25):** an item's dispatchability is decided by ITS OWN persisted status (`ratified` config -> hunter, `specified` spec -> pod), never by a chain-adjacent agent's liveness. A produced `specified` spec whose parent config was consumed by an earlier run still dispatches in a later run; its export is recorded durably under the parent's `config_key` at pod completion (Q16 amendment), and the within-run hunter inbox delivery is an optional live feed for the future verdict node, never a gate.
- The mover logic is extracted as a pure deduction: given (produced set, session registry state, dispatch feedback) it returns (to dispatch, to move, to retry). The impure shell applies the moves and calls the control plane.
- The produced->consumed move IS the at-least-once marker (the memory-topology pattern, G13). The crash window between dispatch and move (R3) is accepted as negligible by ruling; double-dispatch is defended by the session registry state and the file-name novelty gate downstream.

### Agent idle state

- After an agent's workflow graph ends, it enters the idle state: a simple loop that iteratively reads its inbox, reusing the existing mailbox loop machinery. This is NOT checkpoint-resume mechanisation.
- The pod->hunter verdict handling (identity-based refactor, 2026-08-25): the DURABLE record is written at pod completion, keyed by the parent's `config_key` - crash-safe, independent of a live parent. The idle-loop inbox delivery is a within-run live feed for the future verdict-processing node (D67-02/D11/D67-14); consume-and-record only, no re-evaluation.

### Run lifecycle

- The run reaches a terminal status only when all its component sessions have settled (the orchestrator pass done, all hunters and pods settled, produced dirs quiesced). The run-terminal flush of the hunting checkpointer index fires at that point.
- Stop cancels every session of the run through the shared control plane (per-session cancel by id), then persists `stopped`. The per-run surfer is itself a session and is cancelled with the rest.
- Start/stop seam shapes are unchanged (the bootstrap coroutine and the stop handler keep their contracts; only their bodies change).
- A coroutine returning while the run is still mid-flight must never silently `interrupt` the run - that is a control-plane layer defect, addressed there, not here.

### REST surface

- Whole-pipeline launch: the existing hunting launch endpoint, unchanged shape, now wired through the surfer control plane.
- **Empty-candidates launch semantics (AMENDED by #200):** a launch with an omitted/empty `candidates` body is a MEANINGFUL pass - the platform runs its OWN FaultSource selection over the live L1 (the deterministic typed-applies-if stage + the enum-of-system-kinds tag + the pass-through match; FaultSource is an internal stage per the candidates-rewrite spec 4.1), and the pass reasons over the selected candidates. A caller-supplied batch stays the override, never re-selected. The selection summary (faults evaluated / units minted / pruned-by-predicate / pruned-by-tag / passed) is observable via `trace_gate_step` plus a log line, so an all-pruned empty launch is distinguishable from "nothing supplied and nothing ran".
- Singular component launches: one endpoint per component that enqueues into the component's handoff family and moves the component to dispatch. A singular launch never fabricates a chained-dependency error; the component consumes its inbox asynchronously.
- **Singular POD launch (identity-based refactor, 2026-08-25, operator ruling):** the pod-only endpoint does NOT fabricate a produced `specified` spec (the reviewer's ambiguity); it resumes ONE stored/paused pod session by posting its coroutine id. The whole-pod-component path remains the whole-pipeline run.
- Per-session lifecycle verbs: pause, resume, stop for a specific session id, under the project/hunting-run namespace, in addition to the existing module-wide lifecycle verbs.
- At-most-once on launch: the server tracks already-created run rows and refuses replayed triggers for the same id.
- All handlers stay in the thin HTTP adapter following the existing launch seam pattern; use-case and persistence stay in the repository plus the Postgres gateway. No new persistence surface beyond what the memory topology and the run row provide.

## Testing Decisions

- **What makes a good test**: assert external behaviour from the seams, never implementation internals. The mover is a pure function so its deduction is unit-tested in memory; the launch and lifecycle verbs are asserted through the HTTP adapter with a recording launcher stub, never a real boot; the whole pipeline is exercised through the run bootstrap coroutine with injected fakes for the agent work.
- **Production-code-first (identity-based refactor, 2026-08-25):** tests exercise the REAL mover + surfer `build_run_dispatch` path with production stores (temp roots), NOT a `_stub_coro` that bypasses the dispatch decision. The spec-family fixture uses the PRODUCTION `_`-joined fault_key folder convention (the two test files previously disagreed: T4-mover tests used `_`, the wiring test used `::` - masking the pod-dispatch miss). Fakes are minimised to the agent seams (hunter/pod builders) and the control plane; the stores, the mover, `run_work_remaining`, `is_run_quiesced`, and `build_run_dispatch` are the code under test.
- **Primary seam**: the run bootstrap coroutine - the whole pipeline is observable through it (orchestrator pass, produced/consumed movement, per-session dispatch, idle loops, run terminal, stop).
- **REST mirror seam**: the HTTP launcher seam - whole/singular launches and per-session lifecycle verbs asserted with a recording stub.
- **Unit seam**: the surfer mover as a pure function - produced set, registry state, feedback in; dispatch/move/retry deduction out.
- **Runtime seam**: the shared runtime manager's per-session lifecycle extension - hold/resume/cancel by session id at the runtime tier.
- Prior art: the existing orchestration/harness injection patterns (`run_orchestration`, `build_hunting_agent`), the curator pure-builder/impure-orchestrator split, the launch-seam recorder tests in the HTTP adapter tier.
- The verdict-processing stub is tested only to the extent of "consume and record" - no verdict semantics beyond that.

## Out of Scope

- The verdict-processing workflow semantics (ADR Q16-stubbed; a separate ticket owns the real handling).
- The memory-system implementation itself (tickets #165-#168 deliver the produced/consumed topology this spec operates on).
- The 164 state-graph hunter internals (#164 owns the graph, tools, and lifecycle).
- The candidates-rewrite orchestrator rework internals (its own ticket).
- The test-executor pod beyond the reconciliation to the semantic spec id.
- Graceful stop / finish-pass degradation (a separate ticket per the seam).
- The recon and analysis modules; the exploit submodule.
- Any new persistence surface beyond the memory topology and the run row.

## Further Notes

- Sequencing (ADR Q18-A) is strict: implementation is held off until the produced/consumed memory topology lands on the wiring base (blocked by #165, #166, #167, #168) and the reconciled component branches (164 state-graph #164, test-executor pod, candidates-rewrite) are merged in order.
- Integration strategy (ADR Q1): a dedicated integration worktree branched from `dev`; feature branches merged in sequence; the wiring commits are authoritative there.
- Reconciliation item: the pod's spec identity moves from the canonical hash to `<fault>_<strategy>`; the pod's session-address spec discriminator and pod-memory keys follow the semantic spec id (see Implementation Decisions).
- Run-scoped per-project topology means exactly one live hunting run per project (see User Story 10), enforced at launch and relied on by the produced/consumed single-ownership rule.

## References

- `hunting-pipeline-wiring-adr.md` - the grilling dispositions this spec implements.
- `hunting-module-runtime-seam.md` - the sealed seam contract.
- `hunting-memory-system-spec.md` and `hunting-orchestrator-memory-workflow-adr.md` - the topologies and lifecycle the wiring operates on.
- `hunting-164-state-graph-spec.md` and `hunting-164-state-graph-adr.md` - the hunter StateGraph and the spec identity/`pending_verdicts` channel.
- Tracker: spec #169; wiring tickets #170-#175.