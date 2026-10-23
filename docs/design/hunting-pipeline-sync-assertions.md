# Assertion catalogue - hunting pipeline synchronisation

**Scope:** `hunting_pipeline_sync` (`serial | batched | parallel`, default `batched`), spec `docs/design/hunting-pipeline-sync-spec.md`, ADR `docs/design/hunting-pipeline-sync-adr.md` (2026-10-22).
**Seams under assertion:** the project settings surface (`project_management/api.py`, `repository.py`, `app/clients/pg.py`), the run bootstrap (`attack/hunting/runtime.py`), the sync gate (`attack/hunting/pipeline_sync.py`), the mover tick (`attack/hunting/mover.py`), the surfer loop (`attack/hunting/surfer.py`).

## The mode state machine (the model under test)

For one run, `mode = resolve_mode(record.stats.pipeline_sync, settings.hunting)`, frozen at boot.

| mode | phase gate | order | concurrency |
|---|---|---|---|
| parallel | none (historical) | produced order + S2 8.3 tiering | every item as it appears |
| batched | modeller settled; per-unit hunt phase then pod phase | units by model risk desc, intake position, name; loops by rank | whole batch / whole pod set |
| serial | modeller settled; cursor hunt fully done before the next | same queue; pods by spec stem | one hunter, one pod |

Gate signals: modeller session settled; hunter = left its graph; pod = durable PodExport exists; a live pod keeps its unit current.

## Contract predicates (unit + integration tier)

Each predicate names its executable test.

| id | predicate | test |
|---|---|---|
| C1 | The mode enum is exactly `serial`/`batched`/`parallel`; the default is `batched`. | `tests/attack/test_hunting_pipeline_sync.py::test_sync_mode_values_and_default` |
| C2 | `resolve_mode` prefers the run record, then the setting, then the default; an unknown value falls through. | `...::test_resolve_mode_prefers_the_run_record_then_the_settings_then_the_default` |
| C3 | The queue orders by risk contribution DESC, intake position ASC, unit name ASC. | `...::test_order_units_is_risk_desc_then_intake_position_then_name` |
| C4 | While the modeller pass is live, no item is admissible in `batched` or `serial`. | `...::test_modeller_live_holds_every_item` |
| C5 | `batched` admits the whole unit hunter batch and refuses the unit's pods while a loop file remains or a hunt is mid-graph. | `...::test_batched_admits_the_whole_unit_hunter_batch`, `...::test_batched_refuses_pods_while_a_hunt_file_remains`, `...::test_batched_refuses_pods_while_a_hunt_is_mid_graph` |
| C6 | `batched` admits the unit's pods after the hunt batch, and holds the next unit until the current unit is done. | `...::test_batched_admits_all_pods_after_the_hunt_batch`, `...::test_batched_holds_the_next_unit_until_the_current_unit_is_done`, `...::test_batched_skips_a_done_unit_in_the_queue` |
| C7 | `serial` admits one hunter at a time and holds its siblings. | `...::test_serial_admits_one_hunter_and_holds_its_siblings` |
| C8 | `serial` dispatches pods one at a time in stem order and advances past terminal exports. | `...::test_serial_dispatches_pods_one_at_a_time_in_stem_order`, `...::test_serial_advances_the_pod_cursor_past_terminal_specs` |
| C9 | `serial` holds hunter N+1 until hunter N is terminal AND all its pods are terminal; a zero-spec hunt advances immediately. | `...::test_serial_holds_the_next_hunter_until_the_previous_hunts_pods_are_terminal`, `...::test_serial_advances_to_the_next_hunt_when_the_previous_hunt_is_fully_done`, `...::test_serial_treats_a_specless_hunt_as_done` |
| C10 | `serial` holds the next unit while the current unit's hunt is mid-graph. | `...::test_serial_holds_the_next_unit_while_the_current_units_hunt_is_in_graph` |
| C11 | `parallel` admits every item unchanged. | `...::test_parallel_admits_every_item`, `tests/attack/test_hunting_pipeline_sync_gate.py::test_gate_parallel_returns_every_item_unchanged` |
| C12 | The gate reads the model risk, the intake-order tie-break, the live pod session (session-only unit), and the serial stems/exports from the stores. | `tests/attack/test_hunting_pipeline_sync_gate.py::test_gate_*` |
| C13 | A held item stays produced, counts as `paused`, and never reaches the control plane; an admitted item dispatches and moves. | `tests/attack/test_hunting_mover_sync_filter.py::test_pre_filter_*` |
| C14 | The surfer consults the gate once per tick with the live session set and the mid-graph hunt set, and honours its verdict. | `tests/attack/test_hunting_surfer_sync_wiring.py::test_surfer_holds_the_loop_file_until_the_sync_gate_admits_it` |
| C15 | The bootstrap stamps the frozen mode on the run record; the default run is `batched` and dispatches only after the pass settles; `parallel` keeps the interleave. | `tests/attack/test_hunting_run_lifecycle.py::test_default_mode_is_batched_and_holds_dispatch_until_the_pass_settles`, `...::test_parallel_mode_keeps_the_modeller_dispatch_interleave` |
| C16 | The stored `risk_threshold` wins over `HUNT_RISK_THRESHOLD` (basis `db`); a malformed value falls back; no value keeps the env basis. | `tests/attack/test_hunting_run_lifecycle.py::test_threshold_config_*` |
| C17 | The config endpoints: GET defaults/stored, PUT partial merge, enum + extra-field validation, 404 unknown project. | `tests/project_management/test_hunting_config_api.py::*` |
| C18 | The hunting blob deep-merges (partial PUT preserves siblings) and never touches the recon blob. | `tests/integration/test_settings_deep_merge.py::test_partial_hunting_put_preserves_siblings_and_the_recon_blob` (skips without Postgres) |

