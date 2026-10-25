# Hunting lifecycle fail-safe

*Status: implemented on `fix/hunt-spec-contract-realign`.*

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

Only cases 1 and 2 can hold the queue for an unbounded time, and the session
watchdog bounds case 1.
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
6. The pod writes a PodExport on every path, including INIT rejection and the
   outer degrade path.
7. The mover consumes the spec; the pod export is the completion fact.

A consumed malformed body is terminal once its PodExport exists.
Without an export it remains an anomaly and the quiesce blocks.

## The session watchdog

`RunDispatchState.session_timeout_s` defaults to 2700 seconds (45 minutes).

- `run_hunter_session` wraps its graph in `asyncio.wait_for`.
  On timeout the registration is released, `settle_hypothesised` declasses the
  leftover drafts, and the terminal marker lands.
- `run_pod_session` wraps its pod builder in `asyncio.wait_for`.
  On timeout it writes a `budget-timeout` PodExport with `clean=false`.
- The value is a run-state attribute, so a trial can tighten it without a code
  change.

This is simpler and more reliable than polling the lower control plane's thread
state:

- the watchdog is local to the dispatched coroutine and needs no extra API;
- it covers a wedged model call and a wedged harness turn alike;
- it leaves a durable degraded record (a terminal set or a PodExport), so the
  queue advances from storage, not from a transient registry fact;
- the thread-state approach needs a second source of truth and a mapping from a
  worker thread to a hunt, which is exactly the coupling the run-local state
  already avoids.

The existing `a16bb256` settle remains the first line of defence: a graph that
ends without a finalize settles immediately.
The watchdog is the second line: a graph that never ends is bounded.

## Risk assessment

| Scenario | Likelihood | Effect without the fail-safe | Prevention now |
|---|---|---|---|
| A produced spec has corrupt YAML | medium | the mover skips it, the gate blocks, the run stalls | dispatched as a degraded pod, consumed, PodExport |
| A produced spec is a non-mapping body | low | the pod parse raises before INIT | the mover marks it malformed; the detail is recorded |
| A malformed body carries no target URL | low | the pod cannot probe | `init_route` rejects and the PodExport records it; the queue moves |
| A consumed malformed body has no export | low | the quiesce blocks forever | the mover recovers it as a degraded pod; a missing export stays an anomaly only until the retry lands |
| A hunter graph never ends | medium | the gate holds every later unit | the 45-minute watchdog settles the hunt and releases the registration |
| A pod graph never ends | medium | the spec stays consumed with no export | the watchdog writes a `budget-timeout` PodExport |
| A terminal marker exists but a new draft lands after it | low | the cursor could skip a late spec | the gate records the late write as an anomaly; the store rejects a write after finalize |
| The target origin is unreadable | low | the bound identity is empty | the hunter keeps the authored override; the pod records the INIT violation |

The residual risk is a malformed body that makes the pod spend its budget
without a useful result.
That is a cost risk, not a stall risk: the PodExport still lands and the queue
advances.
The report should track the rate of malformed items, so a rising rate is fixed
at the write seam rather than absorbed by pod spend.
