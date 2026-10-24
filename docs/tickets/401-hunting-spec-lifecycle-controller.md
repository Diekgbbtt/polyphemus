# Ticket 401: hunting spec lifecycle - malformed/stale prevention and the consumed-completion controller

- **Tracker:** https://github.com/Diekgbbtt/polyphemus/issues/401
- **Severity:** high (run wedge and false completion).
- **Area:** `src/polymerhus/attack/hunting/`.
- **Status:** open, needs-triage.

## Summary

The serial sync gate now fails closed on a stale or malformed spec set, but the
upstream hunter lifecycle does not prevent those states and has no controller to
repair them. The gate can hold a run indefinitely when a hunter ends without
finalizing, and a builder-exception pod path previously returned a degraded
envelope without a durable `PodExport`.

## Gaps

- **Write-time validation:** `HunterMemoryStore.write_specs` does not validate
  the full body at the `hunts_store.write` seam. A malformed or unparsable file
  can exist outside the tool path, and the surfer must be able to read the state.
- **Stale `hypothesised` specs:** `finalize_specs` refuses a produced
  `hypothesised` set, but nothing detects a hunter that ends or stalls before
  finalizing, re-prompts it, or presents each draft in a structured sequential
  loop.
- **Consumed transition:** `hunts_store` writes `ratified` specs to `produced/`;
  the mover moves them to `consumed/` at pod admission. The ADR says the move is
  ADMISSION, while the operator wording says "dispatchable = consumed". The
  lifecycle contract needs one explicit definition.
- **Pod terminal/degraded state:** the surfer's `surfer-dispatch-degraded` path
  must persist a durable `PodExport`, or expose an equivalent terminal state the
  serial gate can read.
- **Run health:** a stale/malformed hunt must surface a named blocked/degraded
  state, not only an invisible serial hold.

## Acceptance criteria

- A write that fails the spec contract is rejected at the tool seam with a coded
  error; no file lands. An existing corrupt file is reported as a named degraded
  state.
- A hunt with produced `hypothesised` specs is detected after its hunter graph
  ends. The controller re-prompts or walks each draft sequentially, bounded; the
  run records the outcome and does not quiesce `complete`.
- The serial cursor uses consumed `ratified` specs as the completion set,
  produced `ratified` specs as pending admission, and produced `dropped` specs as
  terminal. A hunt is done only with the run-scoped terminal marker, no pending
  produced `ratified` specs, and a `PodExport` or explicit terminal/degraded
  state for every consumed spec.
- `surfer-dispatch-degraded` persists a durable terminal `PodExport` (or an
  equivalent state read) and credits serial completion.
- Tests cover malformed write rejection, stale hypothesised blocking or
  re-prompt, consumed-vs-produced cursor, dropped exclusion, terminal-marker
  requirement, and degraded pod export completion.

## Evidence

- Live run `a5f487fb-8329-431c-b95d-207799a038f9`, hunt
  `Service-sign-in__loop-1`: one successful `PodExport` for
  `attempt-accounting-absent_account-spread`, three pending `ratified` specs, and
  one `dropped` spec (`attempt-accounting-absent_envelope-collapse`).
- The dropped spec wedged the serial cursor before commit `74788514`.
- The builder-exception path returned `surfer-dispatch-degraded` without a
  durable export before the 2026-10-24 gate/surfer repair.
