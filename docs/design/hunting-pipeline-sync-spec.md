# Hunting pipeline synchronisation - spec

*Status: built (2026-10-23). Decision record: `docs/design/hunting-pipeline-sync-adr.md`.
Assertion catalogue: `docs/design/hunting-pipeline-sync-assertions.md`.*
*Extends the run-scoped surfer of `hunting-pipeline-wiring-adr.md` (#169/T4) and the risk halt of `unit-threat-model-ordering-halt-adr.md`.*

## The configuration

- Attribute: `hunting_pipeline_sync`, a string enum `serial | batched | parallel`.
- Default: `batched`.
- Storage: the `settings.hunting` JSONB column (`db/postgres/init.sql`), sibling of `settings.recon`, upserted with the same recursive deep merge.
- Accessors: `pg.get_hunting_settings(project_id)` / `pg.save_hunting_settings(project_id, body)`.
- REST: `GET /projects/{project_id}/hunting/config` and `PUT /projects/{project_id}/hunting/config`.
  - GET returns `{"pipeline_sync": <mode>, "risk_threshold": <int|null>}`; an unknown project is a 404; an unset project reads the defaults.
  - PUT accepts a partial body (`pipeline_sync`, `risk_threshold`), `extra="forbid"`, and merges only the provided keys.
- The same blob carries `risk_threshold`: it overrides `HUNT_RISK_THRESHOLD` when set (basis `db`), and `null` clears the override.

## The freeze

`start_hunting` resolves the mode once: the run record's `pipeline_sync` on a resume, else the project setting, else `batched` (`pipeline_sync.resolve_mode`).
The resolved mode is stamped on every run-record write (`hunting_runs.stats.pipeline_sync`), and a mid-run PUT affects future runs only.

## The modes

- `parallel` - the historical behaviour: the modeller pass and the surfer interleave, the surfer dispatches every produced item as it appears, and the S2 8.3 low-tier sequencing bounds the order. No gate is built.
- `batched` - phase barriers between phases, concurrency inside a phase:
  1. the modeller pass consumes the whole risk budget first (halt or intake exhaustion);
  2. the queue: the run's units sorted by model risk contribution (`model_sum`-equivalent loop weights) descending, ties by intake position ascending, then unit name;
  3. per unit: the whole hunter batch concurrently (one hunter per produced loop file, bounded by `HUNTING_DISPATCH_GATE_WIDTH`);
  4. the batch advances when every hunt of the unit is terminal (see the gate signals);
  5. then the unit's pods concurrently, one per `ratified` spec;
  6. the next unit starts only when the current unit's pods are all terminal;
  7. an empty member set (a zero-loop unit, a zero-`ratified` hunt) advances immediately.
- `serial` - the same queue strictly one agent at a time:
  1. intra-unit hunters are sequential: hunter N+1 dispatches only after hunter N is terminal AND every pod that consumed hunter N's spec set reached a terminal export;
  2. the pods of one hunt are sequential in spec-stem order (`<fault>_<strategy>`), each one dispatched only after the previous stem carries a durable export;
  3. after the unit's last hunt and its pod chain, the cursor moves to the next unit.

## The gate signals

- Modeller phase end: the `hunting:<run>:threat-modeller` session is settled (halt or exhausted).
- Hunter terminal: the hunt left its ReAct graph (`hunters_in_graph` no longer holds it). A hunt that produced no terminal set (a degraded fail-open hunt) authors nothing more and reads as done; its loop file was consumed at admission.
- Pod terminal: the durable `PodExport` record exists for the spec (`pod_store.read_pod_export(stem, run_id)` truthy) - any verdict, or the degraded export.
- A pod still executing (`hunting:<run>:pod:<hunt>:<spec>` live) keeps its unit current.
- Every signal is storage- or registry-backed, so the gate re-derives on resume with no persisted ledger.

## The component

`attack/hunting/pipeline_sync.py`:

- `SyncMode` (`serial`/`batched`/`parallel`), `DEFAULT_SYNC_MODE = BATCHED`, `resolve_mode`.
- Pure surface: `UnitMeta`, `SyncFacts`, `order_units`, `unit_of_dispatch`, `unit_of_item`, `hunt_rank`, `current_unit`, `decide(mode, items, units, facts) -> frozenset[message_id]`.
- Impure adapter: `RunSyncGate.filter(items, live_session_ids=..., hunts_in_graph=...)`, built by `make_sync_gate` (None for `parallel`).
  It reads the unit models for the queue risk, the run record's intake order for the tie-break, the spec stems and the durable exports for the serial cursor; the per-unit metadata is cached for the run's lifetime.
- State: `RunDispatchState.sync_gate` (run-local, never durable, never a session).

## The seam

- `run_delivery_tick(..., pre_filter=...)`: the filter runs after `sequence_dispatch` and before the pure deduction. A filtered item stays produced (at-least-once), counts as `paused`, and never reaches the control plane.
- `run_surfer_loop` supplies `state.sync_gate.filter` once per tick with the live session set and the mid-graph hunt set.
- `run_work_remaining` / `is_run_quiesced` read the UNFILTERED inbox, so held items remain work and a run can never quiesce over a held item.

## Impact map

- `db/postgres/init.sql` - the `settings.hunting` column.
- `src/polymerhus/app/clients/pg.py` - `get_hunting_settings` / `save_hunting_settings`.
- `src/polymerhus/project_management/repository.py` - `read_hunting_config` / `save_hunting_config` + the mode vocabulary.
- `src/polymerhus/project_management/api.py` - `HuntingConfigUpdate`, the GET/PUT config routes.
- `src/polymerhus/attack/hunting/pipeline_sync.py` - the new module.
- `src/polymerhus/attack/hunting/mover.py` - the `pre_filter` seam.
- `src/polymerhus/attack/hunting/surfer.py` - `RunDispatchState.sync_gate`, the per-tick filter.
- `src/polymerhus/attack/hunting/runtime.py` - the mode resolution, the frozen stamp, the gate construction, the DB-first threshold read.
- `src/polymerhus/attack/hunting/run_lifecycle.py` - `threshold_config(db_value=...)`, basis `db`.

## Out of scope

- The verdict-processing workflow (pod exports stay consume-and-record only).
- A durable sync ledger (the gate re-derives).
- The singular launches (`launch_modeller`, the pod resume verb): no surfer, no mode effect.
- The auto-resume health checker.
