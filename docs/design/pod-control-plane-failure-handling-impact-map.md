# Pod control-plane failure handling - impact map

*Status: built 2026-10-26. Branch: `feat/pod-control-plane`.*
*Scope: the test-executor pod control plane, the surfer backstop, the pod store, and the gate's completion semantics.*
*The per-hunt batch fix (`98e25c45`) is already in place and is not re-opened.*

## Target behaviour

1. The pod graph owns the primary failure detection.
   LangGraph node timeouts and error handlers terminate the failed node, route to a terminal, and write a `PodExport` from the durable pod log.
2. The surfer owns scheduling and one hard backstop per pod.
   It no longer owns the primary timeout and it no longer overwrites a pod's terminal with a minimal envelope.
3. Failures are typed.
   Provider quota and transport failures pause and resume the run. Context overflow and node or tool timeouts become explicit pod terminal reasons. A domain verdict is never fabricated for an infrastructure failure.
4. A stopped pod is durably resumable.
   The pod store keeps a resume cursor. A re-dispatch hydrates the log, skips completed variants and executed probes, and continues.
5. The gate advances only on a durable terminal export.
   A resumable pod has no export, so the existing hunt cursor holds.
6. No batch-scoped timer and no per-target concurrency cap.
   The per-hunt batch already bounds the live pod set, and each pod owns its execution timeout.
7. One finalizer owns the terminal record.
   The pod graph, the pod entry point, and the surfer call the same `pod/finalize.py`.
   No scheduler path assembles evidence.

## Finalizer ownership (2026-10-26)

The accepted mechanical rule is:

> Only `pod/finalize.py` constructs and writes a `PodExport`.

| Component | Responsibility |
|---|---|
| `pod/finalize.py` | Assemble evidence from `ExperimentLog` or the durable store; write once; clear the cursor; return the envelope |
| `pod/graph.py` | Select the domain or harness terminal; call the finalizer with the in-memory log |
| `pod/pod.py` | Call the finalizer on the graph-level degrade path |
| `surfer.py` | Call the finalizer on its backstop or builder exception; never build an envelope |
| `pod/pod_memory.py` | Store the log, variants, export, and resume cursor |
| `pipeline_sync.py` | Read the export as the completion fact |

Two write modes:

- **Execution terminal** (`replace_existing=True`): the pod graph or the pod entry point completed the attempt. It replaces a prior export for the same spec and run, so a legitimate re-dispatch rewrites its own result.
- **Fallback terminal** (`replace_existing=False`): the surfer backstop or builder exception. It never overwrites an execution terminal. The existing domain terminal wins.

The finalizer is idempotent under a per-`(spec_id, run_id)` lock.
The surfer no longer produces a minimal envelope.
It passes `PodTerminal.infrastructure(...)` and the finalizer hydrates the durable trail.

## Current dependency graph

```text
pod/agents.py
  default_runner_step_fn / default_triager_fn
        |
        v
pod/graph.py  build_pod_graph
  init -> runner_agent -> triager -> decide -> terminal
        |          |          |
        |          |          +--> pod/agents.py (LLM turns)
        |          +-------------> pod/tools.py (exec, EXEC_TIMEOUT_S)
        +------------------------> pod/context.py (ExperimentLog, durable writes)
                                      |
                                      v
                                 pod/pod_memory.py
                                   experiment-log/<order>.yaml
                                   variants/<ref>.yaml
                                   <run_id>.yaml (PodExport)

pod/pod.py arun_pod
  ainvoke(config={recursion_limit, callbacks})
  node timeouts + error handler -> graph terminal
  graph recursion -> finalize_pod(graph-limit)
  provider failure -> ProviderUnavailableError

pod/finalize.py
  the ONLY PodExport writer
  evidence from the in-memory log or the durable store
  execution terminal replaces; fallback terminal never overwrites

surfer.py run_pod_session
  asyncio.wait_for(arun_pod, pod timeout=3600)
  timeout -> finalize_pod(pod-watchdog-timeout), full trail
  builder exception -> finalize_pod(surfer-dispatch-degraded), full trail
  cancellation -> no export; resume cursor remains

pipeline_sync.py
  _hunt_done / terminal_specs -> durable PodExport is completion
```

## Impact map

