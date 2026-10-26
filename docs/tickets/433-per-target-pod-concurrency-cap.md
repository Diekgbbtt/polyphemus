# 433 - Per-target pod concurrency cap

**What to build:** Add a per-target pod concurrency cap beside the global `HUNTING_DISPATCH_GATE_WIDTH`.
The cap must bound the live pod sessions that probe one target, not only the whole run.

**Blocked by:** 431

**Status:** open

**Seams:** `app/config.py`, `attack/hunting/pipeline_sync.py`, `attack/hunting/surfer.py`, `attack/hunting/runtime.py`

## Context

`HUNTING_DISPATCH_GATE_WIDTH` defaults to 20 and is global.
Iteration B admitted 20 pods in the same second against one qemu-backed host.
The host saturated, every probe slowed, and the watchdog killed most of the wave.
The per-hunt sequencing change (ticket 431) bounds the common case by the specs of one hunt, but a hunt with many specs, or a future mode that overlaps hunts, can still exceed the target's capacity.

## Acceptance criteria

- [ ] A per-target pod concurrency cap is configurable and enforced at pod admission.
- [ ] The effective cap is the smaller of the per-target cap and the global gate width.
- [ ] The run record reports the peak concurrent pods and the cap.
- [ ] A regression test admits more specs than the cap and asserts only the cap is admitted.
- [ ] The next white-jotter run reports the watchdog-envelope share at the new concurrency.

## Verification

- `tests/attack/test_hunting_pipeline_sync_gate.py`
- `tests/attack/test_hunting_surfer_tick.py`
- A white-jotter run.
