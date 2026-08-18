# Assertions - module runtime independence (#118): the six-substream system

**Source:** spec #118 (`gh issue view 118`); architecture `docs/design/module-runtime-architecture.md`; hunting seam `docs/design/hunting-module-runtime-seam.md`. The system spec subsumes six work-item tickets: #119 session-address helper, #120 checkpoints refactor, #121 runtime manager + lifecycle + feed + gate, #122 app wiring, #123 hunting control-plane machinery + startup reconcile, #124 resume-seam scaffold + session-address audit.
**Seams under assertion:** the manager verb surface (`register_module`, `schedule`, `cancel_run`, `pause`, `resume`, `drain`, `shutdown`, `has_run`, `run_ids`, `get_active_runtime`) in `app/runtime.py`; the dispatch mechanism and ONE shared executor (`run_coroutine_threadsafe` / `call_soon_threadsafe`, `asyncio.to_thread`, `runtime.executor`, `WORKER_THREADS`); the per-module gate (`ModuleGate`, module-runtime-architecture section 5.17); the module-context/checkpointer seam (`module_context`, `get_session_checkpointer`, `ModuleIndex`, `agent_contexts`, `flush_module_index`) in `app/llm/checkpoints.py`; the pure `SessionAddress` composition (`app/llm/session_address.py`); the API launch/stop/lifecycle surface (`project_management/api.py`: `POST /projects/{id}/recon|analysis|hunting`, the `/{id}/stop` handlers, the `/{module}/pause|resume|drain` lifecycle handlers); the run-row store (`db/postgres/init.sql`: `recon_runs`, `analysis_runs`, `hunting_runs`); startup/shutdown wiring (`app/main.py` `_startup`/`_shutdown`); the pg orphan reconciles (`reconcile_orphaned_analysis_runs`, `reconcile_orphaned_hunting_runs`).
**Live edges:** the recon/hunting walkthroughs need a live target at the outer boundary - the eval target registry `tests/e2e/fixtures/eval-targets.yaml`; the checkpoint walkthroughs need the live Postgres stack (`POSTGRES_DSN`, or they degrade to `InMemorySaver` and the predicate is carried, not substituted).
**Oracle discipline:** every expected status/value is taken from the spec and the ratified architecture, never recomputed the way the code computes it. Repeated-composition expectations are byte-identical by construction, never "renders the same shape".

## Contract predicates (integration tier)

### Manager verb surface (#121)

- **C1** | seam: `RuntimeManager` + the worker loop | delivery: success shape
  input: one real `asyncio.Runner` thread, `register_module("recon")`, `schedule("recon", work(), name="run-1")` where `work` records `asyncio.get_running_loop()` and `threading.current_thread()` and returns `"done"`
  observable: `schedule` returns a `concurrent.futures.Future`; `fut.result(timeout=5) == "done"`; the recorded loop is `runtime.loop`, the recorded thread is `runtime.worker_thread` (ONE shared worker loop - the ratified topology)
  yields: `tests/app/test_runtime_manager.py::test_schedule_boots_a_run_on_the_worker_loop`

- **C2** | seam: `RuntimeManager.schedule` admission | delivery: malformed/out-of-range
  input: a module in `paused`, `draining`, or `stopped` state; `schedule(module, work(), name="run-x")`
  observable: `ModuleAdmissionRefused` raised; the run is NOT registered (`run_ids(module)` unchanged)
  yields: `tests/app/test_runtime_manager.py` admission-refusal cases

- **C3** | seam: `RuntimeManager.cancel_run` | delivery: success + degradation
  input: (a) a registered run `cancel_run(module, run_id)`; (b) an unregistered id `cancel_run(module, "nope")`
  observable: (a) the registered task is hard-cancelled via `call_soon_threadsafe(task.cancel)` and unregisters; (b) `RunNotRegistered("nope")` raised, nothing else touched
  yields: `tests/app/test_runtime_manager.py` cancel cases

- **C4** | seam: `RuntimeManager.pause`/`resume` | delivery: ordering/concurrency
  input: recon + analysis running concurrently; `pause("analysis")`, then `resume("analysis")`
  observable: while paused the analysis module admits no new runs and its gate holds the next unit at dispatch; recon keeps progressing; after resume analysis dispatches the next unit and its registry refills; no permit/handle leak across the pause+resume cycle (`available_permits` returns to width)
  yields: `tests/app/test_runtime_manager.py` pause-isolation + no-permit-leak cases

