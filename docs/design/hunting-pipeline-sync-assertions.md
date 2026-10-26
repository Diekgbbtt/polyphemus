# Assertion catalogue - hunting pipeline synchronisation

**Scope:** `hunting_pipeline_sync` (`serial | batched | parallel`, default `batched`), spec `docs/design/hunting-pipeline-sync-spec.md`, ADR `docs/design/hunting-pipeline-sync-adr.md` (2026-10-22).
**Seams under assertion:** the project settings surface (`project_management/api.py`, `repository.py`, `app/clients/pg.py`), the run bootstrap (`attack/hunting/runtime.py`), the sync gate (`attack/hunting/pipeline_sync.py`), the mover tick (`attack/hunting/mover.py`), the surfer loop (`attack/hunting/surfer.py`).

## The mode state machine (the model under test)

For one run, `mode = resolve_mode(record.stats.pipeline_sync, settings.hunting)`, frozen at boot.

| mode | phase gate | order | concurrency |
|---|---|---|---|
| parallel | none (historical) | produced order + S2 8.3 tiering over promoted threats | every promoted item as it appears |
| batched | modeller settled; per-unit hunt phase then per-unit pod blocks | units by model risk desc, intake position, name; hunts and their pods by rank; fixed pod blocks of `pod_batch_size` | whole promoted hunter batch / every spec of the block's hunts |
| serial | modeller settled; cursor hunt fully done before the next | same queue; pods by spec stem | one hunter, one pod |

Gate signals: modeller session settled; hunter = left its graph; pod = durable PodExport exists; a live pod keeps its unit current.
Promotion: only a produced threat whose combined `risk >= promotion_risk_threshold` is an item; `null` or 0 means no filter; a demoted threat stays in `produced/` and is not work.

## Contract predicates (unit + integration tier)

Each predicate names its executable test.

