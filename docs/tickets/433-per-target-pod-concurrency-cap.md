# 433 - Per-target pod concurrency cap

**What to build:** Add a per-target pod concurrency cap beside the global `HUNTING_DISPATCH_GATE_WIDTH`.

**Blocked by:** 431

**Status:** rejected (operator, 2026-10-26)

**Seams:** `app/config.py`, `attack/hunting/pipeline_sync.py`, `attack/hunting/surfer.py`, `attack/hunting/runtime.py`

## Context

`HUNTING_DISPATCH_GATE_WIDTH` defaults to 20 and is global.
Iteration B admitted 20 pods in the same second against one qemu-backed host.

The operator rejected the per-target cap.
The per-hunt pod sequencing change (ticket 431) bounds the common case by the specs of one hunt.
The global gate width remains the outer bound.
The residual risk is a hunt with more than 20 specs; that is accepted.
