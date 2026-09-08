# Assertions - work-item "teardown: checkpoint flush dropped for threads at stop (#211)"

**Source:** `docs/design/teardown-checkpoint-flush-211-spec.md` (+ the diagnosis on #211)
**Seams under assertion:**
- S1 `ModuleIndex.flush` / `_archive_thread` (`app/llm/checkpoints.py`) - the flush result + the checkpoint_ns archive repair + the per-thread salvage.
- S2 `_settle_module` / `_flush_module` / `ShutdownFanOut` (`app/runtime.py`) - the strict `flush -> assert -> teardown` ordering + the assert-before-STOPPED gate.
- S3 `POST /projects/{id}/modules/{module}/drain` (`project_management/api.py`) - the flush result in the response.
- S4 `_shutdown` (`app/main.py`) - the halt-everything sequence + the flush-before-pool-close ordering.
- S5 `stop_hunting` / `flush_hunting_checkpointer` (`attack/hunting/runtime.py`) - the run-scoped flush + the single-seam refactor.
- S6 the analysis stop / the recon pipeline stop - the flush present at these surfaces.
- S7 the eval-harness teardown - the assert contract.

## Contract predicates (integration tier)

| id | seam | delivery semantic | input | observable | yields |
|---|---|---|---|---|---|
| C1 | S1 | success | an index with N committed threads; a target that archives all | flush returns `{committed: N, archived: N, dropped: 0, dropped_thread_ids: []}` and the N threads leave the index | `tests/.../test_checkpoints_flush_result.py` |
| C2 | S1 | ordering / contract | a committed thread whose checkpoints carry a non-empty `checkpoint_ns`; a target that REQUIRES `checkpoint_ns` (the real PostgresSaver 3.x config contract) | the archive replays each tuple with its own `checkpoint_ns` + the put's `checkpoint_id`; the flush returns `dropped: 0` - the 27-thread KeyError is gone | contract test against the real saver API shape |
| C3 | S1 | degradation | 2 committed threads, thread A's archive raises, thread B's succeeds | flush returns `{committed: 2, archived: 1, dropped: 1, dropped_thread_ids: [A]}`; B archived, A kept in the index (salvage-saves-what-it-can) | same module |
| C4 | S1 | empty-valid | an index with zero committed threads | flush returns `{committed: 0, archived: 0, dropped: 0}` - a valid result, not a failure | same module |
| C5 | S1 | degradation / loud | an index with N committed threads; `target is None` (no open pool) | flush returns `{committed: N, archived: 0, dropped: N, dropped_thread_ids: [...], cause: no-target}` - recorded LOUD, never a bare debug line | same module |
| C6 | S2 | ordering | a module with live runs; a flush that reports `dropped: 1` | `_settle_module` runs the flush, inspects the result, records the drop, and ONLY then sets `ModuleState.STOPPED` - teardown is never stamped before the flush's outcome is known | `tests/.../test_runtime_settle_assert.py` |
| C7 | S4 | ordering / target-open | the shutdown walk over 3 registered modules with a flush target | every module flush runs while the target is OPEN; `close_session_checkpointer` runs strictly after all flushes (G7c preserved) | shutdown-walk test with an open/close-observing target |
| C8 | S2/S6 | success / resolution | hunting (registered flush hook) + recon + analysis (hook-less) | `_flush_module` resolves the hunting hook and the `flush_module_index` fallback for recon/analysis; both paths return a result the settle inspects; the recon and analysis stops now flush | `tests/.../test_runtime_flush_resolution.py` |
| C9 | S5 | ordering | a run-scoped flush over a hunting index holding threads of run X and run Y | `flush_module_index("hunting", run_id=X)` archives only X's threads; Y's stay in the index | hunting runtime tests |
| C10 | S3 | success | `POST /projects/{id}/modules/hunting/drain` over a module with 3 committed threads | 200 `{module: "hunting", state: "stopped", flush: {committed: 3, archived: 3, dropped: 0, dropped_thread_ids: [], cause: null}}` - the machine-readable assert surface (5-field shape; `cause` nullable) | `tests/.../test_drain_flush_result.py` |
| C11 | S4 | ordering / degradation | the process shutdown with the sole persistent external handle (neo4j driver) raising on close | `_shutdown` runs flush -> executor close -> loop stop -> pool close, then explicitly closes the neo4j driver; the close is fail-open (a raising close is logged, never raised). Kali MCP (per-call session), lightrag (injected per-use client), and LLM/gateway (per-construction clients) hold no persistent app-level handle - surveyed, no close to test | shutdown-sequence test with raising fake driver |
| C12 | S5 | success / duplicate-removed | a hunting run terminal (normal and stopped) | the run's `finally` invokes EXACTLY ONE flush path - the shared run-scoped seam - never a second ad-hoc whole-index call | hunting runtime tests |

## Walkthrough predicates (end-to-end tier)

| id | grounds | entry seam | input | live edge | path | terminal | observed | yields |
|---|---|---|---|---|---|---|---|---|
| E1 | TD-1/TD-4/TD-8 - the 27-thread case is gone | `POST /projects/{id}/recon` + `/hunting` + `/analysis` (live stack, target per `eval-targets.yaml`) | a long-horizon trial: recon (httpx/katana/jsluice), analysis (streaming), hunting with several live sessions | the live target (seeded per the eval target's `settings.recon`); docker stack up | stop verbs per run -> drain each module via the API -> assert each drain's `flush.dropped == 0` -> SIGTERM the stack -> read PG `checkpoints` | every committed thread id present in PG `checkpoints`; every drain response reports `dropped: 0`; the teardown log records no dropped thread ids | `SELECT thread_id FROM checkpoints` for the trial's thread ids; the drain responses; the teardown log | `tests/e2e/.../test_teardown_flush_e2e.py` (BLOCKED: docker down - carried per the walkthrough-blocking rule) |
| E2 | TD-1/TD-9 - a stopped run's last checkpoints ARE in the store | same as E1 | the same stopped trial, committed thread ids enumerated | the live stack + target | after stop + drain + SIGTERM teardown, resolve each committed thread id from PG | for each committed id, `checkpoints` holds the thread's LATEST checkpoint (the last `channel_versions` state), zero absent | the `SELECT` per id returns the latest checkpoint; no id returns empty | same e2e module (BLOCKED: docker down) |
| E3 | TD-4/TD-5 - a forced flush failure is loud | the drain endpoint with the flush target made to raise on archive (a fixture fault injected at S1, not the live edge) | 3 committed threads, target raises | none (the failure is injected inside the live edge at S1 - a fixture substitution, so it is exercised at the CONTRACT tier C3; the e2e walkthrough carries it as the drain-visible variant) | drain -> flush raises per thread -> salvage records -> drain responds | drain 200 `{flush: {committed: 3, archived: 0, dropped: 3, dropped_thread_ids: [...]}}`; module reaches `stopped`; the run stamps terminal (fail-open preserved) | the drain response; the teardown log naming the dropped ids | the contract tier realises C3; the e2e variant is the drain-visible drop (BLOCKED: docker down) |
| E4 | TD-7 - the halt-everything teardown | SIGTERM to the agent process | the running stack with live external clients | the live stack | SIGTERM -> `_shutdown` -> runtime.shutdown (flush, executor close, loop stop) -> bulk `flush_all_indexes` -> pool close -> neo4j driver close (the sole persistent handle; Kali/lightrag/LLM hold none) | the process exits 0; every handle (pool, executor, worker loop, neo4j driver) is released; no hang | the process exit code; the shutdown log sequence | e2e stack test (BLOCKED: docker down) |

**Bootstrap that only the operator can supply (carried as blocked until answered):** the live stack up (docker daemon) for E1-E4; the eval target + the trial's thread ids for E1/E2.

**Gate note:** the catalogue is derived from the spec and stays red until its path is built; it runs only at the verification gate, never inside the `tdd` unit red/green loop.