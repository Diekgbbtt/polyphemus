# 432 - Export live pods on run stop or keep them resumable

**What to build:** When a hunting run stops with live pod sessions, write a durable terminal export for every live pod, or keep the pod durably resumable.
The stop must never leave a pod directory without a terminal record.

**Blocked by:** none

**Status:** open

**Seams:** `attack/hunting/surfer.py`, `attack/hunting/runtime.py`, `attack/hunting/run_lifecycle.py`, `eval/orchestrator/trial.py`

## Context

Iteration B stopped the hunting run at `2026-10-26T03:11:21Z` after crossing the 7M capped-token budget.
The last 20 pod directories were born between `02:48:42Z` and `02:50:50Z`, had 4 to 14 executed probes each, and have no export.
The run stop cancelled them without a terminal record, so the measurement counts 20 export-less directories and the queue cannot tell "not finished" from "lost".

## Acceptance criteria

- [ ] A run stop cancels every live pod and writes one durable export for it, with a reason that names the stop.
- [ ] A pod that cannot be exported is left with a durable in-flight marker and is resumable.
- [ ] The run record names the live-pod count at stop.
- [ ] A regression test starts a run with a live pod, stops it, and asserts the export or the resumable marker.
- [ ] The next run reports zero pod directories without an export.

## Verification

- `tests/attack/test_hunting_surfer_tick.py`
- `tests/attack/test_hunting_run_lifecycle.py`
- `tests/eval/test_orchestrator_trial.py`
- A stopped white-jotter run.
