# Phase 0 audit findings (module runtime refactor brief)

*Status: findings only. No code changed. The brief's stated "current architecture" assumes a runtime layer that is not yet built; this document records what the audits found in the actual code and what that means for the phase plan. Superseded in part 2026-08-13 by the operator's sequential-pipeline ruling: modules run as a pipeline (recon -> analysis -> hunting), only recon and streamed analysis overlap, so the topology is ONE shared worker loop with ONE shared executor - no per-module loops, no per-module pools. Sections 1-4 below were written against the earlier per-module-loop framing; section 3's phased plan and section 4's file list are corrected by section 6.*

## 0. Baseline mismatch (must be acknowledged first)

The brief's "CURRENT ARCHITECTURE (starting point)" describes a runtime that is **not present in the code**:

- No `RuntimeManager` / `app/runtime.py` exists anywhere (`grep src` for `RuntimeManager|module_context|_MODULE_CTX|BoundedSemaphore|ModuleHandle|register_module|PassGate|gate_executor` returns zero files).
- No per-module `asyncio.Runner` threads, no per-module `ThreadPoolExecutor`, no module checkpointer index, no controller->module mailbox. The whole app runs on ONE uvicorn loop; `main.py:45` installs a single process-wide 64-thread `ThreadPoolExecutor` (`config.WORKER_THREADS`, named `recon-worker`) as the API loop's default executor.
- No threading gate, no dedicated gate executor, no pure-`queue.Queue` feed. The feed is `QueuedAnalysisFeed` backed by `asyncio.Queue` (`feed.py:194`); the gate is `ANALYSER_PASS_SEMAPHORE = asyncio.Semaphore(1)` (`feed.py:61`).

