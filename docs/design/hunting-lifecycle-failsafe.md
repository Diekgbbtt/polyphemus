# Hunting lifecycle fail-safe

*Status: implemented on `fix/hunt-spec-contract-realign`; the pod failure boundary and durable resume were added 2026-10-26.*

## The problem

A serial or batched run can stall on one item.
The 2026-10-24 run stalled for 78 minutes on a consumed threat whose hunter never
reached its terminal marker.
A single wedged session or malformed body then held every later unit.

## The three abnormal cases

The gate keeps an anomaly record only for:

1. the graph did not reach COMPLETE;
2. a write appears after the terminal marker;
3. the body is malformed.

Only cases 1 and 2 can hold the queue for an unbounded time, and the pod
failure boundary plus the surfer backstop bound case 1.
Case 3 is recorded and dispatched as a degraded pod, never held.

## The malformed fail-safe

The algorithm changed from "skip and block" to "dispatch, consume, export".

1. `HunterMemoryStore.read_spec_lenient` returns `(body, error)` instead of
   raising on a corrupt file.
2. `read_produced_inbox` emits a `TestSpecItem(malformed=True)` for an
   unparsable or non-mapping produced body.
3. `RunSyncGate._ratified_stems` treats a malformed body as dispatchable.
4. The surfer builds a degraded body with the bound target identity and the
   recorded parse error.
5. The pod's `init_route` rejects only when no probe URL exists; every other
   violation is recorded and the runner attempts a probe.
6. The pod writes a PodExport on every terminal path, including INIT rejection
   and the outer degrade path. A resumable stop writes a cursor and no export.
7. The mover consumes the spec; the pod export is the completion fact.

A consumed malformed body is terminal once its PodExport exists.
Without an export it remains an anomaly and the quiesce blocks.

## The pod failure boundary (2026-10-26)

The primary failure detection is in the pod graph, not in the surfer.

- `PodTimeouts` gives `runner_agent`, `triager`, and `tool_exec` a LangGraph
  `TimeoutPolicy`.
  The node idle timeout is 600 seconds and the tool idle timeout is 300 seconds.
  A node run timeout is off by default; the surfer's one-hour pod backstop is the
  hard wall clock.
- The idle clock resets on model tokens, tool results, state writes, and
  child-task starts. A healthy but slow pod is not killed by a fixed deadline.
- The node `error_handler` classifies the failure:
  - a provider 429, 5xx, transport timeout, or quota is re-raised for the
    surfer's retry and pause policy;
  - a node timeout, context-window overflow, graph recursion limit, or tool
    timeout routes to `degraded_terminal`;
  - a generic error keeps the existing `technical-infeasibility` degrade.
- `degraded_terminal` writes a `PodExport` from the durable experiment log with
  the typed reason and the partial trail.
- The surfer's watchdog is a last-resort backstop.
  The hunter backstop stays at 2700 seconds; the pod backstop is 3600 seconds.
  It writes `pod-watchdog-timeout`, never `budget-timeout`.
- The pod's own lap budget still writes `budget-timeout`.
  The two reasons are no longer conflated.

The provider classifier remains the ONE infrastructure policy.
A provider failure never becomes a domain verdict and never writes a
`PodExport`; the surfer records the child failure, backs off, and pauses the run
on quota exhaustion.

## Durable resume

A stopped pod is resumable at the variant boundary.

- `PodMemoryStore` writes `<spec_id>/<run_id>.resume.yaml`.
  The cursor is a sibling of the terminal export and is never an export.
- The cursor records the last order, the current variant, the iteration, the
  feedback, and the executed ledger.
- `ExperimentLog.hydrate` rebuilds the variants, raw observations, KB
  observations, interpretations, and the executed ledger from the per-order
  slices.
- `init` restarts at the cursor variant. The tools skip every probe signature
  already in the executed ledger.
- A terminal export clears the cursor.
- A cancelled pod writes no export. The gate holds the hunt because no durable
  export exists; the mover's consumed-spec recovery re-offers the spec after the
  backoff, and the next dispatch resumes from the cursor.

The inner `stateful_turn` checkpointer remains the conversation memory of the
pod roles.
The outer pod graph does not add a second checkpointer.

## Measured failure: iteration B, 2026-10-26

The 2700-second window is a deadline, not an inactivity bound.
The iteration B white-jotter run produced 66 pod exports; 58 were this watchdog's
`budget-timeout` envelope.
The pods were progressing, not wedged:

- 37 of the 58 wrote a probe observation less than five minutes before the export;
- the median gap was 3.3 minutes;
- two first-wave pods finished at 29.9 and 45.0 minutes, the second ten seconds
  before the window.

The unit-wide pod batch put 20 pods on the qemu target at once.
One lap could consume the whole window, so the pod's own lap budget never fired.
The per-hunt pod sequencing change (ticket 431) reduces the concurrency.
The pod failure boundary above (tickets 425, 432, 434) replaces the fixed pod
deadline with a progress-resetting idle timeout, a typed pod terminal, and a
one-hour surfer backstop.
The surfer path no longer writes `budget-timeout`; that reason now means only
the pod's own lap budget.

## Risk assessment

| Scenario | Likelihood | Effect without the fail-safe | Prevention now |
|---|---|---|---|
| A produced spec has corrupt YAML | medium | the mover skips it, the gate blocks, the run stalls | dispatched as a degraded pod, consumed, PodExport |
| A produced spec is a non-mapping body | low | the pod parse raises before INIT | the mover marks it malformed; the detail is recorded |
| A malformed body carries no target URL | low | the pod cannot probe | `init_route` rejects and the PodExport records it; the queue moves |
| A consumed malformed body has no export | low | the quiesce blocks forever | the mover recovers it as a degraded pod; a missing export stays an anomaly only until the retry lands |
| A hunter graph never ends | medium | the gate holds every later unit | the 45-minute watchdog settles the hunt and releases the registration |
| A pod node stops making progress | medium | the spec stays consumed with no export | the 600-second node idle timeout routes to the typed pod terminal |
| A pod process is stopped mid-run | medium | the spec has no export and the gate holds forever | the resume cursor hydrates the next dispatch; the gate holds until the terminal export |
| A provider quota is exhausted | medium | a domain verdict would fabricate a miss | the provider failure is re-raised; the surfer pauses the run; no PodExport |
| A terminal marker exists but a new draft lands after it | low | the cursor could skip a late spec | the gate records the late write as an anomaly; the store rejects a write after finalize |
| The target origin is unreadable | low | the bound identity is empty | the hunter keeps the authored override; the pod records the INIT violation |

The residual risk is a malformed body that makes the pod spend its budget
without a useful result.
That is a cost risk, not a stall risk: the PodExport still lands and the queue
advances.
The report should track the rate of malformed items, so a rising rate is fixed
at the write seam rather than absorbed by pod spend.
