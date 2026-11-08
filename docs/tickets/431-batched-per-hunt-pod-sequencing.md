# 431 - Batched pod phase one hunt at a time

**What to build:** Change the `batched` pipeline-sync pod phase from the unit's whole pod set to one hunt at a time in threat-rank order.
Every spec of the current hunt dispatches concurrently, and the next hunt waits until every pod of the current hunt carries a durable export.

**Blocked by:** none

**Status:** done

**Seams:** `attack/hunting/pipeline_sync.py`, `docs/design/hunting-pipeline-sync-adr.md`, `docs/design/hunting-pipeline-sync-spec.md`, `docs/design/hunting-pipeline-sync-assertions.md`, `attack/hunting/CONTEXT.md`

## Context

Iteration B created 20 pods in the same second across five hunts: `threat-1` (5 pods), `threat-10` (3), `threat-11` (5), `threat-2` (4), and `threat-3` (3).
The current ADR and code dispatch the unit's whole pod set after the hunter batch.
The operator's intended behaviour is the per-hunt batch: after all hunters of the unit are terminal, dispatch the first hunt's specs (one pod per spec), wait for all of them, then the next hunt, and so on.
The unit-wide batch saturated the qemu target and drove 58 of 66 pod exports into the 2700-second watchdog.

## Acceptance criteria

- [x] The ADR, spec, assertions, and CONTEXT state the per-hunt pod phase.
- [x] `batch_state` reports `hunt` until every hunt of the unit is terminal; a hunt that ended without a terminal marker is blocked, never a silent pass.
- [x] `batch_state` reports `pod` for the first hunt whose pod set is not fully exported.
- [x] `_decide_batched` admits only the cursor hunt's specs, excluding specs that already carry a durable export.
- [x] The next hunt is held until every pod of the current hunt is terminal.
- [x] The next unit is held until every hunt's pods are terminal.
- [x] A zero-spec hunt advances immediately.
- [x] Unit and gate tests pin all of the above.

## Verification

- `tests/attack/test_hunting_pipeline_sync.py`: 30 passed.
- `tests/attack/test_hunting_pipeline_sync_gate.py`: 18 passed.
- `tests/attack/test_hunting_pipeline_sync_lifecycle.py`, `test_hunting_surfer_sync_wiring.py`, `test_hunting_mover_sync_filter.py`: 19 passed.
- `tests/attack`: 1113 passed.
- `tests/app` and `tests/eval`: 1157 passed, 22 skipped.
- Hunting integration selection: 50 passed, 28 skipped.
