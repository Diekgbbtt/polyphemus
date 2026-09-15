# Teardown Contract - checkpoint flush ordering, loud drop, and the halt-everything stop (#211)

*Spec for ticket #211. Companion: the diagnosis on #211 (confirmed mechanism, refuted hypothesis); the sibling teardown-audit fix is #76 (killed-job output suppression - a SEPARATE fix under the SAME audit). The flush-hook seam this defect lives in is #120 (closed). Decision ids are `TD-*`. This is a living document: it lands in the same change as the implementation.*

## Problem Statement

At stop, a committed session thread's checkpoint can be silently lost. On eval run `26bdaf55-87a7-4386-92d7-82b7ddfe2eca` (white-jotter, 2026-08-31) the flush of **27 hunting session threads** at teardown dropped every one: each thread's archive raised `KeyError: 'checkpoint_ns'`, and the fail-open warn-and-keep turned a systematic teardown failure into a silent one. No evidence was lost in that run, but the threads' checkpoint state (the stateful agents' memory) was not persisted - a future resumed run would start those agents from empty memory, unnoticed.

The teardown sequence across the module runtime is a contract spanning every stop surface. It is currently mis-modelled in two independent ways:

1. **The flush target contract is broken** (the confirmed mechanism): the archive path builds a config with only `thread_id`; the resolved `PostgresSaver` (langgraph-checkpoint-postgres 3.1.0, app pin `>=2.0.0` unbounded) requires `checkpoint_ns` and hard-pops it - so **every** thread's archive fails. The ticket's "likely root cause" (wrongly modelled task dependencies) is REFUTED as the primary mechanism.
2. **The ordering/assert contract is missing** (real, secondary): no flush path returns a result, no stop surface asserts the flush succeeded before stamping teardown, and two stop surfaces (`stop_analysis`, the recon pipeline stop) never flush at run-stop at all - their threads persist only in memory until a later process shutdown.

The user wants: every thread's checkpoint flush completes AND its success is asserted BEFORE teardown is stamped (strict sequential dependency), a dropped flush is LOUD (never silent fail-open), and a stop that halts everything (all external connections) so no future run loses checkpoint state unnoticed.

## Solution

A rewritten teardown contract, applied ubiquitously:

1. **`flush -> assert -> teardown`** is the one ordering at every stop surface: the flush completes, its result (committed vs archived vs dropped) is inspected, and only then is the module marked `stopped` / the run stamped terminal / the pool closed.
2. **The flush actually archives**: the archive replay carries each checkpoint tuple's own `checkpoint_ns` (and the put result's `checkpoint_id`) - one correct config shape, compatible with every PostgresSaver version.
3. **A dropped flush is structurally loud**: the drain response carries the flush result (`committed/archived/dropped/dropped_thread_ids`), the teardown logs the dropped thread_ids, and the structural fact is the committed thread_id's absence from the PG `checkpoints` table. No prose report - the domain model + the stores ARE the teardown state.
4. **Fail-open is preserved but never silent**: teardown never raises; a per-thread failure salvages the rest ("save as much as possible") and the residual drop is recorded and logged.
5. **A stop that halts everything**: the forced process teardown explicitly closes the Kali MCP client, the lightrag client, and the LLM/gateway connections in addition to the existing pool/executor/loop shutdown.

## User Stories

1. As an operator, I want a long-horizon run stopped mid-activity to have every committed thread's checkpoint archived to the store, so that no run loses checkpoint state unnoticed.
2. As an operator, I want a flush failure at teardown to be loud - logged with the dropped thread ids and visible in the drain response - so that a silent drop cannot hide again.
3. As an operator, I want the flush to complete and its success asserted before the run is stamped terminal, so that a "stopped" run truthfully means its threads' last checkpoints are safe.
4. As an operator, I want a stop that halts everything - the pooled saver, the executor, the worker loop, and the external connections (Kali MCP, lightrag, LLM gateway) - so that no half-open handle outlives teardown.
5. As an operator, I want a stopped run's threads resumable by their deterministic thread ids, so that a resumed agent restores its memory from the store.
6. As an operator, I want the drain of a module to report the flush outcome, so that the teardown state is machine-readable for the eval harness and the frontend.
7. As the eval harness, I want to assert, after a trial's teardown, that zero flushes were dropped and every committed thread id is present in the store, so that a trial result is not silently graded over lost agent memory.
8. As an operator, I want teardown to never raise into a run even when a flush fails, so that the fail-open discipline is preserved.
9. As an operator, I want the shutdown walk to flush every module through its registered hook (and the single bulk flush as the fallback), so that no stop path keeps a bespoke second flush seam.
10. As an operator, I want the target-open guarantee kept at every flush site (flush while the pooled saver is still open; close strictly after), so that no flush is ever a silent no-op against a closed target.

## Implementation Decisions

### TD-1 - The strict sequential dependency `flush -> assert -> teardown`

