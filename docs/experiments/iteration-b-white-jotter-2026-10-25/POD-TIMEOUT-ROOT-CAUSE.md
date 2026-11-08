# Pod watchdog failures - root-cause assessment

*Scope: iteration B, project `dda347be-abea-48e4-94e5-4a4039f41858`, hunting run `12d15890-47b2-43c2-bbe3-14c9626a2fdb`.*
*Evidence: 86 pod directories under `hunting/test-executor-pod`, 66 durable exports, 4 successful.*
*The report separates the design cause, the watchdog cause, the concurrency cause, and the stop-path cause.*

## Status

Causes 1 to 4 are fixed on `feat/pod-control-plane`.
The per-hunt batch (ticket 431) removed the unit-wide pod concurrency.
The pod control plane (tickets 425 and 434) owns node timeouts, typed terminals, and the one-hour surfer backstop.
The resume cursor (ticket 432) keeps stopped pods resumable.
The terminal record has ONE writer, `pod/finalize.py`; the surfer backstop now preserves the durable trail and never overwrites an execution terminal.
The per-target concurrency cap (ticket 433) is rejected by the operator.

## What failed

| Metric | Value |
|---|---:|
| Pod directories | 86 |
| Durable exports | 66 |
| Successful verdicts | 4 (6.1% of exports) |
| Unsuccessful verdicts | 62 (93.9% of exports) |
| `terminal_reason: budget-timeout` | 58 (87.9% of exports) |
| `symptom-confirmed` | 4 |
| `no-symptom-evidence` | 2 |
| `technical-infeasibility` | 2 |
| Pod directories with no export | 20 |

The 58 `budget-timeout` exports carry `verdict: unsuccessful`, `clean: false`, and the error text `the pod session exceeded its watchdog window`.
That text is the surfer's watchdog envelope, not the pod's own `HUNT_POD_MAX_ITERS` budget.
The pod's own budget never fired.

## Cause 1 - the batched spec dispatches the whole unit's pod set

The current ADR and spec say, for `batched`:

> Then the unit's pods: one pod per `ratified` spec of the batch, dispatched CONCURRENTLY.

The current code matches that text.
`_decide_batched` returns every `TestSpecItem` of the current unit once the hunter batch has left the graph.

The intended behaviour is one hunt at a time:

1. dispatch the unit's whole hunter batch, one hunter per threat;
2. when every hunter is terminal, dispatch the first hunt's pods, one pod per spec;
3. when every pod of that hunt is terminal, dispatch the next hunt's pods;
4. repeat until every hunt of the unit is done;
5. only then move to the next unit.

The run proves the current behaviour.
Twenty pods were created in the same second, `2026-10-25T23:01:04Z`, and they belong to five different hunts:

| Hunt | First-wave pods |
|---|---:|
| `Service-sign-in__threat-1` | 5 |
| `Service-sign-in__threat-10` | 3 |
| `Service-sign-in__threat-11` | 5 |
| `Service-sign-in__threat-2` | 4 |
| `Service-sign-in__threat-3` | 3 |

The intended design would have dispatched only the five specs of `threat-1` first.

## Cause 2 - the watchdog is a fixed deadline, not a liveness bound

`surfer.py` sets `DEFAULT_DISPATCH_TIMEOUT_S = 2700.0` (45 minutes).
`run_pod_session` wraps the pod builder in `asyncio.wait_for(..., timeout=session_timeout_s)`.
On expiry it writes the `budget-timeout` envelope.

The pods were progressing when the watchdog killed them:

- 18 of the 20 first-wave pods expired at about 45 minutes.
- The two first-wave successes finished at 29.9 minutes and 45.0 minutes.
- The second success landed ten seconds before the window.
- 37 of the 58 timeout pods wrote a probe observation less than five minutes before the export.
- The median gap between the last probe write and the watchdog export was 3.3 minutes.
- 18 timeout pods wrote within two minutes of the export.
- Timeout pods carried between 5 and 47 executed probes; several were deep in a variant.

The pod's own budget is lap-based: `HUNT_POD_MAX_ITERS=8`, checked at the DECIDE to PROBE edge, with up to `HUNT_POD_MAX_TOOL_CALLS=200` tool calls per stretch.
It has no wall-clock term.
Under target saturation, one lap can consume the whole 45-minute window, so the watchdog becomes the budget.

The degraded envelope also destroys the pod's own evidence.
The 18 first-wave timeout exports have no `variant_specs` and no provenance; only the pod's separate `experiment-log/0.yaml` retains the probes.

## Cause 3 - one global gate width creates a 45-minute convoy

`HUNTING_DISPATCH_GATE_WIDTH` defaults to 20.
It is global, not per-target.
The twenty admitted pods held every slot for the full watchdog window.
The remaining 33 specs of `Service:sign-in` waited, and `RESTApi:api` could not start until the unit's pods were terminal.
The unit barrier turned one slow wave into a whole-unit stall.

The `parallel`/`batched` gate width was sized for a healthy target.
Against the qemu-backed white-jotter host, 20 concurrent probe sessions are past the saturation knee.

## Cause 4 - the stop path drops live pods without an export

The last 20 pod directories were born between `02:48:42Z` and `02:50:50Z`.
The trial stopped the hunting run at `03:11:21Z` after crossing the 7M cap.
Those 20 pods had 4 to 14 probes each and no durable export.

A live pod cancelled by the run stop leaves no terminal record.
The queue can therefore not distinguish "not finished" from "lost", and the measurement counts the directories as export-less.

## What is not the cause

- The modeller halt is correct. The crossing unit `Service:library-catalog` finished, and `Service:navigation-menu` was blocked. That matches the intended halt.
- The hunter batch is correct. One hunter per threat of the unit, dispatched concurrently.
- Provider failures are not the cause. The watchdog message is local, and no provider error appears on the pod exports.
- The 12 contract-broken specs are a separate hunter-contract defect; they do not explain the watchdog.

## Ranked root causes

1. **Design and code: `batched` uses a unit-wide pod batch instead of a per-hunt pod batch.** This is the cause the operator named, and the run evidence matches it exactly.
2. **Watchdog: a fixed 2700-second wall clock kills progressing pods.** It is a deadline, not an inactivity bound, and its degraded envelope overwrites the pod's evidence.
3. **Concurrency: the global gate width of 20 saturates the target and creates a 45-minute convoy.** This is a consequence of cause 1 and an independent tuning defect.
4. **Stop path: live pods are cancelled without an export.** This loses the last wave and makes the run unable to resume that work.
5. **Budget model: the pod's own budget is lap-based and has no time term.** The watchdog is the only wall clock, so "budget-timeout" names the wrong bound.

## Fix order

1. Amend the pipeline-sync ADR, spec, assertions, and CONTEXT to the per-hunt pod phase (ticket 431, done).
2. Refactor `pipeline_sync.py` under TDD so `batched` admits only the cursor hunt's specs, and advances the hunt only when every pod of the hunt has a durable export (ticket 431, done).
3. Run the pipeline-sync unit and gate suites, then `tests/attack`, `tests/eval`, and the hunting integration suites (ticket 431, done).
4. Make the watchdog progress-aware or inactivity-based, and preserve the pod's own terminal on expiry (tickets 425 and 434, done).
5. Keep every live pod durably resumable (ticket 432, done).
6. Add a per-target concurrency cap beside the global gate width (ticket 433, rejected by the operator).