| id | predicate | test |
|---|---|---|
| C1 | The mode enum is exactly `serial`/`batched`/`parallel`; the default is `batched`. | `tests/attack/test_hunting_pipeline_sync.py::test_sync_mode_values_and_default` |
| C2 | `resolve_mode` prefers the run record, then the setting, then the default; an unknown value falls through. | `...::test_resolve_mode_prefers_the_run_record_then_the_settings_then_the_default` |
| C3 | The queue orders by risk contribution DESC, intake position ASC, unit name ASC. | `...::test_order_units_is_risk_desc_then_intake_position_then_name` |
| C4 | While the modeller pass is live, no item is admissible in `batched` or `serial`. | `...::test_modeller_live_holds_every_item` |
| C5 | `batched` admits the whole unit hunter batch and refuses the unit's pods while a threat file remains or a hunt is mid-graph. | `...::test_batched_admits_the_whole_unit_hunter_batch`, `...::test_batched_refuses_pods_while_a_hunt_file_remains`, `...::test_batched_refuses_pods_while_a_hunt_is_mid_graph` |
| C6 | `batched` admits every pod of the first unfinished hunt after the hunt batch, holds the next hunt until every pod of the current hunt is terminal, and holds the next unit until the current unit is done. | `...::test_batched_admits_all_pods_of_the_first_hunt`, `...::test_batched_holds_the_next_hunt_until_every_pod_of_the_current_hunt_is_terminal`, `...::test_batched_advances_to_the_next_hunt_when_the_first_hunt_is_exported`, `...::test_batched_holds_the_next_unit_until_the_current_unit_is_done`, `...::test_batched_skips_a_done_unit_in_the_queue` |
| C6a | The impure batched gate reads the terminal markers and the durable exports, and applies the per-hunt pod cursor. | `tests/attack/test_hunting_pipeline_sync_gate.py::test_gate_batched_*` |
| C7 | `serial` admits one hunter at a time and holds its siblings. | `...::test_serial_admits_one_hunter_and_holds_its_siblings` |
| C8 | `serial` dispatches pods one at a time in stem order and advances past terminal exports. | `...::test_serial_dispatches_pods_one_at_a_time_in_stem_order`, `...::test_serial_advances_the_pod_cursor_past_terminal_specs` |
| C9 | `serial` holds hunter N+1 until hunter N is terminal AND all its pods are terminal; a zero-spec hunt advances immediately. | `...::test_serial_holds_the_next_hunter_until_the_previous_hunts_pods_are_terminal`, `...::test_serial_advances_to_the_next_hunt_when_the_previous_hunt_is_fully_done`, `...::test_serial_treats_a_specless_hunt_as_done` |
| C10 | `serial` holds the next unit while the current unit's hunt is mid-graph. | `...::test_serial_holds_the_next_unit_while_the_current_units_hunt_is_in_graph` |
| C11 | `parallel` admits every item unchanged. | `...::test_parallel_admits_every_item`, `tests/attack/test_hunting_pipeline_sync_gate.py::test_gate_parallel_returns_every_item_unchanged` |
| C12 | The gate reads the model risk, the intake-order tie-break, the live pod session (session-only unit), and the per-hunt stems/exports from the stores. | `tests/attack/test_hunting_pipeline_sync_gate.py::test_gate_*` |
| C13 | A held item stays produced, counts as `paused`, and never reaches the control plane; an admitted item dispatches and moves. | `tests/attack/test_hunting_mover_sync_filter.py::test_pre_filter_*` |
| C14 | The surfer consults the gate once per tick with the live session set and the mid-graph hunt set, and honours its verdict. | `tests/attack/test_hunting_surfer_sync_wiring.py::test_surfer_holds_the_loop_file_until_the_sync_gate_admits_it` |
| C15 | The bootstrap stamps the frozen mode on the run record; the default run is `batched` and dispatches only after the pass settles; `parallel` keeps the interleave. | `tests/attack/test_hunting_run_lifecycle.py::test_default_mode_is_batched_and_holds_dispatch_until_the_pass_settles`, `...::test_parallel_mode_keeps_the_modeller_dispatch_interleave` |
| C16 | The stored `risk_threshold` wins over `HUNT_RISK_THRESHOLD` (basis `db`); a malformed value falls back; no value keeps the env basis. | `tests/attack/test_hunting_run_lifecycle.py::test_threshold_config_*` |
| C17 | A pod resume cursor without a durable `PodExport` is not completion; the gate holds the consumed spec until a terminal export exists. | `tests/attack/test_hunting_pipeline_sync_lifecycle.py::test_a_resume_cursor_does_not_count_as_a_terminal_export` |
| C17a | The config endpoints: GET defaults/stored, PUT partial merge, enum + extra-field validation, 404 unknown project. | `tests/project_management/test_hunting_config_api.py::*` |
| C18 | The hunting blob deep-merges (partial PUT preserves siblings) and never touches the recon blob. | `tests/integration/test_settings_deep_merge.py::test_partial_hunting_put_preserves_siblings_and_the_recon_blob` (skips without Postgres) |
| C19 | `pod_batch_size` is an integer at least 1 with default 1; `promotion_risk_threshold` is an integer at least 0 or `null` with default `null`; both validate on GET and PUT and never store an invalid value. | `tests/project_management/test_hunting_config_api.py::test_get_*`, `...::test_put_*` |
| C20 | The resolvers prefer the run record, then the project setting, then the default; a malformed value falls through. | `tests/attack/test_hunting_pipeline_sync.py::test_resolve_pod_batch_size_*`, `...::test_resolve_promotion_risk_threshold_*` |
| C21 | `batched` admits every spec of the first fixed block of `pod_batch_size` hunts, holds the next block until every spec in the block is exported, and default 1 reproduces the per-hunt cursor. | `tests/attack/test_hunting_pipeline_sync.py::test_batched_admits_the_first_block_*`, `...::test_batched_holds_the_next_block_*`, `tests/attack/test_hunting_pipeline_sync_gate.py::test_gate_batched_*` |
| C22 | The block is fixed: a done hunt contributes no work and does not slide the next hunt into the block; a blocked hunt holds the block; a zero-spec hunt is done; a batch larger than the hunts clamps. | `tests/attack/test_hunting_pipeline_sync.py::test_batched_block_does_not_slide_when_an_earlier_hunt_is_done`, `...::test_batched_block_holds_on_a_blocked_hunt`, `...::test_batched_zero_spec_hunt_is_done_inside_its_block`, `...::test_batched_batch_size_larger_than_the_hunts_clamps` |
| C23 | `serial` ignores `pod_batch_size` and stays one hunter and one pod at a time. | `tests/attack/test_hunting_pipeline_sync.py::test_serial_ignores_the_pod_batch_size` |
| C24 | The promotion predicate is inclusive (`risk >= threshold`); `null` or 0 promotes every valid threat; a demoted produced threat is not an item; a recovered consumed threat is never demoted. | `tests/attack/test_hunting_pipeline_sync.py::test_risk_is_promoted_is_inclusive_and_off_by_default`, `tests/attack/test_hunting_mover_sync_filter.py::test_promotion_none_dispatches_every_threat`, `...::test_a_recovered_consumed_threat_is_never_demoted` |
| C25 | A demoted threat stays in `produced/`, is excluded from `run_work_remaining` and `is_run_quiesced`, and the unit model is consumed once the promoted threats are done; the demoted files remain. | `tests/attack/test_hunting_mover_sync_filter.py::test_promotion_omits_a_demoted_threat_and_consumes_the_model`, `...::test_all_demoted_unit_is_model_consume_work_then_quiet`, `tests/attack/test_threat_model_store.py::test_consume_model_if_done_ignores_promotion_demoted_threat_files` |
| C26 | `hunting_artifacts_terminal` ignores demoted produced threats and a demoted hunt's leftover spec folder, including after the model moves. | `tests/attack/test_hunting_pipeline_sync_lifecycle.py::test_demoted_produced_threat_is_not_pending_in_the_completion_audit`, `...::test_demoted_hunt_leftover_spec_is_ignored_after_the_model_moves` |
| C27 | The run record stamps `pod_batch_size` and `promotion_risk_threshold`; a resume prefers the run record; a mid-run PUT changes only future runs. | `tests/attack/test_hunting_run_lifecycle.py::test_the_run_record_stamps_the_pod_batch_and_promotion_threshold`, `...::test_a_resume_prefers_the_recorded_pipeline_settings` |
| C28 | The dispatch-gap diagnostic counts only promoted produced threats. | `tests/attack/test_hunting_review_fixes.py::test_a_demoted_produced_threat_is_not_a_dispatch_gap` |
| C29 | A mover-refused threat file stays in `produced/` and is not archived; once the unit model moves to `consumed/`, it is an orphan in `produced/` and the produced-threat read no longer sees it. `abandoned/` is the whole-unit archive for a stale, degraded, or invalid model. | `tests/attack/test_hunting_mover_sync_filter.py::test_a_refused_threat_stays_in_produced_and_is_not_archived` |

