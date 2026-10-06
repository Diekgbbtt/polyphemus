# ADR: a deliberate recon stop is a first-class `stopped` run terminal

## Status
Accepted (2026-10-06).

## Context
- `POST /projects/{id}/recon/{run_id}/stop` cancels the recon task and returns
  `200 {"stopping": true}`, but the `recon_runs` row stayed `status='running'`
  until `reap_stale_runs(REAP_TTL_SECONDS=300)` flipped it to `failed` ~5.5
  minutes later (ticket #287, run `e278c495`).
- Root cause: `run_pipeline` writes its terminal `complete` after the `finally`
  (`pipeline.py:812`). A `CancelledError` propagates out of the `finally`, so the
  terminal write never runs and no terminal lands at all.
- The run-level terminals were `complete|failed`, so a deliberate stop had no
  first-class terminal and was indistinguishable at the row level from a crash.
- Consumers suffered: the eval surfer's `terminate` reported success while
  `GET /app-state` kept the run in-flight (blocking the version-advance daemon)
  for the whole TTL, and the reaper's `failed` mislabelled the stop.

## Decision
- A deliberate recon stop is the first-class run terminal `stopped`.
  Recon run statuses are now `running` (the only live state) and
  `complete|failed|stopped` terminals. This matches the vocabulary the other two
  run classes already use (analysis `drained|withheld|stopped|interrupted`,
  hunting `complete|stopped|failed|interrupted`), so a stop reads the same way
  across the store.
- The terminal is written by Recon's pipeline cancellation path, never by the
  HTTP adapter. `run_pipeline` catches `asyncio.CancelledError` and writes
  `set_run_status(run_id, "stopped")` before re-raising (`pipeline.py:769-777`);
  the clean path still writes `complete` after the `finally`, and the re-raise
  propagates past that write, so the two terminals never race.
- `_TERMINAL_RUN_STATUSES` gains `stopped`, so `set_run_status("stopped")` stamps
  `finished_at` exactly like `complete`/`failed`.
- `stop_recon` (`project_management/api.py`) stays a thin adapter over
  `RuntimeManager.cancel_run`; its docstring records that the run row's terminal
  is written by the pipeline. Project-management owns the request to stop; Recon
  owns the Run entity's terminal status (CONTEXT-MAP).

## Considered options
- **Write `stopped` in `stop_recon`.** Rejected: it splits terminal authority
  across modules and races the pipeline - a run that completed just before the
  cancel would be clobbered `stopped`, while `cancel_run` already 404s on an
  unregistered (completed) run.
- **Write `complete` on stop.** Rejected: a deliberate stop is not a completion.
- **Write `failed` on stop.** Rejected: indistinguishable from a crash - the
  exact defect the ticket names.
- **A transient `stopping` marker, reaped to a terminal later.** Rejected: it
  needs a second writer and GC, and does not by itself remove the reaper race;
  the run still needs a settled terminal.

## Consequences
- The row leaves `running` promptly (one event-loop turn after the cancel), so
  `GET /app-state` stops reporting the run in-flight and the version-advance
  daemon unblocks at once; the reaper never touches a `stopped` row.
- `set_run_status(run_id, "stopped")` is terminal, so `finished_at` is stamped
  and the row is self-explaining: a stop is not a crash.
- The pipeline's `finally` still runs its teardown on the cancellation path
  (analysis `signal_end`, orchestrator reap, run-scoped flush), so the
  independent analysis consumer still drains what was already pushed.
- Eval consumers learn the new terminal: `RECON_TERMINAL` gains `stopped` in
  `eval/orchestrator/api.py` and `eval/ph.py`; the trial engine treats a natural
  recon `stopped` as terminal and never chains it into hunting
  (`eval/orchestrator/trial.py`).
- Regression coverage: `tests/recon/test_pipeline.py`
  (`test_cancelling_the_pipeline_writes_a_stopped_terminal_not_complete`),
  `tests/test_pipeline_registry.py` (stopped stamps `finished_at`),
  `tests/eval/test_orchestrator_trial.py` (a `stopped` recon terminal stops the
  trial), and `tests/eval/test_orchestrator_api.py` (the vocabulary).

## References
- #287 (this bug), #328 (the sibling recon-module `stopped` state), #75 (recon /
  analysis decoupling and the stop semantics), #121 (the module runtime manager).
- `src/polymerhus/recon/control/pipeline.py`; `src/polymerhus/app/clients/pg.py`;
  `src/polymerhus/project_management/api.py`; `docs/design/recon-pipeline-design.md`;
  `src/polymerhus/recon/CONTEXT.md` (Run terminal);
  `src/polymerhus/project_management/CONTEXT.md` (Recon stop).
