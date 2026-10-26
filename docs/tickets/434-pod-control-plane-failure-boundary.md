# 434 - Pod control-plane failure boundary

**What to build:** Complete the approved pod control-plane path: primary failure detection in the pod graph, typed terminals, a split surfer backstop, and durable variant-boundary resume.

**Blocked by:** none

**Status:** done

**Seams:** `attack/hunting/pod/*`, `attack/hunting/surfer.py`, `attack/hunting/runtime.py`, `attack/hunting/pipeline_sync.py`, `app/llm/context_window.py`

## Context

The iteration B watchdog cascade showed two layers:

1. the unit-wide batched pod batch saturated the target;
2. the fixed surfer deadline killed progressing pods and bypassed the pod's own terminal.

The per-hunt batch fix (ticket 431) removed the first layer.
This ticket removes the second.

## Result

- The pod failure taxonomy is split into domain and harness terminals.
  The triager can choose only the domain reasons.
- `classify_pod_failure` maps node timeout, graph recursion, context overflow, tool timeout, and provider failure.
  A provider failure is never a domain verdict.
- The pod graph's async nodes carry `TimeoutPolicy`; the error handler routes typed failures to `degraded_terminal`, which writes the export from the durable log.
- The surfer backstops are split: 2700 seconds for a hunter, 3600 seconds for a pod.
  The pod path writes `pod-watchdog-timeout`, not `budget-timeout`.
- The pod store writes a resume cursor; `ExperimentLog.hydrate` rebuilds the D6 trail; the next dispatch skips executed probes.
  A cancelled pod writes no export, so the gate holds.
- The impacted design specs are updated: the lifecycle fail-safe, the pod spec, the pipeline-sync ADR and spec, and the hunting CONTEXT.

## Acceptance criteria

- [x] Pod graph node and tool timeouts are configured.
- [x] A typed failure routes to a degraded terminal with the partial log.
- [x] Provider failures remain infrastructure and never become domain verdicts.
- [x] Context, graph, tool, node, and watchdog terminals are distinct.
- [x] The surfer pod default is one hour and is separate from the hunter default.
- [x] A stopped pod is resumable at the variant boundary.
- [x] The gate holds a pod with a resume cursor and no export.
- [x] The impacted design specs describe the code as built.

## Verification

- `tests/attack`: 1143 passed.
- `tests/app` and `tests/eval`: 1157 passed, 22 skipped.
- `tests/project_management`: 159 passed, 6 skipped.
- Hunting integration selection: 50 passed, 28 skipped.
- `tests/test_llm_context_window.py` and `tests/test_llm_summary.py`: 44 passed.
- `compileall` and `git diff --check`: clean.

## Out of scope

- A batch-scoped watchdog. Rejected: it couples pod execution to pipeline sync and penalises late pod admissions.
- A per-target concurrency cap. Rejected by the operator (ticket 433).
- A full outer-graph checkpointer. Deferred until the log-based resume proves insufficient.
