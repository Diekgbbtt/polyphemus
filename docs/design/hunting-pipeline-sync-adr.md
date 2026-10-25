# Hunting pipeline phase synchronisation - ADR

## Amendment 2026-10-25: impact-first elicitation

The threat-model impact-elicitation workstream supersedes the likelihood-only risk score and the failure-mode artifact in this document.
The decisions are in `docs/design/threat-model-impact-elicitation-adr.md`; the component map is `docs/design/threat-model-impact-elicitation-impact-map.md`.
Where this document and the amendment disagree, the amendment wins.

- A threat carries `VC`, `VI`, and `VA` plus a literal end impact. The store computes `impact = 1 - (1-VC)(1-VI)(1-VA)`, the ordinal weight, and `threat risk = likelihood_weight * impact_weight`.
- The ranking and the dispatch buckets use the combined risk. The run record carries `impact_weights` and `impact_breakdown`.
- The `failure_modes` artifact, `Threat.failure_mode_refs`, and the pod `failure-mode` variant basis are removed. The modeller no longer judges technical feasibility; the hunter and the pod own the effective attempt.
- The trust procedure uses the four axes `identity`, `spatial`, `temporal`, and `controls_semantics`.
- The well-formedness phase runs between `VULNERABILITIES_WRITTEN` and `COMPLETED`. Its exit is one `wellformedness` note plus the `COMPLETED` write; a lower-gate write is the re-entry signal.
- Every vulnerability binds a suite class parent or leaf. Technique families are not classes. `suite_gap` is removed. Class findings are non-blocking.


*Status: decided (2026-10-22), built (2026-10-23). Spec: `docs/design/hunting-pipeline-sync-spec.md`; assertions: `docs/design/hunting-pipeline-sync-assertions.md`.*
*Extends: `hunting-pipeline-wiring-adr.md` (the run-scoped inbox surfer, ADR #169/T4), `unit-threat-model-ordering-halt-adr.md` (the risk budget and the halt).*
*Decision owner: operator. Grilled and settled 2026-10-22; every decision below is operator-ratified.*

## Problem

The pipeline wiring T4 interleaves the hunting phases: `start_hunting` schedules the
threat-modeller pass and the run-scoped surfer as two independent sessions, and the surfer
dispatches one hunter per produced threat file while the pass models the next unit (S1 7.3).
There is no phase barrier anywhere.
A deployed run therefore fans out hunters over every threat the modeller has already produced,
and every hunter fans out pods over every `ratified` spec, regardless of what the other
phases are doing.
The operator wants the phases synchronisable per project: controllable burst shape, bounded
downstream fan-out, and a dispatch order the operator can reason about.
It must remain an extension of the current control plane, never a refactor of it.

## Decision

### 1. The sync mode is a project-level configuration

- The configuration attribute is `hunting_pipeline_sync`.
- It is a string enum with exactly the values `serial | batched | parallel`.
- The default is `batched`.

Storage: a new `hunting` JSONB column on the existing `settings` table, sibling of `recon`
(upserted with the same deep-merge discipline as `save_settings`, so a partial write never
drops siblings).
pg accessors mirror the settings pair: `get_hunting_settings(project_id)` /
`save_hunting_settings(project_id, body)`.
The `hunting` blob also lifts the threat-modeller budget into it: a stored `risk_threshold`
OVERRIDES the `HUNT_RISK_THRESHOLD` environment variable when set (the env stays the
fallback), and `threshold_config()` gains the resulting `db` basis value next to
`default`/`override`.
(Verified fact at decision time: no hunting settings area existed; `settings` carried only
the `recon` column, and the budget was env-only.)

API surface (`project_management/api.py`): `GET /projects/{project_id}/hunting/config` and
`PUT /projects/{project_id}/hunting/config`, typed pydantic body, validated enum, 404 on an
unknown project.
The endpoints read and write the project's `settings.hunting` blob only; they never touch a
live run.

Resolution timing: `start_hunting` reads the mode ONCE at run start and freezes it for the
run's whole lifetime, like the intake freeze (S1 7.1).
The frozen value is recorded on the run row's `stats` for observability.
A mid-run `PUT` therefore affects future runs only; a running pipeline is never
half-re-synchronised.
The next releases may migrate the config to richer shapes without touching the mode
vocabulary itself.

### 2. The three modes

**`parallel`** - today's behavior, byte-for-byte unchanged: the S1 7.3 interleave, the S2 8.3
low-tier sequencing, and the shared dispatch gate width bound.
The policy implementation is a no-op.

**`batched`** - phase barriers BETWEEN phases, concurrency inside a phase:

1. The modeller pass runs the intake ONE UNIT AT A TIME until the risk budget is fully
   consumed - the pass settles on the halt (with its `blocked_unit`, S1 7.4) or on intake
   exhaustion, exactly as today.
   Nothing downstream dispatches while the pass session is live.
2. When the pass settles, the surfer builds the dispatch queue: the run's units sorted by
   their model's risk contribution (`model_sum`, the run record's own figures) DESCENDING,
   ties broken by intake position ASCENDING.
   The halt never influences the queue order beyond freezing the pass (the halt never
   re-sorts, S1 7.4).
