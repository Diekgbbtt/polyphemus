# Control-Plane Decoupling - Architectural Decision Records

Decisions taken (operator-authoritative, grilled 2026-08-04) for ticket #75: re-architecting recon and analysis as two independent runtime modules at the root of the control plane.
Companion to the redesign program (#73 done, #74 done, #75 this, #76 teardown suppression, #88 queue persistence).
These records are authoritative over `docs/design/recon-analysis-decoupling.md` where they clash - they reverse that doc's Q3=(a) cursor+re-read and remove Q10's `analysed_keys`.
Where a record and the live code disagree, the code wins and the record is stale.

## D1 - Two independent asyncio tasks per run, sharing a per-run FIFO

Recon and analysis run as two independent `asyncio` tasks (the codebase is single-event-loop; "thread" in the operator's framing = an independent concurrent execution unit, not an OS thread).
They communicate ONLY through the in-memory `L0Chunk` FIFO built in #74.
There is ONE FIFO per run, held in a process-level registry keyed by `run_id`.
Recon pushes to run X's queue; the analysis task for run X drains that same queue.
The queue's lifetime is the run's: it is created when the run's tasks are dispatched and discarded on teardown, which bounds process memory to live runs.

**Rationale.** recon-only and analysis-only can be launched for different runs concurrently, so a global queue would have to tag-and-filter every chunk and could not give a clean per-run exactly-once/ordering guarantee.
A per-run queue in a registry is the isolation that makes independent start/stop coherent.

## D2 - A dispatcher at the control-plane root, with three entrypoints

The control plane gains a dispatcher with three API entrypoints:
- a **combined** endpoint that starts BOTH a recon task and an analysis task for one `run_id`;
- a **recon-only** endpoint that starts recon (which pushes chunks to the run's queue);
- an **analysis-only** endpoint that starts the analysis task draining the run's queue.

"Starting" creates the independent task and, for the combined/first-started case, the run's queue in the registry.
The combined endpoint is a convenience launcher over the two independent ones; it introduces no coupling beyond sharing one `run_id`.

**Rationale.** The operator requires recon and analysis to be launchable, stoppable, and torn down fully independently, with a single dispatch point for the common "run both" case.

## D3 - Analysis is its own module with its own run table; recon never waits on it

Analysis becomes its own module with its own persistence: an `analysis_runs` row carrying its own status (`draining -> drained | withheld | interrupted | stopped`).
`recon_runs.status` flips to `complete` the instant recon jobs finish - recon NEVER waits on analysis.
The analysis task records its OWN terminal status when it finishes draining.

**Rationale.** Full lifecycle independence (operator decision "separate analysis-run module + table"); the old `await feed.drain()` before `set_run_status("complete")` is exactly the coupling being removed.

## D4 - End-of-stream is a terminal marker recon enqueues on complete AND stop

For analysis to ever claim `drained` it must know recon will push no more chunks.
Recon signals this by enqueuing a terminal `L0Chunk` (the marker) onto the run's queue - fire-and-forget, WITHOUT waiting for analysis.
Recon enqueues the marker on BOTH paths: normal completion AND stop/teardown (including an abnormal kill), so analysis can always conclude.
Analysis consumes the marker LAST (FIFO), and only then computes `drained` (marker consumed + at least one pass entered a dispatch = non-vacuity).

**Rationale.** This is the single, minimal remaining coupling: recon says "no more chunks", never "wait for me".
An idle-timeout inference was rejected - it reintroduces a timing/length gate (violates D8) and races a slow recon job.

## D5 - Analysis run keyed by the recon run_id (1:1 now), indexed to allow later relaunch

For now the `analysis_runs` row is keyed by the same `run_id` as its recon run (1:1), so an observer/e2e finds the analysis result by the same id it launched recon with.

**Forward constraint (operator caveat).** The domain model and indexing MUST NOT preclude a later relaunch - a fresh analysis attempt over the same recon `run_id` after a teardown.
Do NOT impose a bare `UNIQUE(run_id)` that would collide on re-creation.
Use a surrogate primary key (an `analysis_run_id`) with `run_id` as a non-unique indexed correlation column, or a `(run_id, attempt)` key - so a future 1:N (multiple analysis attempts per recon run) needs no schema migration.
The 1:1 read path is a convention over that shape, not a hard uniqueness constraint.

## D6 - Recon stop/teardown stops recon only, and never touches analysis

Stopping or tearing down recon kills its running jobs and suppresses their output (the suppression mechanism itself is #76), enqueues the terminal marker (D4), and returns.
It NEVER cancels the analysis task.
The current `run_pipeline` `finally: feed.stop()` (which cancels the consumer on every recon exit) is removed.

**Rationale.** "Recon teardown stops recon only; analysis drains the queue naturally" (operator).

## D7 - Analysis stop is graceful and resumable within the process

Stopping the analysis task lets the CURRENTLY-RUNNING chunk analysis finish to completion; only FURTHER chunks are not consumed.
Stop preserves the queue and its un-consumed chunks (it is "stop pulling new chunks", not "cancel the in-flight one", and not "discard the queue").
A stopped analysis task can be resumed by starting a fresh task that keeps draining the same in-memory queue where it left off.
Stop records status `stopped` (distinct from `drained`), since the queue may be non-empty.

**Rationale.** Operator caveat on stop/resume: never lose the in-flight chunk's work; resume is task-level within the living process (cross-process-restart resume is #88).

## D8 - No internal wall-clock length gate; remove the deadline and grace entirely

`ANALYSIS_DRAIN_DEADLINE_S` and the interim drain-grace mitigation are removed.
The analysis task drains the queue naturally and sequentially with no internal wall-clock bound.
The only internal bounds are the per-call / per-turn / per-job timeouts (#73 for LLM calls; `EXEC_TIMEOUT_S` / `CRAWL_JOB_TIMEOUT_S` for recon jobs).
Total wall-clock gating for tests lives in the e2e scripts.

**Sequencing.** This removal lands in the SAME change that introduces the independent analysis module and natural drain - removing it earlier reopens the live wedge (run 27386f9c) on the still-coupled architecture.

## D9 - No heartbeat/reaper for analysis liveness

The analysis run has no heartbeat and is not swept by the reaper for slowness.
Because #73 bounds every LLM call (escalating 300/600/900/2700s, then fail-closed), a chunk analysis cannot hang forever; a merely-slow drain is acceptable and the e2e owns total wall-clock.

**Rationale.** The reaper exists to kill hung runs; #73 makes an analysis hang structurally impossible, so a liveness watchdog would only add false positives.

## D10 - Startup reconcile flips orphaned draining analysis runs to interrupted

On process boot, a sweep flips any `analysis_runs` row left `draining` with no live in-memory queue to `interrupted` (mirroring the recon zombie-reaper's stale-run sweep).

**Rationale.** The in-memory queue dies on a process teardown while the table persists, so without this a crashed/redeployed run leaves a visibly-wrong `draining` zombie.
Queue persistence (#88) later upgrades `interrupted` to a true resume.

## D11 - Keep the process-global one-pass-in-flight semaphore

`ANALYSER_PASS_SEMAPHORE` (one analysis pass in flight process-wide, across ALL runs) is retained.
Independent analysis runs still serialize through it.

**Rationale.** It is the memory guard the FR-STREAM/NM-7 ledger required; independence changes lifecycle, not the residency bound.

## D12 - The per-run FIFO stays unbounded; memory bounded by run lifetime

The per-run `L0Chunk` FIFO is unbounded (chunks are KB-scale; the historical OOM was analyser residency, not queue payload - operator decision, #74).
No blocking back-pressure is added (it would reintroduce the recon<->analysis coupling this redesign removes).
Process memory is bounded by run lifetime (the queue is discarded on teardown, D1).

**Residual risk (recorded).** The independent split introduces a new mode: a recon-only run that pushes chunks while analysis is NEVER started grows its queue unboundedly for the run's lifetime.
This is an operator responsibility (do not start recon-only without eventually draining it); it is not guarded in code for now.
