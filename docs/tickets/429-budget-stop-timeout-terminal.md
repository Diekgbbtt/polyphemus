# 429 - Retry the budget-stop POST and record the true terminal

**What to build:** Retry the budget-stop POST on transport timeout, and record the terminal as `stopped` with the overshoot when the app run has stopped.

**Blocked by:** none

**Status:** open

**Seams:** `eval/orchestrator/trial.py`, `eval/orchestrator/api.py`, `eval/orchestrator/store.py`

## Context

Iteration B's app hunting run finished `stopped` at 03:11:21 after crossing the 7M cap.
The trial's `POST /projects/{id}/execution/stop` timed out, so `trial.yaml` says `failed`, records `spend_overshoot: null`, and leaves `hunting.run_id: null` although run `12d15890` produced the artifacts.

## Acceptance criteria

- [ ] A transport timeout on the stop POST is retried with a bounded backoff.
- [ ] A run that is already stopped is recorded as `stopped`, not `failed`.
- [ ] `spend_overshoot` records the real 17,453 overshoot.
- [ ] `trial.yaml` keeps the hunting run id on the stop path.
- [ ] A regression test drives a stop timeout and asserts the terminal and the run id.
- [ ] The next trial's record matches the app run row.

## Verification

- `tests/eval/test_orchestrator_trial.py`
- `tests/eval/test_orchestrator_store.py`
- A budget-stopped trial.