| # | Component | Current behaviour | Change | Tests |
|---|---|---|---|---|
| 1 | `pod/types.py` | Six-value terminal vocabulary. | Add `node-timeout`, `context-window-exceeded`, `graph-limit`, `tool-timeout`, `pod-watchdog-timeout`. Keep `budget-timeout` for the pod's own lap cap. | `tests/attack/pod/test_verification.py`, `test_prompts.py` |
| 2 | `pod/verification.py` | Validates the triager decision against the terminal set. | Accept the new terminal reasons; the triager vocabulary stays domain-only. | `tests/attack/pod/test_verification.py` |
| 3 | `app/llm/context_window.py` (new) | Context-length classification lives inside `app/llm/summary.py`. | Move the classifier to one shared module; `summary.py` re-exports it. Use it from the pod failure classifier. | `tests/test_llm_summary.py`, new unit test |
| 4 | `pod/failures.py` (new) | No single failure classifier. | Classify provider, node timeout, graph limit, context overflow, tool timeout, generic domain degrade. | new `tests/attack/pod/test_failures.py` |
| 5 | `pod/config.py` | Lap and tool-call caps only. | Add pod node idle/run defaults and the tool timeout default. | `tests/attack/pod/test_graph.py` |
| 6 | `pod/graph.py` | Nodes have no timeout or error handler; terminals are only on the normal path. | Add `TimeoutPolicy` to async nodes, an `error_handler` that routes known failures, a `degraded_terminal`, and a resume-aware `init`. | `tests/attack/pod/test_graph.py`, `test_react_seams.py` |
| 7 | `pod/pod.py` | `arun_pod` catches generic exceptions and writes `technical-infeasibility`. | Classify graph recursion and fallback node timeouts; preserve provider failures; clear the resume cursor on terminal. | `tests/attack/pod/test_graph.py`, `test_provider_failure.py` |
| 8 | `pod/context.py` | `ExperimentLog` starts fresh; `start_run` clears old summaries. | Add `hydrate()` for resume and a cursor payload for the last durable state. | `tests/attack/pod/test_pod_memory.py`, new context tests |
| 9 | `pod/pod_memory.py` | Persists logs, variants, notes, and exports. | Add `write_resume` / `read_resume` / `clear_resume` under `<spec_id>/<run_id>.resume.yaml`. | `tests/attack/pod/test_pod_memory.py` |
| 10 | `pod/llm.py` | Inner stateful turns already use a checkpointer. | No ownership change. The outer pod graph stays log-based resumable, not checkpoint-based. | existing tests |
| 11 | `surfer.py` | One shared 2700-second watchdog; writes a minimal `budget-timeout`. | Split hunter and pod timeouts. Pod default one hour. Surfer writes `pod-watchdog-timeout`, not `budget-timeout`. The pod control plane fires first. | `tests/attack/test_hunting_session_watchdog.py`, `test_hunting_surfer_tick.py` |
| 12 | `runtime.py` | `RunDispatchState()` uses the shared timeout. | Carry the split hunter and pod timeouts on the run state. | `tests/attack/test_hunting_run_lifecycle.py` |
| 13 | `pipeline_sync.py` | Persisted `PodExport` is terminal; no export holds the hunt. | No code change if resumable pods write no export. Add a gate test that a resume cursor without an export holds the hunt. | `tests/attack/test_hunting_pipeline_sync_gate.py` |
| 14 | `eval/measure_utm.py` | Counts `symptom-confirmed` only. | No change required for the new reasons; the measurement report must split watchdog, node, context, and pod-budget terminals. | `tests/eval/test_measure_utm.py` if a helper is added |
| 15 | Pod prompts | Triager prompt lists the domain terminal reasons. | Add a note that infrastructure reasons are harness-owned, never triager choices. | `tests/attack/pod/test_prompts.py` |
| 16 | Design docs | The fail-safe, pod spec, and pipeline-sync docs describe the surfer as the primary timeout and do not describe resume. | Update `hunting-lifecycle-failsafe.md`, `hunting-67-test-executor-pod-spec.md`, `hunting-pipeline-sync-adr.md`, `hunting-pipeline-sync-spec.md`, and `attack/hunting/CONTEXT.md`. | docs review |
| 17 | `pod/finalize.py` (new) | The graph and the surfer both assembled and wrote `PodExport`; the backstop could overwrite a domain terminal with minimal evidence. | The finalizer is the only writer. Execution terminals replace; fallback terminals never overwrite. The surfer passes a typed terminal, not an envelope. | `tests/attack/pod/test_finalize.py`, `tests/attack/test_hunting_session_watchdog.py` |

## Failure taxonomy

| Failure | Owner | Terminal | Gate effect | Retry or resume |
|---|---|---|---|---|
| Provider 429, 5xx, transport timeout, quota | Surfer child-failure ledger | None | Hold | Retry after backoff; quota pauses the run |
| Context window exceeded | Pod graph error handler | `context-window-exceeded` | Advance | No automatic retry; the next variant starts smaller |
| Node idle or run timeout | Pod graph error handler | `node-timeout` | Advance | No automatic retry |
| Graph recursion limit | `arun_pod` | `graph-limit` | Advance | No automatic retry |
| Tool exec timeout | Pod graph error handler on `tool_exec` | `tool-timeout` | Advance | The runner may try a different probe |
| Pod lap budget | Pod `budget_terminal` | `budget-timeout` | Advance | No automatic retry |
| Surfer hard backstop | Surfer | `pod-watchdog-timeout` | Advance | No automatic retry |
| Run stop or drain | Pod graph and store | None; resume cursor | Hold | Resume on re-dispatch |
| Malformed spec | Pod INIT gate | `technical-infeasibility` | Advance | No automatic retry |

## Timeout hierarchy