At EVERY stop surface (module stop `_settle_module`, the shutdown fan-out `ShutdownFanOut.run`, the hunting run stop, the analysis stop, the recon pipeline stop, the eval-harness stop) the order is fixed:

1. FLUSH: settle runs, then run the module's flush.
2. ASSERT: inspect the flush result (TD-2). A non-zero drop is recorded (TD-4) and logged; it never blocks teardown (TD-5).
3. TEARDOWN: mark the module `stopped` / stamp the run terminal / close the pool - strictly after the assert.

The assert's safe condition follows the clusterised state catalogue (see the Assertion Catalogue in `to-assertions`): the stateful-session cluster (C1) must be persisted (archived) before the run-lifecycle cluster (C2) stamps terminal, before the control-plane cluster (C4) marks the module `stopped`, before the handle cluster (C5) closes the pool.

### TD-2 - The flush seam returns a typed result

The flush seam (`flush_module_index` / `flush_all_indexes` / the registered hooks) returns a typed result per module: `{committed, archived, dropped, dropped_thread_ids, cause}`. `_settle_module` and `ShutdownFanOut` inspect it for the assert. The runtime no longer discards the outcome of a flush.

The closed `cause` vocabulary (a drop is never a bare debug no-op): "no-target" (no open pooled saver - the whole eligible set reported dropped), "hook-raised" (the flush seam raised - degraded zero result), "no-result" (a registered hook returned nothing - degraded), "never-flushed" (a drain read before any flush ran - wire surface only, never stored). `cause: null` means the flush itself ran (clean or salvaged).

### TD-3 - The archive replay carries the tuple's own checkpoint_ns (the confirmed-mechanism repair)

`_archive_thread` builds the archive config from each tuple's own config - `thread_id` + the tuple's `checkpoint_ns` - and threads the put result (which carries the `checkpoint_id`) into `put_writes`. This is ONE correct config shape, compatible with the resolved `PostgresSaver` API (2.x ignores `checkpoint_ns`; 3.x requires it). No version branching, no version detection. The app's `langgraph-checkpoint-postgres` pin is reviewed (the `>=2.0.0` unbounded range is what let a 3.x resolution silently break the archive); the archive itself stays contract-compatible across the resolved range, proven by a contract test against the real saver API shape (TD-T2).

### TD-4 - A dropped flush is structurally loud (no prose report)

- The drain response (`POST /projects/{id}/modules/{module}/drain`) returns `{module, state, flush: {committed, archived, dropped, dropped_thread_ids, cause}}` - the machine-readable assert surface for the eval harness and the future frontend. The flush is ALWAYS an object: a raising hook degrades to `cause="hook-raised"`, a result-less hook to `cause="no-result"`, and a drain that settled no flush yet (an already-stopped module that never flushed) reports `cause="never-flushed"` - never null for a flush that ran, so the harness reads `body["flush"]["dropped"]` without a null branch.
- The teardown logs a structured record naming the dropped thread ids and the count.
- The structural fact: a committed thread id that is absent from the PG `checkpoints` table after teardown IS the drop. The domain model + the stores are the teardown state; no prose report artifact is written.

### TD-5 - Fail-open preserved, never silent (fail-safe-first)

Teardown never raises into a run. A per-thread archive failure salvages the remaining threads (the loop continues past a failure - "save as much as possible"). A residual drop is recorded in the flush result (TD-4) and logged; teardown completes. The agents are engineered to be seamlessly flushable, so a drop after the repair is the rare residual (e.g. the pool is down mid-teardown), not the norm.

### TD-6 - flush_all_indexes is the bulk shutdown flush; the registered hook stays primary

- The runtime walk keeps resolving each module's REGISTERED flush hook (hunting's registered `flush_hunting_checkpointer`, and the `flush_module_index` fallback for recon/analysis) - the primary path.
- `flush_all_indexes` becomes the guaranteed single bulk flush for the non-runtime teardown path (and the close-ordered guarantee: call before `close_session_checkpointer`).
- The inline `flush_hunting_checkpointer()` call in the hunting run's `finally` is refactored onto the shared seam (run-scoped flush through `flush_module_index("hunting", run_id=...)` when a run id is in scope), removing the second ad-hoc path.

### TD-7 - A stop that halts everything

The forced process teardown (`_shutdown`) gains explicit release of the external handles in addition to the existing sequence: flush every module into the still-open pooled saver (runtime walk, then the guaranteed single bulk `flush_all_indexes` for indexes whose module never registered), close the executor, stop the worker loop, THEN close the pooled saver, and explicitly close the persistent outbound handles. Fail-open on each close (a close failure is logged, never raised).

