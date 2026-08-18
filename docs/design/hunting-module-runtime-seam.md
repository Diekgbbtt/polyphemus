# Hunting module runtime seam

*Status: contract (ratified 2026-08-11; amended 2026-08-12 - single shared worker loop topology, ratified by operator ruling; amended 2026-08-13 - sequential-pipeline premise ratified, per-module pools retired, ONE shared default executor). The control-plane side is delivered by the module-runtime-independence workstream; the hunting-module side is the obligation of the hunting runtime wiring ticket.*

This document specifies the **app module seam**: the contract between the control plane (the runtime manager and the FastAPI layer) and the hunting module, covering bootstrap, stop, and tear-down. It exists so the hunting module's internal orchestration logic can be migrated and wired independently of this workstream, without either side guessing the other's interface.

The hunting module's INTERNAL orchestration logic (the per-fault-unit(s) stateful orchestration pass, the graph workflow, the hunting-agent dispatch harness) is deliberately OUT of scope here. Its contract is carried by its own ticket and by the existing hunting specs (`hunting-67-*`); this seam only says how that logic is BOOTED, STOPPED, and TORN DOWN by the app.

## 1. Roles

- **Control plane**: the uvicorn event loop (loops on API requests), the runtime manager (`app/runtime.py`, a plain registry/coordinator object on that loop, not a thread), and the ONE shared worker loop it owns (all module tasks run on it). Owns the Q4 pools, the Q3 checkpoint registries, the run->task registries, the per-module lifecycle state machines, and the shutdown fan-out.
- **Hunting module**: `src/polymerhus/attack/hunting/`. Consumes the seam. Its internal logic is its own.
- **Seam**: the typed surface in section 2 (provided) and section 3 (obligations).

## 2. What the control plane provides

### 2.1 The hunting runtime

- A place to run: all module tasks - recon runs, analysis consumers, hunting runs - execute on the ONE shared **worker loop** (an `asyncio.Runner` thread created at app startup, stopped at app shutdown, separate from the uvicorn API loop). There is no per-module loop (2026-08-12 reversal): the cross-loop machinery a multi-loop design would force - threading pass gate, cross-loop feed subscription, the loop-routing rulebook - is retired. Hunting runs boot as tasks on the worker loop like every other module run.
- The **shared default executor**: one process-wide `ThreadPoolExecutor` (the existing `main.py:45-49` default, `WORKER_THREADS=64`). Hunting blocking work offloads via `asyncio.to_thread` onto it. There is NO per-module pool and NO `HUNTING_POOL_SIZE` (2026-08-13: per-module pools retired with the sequential-pipeline ruling).
- The **hunting module context**: the `_MODULE_CTX` ContextVar set to `"hunting"` at the module's lifecycle entry points. `copy_context` propagation carries it into executor work, so work offloaded from hunting code resolves the hunting checkpointer automatically. Pool routing is gone - there is one shared executor.
- The **hunting checkpointer index**: an in-memory per-module context index (lazily created, lock-guarded, owned by the worker loop thread). `get_session_checkpointer()` resolves it when the module context is set. The index is flushed TWICE: at run terminal (when a hunting run reaches a terminal status, the committed thread states are archived - bounds crash loss to the in-flight run) and at shutdown (the fan-out flush hook). Target: the #94 process-wide pooled PG saver (pre-warmed at app startup, `setup_session_checkpointer`); per-module threads are isolated in that store by `SessionAddress` namespacing. Fail-open (warn and drop), no restore at startup (archive seam).

### 2.2 Scheduling, lifecycle and cancellation seams

