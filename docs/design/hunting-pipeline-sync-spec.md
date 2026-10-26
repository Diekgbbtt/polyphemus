# Hunting pipeline synchronisation - spec

*Status: built (2026-10-23); amended (2026-10-26) for the configurable pod batch and the
per-threat promotion threshold. Decision record: `docs/design/hunting-pipeline-sync-adr.md`.
Batch and promotion contract: `docs/design/hunting-batch-and-promotion-spec.md`.
Assertion catalogue: `docs/design/hunting-pipeline-sync-assertions.md`.*
*Extends the run-scoped surfer of `hunting-pipeline-wiring-adr.md` (#169/T4) and the risk halt of `unit-threat-model-ordering-halt-adr.md`.*

## The configuration

- Attribute: `hunting_pipeline_sync`, a string enum `serial | batched | parallel`.
- Default: `batched`.
- Storage: the `settings.hunting` JSONB column (`db/postgres/init.sql`), sibling of `settings.recon`, upserted with the same recursive deep merge.
- Accessors: `pg.get_hunting_settings(project_id)` / `pg.save_hunting_settings(project_id, body)`.
- REST: `GET /projects/{project_id}/hunting/config` and `PUT /projects/{project_id}/hunting/config`.
  - GET returns `{"pipeline_sync": <mode>, "risk_threshold": <int|null>, "pod_batch_size": <int>, "promotion_risk_threshold": <int|null>}`; an unknown project is a 404; an unset project reads the defaults.
  - PUT accepts a partial body (`pipeline_sync`, `risk_threshold`, `pod_batch_size`, `promotion_risk_threshold`), `extra="forbid"`, and merges only the provided keys.
- The same blob carries `risk_threshold`: it overrides `HUNT_RISK_THRESHOLD` when set (basis `db`), and `null` clears the override.
- The same blob carries `pod_batch_size` (integer at least 1, default 1) and `promotion_risk_threshold` (integer at least 0 or `null`, default `null`). Neither has an environment fallback. A malformed stored value reads back the default with a warning. See `docs/design/hunting-batch-and-promotion-spec.md`.

## The freeze

`start_hunting` resolves the mode once: the run record's `pipeline_sync` on a resume, else the project setting, else `batched` (`pipeline_sync.resolve_mode`).
It resolves `pod_batch_size` and `promotion_risk_threshold` the same way: the run record first, then the project setting, then the defaults (1 and `null`).
The resolved values are stamped on every run-record write (`hunting_runs.stats.pipeline_sync`, `.pod_batch_size`, `.promotion_risk_threshold`), and a mid-run PUT affects future runs only.

## The modes

- `parallel` - the historical behaviour: the modeller pass and the surfer interleave, the surfer dispatches every produced item as it appears, and the S2 8.3 low-tier sequencing bounds the order. No gate is built.
- `batched` - phase barriers between phases, concurrency inside a phase:
  1. the modeller pass consumes the whole risk budget first (halt or intake exhaustion);
  2. the queue: the run's units sorted by model risk contribution (`model_sum`-equivalent threat weights) descending, ties by intake position ascending, then unit name;
  3. per unit: the whole hunter batch concurrently (one hunter per promoted produced threat file, bounded by `HUNTING_DISPATCH_GATE_WIDTH`);
  4. the batch advances when every hunt of the unit is terminal (see the gate signals);
  5. then the unit's pods in fixed blocks of `pod_batch_size` hunts in threat-rank order (default 1):
     every `ratified` spec of every hunt in the current block concurrently (one pod per spec),
     and the next block only when every pod of every hunt in the current block is terminal;
  6. the next unit starts only when every hunt's pods are terminal;
  7. an empty member set (a zero-threat unit, a zero-`ratified` hunt) advances immediately.
- `serial` - the same queue strictly one agent at a time:
  1. intra-unit hunters are sequential: hunter N+1 dispatches only after hunter N is terminal AND every pod that consumed hunter N's spec set reached a terminal export;
  2. the pods of one hunt are sequential in spec-stem order (`<fault>_<strategy>`), each one dispatched only after the previous stem carries a durable export;
  3. after the unit's last hunt and its pod chain, the cursor moves to the next unit.
  4. `pod_batch_size` does not apply; `serial` stays one hunter and one pod at a time.

### The promotion filter

The mover's produced-inbox read promotes only produced threats whose combined `risk` is at least
`promotion_risk_threshold` (inclusive; `null` or 0 means no filter).
A demoted threat stays in `produced/` as evidence and is not an item.
It is excluded from the hunter completion set, the dispatch work, and the run quiesce.
The unit model moves to `consumed/` once its promoted threats are done; the demoted files remain
in `produced/`.
Recovered consumed threats are never filtered.
The filter runs before the low-tier sequencing.
The full hunt list includes only promoted, dispatchable, observable hunts: a zero-risk threat has
no threat file (S2 8.3), and a refused threat has no observable artifact. Neither can hold the pod
phase.
A threat whose combined risk is unreadable is a refusal, never a demotion; the audit sees it
while the model is produced.
A refused threat file is not archived by the mover. It stays in `produced/`; once the unit
model moves to `consumed/`, it is an orphan and the produced-threat read no longer sees it.
`abandoned/` is the whole-unit archive for a stale produced model or a degraded or invalid
model, written by the intake freeze or the modeller, never by a mover refusal.
The gate's lifecycle read uses the same demoted-hunt resolution, so a leftover spec folder
cannot hold the pod phase after the model moves.
The threat modeller is not aware of the threshold; the unit risk budget and the queue order
still use every stored threat.

## The gate signals

- Modeller phase end: the `hunting:<run>:threat-modeller` session is settled (halt or exhausted).
- Hunter terminal: the hunt left its ReAct graph (`hunters_in_graph` no longer holds it) AND its consumed-threat recovery is settled. The move is only admission: F-022 recovers a consumed threat whose hunter left no current-run `terminal.yaml`, so a hunt that ended without finalizing (a degrade or a transiently failed child) reappears as a pending threat item and the phase holds while it re-dispatches; F-026 defers a transient provider failure per child until its backoff. A normal completion finalizes the set (zero-spec is valid) and is done.
- Pod terminal: the durable `PodExport` record exists for the spec (`pod_store.read_pod_export(stem, run_id)` truthy) - any verdict, or the degraded export. A transiently failed pod has no export, so F-017 recovers its spec and the cursor holds until the retry exports. A stopped pod has a resume cursor and no export; the cursor is not a terminal, and the next dispatch resumes from it.
- A pod still executing (`hunting:<run>:pod:<hunt>:<spec>` live) keeps its unit current.
- A demoted produced threat (combined `risk` below the frozen `promotion_risk_threshold`) is not
  work: it does not hold the hunter phase, the pod block, the unit queue, or the run quiesce.
- Every signal is storage- or registry-backed, so the gate re-derives on resume with no persisted ledger.

## The component

`attack/hunting/pipeline_sync.py`:

- `SyncMode` (`serial`/`batched`/`parallel`), `DEFAULT_SYNC_MODE = BATCHED`, `resolve_mode`.
- `DEFAULT_POD_BATCH_SIZE = 1`, `resolve_pod_batch_size`, `resolve_promotion_risk_threshold`.
- `threat_is_promoted(record, threshold)` - the ONE pure promotion predicate; the mover, the
  gate, the completion audit, and the dispatch-gap diagnostic share it.
- Pure surface: `UnitMeta`, `SyncFacts`, `order_units`, `unit_of_dispatch`, `unit_of_item`, `hunt_rank`, `current_unit`, `decide(mode, items, units, facts, pod_batch_size=1) -> frozenset[message_id]`.
- `BatchState` gains the current `pod_batch` block; the cursor and pod cursor stay for `serial`
  and for the batch's first unfinished hunt.
- Impure adapter: `RunSyncGate.filter(items, live_session_ids=..., hunts_in_graph=...)`, built by `make_sync_gate` (None for `parallel`).
  It reads the unit models for the queue risk, the run record's intake order for the tie-break, the spec stems and the durable exports for the pod block; the per-unit metadata is cached for the run's lifetime.
  It carries the frozen `pod_batch_size` and `promotion_risk_threshold`.
- State: `RunDispatchState.sync_gate` and `RunDispatchState.promotion_risk_threshold` (run-local, never durable, never a session).

## The seam

- `run_delivery_tick(..., pre_filter=..., promotion_risk_threshold=...)`: the filter runs after `sequence_dispatch` and before the pure deduction. A filtered item stays produced (at-least-once), counts as `paused`, and never reaches the control plane.
- The promotion threshold reaches `read_produced_inbox` from `run_delivery_tick` and `run_work_remaining`, so dispatch and quiesce see the same promoted item set.
- `run_surfer_loop` supplies `state.sync_gate.filter` once per tick with the live session set and the mid-graph hunt set.
- `run_work_remaining` / `is_run_quiesced` read the UNFILTERED inbox, so held items remain work and a run can never quiesce over a held item; a demoted threat is not in that inbox.
- `hunting_artifacts_terminal` ignores demoted produced threats. The dispatch-gap diagnostic counts only promoted produced threats.

## Impact map

- `db/postgres/init.sql` - the `settings.hunting` column.
- `src/polymerhus/app/clients/pg.py` - `get_hunting_settings` / `save_hunting_settings`.
- `src/polymerhus/project_management/repository.py` - `read_hunting_config` / `save_hunting_config` + the mode and batch-size vocabulary.
- `src/polymerhus/project_management/api.py` - `HuntingConfigUpdate`, the GET/PUT config routes, the batch-size and promotion-threshold validation.
- `src/polymerhus/attack/hunting/pipeline_sync.py` - the new module, the batch block, the promotion predicate, the resolvers.
- `src/polymerhus/attack/hunting/mover.py` - the `pre_filter` seam, the promotion filter in `read_produced_inbox`, the non-pending stems on the model consume.
- `src/polymerhus/attack/hunting/threat_model_store.py` - the model-consume primitive accepts non-pending stems.
- `src/polymerhus/attack/hunting/surfer.py` - `RunDispatchState.sync_gate`, `promotion_risk_threshold`, the per-tick filter, the quiesce threshold.
- `src/polymerhus/attack/hunting/runtime.py` - the mode and setting resolution, the frozen stamp, the gate construction, the DB-first threshold read, the dispatch-gap threshold.
- `src/polymerhus/attack/hunting/run_lifecycle.py` - `threshold_config(db_value=...)`, basis `db` (unchanged for the promotion threshold, which is DB-only).

## Out of scope

- The verdict-processing workflow (pod exports stay consume-and-record only).
- A durable sync ledger (the gate re-derives).
- The singular launches (`launch_modeller`, the pod resume verb): no surfer, no mode effect.
- The auto-resume health checker.
- A per-target pod concurrency cap (ticket 433 rejected).
- A batch-scoped watchdog.
- A change to the risk halt, the unit queue order, or the threat modeller schema.
- A new store family for demoted threats.
- A migration of old runs.
