# 425 - Preserve the pod terminal on watchdog expiry and emit an export for every pod

**What to build:** Make the pod watchdog preserve the pod's own terminal or extend the window on progress, and guarantee one export per pod directory.

**Blocked by:** none

**Status:** open

**Seams:** `attack/hunting/surfer.py`, `attack/hunting/pod/pod.py`, `attack/hunting/pod/types.py`, `attack/hunting/pod/graph.py`

## Context

Iteration B produced 86 pod directories and 66 exports.
58 of the 66 exports are degraded `budget-timeout` envelopes written by the 2700 s watchdog, with top-level terminal fields and zero raw observations.
20 pod directories have no export at all.
The one pod that reached the correct semicolon spelling lost its evidence to the watchdog.

## Acceptance criteria

- [ ] A watchdog expiry preserves the pod's own last terminal when one exists.
- [ ] A progressing pod extends its window instead of being cut at a fixed wall clock.
- [ ] Every pod directory receives exactly one export, including a degraded one when the pod never concluded.
- [ ] The export schema is single: the degraded envelope and the normal export do not fork the top-level contract.
- [ ] A slow-target test drives a pod past the watchdog and asserts the export and the terminal are preserved.
- [ ] The next run reports the watchdog-envelope share and the no-export count.

## Verification

- `tests/attack/pod/test_pod_lifecycle.py`
- `tests/attack/test_hunting_surfer_tick.py`
- A slow-target pod run.