## E2E / live-stack assertions (opt-in, `PH_E2E_LIVE=1`)

These are the end-to-end cases to run against a live compose stack; they observe the app log, the run row, the stores and Langfuse, never internals.

- E1 - batched happy path: one project, `hunting_pipeline_sync=batched`; launch a run; the modeller pass settles before ANY hunter session starts (app log order / Langfuse session start times); each unit's hunter batch starts together; the unit's pods start only after every hunt of the unit is terminal; only one hunt's pod set is live at a time, in threat-rank order; the next hunt starts only after every pod of the current hunt has a durable export; the next unit starts after the last hunt's pods export; the run reaches `complete` with `stats.pipeline_sync == "batched"`.
- E2 - serial happy path: same target, `serial`; at no moment are two hunter sessions of the same unit live; at no moment are two pod sessions of the same hunt live; each pod starts after the previous spec's `PodExport` file exists; the run reaches `complete` (or the token cap) with `stats.pipeline_sync == "serial"`.
- E3 - parallel regression: `parallel` reproduces the historical interleave (a hunter starts while the modeller pass is still modelling a later unit) and the S2 8.3 low-tier sequencing still applies.
- E4 - config round-trip: `GET /projects/{p}/hunting/config` returns `batched` on a fresh project; `PUT` `serial` then `GET` returns `serial`; a run launched afterwards records `serial`; a run launched BEFORE the PUT keeps its frozen mode.
- E5 - interrupted resume: interrupt a batched run mid-unit-batch (provider pause or stop); resume; the gate re-derives the queue from the stores - already-terminal hunts and exported pods are not re-run, the first unfinished phase dispatches.
- E6 - threshold override: a stored `risk_threshold` below the env value halts the run at the stored value, and `stats.threshold_basis == "db"`.
- E7 - resumable pod: stop a batched run while a pod is live; the pod writes no export and a resume cursor; the gate holds the hunt; resume with the same spec, run, and project; the pod continues at the cursor variant and skips an executed probe; the terminal export clears the cursor and advances the hunt.
- E8 - pod batch size: a batched run with `pod_batch_size=2` starts the first two hunts' pods together after every hunter is terminal; the third hunt's pods start only after every spec of the first two hunts has a durable export; the run reaches `complete` with `stats.pod_batch_size == 2`.
- E9 - promotion: a batched run with `promotion_risk_threshold` set dispatches only the threats at or above the threshold; the demoted threat files remain in `produced/`; the unit model reaches `consumed/`; the run reaches `complete` and the run record carries the frozen threshold.
- E10 - default regression: `pod_batch_size=1` and `promotion_risk_threshold=null` reproduce the pre-change per-hunt pod phase and dispatch every valid threat.

## Deliberately uncovered here

- Provider-failure retry semantics inside a phase beyond the interaction point: F-026 itself (the per-child backoff and the three-strike fatal rule) is owned by the trunk's own tests (`tests/attack/test_hunting_wiring.py::test_a_transient_pod_failure_requeues_only_that_spec_and_keeps_the_sibling_live`); this feature's gate only holds the phase while the recovered item waits, which the batched/serial cursor predicates already pin.
- Token-cap behaviour (unchanged by the mode).
- The verdict-processing workflow (stubbed: consume-and-record).
