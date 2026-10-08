# ADR: a deliberate recon stop is a first-class `stopped` run terminal

## Status
Accepted (2026-10-06).

## Context
- `POST /projects/{id}/recon/{run_id}/stop` cancels the recon task and returns
  `200 {"stopping": true}`, but the `recon_runs` row stayed `status='running'`
  until `reap_stale_runs(REAP_TTL_SECONDS=300)` flipped it to `failed` ~5.5
  minutes later (ticket #287, run `e278c495`).
- Root cause: `run_pipeline` writes its terminal `complete` after the `finally`
  (`pipeline.py:819`). A `CancelledError` propagates out of the `finally`, so the
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
  HTTP adapter. `run_pipeline`'s exit teardown ends in a `finally` that tests
  the in-flight exception (`isinstance(sys.exc_info()[1], asyncio.CancelledError)`)
  and, when a `CancelledError` is unwinding, writes
  `set_run_status(run_id, "stopped")` (`pipeline.py:815-816`). The check runs
  after the flush so it covers a cancellation delivered anywhere in the pipeline
  body AND one that lands during the exit teardown itself. The clean path still
  writes `complete` after the `finally` (`pipeline.py:819`), and the fail-close
  paths write `failed` and `return`; on those paths no exception is unwinding,
  so the `stopped` write never fires and cannot clobber either terminal. Testing
  the in-flight exception (not a cancel-request count) is deliberate: a cancel
  request absorbed by the awaited heartbeat task must not be read as a stop.
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
- The row leaves `running` at the run's exit teardown (bounded: the analysis
  `signal_end`, the orchestrator reap, and the run-scoped flush) rather than
  after `REAP_TTL_SECONDS`, so `GET /app-state` stops reporting the run
  in-flight and the version-advance daemon unblocks; the reaper never touches a
  `stopped` row.
  A cancellation delivered during the pipeline's pre-body setup awaits (before
  the `try` opens) still has no terminal and falls to the reaper - a pre-existing
  window, not the running-run defect this ticket names.
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
  (`test_cancelling_the_pipeline_writes_a_stopped_terminal_not_complete` and
  `test_cancelling_during_teardown_still_writes_a_stopped_terminal`),
  `tests/test_pipeline_registry.py` (stopped stamps `finished_at`; the reaper
  predicate only touches `status='running'`),
  `tests/eval/test_orchestrator_trial.py` (a `stopped` recon terminal stops the
  trial), and `tests/eval/test_orchestrator_api.py` (the vocabulary).

## Amendment (2026-10-08, #113): the Run is the operator cancellation unit

- Context: ticket #113 asked for an operator-facing job/run cancel path.
  The operator-facing face already exists: `POST /projects/{id}/recon/{run_id}/stop` is a thin adapter over `RuntimeManager.cancel_run` (`project_management/api.py`), the run row reaches the first-class `stopped` terminal promptly via the pipeline cancellation path (#287), and already-curated data is preserved because `curate()` persists per pod incrementally.
  The eval trial already calls the same stop endpoint on timeout (#338).
- Decision: the operator cancellation unit is the **Run**, never an individual **Job**.
  A per-job cancel is deliberately not provided.
  A run's jobs run sequentially within a phase behind a phase barrier, so the in-flight job is the only thing a stop can be waiting on.
  Job selection is a launch-time concern already served by the `jobs` subset on `POST /recon`, and the operator's stop intent is run-scoped (the ticket's own example is a whole run judged to be noisy).
  A per-job cancel would add a second lifecycle verb and a job-level terminal vocabulary for no operator use case.
- Residual, explicitly out of this surface's scope: the run-level stop does not promptly tear down the in-flight pod/tool.
  `run_job` awaits `asyncio.to_thread(graph.invoke, ...)` (`recon/control/job_agent.py`); cancelling the pipeline task cancels that await immediately but the worker thread keeps running the pod graph and the tool to `EXEC_TIMEOUT_S`, including up to `MAX_POD_ITERS` retries.
  That exec-kill and output-suppression is workflow ticket #76 ("suppress killed-job output on teardown", D3), the sibling teardown-audit fix under the same audit; it is a separate change, not part of the operator cancel surface.
- The run-level stop therefore satisfies #113's API action, data-preservation, and run-terminal criteria.
  #113's pod-teardown criterion is owned by #76.

## References
- #287 (this bug), #328 (the sibling recon-module `stopped` state), #75 (recon /
  analysis decoupling and the stop semantics), #121 (the module runtime manager),
  #113 (the operator cancel surface; this amendment), #76 (the killed-job
  exec-kill and output-suppression residual), #338 (the eval trial stops on
  timeout).
- `src/polymerhus/recon/control/pipeline.py`; `src/polymerhus/app/clients/pg.py`;
  `src/polymerhus/project_management/api.py`; `docs/design/recon-pipeline-design.md`;
  `src/polymerhus/recon/CONTEXT.md` (Run terminal, Run cancellation);
  `src/polymerhus/project_management/CONTEXT.md` (Recon stop);
  `docs/design/teardown-checkpoint-flush-211-spec.md` (#76 sibling).