| Layer | Default | Scope | Behaviour |
|---|---:|---|---|
| LLM request timeout | 300 s | One model request | Provider timeout classification |
| Tool exec timeout | 300 s | One exec | Tool return or tool timeout |
| Pod node idle timeout | 600 s | One node attempt | Fires only when no progress signal |
| Pod node run timeout | off by default | One node attempt | Optional tighter pod-owned ceiling |
| Pod graph recursion limit | 3244 supersteps | One pod graph | Structural backstop |
| Surfer pod backstop | 3600 s | One pod session | Last-resort `pod-watchdog-timeout` |
| Surfer hunter backstop | 2700 s | One hunter session | Existing hunter recovery |

The idle timeout is the primary liveness bound. The surfer's one-hour pod backstop is the only hard wall clock by default; a deployment can opt into a tighter node run timeout.

## Resume design

The resume unit is the variant boundary, not the byte-identical LangGraph state.

1. `ExperimentLog` persists each variant slice and the full `executed` ledger.
2. The graph writes a resume cursor after `init`, `runner_agent`, `triager`, and `mint_variant`.
3. The cursor records:
   - `schema_version`
   - `spec_id`
   - `run_id`
   - `last_order`
   - `current_variant_ref`
   - `iteration`
   - `feedback`
   - `executed`
   - `updated_at`
4. A terminal export clears the cursor.
5. A re-dispatch finds the cursor, hydrates `ExperimentLog` from the variant slices, starts at the current variant, and reuses the executed ledger.
6. The gate sees no export and holds the hunt. The mover's consumed-spec recovery re-offers the spec after the backoff.
7. The inner `stateful_turn` checkpointer remains the conversation memory of the pod roles. The outer pod graph does not add a second checkpointer.

## TDD slices

Each slice is one red test, one minimal implementation, then the next slice.

1. Terminal vocabulary accepts the infrastructure reasons and still rejects unknown reasons.
2. The shared context-window classifier recognises a provider 400 and leaves other errors alone.
3. The pod failure classifier maps node timeout, graph limit, context overflow, tool timeout, provider failure, and generic failure.
4. The pod graph routes a hung async runner through `node-timeout` to a degraded terminal with the partial log.
5. A provider failure inside a node is re-raised, not written as a domain verdict.
6. A context-window error inside a node becomes `context-window-exceeded`.
7. `arun_pod` maps a graph recursion error to `graph-limit`.
8. The pod store round-trips and clears a resume cursor.
9. `ExperimentLog.hydrate` restores variants, observations, interpretations, and the executed ledger.
10. A resumed pod starts at the cursor variant and skips an executed probe.
11. A cancelled pod leaves no terminal export and keeps its resume cursor; the gate holds.
12. The surfer splits hunter and pod timeouts and writes `pod-watchdog-timeout` for its backstop.
13. The finalizer writes the full store trail on a backstop, returns an existing execution terminal unchanged, and lets a new execution terminal replace a prior export.
14. A source guard asserts only `pod/finalize.py` calls `write_pod_export`.
15. Existing session-watchdog, pod contract, pipeline-sync, and resume tests are updated where the vocabulary or defaults changed.

## Out of scope

- A batch-scoped watchdog. Rejected: it couples pod execution to pipeline sync and penalises late pod admissions.
- A per-target concurrency cap. Rejected by the operator. The per-hunt batch bounds the common case.
- A full outer-graph checkpointer. Deferred until the log-based resume proves insufficient.
- Rewriting the inner stateful-turn checkpointer.

## Risks and anti-patterns

- Two primary timeouts. The pod node timeout is primary; the surfer is a backstop above it.
- Domain verdicts for infrastructure failures. The classifier must never route a provider failure to a domain terminal.
- A terminal export for a resumable stop. The gate would advance and lose the work.
- A live store handle in checkpoint state. The log-based resume avoids serialising the store.
- Resuming a completed pod. A terminal export must clear the cursor.
- Duplicate side effects. The executed ledger skips probes; write probes need per-command idempotency review.
- Late writes after a timeout. A node timeout clears graph writes but the in-place log may retain partial entries; the terminal reads the durable log.
- A one-hour fixed deadline. The idle timeout is the liveness bound; the run timeout is only a ceiling.

## Acceptance criteria

- [x] The pod graph writes a typed export for node, context, tool, and graph failures.
- [x] Provider failures still pause or retry the run and never become domain verdicts.
- [x] The pod graph's idle timeout owns a hung node; the surfer backstop is above it.
- [x] A cancelled pod leaves a resume cursor and no export; a re-dispatch resumes and skips an executed probe.
- [x] The gate holds a pod with a resume cursor and no export.
- [x] The surfer backstop writes the full durable trail, not a minimal envelope.
- [x] Only `pod/finalize.py` writes a `PodExport`; a fallback never overwrites an execution terminal.
- [x] The surfer pod default is one hour and is separate from the hunter default.
- [x] The full relevant suites pass: `tests/attack`, `tests/app`, `tests/eval`, `tests/project_management`, and the hunting integration selection.
- [x] The impacted design specs describe the code as built.