Surveyed handle list (amended per review - the as-written "close the Kali MCP client, the lightrag client, and the LLM/gateway connections" is unmet because no such persistent handle exists): the Kali MCP client is built per call inside `async with client.session(...)` (`app/clients/kali_mcp.py:15-18`); the lightrag ingestion adapter takes an injected per-use client (`ingestion/lightrag_adapter.py:25-33`); the LLM/gateway clients are built per construction with per-call httpx timeouts (`app/llm/providers.py`). The neo4j driver is therefore the SOLE persistent outbound handle at app level and is the one explicitly closed. If a future client gains a persistent handle, it joins this list with its own fail-open close.

### TD-8 - The eval-harness teardown contract

The harness: (1) issues the per-run stop verbs, (2) drains each module via the documented `drain` endpoint and asserts each flush result has `dropped == 0`, (3) tears the stack down gracefully (SIGTERM so the uvicorn shutdown walk runs), and (4) post-teardown asserts the structural fact - every committed thread id is present in the store (or the drop is in the logged teardown record). Drain remains graceful-completion (a test-executor pod drains to a produced PodExport); the halt-everything semantics belong to the forced process teardown (TD-7).

### TD-9 - Resumption is thread-id driven

A session thread resumes by its deterministic thread id (the #119 module-scoped address); the flush archives the thread under that id. A drop IS the id's absence from the store. No durable enumeration is built (the resume seam is a future consumer of the archived ids).

### TD-10 - The target-open guarantee holds at every flush site

Every flush (runtime walk, per-module hooks, `flush_all_indexes`, run-terminal flushes) runs strictly BEFORE the pool closes; the pool closes strictly after all flushes. Verified at every flush site, including the eval-harness teardown (which must never close the pool before the walk's flushes).

### TD-11 - Guardrails

- No change to the checkpoint data format.
- No weakening of the fail-open contract to a raise.
- No touch to the #206 compaction or #210 summariser robustness surfaces - the teardown contract is orthogonal.

## Testing Decisions

### What makes a good test

- The unit tier drives the pure mechanics with the LLM, the gateway, and the PG saver mocked (CODING_STANDARD section 6/10): the strict ordering, the assert step, the flush-result shape, the checkpoint_ns archive config, the loud-drop record, the hook-registry resolution. The unit tier touches no live model, no live gateway, no DB.
- The contract catalogue lives in the integration tier: the archive round-trips the REAL `PostgresSaver` config contract (TD-T2), and the stop surfaces complete with the pool open-then-closed ordering.
- A live walkthrough (a long-horizon run stopped mid-activity -> every thread's checkpoint IN the store -> zero dropped flushes -> the drain responses clean) lives in e2e, with a forced-flush-failure case proving the drop is loud.

### Modules under test

- `app/runtime.py` (`_settle_module`, `_flush_module`, `ShutdownFanOut`, `drain`) - the ordering + assert + report aggregation.
- `app/llm/checkpoints.py` (`ModuleIndex.flush`, `_archive_thread`, `flush_module_index`, `flush_all_indexes`) - the flush result shape + the checkpoint_ns repair + the salvage loop.
- `app/main.py` `_shutdown` - the halt-everything sequence (TD-7) + the flush-before-close ordering.
- `attack/hunting/runtime.py` (`stop_hunting`, `flush_hunting_checkpointer`) - the run-scoped flush + the seam refactor.
- `project_management/api.py` `drain` - the flush result in the response (TD-4).
- The eval-harness teardown path - the assert contract (TD-8).

### Prior art

- The existing `_settle_module` / `ShutdownFanOut` unit tests (`tests/app/`), the checkpointer index tests from #120, the module-runtime assertions catalogue (C16/C17 and the pause/resume/drain walkthroughs), and the `tests/e2e` module-runtime walkthroughs.

## Out of Scope

- The resume seam itself (a future ticket consumes the archived thread ids; #211 makes them present and enumerable-by-id, not resumable).
- Cross-process analysis-FIFO resumption (deferred #88) - the FIFO stays in-memory; its not-cross-process-resumable status is structural, not fixed here.
- #76 (killed-job output suppression) - a SEPARATE fix under the SAME teardown audit; the only shared piece is the teardown-state surface, which stays per-fix (shared shape, separate PRs, cross-referenced).
- The F5-style move-consistency defects in the hunt/hunter memory (produced/consumed mutual exclusion) - the #76-adjacent tail, not this flush.

## Further Notes

- Cross-references: #76 (sibling teardown-audit fix), #120 (the closed flush-hook seam this defect lives in), #88 (cross-process feed resume), #206/#210 (untouched compaction/summariser surfaces).
- The diagnosis (confirmed `checkpoint_ns` mechanism, refuted ordering hypothesis, stop-surface attribution, target-open verification, missing-assert finding) is recorded on #211.
- The decision record + any glossary sharpenings (e.g. "flush result", "archived vs dropped thread") land in the same change as the implementation, per the living-documents rule.
- The assertion catalogue (the per-surface instantiations of TD-1..TD-11, mechanised at the integration/e2e tiers) lives in the `/to-assertions` output.