3. Per unit, in queue order: ONE BATCH of hunters, one hunter per produced threat file of that
   unit, dispatched CONCURRENTLY (each still bounded by the shared `HUNTING_DISPATCH_GATE_WIDTH`
   gate).
   The batch is the unit's whole threat set; the low-tier sequencing (S2 8.3) is subsumed and
   does not order a batch.
4. The batch advances only when every hunt of the batch is terminal (signals in section 3).
5. Then the unit's pods: one pod per `ratified` spec of the batch, dispatched CONCURRENTLY
   (same gate bound).
   The pod phase advances only when every pod is terminal.
6. The queue cursor moves to the next unit and the batch threat repeats, until the queue is
   exhausted and the run quiesces as today (`is_run_quiesced`, unchanged).

**`serial`** - the same queue, strictly one agent at a time:

1. The modeller phase is identical to `batched` (full risk budget first).
2. Intra-unit hunters are dispatched SEQUENTIALLY: hunter N+1 is dispatched only after
   hunter N completed AND every downstream pod that consumed the `TestImplementationSpec`s of
   hunter N has reached its terminal.
3. Pods are dispatched SEQUENTIALLY within a hunt: one pod is dispatched only once the
   previous one has completed.
   The pod cursor order is deterministic and re-derivable: the spec files sorted by file stem
   (`<fault>_<strategy>`); the order is cosmetic (all pods must complete before the cursor
   advances anyway), never a priority claim.
4. After the unit's last hunt and its pod chain finish, the cursor moves to the next unit.

### 3. The gate signals (unchanged completion semantics)

Every gate transition consumes the SAME completion signals the run already owns, all
storage-backed or registry-backed; no new artifact kind is introduced.
"Fully specified or in ratified status depending on the artifact itself" stays the rule.

- Modeller phase end: the modeller pass session is settled in the registry (its
  `threat-modeller` session id is gone), which covers both the halt and intake exhaustion.
- Hunter terminal: the hunt session has left its ReAct graph (`hunters_in_graph` no longer
  holds it) AND its consumed-threat recovery is settled. On this trunk the produced->consumed
  move is only ADMISSION: F-022 recovers a consumed threat whose hunter left no current-run
  `terminal.yaml` set, so a hunt that ends without finalizing (a builder failure, a
  non-provider harness degrade, or a transiently failed child) reappears as a pending threat
  item. The gate therefore keeps that hunt in the hunt phase (batched) or at the cursor
  (serial) and the item re-dispatches; F-026 defers a transient provider failure per child
  until its backoff elapses, and the batch/cursor holds meanwhile. A normal completion
  finalizes the terminal set (a zero-spec set is valid), so nothing is recovered and the
  hunt is done.
  A fatal provider failure (quota exhaustion or three consecutive transient failures of one
  child) raises `provider_failure` and pauses the run (`interrupted`) through the existing
  #331 handler; it never reads as terminal.
- Pod terminal: the durable parent-keyed PodExport record exists for the spec (the ADR #169
  Q16 amendment record authored at pod completion) - a `successful`/`unsuccessful` verdict,
  the fail-open degraded export (`surfer-dispatch-degraded`), or any terminal export record
  credits completion.
  A pod still executing keeps its unit current; a transiently failed pod has no export, so
  F-017 recovers its spec and the mover re-dispatches it after the per-child backoff - the
  pod cursor holds meanwhile.