What the brief calls the "current architecture" is the **ratified target** recorded in `docs/design/hunting-module-runtime-seam.md` and `docs/design/module-runtime-architecture.md` (which live untracked in this worktree). Those docs are DESIGN, not implementation. The sibling `HUNTING-RUNTIME-IMPLEMENTER-BRIEF.md` (#110) corroborates - it explicitly tells the #110 agent: *"If the control plane implementation is not yet present in your base, treat the seam doc as the interface and leave the integration points as thin adapters over it."*

What IS landed on `dev` that matters:
- `d9f066f` supervisor compiles against an in-memory saver/store (no per-run PG opens); proposers run as stateful session agents on the process-wide `#94` pooled `PostgresSaver`.
- `6d27b2e` (async-actor-agents) added LLM-level mailbox actors (`app/llm/actor.py`: `ReconOrchestratorActor`, `HuntOrchestratorActor`, `HuntingHunterActor`) on session threads - the LLM dispatch pattern, NOT module-level runtime control.

Per the brief's working method (*"If any assumption above proves false in the code, stop and report rather than working around it"*) - I am stopping and reporting. I have not changed any code.

## 1. CONTROL 1 - GATE DEADLOCK AUDIT

### Finding: REFUTED in the actual code

The described deadlock (single-thread gate executor, `release()` queued behind a blocked `acquire()`) cannot occur because the mechanism it requires does not exist:

- The gate is `ANALYSER_PASS_SEMAPHORE = asyncio.Semaphore(1)` (`feed.py:61`), an asyncio primitive bound to whatever loop first touches it.
- It is acquired natively inside the consumer task: `async with self._sem:` (`feed.py:275`), inside `QueuedAnalysisFeed._consume`, which runs as a task on the uvicorn loop (`feed.py:241` `asyncio.create_task`).
- Release happens implicitly when the `async with` block exits (`feed.py:275-278`). No executor is involved in either acquire or release; both are loop-local async operations on the one loop.
- There is no `run_in_executor` / `call_soon_threadsafe` / dedicated executor anywhere in the gate path. `grep src/analysis` finds `run_in_executor` exactly zero times; `to_thread` only in `lifecycle.py:80` (status persistence) and `pod.py:177` (pod graph invoke, unrelated to the gate).

The brief's suspected deadlock is a property of the DESIGNED architecture (`module-runtime-architecture.md` section 3/§5.15: a one-thread "gate executor" doing the blocking `acquire` off-loop), not the current code. If that design were built verbatim with `release()` ALSO dispatched through the same one-thread executor, the self-deadlock WOULD manifest. So the finding becomes a **build-time guard for Phase 1**, recorded now:

> Phase 1 guard: a `threading.BoundedSemaphore.release()` is non-blocking and thread-safe; it MUST be called directly on the loop that finishes the pass, never funneled through the same single-thread executor that `acquire()` blocks. Equivalently, prefer a per-module `asyncio.Semaphore` on the module loop (no executor at all, no cross-loop acquire for the on-loop pass).

### What IS real about defect 1

The simultaneity half of defect 1 is real, but at a different layer than the brief assumes. There is no concurrency BETWEEN modules because there is only ONE loop and ONE `asyncio.Semaphore(1)` gate that serialises every analysis pass process-wide. Recon and analysis share the uvicorn loop as asyncio tasks. So "all modules running passes concurrently" is not blocked by a gate today - it is blocked by the absence of per-module loops + a process-wide serialising semaphore. The fix is identical in spirit to the brief's: replace the global width-1 gate with a per-module limit. But it lands as part of building the per-module runtime, not as a tweak to an existing threading gate.

### Recommendation: KEEP the gate as-is for now; the per-module limit is a Phase 1 BUILD decision, not a swap

No code change to the gate in isolation is meaningful - there is no threading gate to replace. Phase 1 will build the per-module runtime with a per-module concurrency limit baked in (see section 3).

## 2. CONTROL 2 - FEED EXECUTOR AUDIT

### Finding (a): the consumer wait is NATIVE asyncio, not `run_in_executor`

- Consumer wait: `pending_get = asyncio.ensure_future(self._queue.get())` (`feed.py:257`), awaited via `asyncio.wait({pending_get, stop_wait}, ...)` (`feed.py:260-261`). This is a native coroutine suspension on the uvicorn loop. It parks ZERO threads - the coroutine resumes when an item is pushed.
- Push: `self._queue.put_nowait(chunk)` (`feed.py:224`), a non-blocking put onto an `asyncio.Queue`. (Note: `asyncio.Queue.put_nowait` IS safe from a thread other than the consumer's only when no getter is blocked; today recon pushes from the same loop, so this is fine. Under a future split where recon pushes from a different loop, a pure `queue.Queue` would be required - that is exactly the G5 design.)
- The pass body itself (`analyse_chunked`, `supervisor.py:481`) is async-native and awaited inline in the consumer; its LLM calls go through stateful session agents that use `asyncio.to_thread` (`pod.py:177`) to run the blocking `graph.invoke` on the loop's default executor (the 64-thread pool). That is on-loop coroutine suspension, not a feed wait.

### Finding (b): the API loop's default executor IS a process-wide 64-thread pool

- `main.py:45-49` installs `ThreadPoolExecutor(max_workers=config.WORKER_THREADS=64, name="recon-worker")` as the uvicorn loop's default executor, so `run_in_executor(None, ...)` and `asyncio.to_thread` land in THAT pool.
- But there is only ONE loop and ONE pool. There is no "module pool" installed as a per-module default executor (the per-module loop/pool does not exist), so the coupling the brief worries about (feed idle wait parking a pass-pool thread) does not exist either.

### Recommendation: LEAVE THE FEED UNCHANGED (Phase 5 does not fire)

The brief's condition for changing the feed is: "ONLY if the audit shows the real pool-coupling exists AND the change simplifies without regressing the no-loop-affinity-at-creation property." The audit shows NO pool-coupling exists today: the wait is native `asyncio.Queue.get()`, parks no thread, uses no executor. There is nothing to fix. **Phase 5 does not fire on the current evidence.**

Corollary: when Phase 1 builds per-module loops, the feed migrates to the pure `queue.Queue` + `threading.Event` shape FROM THE G5 design (architecture doc section 3/§5.2): `get_or_create_feed` creates a loop-free `queue.Queue` (creation has no loop affinity, satisfying the invariant); the consumer on the analysis loop subscribes via `await loop.run_in_executor(None, notifier.wait)` then `get_nowait()`. At THAT point finding (a/b) must be re-audited for the NEW design: the analysis loop's DEFAULT executor must NOT be the analysis pass pool, or the idle wait parks a pass-pool thread (the coupling the brief warns of). Resolution is to give the analysis module's wait a DEDICATED one-thread notifier executor (separate from the pass pool), or subscribe with a native asyncio mechanism that does not need an executor at all. That is a Phase 1 build decision - I will flag it there and re-run this audit against the new code before merging Phase 1.

## 3. What the audits mean for the phase plan (re-baseline proposal)

The brief's defects 2,3,4 (no pause state; discipline-based safety; memory guard at the wrong layer) are ABOUT a runtime layer that does not exist yet. Defect 1 (simultaneity) is real but rooted in the same absence. So the brief, applied to the actual code, is not a refactor of an existing runtime - it is the **build of the module-runtime-independence workstream** (the seam + architecture docs), with the brief's improvements folded in.

> The re-baseline below was corrected on 2026-08-13: the operator ratified the sequential-pipeline premise, so per-module loops and per-module pools are RETIRED. The corrected plan is section 6. The earlier per-module-loop wording of sections 3-4 is retained below only as the historical record.

- per-module loops + pools + index (the architecture doc), with a per-module concurrency limit INSTEAD of the architecture doc's process-wide width-1 gate (Phase 1 of the brief);
- controller->module mailbox as the ONLY control channel (brief Phase 3), superseding the architecture doc's three-verb rulebook (`schedule`/`cancel_run`/`get_pool`);
- per-module lifecycle state machine with PAUSE/RESUME (brief Phase 2), which the architecture doc did not have;
- bounded checkpoint retention per pass with a latest-only / pruned saver (brief Phase 4), instead of the architecture doc's "flush the whole in-memory index at shutdown";
- the feed migrates to the pure `queue.Queue` shape (G5), audit-justified (Phase 5 fires only against the new code, not now).

That maps cleanly onto the G6 "split per-layer tickets" decision (six workflow tickets, bottom-up): checkpoints refactor, pool+address helper, loops+manager+feed+gate, app wiring, hunting control-plane, resume-scaffold + address audit. The brief's five phases reorder slightly because the mailbox (brief Phase 3) and the per-module gate (brief Phase 1) land together with the loops+manager ticket rather than as standalone swaps of an existing mechanism.

Proposed re-baselined phases (to confirm before I touch code):

- **Phase A** (build missing runtime skeleton + brief Phase 1 gate): introduce `app/runtime.py` with `RuntimeManager` + per-module `ModuleHandle` (loop, pool, index, registry), start the per-module `asyncio.Runner` threads at startup, register modules; replace `ANALYSER_PASS_SEMAPHORE` with a per-module `asyncio.Semaphore(N)` on the analysis loop (no executor, no deadlock possible); wire `_launch_pipeline`/`start_analysis` through `runtime.schedule`. Tests: real `Runner` threads, three modules running passes concurrently and progressing (brief test a).
- **Phase B** (brief Phase 2): per-module lifecycle state machine `created -> running -> paused -> running -> draining -> stopped`; cooperative PAUSE (finish current unit, dispatch no further) / RESUME; define the unit-of-work per module (analyser pass; hunting turn; recon job). Tests: pause one module while the others keep progressing (brief test b); no permit/handle leak on pause+resume and cancel-while-waiting (brief test c).
- **Phase C** (brief Phase 3): converge controller->module onto ONE actor mailbox of typed commands (START/PAUSE/RESUME/STOP + data handoffs); retire the ad-hoc `schedule`/`cancel_run`/`get_loop` verbs as mailbox sends; preserve the feed's pure-queue producer side untouched.
- **Phase D** (brief Phase 4): per-module in-memory checkpointer with bounded retention per pass (prune retained checkpoints / latest-only saver); measure the worst-case pass, not the average; flush to the #94 pool at graceful shutdown only. Tests: worst-case retention bounded (brief test d).
- **Phase E** (brief Phase 5, conditional): feed consumer wait mechanism review AGAINST the new per-module-loop code; change ONLY if the re-audit shows pool coupling and the change preserves the no-loop-affinity-at-creation property. Otherwise leave it.

Where the work lands: this worktree (`feat/module-runtime-independence`, currently at `6d27b2e`), rebased onto current `dev` (`3960101`) so the in-memory supervisor + async-actor-agents base is fresh. I will NOT work on the default branch.

## 4. Files Phase A would touch (for confirmation)

- new: `src/polymerhus/app/runtime.py` - `RuntimeManager`, `ModuleHandle`, per-module loop/pool/index, `schedule`/`cancel_run`/`get_pool` verbs, shutdown fan-out.
- edit: `src/polymerhus/app/main.py` - construct the manager at startup, start per-module `Runner` threads, register modules, run shutdown fan-out (replaces the bare `setup/close_session_checkpointer` calls with the same calls driven by the fan-out).
- edit: `src/polymerhus/project_management/api.py` - `_launch_pipeline` and `launch_analysis` route through `runtime.schedule`; the `_IN_FLIGHT`/`_RECON_TASKS` registries move into the manager.
- edit: `src/polymerhus/analysis/feed.py` - replace `ANALYSER_PASS_SEMAPHORE` with the per-module gate (the feed's `_sem` injection seam keeps tests injectable as today).
- edit: `src/polymerhus/analysis/lifecycle.py` - `start_analysis` registers the supervisor task with the manager.
- new: `tests/app/test_runtime_manager.py` - real `Runner` threads; concurrent three-module progress; pause isolation; no-leak; bounded retention.

Deliberately NOT in Phase A: the pure-`queue.Queue` feed migration (the current `asyncio.Queue` feed is correct on a single loop and the migration is Phase E work, gated on its own re-audit); the mailbox convergence (Phase C); the lifecycle state machine (Phase B); checkpoint retention bounding (Phase D).

## 5. Ask

Two audits are reported; the baseline mismatch is recorded. **I have not changed any code.** Per the working method, I am waiting for confirmation before proceeding.

Please confirm one of:
1. Proceed with the re-baselined Phase A (build the missing runtime skeleton with a per-module gate), on `feat/module-runtime-independence` rebased onto `dev`.
2. You want the brief treated as written against the design (assume the runtime already exists) and the defects fixed as standalone swaps - I will flag again that the swap targets are not in code.
3. Re-scope: tell me which subset of the brief to land first and I will plan to that.

## 6. Corrected plan after the 2026-08-13 sequential-pipeline ruling

The operator ratified the sequential-pipeline premise on 2026-08-13, which RESOLVES the section 5.1 open question and corrects sections 3-4 above:

- Modules run as a pipeline: recon -> analysis -> hunting. The only inter-module concurrency on the worker loop is recon (producer) and streamed analysis (consumer), already shipped and proven. Inter-module parallelism is NOT a prerequisite.
- Topology: ONE shared worker loop (`asyncio.Runner` thread), NOT per-module loops. The 2026-08-12 one-loop amendment in `module-runtime-architecture.md` stands; the audit's earlier Phase A wording ("per-module `Runner` threads") is superseded.
- Pools: ONE shared default executor (the existing `main.py:45-49` process-wide 64-thread pool), NOT per-module `ThreadPoolExecutor`s. `runtime.get_pool` is retired.
- Feed: the `asyncio.Queue` feed stays as-is on the shared worker loop. No cross-loop marshalling, no pure-`queue.Queue` migration. Phase E does not fire.
- Inline mode (`async_analysis_consumer=False`): the pass and the gate now share the same worker loop, so the inline-mode gate question is resolved by construction (no cross-loop semaphore acquisition exists).

Corrected phase plan (superseding section 3's Phase A-E):

- **Phase A** (build the missing runtime skeleton + the per-module gate): introduce `app/runtime.py` with `RuntimeManager` + per-module `ModuleHandle` (index, run-task registry, lifecycle state machine) + ONE shared worker `asyncio.Runner` thread; register recon/analysis/hunting modules; replace `ANALYSER_PASS_SEMAPHORE` with a per-analysis-module `asyncio.Semaphore(N)` on the worker loop (no executor, no deadlock possible); wire `_launch_pipeline`/`start_analysis`/hunting's `schedule_hunting` through `runtime.schedule`. Tests: real `Runner` thread; recon + streamed analysis running concurrently and progressing (brief test a - the only inter-module concurrency that exists).
- **Phase B** (brief Phase 2): per-module lifecycle state machine `created -> running -> paused -> running -> draining -> stopped`; cooperative PAUSE (finish current unit, dispatch no further) / RESUME; the unit-of-work per module (analyser pass; hunting turn; recon job). Tests: pause one module while the others keep progressing (brief test b); no permit/handle leak on pause+resume and cancel-while-waiting (brief test c).
- **Phase C** (brief Phase 3): converge controller->module onto ONE typed command surface (START/PAUSE/RESUME/STOP + data handoffs) over the shared worker loop; retire the ad-hoc `schedule`/`cancel_run` verbs as mailbox sends.
- **Phase D** (brief Phase 4): per-module in-memory checkpointer with bounded retention per pass (prune retained checkpoints / latest-only saver); measure the worst-case pass, not the average; flush to the #94 pool at graceful shutdown only. Tests: worst-case retention bounded (brief test d).
- **Phase E** (brief Phase 5): no longer applicable - the feed stays on the shared worker loop; closed as not-firing.

Files Phase A would touch (2026-08-13 correction of section 4):

- new: `src/polymerhus/app/runtime.py` - `RuntimeManager`, `ModuleHandle`, the shared worker loop, `schedule`/`cancel_run` verbs, shutdown fan-out.
- edit: `src/polymerhus/app/main.py` - construct the manager at startup, start the ONE worker `Runner` thread, register modules, run the shutdown fan-out (replaces the bare `setup/close_session_checkpointer` calls with the same calls driven by the fan-out).
- edit: `src/polymerhus/project_management/api.py` - `_launch_pipeline` and `launch_analysis` route through `runtime.schedule`; the `_IN_FLIGHT`/`_RECON_TASKS` registries move into the manager.
- edit: `src/polymerhus/analysis/feed.py` - replace `ANALYSER_PASS_SEMAPHORE` with the per-module gate (the feed's `_sem` injection seam keeps tests injectable as today).
- edit: `src/polymerhus/analysis/lifecycle.py` - `start_analysis` registers the supervisor task with the manager.
- new: `tests/app/test_runtime_manager.py` - the real `Runner` thread; recon + streamed-analysis concurrent progress; pause isolation; no-leak; bounded retention.

(End of file - total 132 lines)