- **C5** | seam: `RuntimeManager.drain` | delivery: ordering/concurrency
  input: an analysis module with a registered run, a flush hook on the handle; `drain("analysis")`
  observable: after settle the module reaches `ModuleState.STOPPED`, its registry is empty, and its flush hook ran exactly once (fail-open, archive before return)
  yields: integration-tier drain+flush test

- **C6** | seam: `RuntimeManager.shutdown` (ShutdownFanOut) | delivery: ordering
  input: three registered modules (recon, analysis, hunting) with recorded hooks + a shared pool/loop; `shutdown()` then `close_session_checkpointer()`
  observable: the ordering is stop-accepting -> hard-cancel in-flight -> flush each module's index into the STILL-OPEN pooled saver -> close the executor -> stop the worker loop -> ONLY THEN the pool closes; recorded order matches G7c exactly; pause must never flush
  yields: integration-tier shutdown-ordering test with recorded hooks

- **C7** | seam: per-module `ModuleGate` | delivery: concurrency + cancel-while-waiting
  input: two consumers contending over one analysis gate (width 1); a consumer cancelled while waiting on a paused gate
  observable: at most one pass in flight (width bound holds); the cancelled wait acquires nothing; after the cancel `available_permits` returns to width (no permit leak on pause+resume and cancel-while-waiting, #121 AC(c))
  yields: `tests/app/test_runtime_manager.py` no-permit-leak cases + feed contention tests

### Module-context / checkpointer seam (#120, #124)

- **C8** | seam: `module_context(name)` + `get_session_checkpointer()` | delivery: success shape
  input: a stateful turn executed under `module_context("analysis")`; a second stateful turn without any context
  observable: the contextualized turn resolves the analysis module's per-module `ModuleIndex` (per-thread in-memory saver + store); the un-contexted call resolves the shared `InMemorySaver` fallback; neither leaks into the other
  yields: `tests/test_llm_checkpoints_module.py` (existing module-context tests)

- **C9** | seam: `agent_contexts(run_id, phase, tool)` | delivery: empty-valid + read-only
  input: (a) a run with committed pod contexts (matching and non-matching phases/tools); (b) an absent run/phase/tool; read the enumeration twice
  observable: (a) exact sorted list of matching thread_ids, nothing else; (b) `[]` - an empty enumeration, NEVER an error; reading does not mutate the committed sets (read-only, lock-guarded)
  yields: `tests/app/test_resume_seam_audit.py` (empty-never-error + read-only cases)

- **C10** | seam: `agent_contexts` upstream compatibility with #121 | delivery: success shape
  input: a real `RuntimeManager` worker loop schedules runs whose committed pod contexts are enumerated from a second thread
  observable: the API-thread enumeration equals the worker-loop committed set; no new manager verb and no new cross-thread surface (`hasattr(runtime, "agent_contexts") is False`)
  yields: `tests/app/test_resume_seam_audit.py` upstream-compat case

- **C11** | seam: `flush_module_index(module, run_id)` + run-terminal/shutdown flush hooks | delivery: degradation + duplicate-idempotent
  input: (a) flush with no open pooled saver; (b) flush the same module twice; (c) a failing underlying flush
  observable: (a) a safe no-op (never raises); (b) idempotent - no duplicate archive, no raise; (c) warns and drops that thread, never raises (fail-open)
  yields: `tests/app/test_llm_checkpoints_module.py` flush-hook tests

### SessionAddress determinism (#119, #124)

- **C12** | seam: `SessionAddress` composition (`AnalysisSession`, `HuntSession`, `ModuleScopedSession`, `PodSession`) | delivery: success + duplicate-idempotent
  input: the full #119 discriminating matrix - all three modules x each of phase/tool/discriminator/role present and absent x an over-long discriminator - composed 25 times
  observable: each thread_id is byte-identical across all 25 compositions; the hand-escaped literal set `(module:run:phase:tool:disc:role)` matches byte-for-byte; a None/empty discriminator never shifts the address (drop not shift); an over-long discriminator is hash-bounded but stays unique; NO UUID/time/random/datetime/secrets/os source can influence the composition (module-import audit + monkeypatched sources)
  yields: `tests/app/test_resume_seam_audit.py` (matrix + structural half) and `tests/test_session_address.py` (existing boundary cases)

### Startup/shutdown wiring + reconcile (#122, #123)

- **C13** | seam: `app/main.py` `_startup` | delivery: success shape + degradation
  input: boot the app with a stubbed stack (monkeypatched pg/neo4j/llm, per `tests/app/test_app_runtime_wiring.py::_stub_startup`)
  observable: `app.state.runtime` is a started `RuntimeManager`; recon, analysis, and hunting modules are all registered (hunting carries `hooks={"flush": flush_hunting_checkpointer}`); startup runs `reap_stale_runs`, `reconcile_orphaned_analysis_runs`, and `reconcile_orphaned_hunting_runs` in that order; the reaper task is started
  yields: `tests/app/test_app_runtime_wiring.py` startup-wiring cases + new reconcile-assertion cases

- **C14** | seam: `app/main.py` `_shutdown` | delivery: ordering + degradation
  input: `_shutdown()` with a runtime present; `_shutdown()` with no runtime (`app.state.runtime` absent, partial-startup failure)
  observable: with runtime: reaper cancelled -> `runtime.shutdown()` -> `close_session_checkpointer()` LAST; without runtime: `close_session_checkpointer()` still runs, no crash
  yields: `tests/app/test_app_runtime_wiring.py` shutdown cases

- **C15** | seam: `reconcile_orphaned_*` in `app/clients/pg.py` | delivery: duplicate-idempotent
  input: run each reconcile twice over the same orphaned rows (`draining` analysis rows, `running` hunting rows)
  observable: the first run flips each orphan to `interrupted`; the second run flips zero rows (idempotent); no live row is touched
  yields: `tests/app/test_hunting_runs.py` + `tests/app/test_analysis_runs.py` reconcile cases

### API fail-closed behavior (#121, #122, #123)

- **C16** | seam: API launch/stop handlers with NO active runtime | delivery: degradation
  input: `POST /projects/{id}/recon`, `POST /projects/{id}/recon/{run_id}/stop`, `POST /projects/{id}/hunting` against an app whose runtime never started
  observable: recon launch raises (no manager active) and the handler 503s; recon stop 503s; hunting launch 503s with `hunting_control_plane_available() is False` - a real orchestration pass never rides the uvicorn request loop
  yields: `tests/app/test_app_runtime_wiring.py` fail-closed cases

- **C17** | seam: API launch/stop handlers WITH the active runtime | delivery: success shape
  input: `POST /projects/{id}/recon` (recon-only and combined), `POST /projects/{id}/analysis`, `POST /projects/{id}/hunting`, and each `/{id}/stop` with a stubbed pipeline/hunt
  observable: each launch routes through `runtime.schedule("<module>", ..., name=run_id)` and the stop handlers through `runtime.cancel_run`; the run is registered (`runtime.has_run(module, run_id) is True`) while live and unregisters at terminal; hunting launch returns 201 once `hunting_control_plane_available()` flips live (the #123 503->live flip)
  yields: `tests/app/test_app_runtime_wiring.py` launch/stop + hunting-flip cases

### Dispatch mechanism and thread consumption (#118 topology, #121)

- **C18** | seam: `RuntimeManager.schedule` dispatch mechanism | delivery: success shape
  input: a module run whose `work()` records `asyncio.get_running_loop()` / `threading.current_thread()`; drive `schedule` from the API/test thread while a second run is in flight
  observable: the run's coroutine executes on `runtime.loop` / `runtime.worker_thread` (ONE shared worker loop); dispatch is `run_coroutine_threadsafe` (never a bare `create_task` on the caller's loop); the outcome is a `concurrent.futures.Future`
  yields: `tests/app/test_runtime_manager.py` worker-loop-affinity cases

- **C19** | seam: blocking work offloads onto the ONE shared executor | delivery: concurrency + ordering
  input: inside a module run, an `await asyncio.to_thread(blocking_sync_fn)` where `blocking_sync_fn` records its `threading.current_thread().name` and blocks ~0.5s; a second module run launched while the first is blocked
  observable: the blocking call executes on a thread whose name starts `runtime-executor` (the shared default executor, `max_workers=WORKER_THREADS`, one instance - `runtime.executor is not None` and the module registry has no per-module executor, `get_pool` absent); while it blocks, the worker loop stays responsive (the second run progresses); the blocked run resumes and completes
  yields: integration-tier offload-attribution test (thread-name prefix + responsiveness)

- **C20** | seam: module attribution across the dispatch | delivery: success shape + concurrency
  input: a recon run and an analysis run both offload blocking work via `asyncio.to_thread`; each offloaded fn reads the module `ContextVar` under `copy_context`
  observable: each offloaded fn resolves its OWN module's context/checkpointer index (recon work resolves recon, analysis work resolves analysis - the ContextVar copy carried the attribution); no cross-module bleed
  yields: `tests/test_llm_checkpoints_module.py` module-context tests + offload attribution case

- **C21** | seam: worker loop does NOT block on module I/O | delivery: degradation/concurrency
  input: one module run holds a long `asyncio.to_thread` blocking call (e.g. a pg accessor); the API/health path (`runtime.call`, a second `schedule`) is exercised concurrently
  observable: the API path and the second run complete while the first is still offloaded (the worker loop is never the thread that runs blocking pg/io - Defect C thread-starvation case is closed); no stall
  yields: integration-tier responsiveness test (the historical Defect C regression guard)

## Walkthrough predicates (end-to-end tier)

- **E1** | grounds: user stories 1-4, 10-12 - pause one module while the others keep progressing, both kept at the same wall-clock time | entry seam: `POST /projects/{id}/recon` then `POST /projects/{id}/analysis`
  input: a live eval target from `tests/e2e/fixtures/eval-targets.yaml`; body `{"jobs": [...], "with_analysis": true}` and the analysis body `{"run_id": "<same run>"}`
  live edge: the eval target (live site, per eval-targets) - nothing inside it is substituted
  path: `launch_recon` opens a `recon_runs` row (`running`) and schedules `run_pipeline` on the recon module; `pipeline` pushes chunks to the run's FIFO; analysis consumes under `module_context("analysis")`; the test then `runtime.pause("analysis")` mid-run: recon jobs keep completing, analysis holds at the dispatch gate; `runtime.resume("analysis")` drains the accumulated FIFO
  terminal: recon run row `complete` with `finished_at` set; analysis run row terminal (`drained`/`withheld`) with its `stats` census present; job rows each terminal; the analysis `stats.dispatches_entered` equals the count of pushed chunks plus the terminal marker
  observed: `SELECT * FROM recon_runs/analysis_runs` read back; pause/resume observed through `recon_jobs` rows and `analysis_runs.stats` advancing only after resume
  yields: `tests/e2e/test_module_runtime_walkthrough.py::test_E1_pause_isolates_analysis_while_recon_progresses`

- **E2** | grounds: user story 3, decision 5.11 - drain analysis to a clean stopped state while recon stays up | entry seam: `POST /projects/{id}/recon` plus a `runtime.drain("analysis")` drive
  input: live target; a running combined run; `runtime.drain("analysis", timeout=...)`
  live edge: the eval target (live)
  path: recon keeps running; `drain` pauses analysis, settles its runs to an empty registry, runs the analysis module's flush hook (archiving its index), and reaches `stopped`; recon produces no new analysis (its FIFO accumulates an inbound queue that only the resumed/relaunched consumer drains)
  terminal: analysis module `ModuleState.STOPPED`, registry empty, index flushed (committed threads present in the PG saver), recon run still `running`/`complete`; no recon row touched by the drain
  observed: the flush hook's archive read back from the pooled PG saver via `agent_contexts(run_id, ...)`
  yields: `tests/e2e/test_module_runtime_walkthrough.py::test_E2_drain_analysis_while_recon_stays_up`

- **E3** | grounds: user story 7, decision "Hunting integration" + #123 AC - the 503->live flip and hunting launches boot on the worker loop | entry seam: `POST /projects/{id}/hunting`
  input: live target; `{"candidates": [{"unit_id": ..., "fault_class": ..., "..."}]}` per the `HuntingLaunch` schema
  live edge: the eval target (live) where the hunt's graph engine behaves
  path: `launch_hunting` 503s while the runtime has not landed; once the app boots with the hunting module registered it 201s, mints a `hunting_runs` row (`running`), and `runtime.schedule("hunting", start_hunting(...), name="hunting:<id>")`; `start_hunting` runs the orchestration under `module_context("hunting")`, its pg calls offload via `asyncio.to_thread`, and it persists a terminal status
  terminal: `hunting_runs.status` is `complete` (or `failed` if the pass degraded - never a crash through the control plane); `POST /{id}/hunting/{rid}/stop` while `running` yields `stopped`; the partial append-only trail is preserved
  observed: `SELECT status FROM hunting_runs WHERE hunting_run_id = ...`; the stop handler's `{"stopping": true}` response
  yields: `tests/e2e/test_module_runtime_walkthrough.py::test_E3_hunting_launch_flips_503_to_live_and_hunts`

- **E4** | grounds: user story 5 - stop one module's run without touching the others | entry seam: `POST /projects/{id}/recon/{run_id}/stop`
  input: a combined recon+analysis run on a live target, mid-run; `POST /projects/{id}/recon/{run_id}/stop`
  live edge: the eval target (live)
  path: the stop handler `runtime.cancel_run("recon", run_id)`; the recon pipeline's `finally` enqueues the terminal marker (`feed.signal_end`); the independent analysis consumer drains what was already pushed; analysis is never cancelled
  terminal: recon run cancelled (task gone from the recon registry; the run row reaches its terminal via the pipeline), analysis run still reaches its own terminal census; no other run touched
  observed: `recon_jobs`/`recon_runs` row transitions + the analysis `stats` census read back
  yields: `tests/e2e/test_module_runtime_walkthrough.py::test_E4_stop_recon_leaves_analysis_untouched`

- **E5** | grounds: user stories 6/8, decisions G7c + 5.13, #119/#124 - crash-bound loss + deterministic resume keys | entry seam: a launched run then a hard process kill, then a fresh boot; the resume seam reads back
  input: live target; launch a combined run, let it commit threads, `kill -9` the app process mid-run (no shutdown hook fires); reboot the app with the same DB
  live edge: the eval target (live); the Postgres stack must be live (no DSN means the predicate is carried, not substituted)
  path: on reboot `_startup` runs the reconciles: the orphaned `draining` analysis row and `running` hunting row (if any) flip to `interrupted`; committed thread ids are re-derived via `agent_contexts(run_id, phase, tool)` from the flushed index
  terminal: post-reboot rows show `interrupted` for the orphans (exact count = the rows left `running`/`draining`); `agent_contexts` enumerates the SAME byte-identical committed thread_ids as before the kill (the #124 fresh-registry re-derivation); no row is `running`/`draining` with no live engine behind it
  observed: `SELECT status FROM analysis_runs/hunting_runs` after reboot + `agent_contexts(...)` comparison
  yields: `tests/e2e/test_module_runtime_walkthrough.py::test_E5_post_crash_reconcile_and_deterministic_resume_keys`

- **E6** | grounds: user story 10, decision "Feed and inline mode" - the feed keeps its exact proven semantics | entry seam: the combined launch (E1's launch), then an app-initiated graceful stop and a relaunch that resumes the preserved queue
  input: live target; a combined run; `POST /projects/{id}/analysis/{run_id}/stop` (graceful), then `POST /projects/{id}/analysis` again for the same run
  live edge: the eval target (live)
  path: graceful stop lets the in-flight chunk finish, consumes no further chunk, preserves the FIFO (NOT dropped); the relaunched consumer attaches to the preserved queue and drains the tail
  terminal: the consumed chunk set is identical across the graceful-stop boundary (consume-once, push-order preserved - no duplication, no loss); the run's analysis census counts every pushed chunk exactly once; only a truly terminal drain calls `drop_feed`
  observed: chunk consumption recorded through the run's analysis stats + the feed's preserved-queue registry
  yields: `tests/e2e/test_module_runtime_walkthrough.py::test_E6_feed_semantics_survive_graceful_stop_and_resume`

## Notes for the evaluator

- **Mechanised tier mapping:** C1-C21 are integration-tier (manager/checkpoint/address seams, no live stack for most - a sqlite/stubbed pg may stand in but the reconciles need `app/clients/pg.py` fakes as the prior art does). E1-E6 are e2e-tier and gated on the live stack (docker + Postgres + a live eval target), per the spec's "carried, not substituted".
- **Dispatch mechanism + thread consumption:** C18-C21 are the direct answers to the operator's critique - the dispatch mechanism (`run_coroutine_threadsafe` / `call_soon_threadsafe`), the ONE shared executor offload (thread-name prefix `runtime-executor`, no per-module pools, no `get_pool`), module attribution via the copied `ContextVar`, and the worker-loop non-blocking guarantee (the Defect C regression guard). C1's worker-loop affinity remains the topology anchor.
- **The shared-executor claim** is now asserted directly by C18-C21 (dispatch mechanism + executor thread-name + `get_pool` absence + responsiveness), not merely implied by C1/C2/C8 and E1/E3.
- **Empty vs error:** C9, C11, C15 name the empty/degradation return shapes so a predicate can never read an absence as a failure.
- **The catalogue is the gate:** none of these run in the unit red/green loop (`tests/` pyproject pytest config excludes `tests/e2e` from the default `addopts` selection the loop uses). They are selected only under the verification gate, after the unit tier is claimed done.