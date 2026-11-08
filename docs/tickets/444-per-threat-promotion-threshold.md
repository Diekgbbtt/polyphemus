# 444 - Per-threat promotion risk threshold

**What to build:** Add a frozen project setting `promotion_risk_threshold` that promotes only produced threats whose combined `risk` is at least the threshold. The filter lives in the pipeline sync and mover layer. The threat modeller is not aware of it. Demoted threats stay in `produced/` as evidence and never reach a hunter.

**Blocked by:** 443

**Status:** done

**Seams:** `attack/hunting/pipeline_sync.py`, `attack/hunting/mover.py`, `attack/hunting/surfer.py`, `attack/hunting/runtime.py`, `attack/hunting/threat_model_store.py`, `project_management/repository.py`, `project_management/api.py`, `docs/design/hunting-pipeline-sync-*`, `docs/design/hunting-67-threat-model-artifact-spec.md`

## Result

- `settings.hunting.promotion_risk_threshold` (integer at least 0 or `null`, default `null`) is exposed on GET/PUT and frozen on the run record.
- The mover's produced-inbox read promotes only threats whose combined `risk` is at least the threshold; a demoted threat stays in `produced/` as evidence.
- The demoted threat is excluded from the dispatch work, the hunter completion set, the work read, the quiesce, the completion audit, and the dispatch-gap count.
- The unit model moves to `consumed/` once its promoted threats are done; the demoted file remains.
- A demoted hunt's leftover spec is dropped from the mover's spec inbox and excluded from the pod block, including after the model moves.
- The filter applies in `parallel`, `batched`, and `serial`; recovered consumed threats are never demoted.
- The pure, mover, surfer, lifecycle, runtime, API, and integration tiers pin the lifecycle end to end.
- The pipeline-sync spec, ADR, assertions, the threat artifact spec, and both CONTEXT glossaries describe the built behaviour.

## Context

Every produced non-zero-risk threat currently reaches a hunter.
The operator wants a per-threat risk floor.
Only threats at or above the floor should be promoted.
The comparison is inclusive: `risk >= threshold`.
A `null` or 0 threshold promotes every valid threat.
The filter runs in the mover's produced-inbox read before the low-tier sequencing.
A demoted threat stays in `produced/` as evidence.
It is not an item, is excluded from the hunter completion set, the dispatch work, and the run quiesce.
The unit model moves to `consumed/` once its promoted threats are done; the demoted files remain.
The unit risk budget and the queue order still use every stored threat.
The filter applies in every sync mode.

## Acceptance criteria

- [x] `settings.hunting.promotion_risk_threshold` is an integer at least 0 or `null` with default `null`.
- [x] GET `/projects/{id}/hunting/config` returns it; PUT accepts a partial update with `extra="forbid"`; an invalid value or an unknown project lands nothing.
- [x] `start_hunting` resolves the value from the run record first, then the project setting, then `null`; a malformed stored value falls back with a warning.
- [x] The run record stamps `promotion_risk_threshold` beside `pipeline_sync`, and a resume prefers the frozen value.
- [x] One pure predicate decides promotion; the mover, the gate, the completion audit, and the dispatch-gap diagnostic share it.
- [x] The comparison is inclusive; `null` or 0 promotes every valid threat.
- [x] A demoted threat is not an item and stays in `produced/`; a recovered consumed threat is never demoted.
- [x] The filter runs before the low-tier sequencing.
- [x] `run_work_remaining` and `is_run_quiesced` see a demoted threat as not work; `run_delivery_tick` consumes the unit model once its promoted threats are done and leaves the demoted files.
- [x] `hunting_artifacts_terminal` ignores demoted produced threats.
- [x] The dispatch-gap diagnostic counts only promoted produced threats.
- [x] The filter applies in `parallel`, `batched`, and `serial`.
- [x] Unit, mover, surfer, lifecycle, runtime, API, and integration tests pin all of the above.
- [x] The pipeline-sync spec, ADR, assertions, the threat artifact spec, and the hunting CONTEXT describe the built behaviour.

## Verification

- `tests/attack/test_hunting_pipeline_sync.py`
- `tests/attack/test_hunting_mover_sync_filter.py`
- `tests/attack/test_hunting_surfer_tick.py`
- `tests/attack/test_hunting_pipeline_sync_lifecycle.py`
- `tests/attack/test_hunting_run_lifecycle.py`
- `tests/attack/test_threat_model_store.py`
- `tests/project_management/test_hunting_config_api.py`
- The hunting integration selection.