## E2E / live-stack assertions (opt-in, `PH_E2E_LIVE=1`)

These are the end-to-end cases to run against a live compose stack; they observe the app log, the run row, the stores and Langfuse, never internals.

- E1 - batched happy path: one project, `hunting_pipeline_sync=batched`; launch a run; the modeller pass settles before ANY hunter session starts (app log order / Langfuse session start times); each unit's hunter batch starts together; the unit's pods start only after every hunt of the unit left its graph; the next unit starts after the pods' exports land; the run reaches `complete` with `stats.pipeline_sync == "batched"`.
- E2 - serial happy path: same target, `serial`; at no moment are two hunter sessions of the same unit live; at no moment are two pod sessions of the same hunt live; each pod starts after the previous spec's `PodExport` file exists; the run reaches `complete` (or the token cap) with `stats.pipeline_sync == "serial"`.
- E3 - parallel regression: `parallel` reproduces the historical interleave (a hunter starts while the modeller pass is still modelling a later unit) and the S2 8.3 low-tier sequencing still applies.
- E4 - config round-trip: `GET /projects/{p}/hunting/config` returns `batched` on a fresh project; `PUT` `serial` then `GET` returns `serial`; a run launched afterwards records `serial`; a run launched BEFORE the PUT keeps its frozen mode.
- E5 - interrupted resume: interrupt a batched run mid-unit-batch (provider pause or stop); resume; the gate re-derives the queue from the stores - already-terminal hunts and exported pods are not re-run, the first unfinished phase dispatches.
- E6 - threshold override: a stored `risk_threshold` below the env value halts the run at the stored value, and `stats.threshold_basis == "db"`.

## Deliberately uncovered here

- Provider-failure retry semantics inside a phase beyond the interaction point: F-026 itself (the per-child backoff and the three-strike fatal rule) is owned by the trunk's own tests (`tests/attack/test_hunting_wiring.py::test_a_transient_pod_failure_requeues_only_that_spec_and_keeps_the_sibling_live`); this feature's gate only holds the phase while the recovered item waits, which the batched/serial cursor predicates already pin.
- Token-cap behaviour (unchanged by the mode).
- The verdict-processing workflow (stubbed: consume-and-record).