- `runtime.schedule("hunting", coro, *, name) -> concurrent.futures.Future` - schedule a coroutine onto the shared worker loop (`run_coroutine_threadsafe`), refused while the module is `paused` / `draining` / `stopped`. This is how the control plane BOOTS a hunting run.
- `runtime.cancel_run("hunting", run_id)` - hard-cancel a run's task via `call_soon_threadsafe(task.cancel)`. This is the phase-1 STOP.
- `runtime.pause("hunting")` / `runtime.resume("hunting")` / `runtime.drain("hunting")` - the module lifecycle state machine (`created -> running -> paused -> draining -> stopped`). Pause stops module-level admission and the dispatch of the NEXT unit (job / chunk pass / fault pair) after the in-flight one; run tasks, heartbeats, and persistence stay alive, so the reaper does not touch a paused module's runs. Drain = pause plus graceful settle: finish the in-flight unit, dispatch no further, then the module reaches `stopped`.
- The shutdown fan-out calls the hunting module's tear-down in the ratified ordering: stop accepting new work -> graceful cancel of in-flight tasks -> flush the in-memory checkpointer index (via the still-open pool) -> close the shared executor -> stop the worker loop. Fail-open throughout.
- **Shutdown semantics (G7c)**: process shutdown (`main.py` `_shutdown`) HARD-cancels the module consumers by default (drain each run's FIFO, cancel the in-flight turn, no new dispatches; the append-only store and the flush-archive preserve the partial trail). In addition, each module may register a module-specific **termination feature** with the shutdown fan-out - a hook implying a GRACEFUL shutdown (finish the in-flight turn, dispatch no further work, then flush) that the app can invoke instead of the hard-cancel default. App-initiated stops stay graceful.

### 2.3 Control-plane housekeeping

- API handlers stay on the uvicorn loop; they marshal hunting work onto the shared worker loop through the seams above. Blocking work offloads onto the one shared default executor via `asyncio.to_thread` (no per-module pool - 2026-08-13).
- Startup reconcile mirrors `reconcile_orphaned_analysis_runs`: orphaned `running` hunting runs become `interrupted`.

## 3. What the hunting module must provide

The hunting runtime wiring ticket implements these against the seam:

### 3.1 Lifecycle entry points

- **Bootstrap**: a module entry point (a coroutine, e.g. `start_hunting(project_id, ...)`) that the control plane schedules onto the shared worker loop via `runtime.schedule("hunting", ...)`. It sets the hunting module context first, then runs the module's orchestration logic, then persists the terminal status and triggers the run-terminal flush of the hunting index.
- **Module-context rule (control plane machinery, applies to every module)**: each module's OUTERMOST runtime entry point sets its module context for the entry point's full duration via a context manager (`module_context("analyse")`); executor threads propagate it automatically through `copy_context` (concurrent.futures and `asyncio.to_thread` carry the ContextVar). The setter call sites: recon = `run_pipeline`; analysis = the supervise/consume task AND the `run_analyser_chunked` pod seam (analysis-domain work reached from the recon pipeline task); hunting = `start_hunting`. API-direct calls, boot-strap scripts, and admin reads set no context; they resolve the unset-context fallback (shared in-process `InMemorySaver`).
- **Stop**: a stop handler wired to `runtime.cancel_run("hunting", run_id)` for phase-1 (hard cancel; the append-only hunt store preserves the partial trail). The graceful variant (finish the in-flight turn, dispatch no further hunts) is a separate ticket and may add a stop flag the orchestration turn polls.
- **Tear-down**: register the hunting module's flush hook with the runtime manager's shutdown fan-out (flush in-memory checkpointer index to PG, fail-open). The module does not own the loop or the executor.

### 3.2 Run identity and status

- A hunting run is **project-scoped** with its own surrogate `hunting_run_id` (never a recon run_id; the L1 model is project-keyed). The same id keys the hunt store's append-only trail.
- Status lifecycle: `running -> complete | stopped | failed | interrupted`. Persisted in a `hunting_runs` table; the control plane's startup reconcile flips orphans to `interrupted`.
- The terminal `complete` status is written by the module entry point after the orchestration pass returns.

### 3.3 Endpoints

- `POST /projects/{project_id}/hunting` - launch a hunting run (returns `hunting_run_id`).
- `POST /projects/{project_id}/hunting/{hunting_run_id}/stop` - phase-1: hard cancel; returns the stopping acknowledgement.
- `GET /projects/{project_id}/hunting/{hunting_run_id}` - the run's status row.
- **Surface ownership**: the three handlers land in the existing `project_management/api.py` HTTP adapter router, added by the module runtime wiring (#110) as an additive block AFTER the runtime independence workstream's PRs land on `dev` (sequenced landings; the runtime-independence workstream lands first - one `workflow` ticket per layer: checkpoints refactor, session-address helper, runtime manager + lifecycle state machine + feed + per-module gate, app wiring, hunting control-plane machinery + `hunting_runs` DDL/accessors/reconcile, resume-seam scaffold + address audit - then #110 rebases). My PRs deliver the harness those handlers call: `runtime.schedule("hunting", ...)`/`runtime.cancel_run("hunting", ...)` marshalling and the `hunting_runs` DDL + accessors + startup orphan reconcile in `app/clients/pg.py`. Neither PR writes a file the other PR also writes.

### 3.4 Store

- The `HuntStore` lives at the FIXED path `src/polymerhus/attack/hunting/data/hunts/` (no env var).
- The store is the append-only audit trail (run/config/hunt/dispatch/result/spec/evidence/...). There is NO LLM-facing store tool: fault attributes are rendered in the initial prompt of each fault matching session, not read by the orchestrator through a tool.

### 3.5 Fail-open

- Every collaborator failure (KB, back-edge, graph view, store, checkpoint flush) degrades the run; the run always advances to a terminal status. No hunting code raises through the control plane.

## 4. Internal orchestration contract (summary)

Carried in detail by the hunting runtime wiring ticket; the seam-relevant shape:

- One stateful orchestration turn per fault-unit(s) pair, each turn a PASS (optional back-edge tool call -> reasoning -> HuntConfig elicitation -> next pair with context).
- ONE flexible graph workflow (not one StateGraph per pair) with enforced determinism, implementing the engine that drives the per-candidate loop.
- The harness calls the hunting agent per HuntConfig (`build_hunting_agent` consumed per config, not passed as a single dispatch_fn).

## 5. Evolution

- Graceful stop / degradation (finish-pass semantics) is its own ticket.
- The test-executor pod remains an injected seam (its spec is contract-only); building it is a separate decision, never blocked on this seam.

(End of file - total 81 lines)