- A batch (or the serial cursor) with an EMPTY member set advances immediately: a zero-threat
  unit skips hunting, a hunt with zero `ratified` specs skips the pod phase.
- Empty-unit cases therefore never wedge the queue; a degraded hunt holds its unit until a
  retry finalizes, which is the trunk's existing at-least-once resilience, not a new hold.

### 3a. Spec-lifecycle completion amendment (2026-10-24)

The serial cursor has three distinct sets; it must not collapse them:

- **Pending admission:** produced `ratified` specs. These are pod-dispatchable to the mover;
  the mover moves one to consumed at admission.
- **Completion set:** consumed `ratified` specs. Each must carry a durable `PodExport`
  (`successful`, `unsuccessful`, or the fail-open `surfer-dispatch-degraded` export) or an
  equivalent terminal/degraded state.
- **Decided:** produced `dropped` specs. They are terminal by decision and never need an
  export.

A hunt is done only when the run-scoped hunter terminal marker (`terminal.yaml`, with this
run's id) exists, no produced `ratified` spec remains pending, and every consumed `ratified`
spec has a terminal export. A stale `hypothesised` spec, an unreadable/malformed body, or a
missing terminal marker blocks the hunt and its unit; it is never silently skipped. An
unknown blocked unit sorts ahead of the known queue so the queue fails closed.

The surfer's `surfer-dispatch-degraded` path persists its degraded envelope as the durable
`PodExport` before the serial gate reads completion. At the hunter graph COMPLETE, the
settle hook declasses any produced `hypothesised` spec to `dropped` and writes the terminal
marker; an undecided draft can therefore not wedge a completed hunt. The surfer's quiesce
audit (`hunting_artifacts_terminal`) blocks `complete` while any current-run malformed,
stale, pending, or export-less artifact remains, even when the mover has no dispatchable
item. The upstream write-time validation, structured draft threat, consumed-transition
ownership, and run-record blocked state are ticket #401; the gate-side hold is a safety
net, not the repair.

### 4. The slim sync ledger (component shape)

One new module, `attack/hunting/pipeline_sync.py`, clean separation of concerns:

- `SyncMode` - the frozen enum (`serial` / `batched` / `parallel`) and `resolve_mode`.
- The PURE surface - `SyncFacts` (the storage/registry snapshot), `UnitMeta`, `BatchState`
  (the derived per-unit phase snapshot: `hunt`/`pod`/`serial`/`done`, the rank-ordered hunts,
  the serial cursor and pod cursor), `order_units`, `batch_state`, and
  `decide(mode, items, units, facts) -> frozenset[message_id]`, which dispatches to the
  batched/serial rule bodies.
- `PipelineSyncState` - the run-local ledger: the frozen mode, the intake-order source, and
  the per-unit metadata cache. It is in-memory and run-scoped, living beside
  `RunDispatchState`; the single worker thread stands, so no lock.
- `RunSyncGate` - the impure adapter (`make_sync_gate`, None for `parallel`) that gathers the
  facts from the stores and the session registry and applies `decide`.

Wiring: the ledger is consulted at the TWO existing dispatch seams only.

- `build_run_dispatch`'s `coro_for` asks the policy before it builds a hunter or pod
  coroutine; a policy refusal answers `None` (the mover's `None`-means-refused rule), which
  leaves the threat file / spec in produced for the next tick (at-least-once, never dropped).
- `sequence_dispatch` (or the equivalent pre-deduction filter) is extended so the quiesce
  read and the dispatch decision can still never disagree: a held item is produced work, and
  `run_work_remaining` keeps counting it until dispatch or quiesce - the existing contract.

The surfer keeps ticking unchanged; the mover protocol, the stores, the quiesce
predicate, and the at-least-once ring are untouched.
No new session is scheduled; the ledger is not a runtime entity, it is state the existing
surfer and builders read.
A handful of small state classes (`BatchState`, the phase cursors) ride the module.

### 5. Resume and interruption

The ledger holds NO durable state.
Every gate decision re-derives from stored facts (the produced/consumed threat files and model
documents, the spec statuses, the durable PodExport records) plus registry liveness.
A resumed run therefore rebuilds the queue and applies its cursor to already-terminal work:
modelled units that never dispatched (the provider-pause case), completed batches, and
delivered exports are all recognised, and the cursor lands on the first unfinished phase.
Stop / interrupted / resume semantics are otherwise untouched (#331 stop-only, the operator
resume verb T11 #398).

## Explicitly unchanged

- The completion signals themselves (the hunt's graph exit, the terminal spec-set statuses,
  the PodExport records) and the F-017 consumed-spec / F-022 consumed-threat recovery with the
  F-026 per-child transient retry. The gate reads those signals; it never changes them.
- The agent sub-module role gates (#317) and the module dispatch gate width (Q15): the
  policy refusals layer ON TOP, and a stopped role still refuses before the policy is asked.
- The singular launches (`launch_modeller`, the pod resume verb): they carry no surfer and
  are unaffected by the mode.
- The verdict stub (Q16): pod exports stay consume-and-record only; the mode does not feed
  any re-evaluation.
- `report_dispatch_gap` remains the terminal diagnostic for runs that produced models but
  dispatched nothing.
- A transient provider requeue still pauses only its child, never the phase it sits in.

## Alternatives considered

- Persisting the ledger (queue position, per-member completion) durably: rejected - every
  input of the gate is storage-backed, so a durable ledger would be a second record of
  derived state that can contradict the stores.
- Gating inside the mover's pure deduction only: rejected - the deduction is pure and the
  gate needs registry liveness plus the policy object; the seams (`coro_for` / the
  sequencing filter consulted per tick with the live state) already carry both.
- Reading the mode live per tick: rejected - a mid-run flip could half-re-synchronise a
  running pipeline; the freeze makes the run's semantics total.

## Consequences

- In `batched`/`serial`, produced threat files accumulate while the modeller pass runs; every
  tick the held items count as `paused` on the `TickReport` (they stay produced, never
  dropped), and logs are bounded by the existing log-once discipline.
- A long silent stretch between run start and the first hunter dispatch is EXPECTED in
  `batched`/`serial` (the whole risk budget is modelled first); operators read the run
  record's `stats` rather than judging liveness by dispatch activity.
- The `parallel` default of the past is now opt-in; `batched` is the new default.

## Known issue: cross-unit tier hold in `serial`

The S2 8.3 tier ordering is global over the run's produced threat files, and
`serial` still applies it.
The queue admits only the current unit, so a `low` threat of the current unit is
held while ANY unit's higher-tier threat is produced.
Those higher-tier threats cannot consume until their own unit is current, which is
after the current unit finishes.
A current unit whose only remaining threats are `low` therefore cannot progress,
and the run wedges on produced work.

`batched` is unaffected: the tier ordering is subsumed and does not order a
batch (section 2).
The `serial` fix is a product decision:

- scope the tier check to the current unit's threat set (the natural reading under
  a unit-serialising queue), or
- drop the tier ordering in `serial` as well and let the cursor own the order.

Until that decision lands, do not run `serial` on a unit whose only remaining
threats are `low` while a later unit still has produced medium/high threats.

## The stall fail-safes (2026-10-25)

The tier hold above is a sequencing defect.
Two lifecycle fail-safes bound the OTHER stall classes:

- **The per-session watchdog.** `RunDispatchState.session_timeout_s` (default
  2700 seconds) wraps each hunter and pod graph.
  A hunter past its window releases its registration and settles its drafts; a
  pod past its window writes a `budget-timeout` PodExport.
  The queue advances from storage, not from a transient registry fact.
- **The malformed fail-safe.** A produced body the store cannot parse is
  dispatched as a degraded pod, consumed, and closed by its PodExport.
  It is never left produced to hold the queue.

The comparison and the risk table are in
`docs/design/hunting-lifecycle-failsafe.md`.
The lower control plane's thread state was not used: it needs a second source
of truth and a worker-thread-to-hunt mapping, while the watchdog is local to
the dispatched coroutine and leaves a durable degraded record.
