# 424 - Coverage-aware risk halt and per-unit budget reservation

**What to build:** Stop the progressive halt from starving the ground-truth units, and reserve budget for the crossing unit before the next batch.

**Blocked by:** none

**Status:** open

**Seams:** `attack/hunting/run_lifecycle.py`, `attack/hunting/pipeline_sync.py`, `attack/hunting/runtime.py`, `eval/setups/white-jotter-iteration-b.yaml`

## Context

Iteration B modelled 3 of 27 intake units at `HUNT_RISK_THRESHOLD=110`.
The third unit, `Service:library-catalog`, held the best SQL-injection loop and was never dispatched.
93% of the capped budget went to the first two units; the third unit starved behind the batched risk-descending queue.

## Acceptance criteria

- [ ] The run record names the crossing unit and its dispatch reservation.
- [ ] The crossing unit is dispatched before the next unit's batch.
- [ ] A per-unit budget reservation or a coverage floor prevents one unit from consuming the trial budget.
- [ ] A unit that reaches COMPLETED is never silently left undspatched.
- [ ] A regression test models a 3-unit intake with a threshold that crosses on unit 3 and asserts unit 3 dispatches.
- [ ] The next white-jotter run reports how many ground-truth units were modelled and hunted.

## Verification

- `tests/attack/test_run_lifecycle.py`
- `tests/attack/test_hunting_pipeline_sync.py`
- A white-jotter run with the new halt.
