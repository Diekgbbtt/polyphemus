# Module runtime architecture: the interaction pattern and lifecycle

*Status: reference architecture for the module-runtime-independence workstream. Amended 2026-08-12 by operator ruling: ONE shared worker loop (the per-module-loop design is REVERSED), per-module lifecycle state machines, per-module gate, run-terminal flush. Amended 2026-08-12/13 by the ratified spec (#118) and #121 ACs: ONE shared 64-thread default executor (the existing `main.py` process-wide pool) - per-module pools, `runtime.get_pool`, and `HUNTING_POOL_SIZE` are RETIRED (the earlier per-module-pool text in this document is superseded). Rulings Q1-Q6, G1-G7c remain binding except where this amendment supersedes them (per-module loops, per-module pools, the threading pass gate, and the pure-queue Event feed subscription are retired). The hunting module's obligations are the same as in `hunting-module-runtime-seam.md`.*

This document answers one question precisely - which interaction pattern the reframed runtime implements - and walks through every lifecycle path the process can traverse, naming the abstractions that implement each behaviour.

## 0. The short answer

The pattern is NEITHER pure RPC NOR partial RPC. It is:

- **Control path**: the control plane holds a per-module handle (pool, index, run-task registry, lifecycle state) and invokes the ONE shared worker loop through `run_coroutine_threadsafe` / `call_soon_threadsafe`. The runtime manager is a plain registry/coordinator object on the API thread, not a thread.
- **Data path**: an in-loop FIFO (`asyncio.Queue`). Recon pushes curated `L0Chunk` payloads with `put_nowait`, the analysis consumer drains them on the SAME loop, exactly as the proven pre-reframe code does. There is no cross-loop feed machinery at all.
- **Width control**: a per-module `asyncio.Semaphore` guarding analyser passes (the measured memory guard), per module, width configurable. Same-loop, cancellation-safe, no executor, no leak.

The topology: TWO owner threads. The uvicorn API thread runs the HTTP adapter, the manager, the reaper, startup and shutdown. ONE worker loop (an `asyncio.Runner` thread) runs every module's tasks - recon runs, analysis consumers, hunting runs. Module-tagged blocking work offloads via `asyncio.to_thread` onto the ONE shared 64-thread default executor (the existing `main.py` process-wide pool, `thread_name_prefix="runtime-executor"`); the module context (`ContextVar`) routes checkpointer resolution and carries the module attribution onto the shared executor (G3, entry-point residency).

## 1. Why this pattern - and the topology record

RPC is the right tool only across a message boundary: separate processes, separate address spaces, serialization, request/reply correlation. The ratified reframe creates NO such boundary. The real forks were one loop versus N loops versus N processes, and the 2026-08-12 review settled them:

| Candidate | Assessment | Verdict |
|---|---|---|
| N processes | Real isolation (a crash takes one module), real parallelism (no shared GIL). Cost: a protocol (RPC), serialization, the memory guard becomes cross-process accounting, resumption semantics for every module. | Rejected: contradicted the goal (lifecycle independence, not load) and the memory budget. Noted as the evolution seam (section 8). |
| N loops (one per module) | Gives scheduling isolation and blocked-loop containment - insurance against a discipline failure inside one module wedging another. Costs: the entire cross-loop rulebook. The threading pass gate exists only because passes cross two loops; the parked-thread feed subscription exists only because the queue must not bind a loop; the verb discipline and ContextVar loop-routing exist only because there are four loop threads. Under the GIL there is no CPU-parallelism gain, and a crash still takes the whole process (no isolation). | REVERSED 2026-08-12. The insurance was unquantified; the tax was the rulebook and three concrete failure modes (gate deadlock / permit leak on cancel, feed thread-park + pool starvation + shutdown hang, loop-affinity discipline erosion). |
| ONE worker loop (RATIFIED) | The API loop and the worker loop separate - which already insulates the API, health, and reaper from module work (the historical Defect C failure was thread starvation INTO the API loop; the split fixes that case regardless of N). All module tasks share the worker loop: stopping/starting/pausing a module is task-registry and state-machine work, not loop surgery. The gate reverts to today's `asyncio.Semaphore`; the feed reverts to today's `asyncio.Queue` consumer; the cross-thread surface shrinks to the two verbs already used today. | RATIFIED 2026-08-12. Lifecycle independence is delivered by the state machine, not by the loop count. |

Everything in this document that mentions a cross-loop mechanism is gone: the threading pass gate + gate executor, the `threading.Event` feed subscription, per-module event loops, the `runtime.get_loop` verb.

## 2. The thread and ownership map

```
                    API thread (uvicorn loop)
                    RuntimeManager (plain object, NOT a thread)
                    HTTP handlers, reaper, startup, shutdown
                       |  runtime.schedule / runtime.cancel_run
                       |  run_coroutine_threadsafe / call_soon_threadsafe
                       v
               +----------------------+
               |  WORKER LOOP         |         ONE SHARED EXECUTOR
               |  (asyncio.Runner)    |         (64-thread default pool,
               |  recon pipeline task | <---->  thread_name_prefix=runtime-executor;
               |  analysis consumers  |         asyncio.to_thread offloads,
               |  hunting runs        |         context-routed per module)
               |  per-module FIFOs    |
               |  per-module gates    |
               +----------------------+
                       |  module indexes (lock-guarded for reads)
                       v
               +--------------------------------+
               |  #94 pooled PG saver (pre-warmed|  run registry / hunting_runs /
               |  flush target, G1;              |  analysis_runs / graph (shared
               |  InMemorySaver fallback)        |  durable store)
               +--------------------------------+
```

Ownership rules - the shrunken rulebook:

1. **The worker loop's asyncio objects are touched only from the worker loop thread**, or through the two sanctioned verbs (`run_coroutine_threadsafe` to start work, `call_soon_threadsafe` for plain callbacks like a cancellation). The API thread never touches a module task, feed, or gate directly.
2. **The manager is touched only from the API thread** (like an asyncio object). Its only callers are the HTTP handlers and `main.py` startup/shutdown.
3. **Threading primitives guard only cross-thread structures**: the per-module index lock (the resume scaffold reads indexes cross-thread) and the executor internals. Nothing else is shared across threads.
4. **The `ContextVar` module context is copied, never mutated, across threads**: `copy_context` carries it into executor work, so offloaded work resolves the right module checkpointer and carries module attribution (G3, entry-point residency).
5. **The #94 pooled PG saver is thread-safe by construction** (a psycopg connection pool): opened at startup, closed at shutdown after the last flush (G1).

## 3. The sanctioned interaction verbs

The complete cross-thread contact surface - there is nothing else:

| Verb | Implementation | Semantics |
|---|---|---|
| `runtime.schedule(module, coro, *, name)` | `run_coroutine_threadsafe` onto the worker loop | Boots a run. Returns a `concurrent.futures.Future` as an outcome handle (finished or raised). Refused while the module is `paused` / `draining` / `stopped`. |
| `runtime.cancel_run(module, run_id)` | `call_soon_threadsafe(task.cancel)` | Hard-cancels the run's task from the module's registry. The phase-1 STOP verb. |
| `runtime.pause(module)` / `runtime.resume(module)` / `runtime.drain(module)` | manager state machine | Lifecycle verbs; see 5.10-5.11. |
| Blocking work (`asyncio.to_thread`) | the ONE shared 64-thread default executor (the existing `main.py` process-wide pool) | Module-tagged blocking work offloads onto the shared executor, context-routed; never a per-module pool, never the worker loop. |
| `agent_contexts(run_id, phase, tool)` | lock-guarded index read | Read-only enumeration of committed pod contexts (G7a). |
| `register_module(name, hooks)` / `runtime.shutdown()` | fan-out | Registration and the ordered shutdown walk (G7c). |

Everything else stays inside the worker loop. Lifecycle functions (`start_analysis`, `stop_analysis`, `_launch_pipeline`, `run_pipeline`, `start_hunting`) are plain coroutines that run as tasks on the worker loop; the unit tier calls them directly with `asyncio.run`, unchanged (G4). The feed push/consume and the gate acquire are plain in-loop asyncio operations - today's proven code.

## 4. The abstractions catalogue

| Abstraction | Thread affinity | Role | Test seam |
|---|---|---|---|
| `RuntimeManager` (`app/runtime.py`) | API thread only | Plain registry/coordinator: module handles, run-task registries, the per-module lifecycle state machines, the shutdown fan-out. | Instantiated as a plain object; one real `asyncio.Runner` thread in fixtures (G7b). |
| `ModuleHandle` | Handle on the API thread; pointed-to state on the worker loop | `{name, index, tasks: dict[run_id -> Task], state: created/running/paused/draining/stopped, hooks}` | Per-module fixture. |
| `module_context(name)` | ContextVar | Async context manager; entry-point residency (G3). Set at: `run_pipeline` (recon), the supervise/consume task and `run_analyser_chunked` (analysis), `start_hunting` (hunting, #110). Propagates via `copy_context`; routes checkpointer resolution and carries module attribution onto the shared executor. | Direct `asyncio.run` tests. |
| `ModuleIndex` | Worker loop, lock-guarded for reads | Per-module in-memory checkpointer index, lazily built on first resolution; flush hooks iterate it (run-terminal + shutdown); read-only enumeration for `agent_contexts`. | Unit tests with a fake saver. |
| `get_session_checkpointer()` | worker loop (fallback anywhere) | Resolves: context set -> module index -> per-thread in-memory saver + in-memory store; unset -> shared `InMemorySaver` fallback. | Existing checkpointer tests keep passing against the fallback. |
| #94 pooled PG saver (`setup_session_checkpointer`) | none (pool is thread-safe) | Pre-warmed at startup, the flush target of every module, closed at shutdown after flushes (G1). | No-DSN tests hit the `InMemorySaver` fallback. |
| `QueuedAnalysisFeed` | worker loop (creation anywhere on it) | The proven consumer engine: unbounded per-run `asyncio.Queue` FIFO, one consumer task per run, one chunk per pass, holding the per-module gate; terminal marker rides the queue; graceful stop preserves it for resume; per-run registry (`get_or_create_feed`/`drop_feed`). | Existing feed tests; gate injectable. |
| `InlineAnalysisFeed` | caller's task | The rollback path (`async_analysis_consumer=False`): the same chunk pass on the caller's task, identical semantics, acquires the SAME analysis gate. | Existing. |
| Per-module pass gate | worker loop | An `asyncio.Semaphore` instance per module (default width 1 for the analysis module, env-configurable), the measured memory guard: one analyser pass in flight per analysis module. Cancellation-safe by construction (asyncio semantics). | Fake gate injected into the feed. |
| `SessionAddress` | pure | Deterministic `thread_id` composition `(module, run, phase, tool, discriminator)`; no UUID/time sources (the address audit, G7a). | Pure-function tests. |
| `ShutdownFanOut` | API thread | Ordered walk: stop accepting -> hard-cancel in-flight (default) or the module's registered graceful termination feature -> flush indexes into the still-open #94 pool -> close pools -> stop the worker loop (G7c). | Fixture modules with recorded hooks. |
| Run registry + reaper + run-terminal flush | API thread + worker loop | Heartbeat TTL sweeps on the API loop; startup orphan reconciles (recon, `analysis_runs`, `hunting_runs` -> `interrupted`); each module run flushes its index when the run reaches a terminal status (bounds crash loss to the in-flight run). | Unit tests against the gateway. |

## 5. Lifecycle walkthroughs

Notation: `[API]` = API thread, `[work]` = worker loop. All paths are the TARGET architecture.

### 5.1 App startup

1. `[API]` `configure_logging`; schema setup (`pg.ensure_checkpoint_tables`, `ensure_recon_schema`, neo4j schemas), `validate_llm_config`.
2. `[API]` `setup_session_checkpointer()` opens the #94 pooled PG saver - the pre-warmed flush target (G1). Fail-open to `InMemorySaver` with no DSN.
3. `[API]` construct the `RuntimeManager`; create the worker loop (`asyncio.Runner` thread, idle); for each module (recon, analysis, hunting): create the `ModuleHandle` (state `created`, pool created lazily) and `register_module(name, {flush, termination})`.
4. `[API]` transitions each module to `running`; startup reconciles: `reap_stale_runs` (TTL), `reconcile_orphaned_analysis_runs` -> `interrupted`, the `hunting_runs` orphan reconcile -> `interrupted`. In-memory indexes are NOT restored (archive seam).
5. `[API]` start the reaper task. The process is serving.

### 5.2 Combined recon + analysis launch (`POST /projects/{id}/recon`, `with_analysis=true`)

1. `[API]` handler: `repository.open_run` -> `run_id`; `runtime.schedule("recon", run_pipeline(...))` and `runtime.schedule("analysis", start_analysis(...))` - both via `run_coroutine_threadsafe` onto the worker loop; each returns an outcome Future.
2. `[work]` `run_pipeline` enters with `module_context("recon")` for its full duration. Per job: pods offload onto the recon pool (context copied); each job's curated `L0Chunk` is pushed via `feed.push` (a `put_nowait`, never blocking); the heartbeat loop bumps the run row via `to_thread`.
3. `[work]` on job completion or stop, `feed.signal_end()` puts the terminal marker (fire-and-forget). The recon run reaches `complete` WITHOUT waiting for analysis.
4. `[work]` `start_analysis` enters with `module_context("analyse")`; creates the `analysis_runs` row (`draining`); the consumer drains the per-run FIFO (`ensure_future(queue.get())` + `asyncio.wait` against the stop event, one chunk per pass, exactly once, in push order); each pass holds the per-module analysis gate (`async with`).
5. `[work]` the terminal marker is consumed LAST (FIFO); the run classifies `drained` / `withheld`; the supervisor persists the `analysis_runs` status; a truly terminal drain calls `drop_feed` (memory bound); the run-terminal flush archives the analysis index.
6. `[API]` the manager's task-registry callbacks pop the run ids when the run tasks finish.

### 5.3 Recon-only launch / 5.4 Analysis-only launch and resume

Identical launcher mechanics; the analysis-only handler validates the run exists, then schedules `start_analysis`, whose consumer attaches to the existing feed; after a graceful stop the preserved queue is drained (resume, D7). A fresh `analysis_run_id` surrogate is minted per attempt (D5).

### 5.5 Recon stop (`POST /projects/{id}/recon/{run_id}/stop`)

1. `[API]` `runtime.cancel_run("recon", run_id)` -> `call_soon_threadsafe(task.cancel)` -> `[work]`.
2. `[work]` the pipeline's `finally` enqueues the terminal marker (`feed.signal_end`), so the independent consumer can still drain what was already pushed. Analysis is never touched here.

### 5.6 Analysis stop (app-initiated, graceful)

1. `[API]` handler awaits `stop_analysis(run_id)` scheduled onto the worker loop (marshalled by the handler, G4).
2. `[work]` the consumer finishes its in-flight chunk, consumes no further chunk, sets `stopped`; the queue is preserved; the supervisor persists `stopped`; the run-terminal flush archives the analysis index.

### 5.7 Hard cancel (app-initiated, abnormal)

`runtime.cancel_run("analysis" | "recon", run_id)` propagates a task cancellation into the run task. Used only where hard semantics are demanded; graceful stop is the default everywhere.

### 5.8 Hunting launch / 5.9 Hunting stop (phase-1)

1. `[API]` `runtime.schedule("hunting", start_hunting(...))` -> `[work]`; `start_hunting` enters with `module_context("hunting")`, runs the orchestration (stateful turns resolve the hunting index), writes the `hunting_runs` status lifecycle, and triggers the run-terminal flush.
2. `[API]` `runtime.cancel_run("hunting", hunting_run_id)` - hard cancel (phase-1 STOP); the append-only hunt store preserves the partial trail. Graceful stop is a later ticket.

### 5.10 Module pause / resume (NEW - the direct deliverable of the goal)

1. `[API]` `runtime.pause("analysis")` flips the module's state machine to `paused`.
2. `[work]` `paused` has two effects, both at dispatch entry points, never in-flight: `runtime.schedule` for that module is refused (no new runs), and the module's current dispatch unit does not start the NEXT unit (recon: no next job; analysis: no next chunk pass after the in-flight one; hunting: no next fault pair after the in-flight turn).
3. Run tasks, heartbeats, and persistence stay alive, so the reaper does not touch the paused module's runs; the FIFOs keep accumulating what producers push (D8 unbounded stands - pause duration is operator time, and memory is bounded by run lifetime).
4. `[API]` `runtime.resume("analysis")` returns the module to `running`; dispatch continues from the next unit.

### 5.11 Module drain (graceful module stop)

`runtime.drain("analysis")` = pause plus settle: finish the in-flight unit, dispatch no further, let queued consumers attach nothing new; when the registry empties the module reaches `stopped`; its flush hook archives the index; the pool closes. The module is now stopped while recon keeps running - the independence the goal names, exercised.

### 5.12 Process shutdown (`main.py` `_shutdown`)

1. `[API]` cancel the reaper task; call `runtime.shutdown()`.
2. `[API -> work]` for each module, in the ratified ordering: stop accepting new work; HARD-cancel in-flight runs by default (drain each run's FIFO, cancel the tasks) - or, when the app requests graceful mode and the module registered one, invoke the module's **termination feature** (finish the in-flight turn, dispatch no further work) instead (G7c).
3. `[API -> work]` run each module's flush hook (the run-terminal flush already archived most state; the shutdown flush covers the tail), writing into the STILL-OPEN #94 pool (fail-open); the ONE shared executor is closed by the manager after the flush (never before).
4. `[API]` stop the worker loop; `close_session_checkpointer()` closes the #94 pool. The process exits.

### 5.13 Crash (no shutdown ran)

1. The process dies without any hook firing: in-memory indexes lose only what was not yet archived. The run-terminal flush bounds that loss to the in-flight run's tail (the G1 consequence is thereby narrowed).
2. Run rows stay `live`/`draining`/`running` until the heartbeat TTL expires; the reaper (or the next startup reconcile) flips them: recon runs -> `failed`, `analysis_runs` -> `interrupted`, `hunting_runs` -> `interrupted`.
3. A future resume agent can enumerate what a run had committed through `agent_contexts` (thread_ids are deterministic per the address audit); the memory itself is not restored by design.

### 5.14 Feed lifecycle within a run

first touch creates and registers the feed -> recon pushes chunks -> terminal marker -> consumer drains -> `drained`/`withheld` retires the feed (`drop_feed`) -> graceful stop preserves it -> a later attach resumes the preserved queue.

### 5.15 Checkpointer lifecycle

first stateful turn under a module context -> index lazy-build (in-memory saver + in-memory store per thread) -> subsequent turns in that module resolve the same pair -> the supervisor graph compiles against the in-memory pair (Q2/Q3b) -> run-terminal flush archives the committed threads -> the shutdown flush covers the tail -> the #94 pool closes. An un-contexted call (bootstrap, admin reads) resolves the shared `InMemorySaver` fallback.

### 5.16 Executor lifecycle (ONE shared)

The ONE shared 64-thread default executor (the existing `main.py` process-wide pool) is opened at startup and closed by the manager at shutdown AFTER every module's flush hook has archived into the still-open #94 pool (G7c) - never before, so a flush target is always alive. Blocking work offloads onto it via `asyncio.to_thread`; the module context (`ContextVar`) carries attribution so offloaded work resolves the right module checkpointer. Multiple sub-threads run concurrently - the pod fan-out, analyser passes, and hunting turns all dispatch freely; nothing serialises them except the analysis module's own pass gate.

### 5.17 The pass-gate path (per analysis pass)

1. `[work]` the consumer (or the inline pass) enters `async with analysis_gate:` - an `asyncio.Semaphore` instance owned by the analysis module.
2. The slot is held only for the pass; width 1 by default (the measured memory guard: ~883 MiB peak with one 176-asset pass in flight against a 4.8 GiB limit), env-configurable, so width can be raised after re-measurement.
3. Cancellation is asyncio-natural: a cancelled wait acquires nothing; no thread is parked; nothing can leak.

## 6. Determinism and the resume seam

- Every `SessionAddress` `thread_id` is a pure function of `(module, run, phase, tool, discriminator)`; no UUID or time source enters the composition. The address audit (part of the workstream) proves this by test so post-crash enumeration keys are stable.
- `agent_contexts(run_id, phase, tool)` reads the module indexes (lock-guarded, read-only) and enumerates the committed pod contexts of a run. It contains NO resumption logic; it is the documented contract a future resume agent implements against (G7a).

## 7. What the tests exercise

- The manager is a plain object: fixtures instantiate it with ONE real `asyncio.Runner` thread, drive `schedule`/`cancel_run`/`pause`/`resume`/`drain`, assert task lifecycle and state-machine transitions, and tear the loop down in fixture teardown. No database, no uvicorn, no app boot (G7b).
- The feed is exercised exactly as it is today (same-loop push/consume, terminal marker, graceful-stop/resume pair, gate contention via two consumers over the same per-module gate).
- The concurrency properties that matter are now ordinary asyncio properties: no cross-loop races exist to test.
- App-level wiring (startup/shutdown fan-out, handler marshalling, pause/resume endpoints) is covered by the integration/e2e tier through the live stack.

## 8. Evolution notes

- **Process split**: if a future iteration moves a module into its own process, RPC enters at exactly the two seams that are today in-process: the feed (an `asyncio.Queue` becomes a wire protocol with its own delivery semantics) and the checkpointer store (the shared Postgres it already is). Nothing else in this document changes; the module's index/state-machine pattern and the shared-executor routing survive inside the process.
- **Inline mode** (`async_analysis_consumer=False`) remains a first-class configuration: analysis runs on the recon pipeline task, the feed takes the direct path, the pod seam (`run_analyser_chunked`) sets the analysis context for its duration, and the analysis gate still applies. The pattern does not fork for the rollback path.
- **Retired by this amendment**: the threading pass gate and gate executor, the `threading.Event` feed subscription (pure-queue G5 shape), per-module event loops, the `runtime.get_loop` verb, and the multi-loop ownership rulebook.

(End of file - total 198 lines)