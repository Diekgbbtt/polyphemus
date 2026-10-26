# 443 - Configurable pod batch size for the batched phase

**What to build:** Add a frozen project setting `pod_batch_size` that widens the `batched` pod phase from one hunt to a fixed block of hunts. The hunter phase stays unchanged. The default of 1 keeps the current behaviour.

**Blocked by:** none

**Status:** done

**Seams:** `attack/hunting/pipeline_sync.py`, `attack/hunting/runtime.py`, `attack/hunting/surfer.py`, `project_management/repository.py`, `project_management/api.py`, `docs/design/hunting-pipeline-sync-*`, `docs/design/hunting-batch-and-promotion-spec.md`

## Result

- `settings.hunting.pod_batch_size` (integer at least 1, default 1) is exposed on GET/PUT and frozen on the run record.
- The `batched` pod phase dispatches fixed blocks of `pod_batch_size` hunts in rank order; the block advances only when every consumed spec in it has a durable export.
- The full hunt list is built from positive-risk, promoted, observable hunts, so a zero-risk or refused model threat cannot freeze the pod phase.
- `serial` ignores the setting and stays one hunter and one pod at a time.
- The pure, gate, runtime, API, and integration tiers pin the block, the default, the freeze, and the real-store flow.
- The pipeline-sync spec, ADR, assertions, the threat artifact spec, and both CONTEXT glossaries describe the built behaviour.

## Context

The `batched` pod phase currently dispatches one hunt's spec set at a time.
Ticket 431 made that behaviour explicit after iteration B saturated the target with a unit-wide pod batch.
The operator now wants the block width configurable without a code change.
The intended behaviour is: after every hunter of the unit is terminal, the first `n` hunts in threat-rank order dispatch their pod sets together.
The next `n` hunts start only when every consumed spec in the current block has a durable export.
The block is fixed. A done hunt does not slide the next hunt into the block.
A blocked hunt holds the block.
The default is 1, which is the current per-hunt behaviour.
`serial` ignores the setting.
`parallel` has no gate and ignores it.

## Acceptance criteria

- [x] `settings.hunting.pod_batch_size` is an integer at least 1 with default 1.
- [x] GET `/projects/{id}/hunting/config` returns it; PUT accepts a partial update with `extra="forbid"`; an invalid value or an unknown project lands nothing.
- [x] `start_hunting` resolves the value from the run record first, then the project setting, then 1; a malformed stored value falls back with a warning.
- [x] The run record stamps `pod_batch_size` beside `pipeline_sync`, and a resume prefers the frozen value.
- [x] The pure `decide` and `batch_state` accept the batch size and admit every spec of the first fixed block of `n` hunts.
- [x] The next block is held until every consumed spec in the current block has a durable export.
- [x] A done hunt in the block contributes no work and does not slide the next hunt into the block.
- [x] A blocked hunt holds the block; a zero-spec hunt is done immediately; a value larger than the remaining hunts clamps.
- [x] `serial` stays one hunter and one pod at a time; `parallel` is unchanged.
- [x] The default of 1 reproduces the current per-hunt behaviour exactly.
- [x] Unit, gate, runtime, API, and integration tests pin all of the above.
- [x] The pipeline-sync spec, ADR, assertions, and the hunting CONTEXT describe the built behaviour.

## Verification

- `tests/attack/test_hunting_pipeline_sync.py`
- `tests/attack/test_hunting_pipeline_sync_gate.py`
- `tests/attack/test_hunting_pipeline_sync_lifecycle.py`
- `tests/attack/test_hunting_surfer_sync_wiring.py`
- `tests/attack/test_hunting_run_lifecycle.py`
- `tests/project_management/test_hunting_config_api.py`
- The hunting integration selection.
