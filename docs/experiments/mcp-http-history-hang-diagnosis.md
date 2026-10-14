# Upstream diagnosis: the kali HTTP-history MCP hang (arm F, 2026-10-13)

Scope: the UPSTREAM cause of the `search_http_history` call that never returned.
The app-side client fix (session-per-unit, bounded waits) is out of scope and was not touched.
Branch: `exp/endpoint-first-prefix`, worktree `/Users/diekgbbtt/.claude/worktrees/endpoint-first-prefix`.
Client-side context: `docs/design/http-history-mcp-session-per-unit-adr.md`.

## TL;DR

The root cause is a LOCAL, NARROW bug in the kali HTTP-history store: `search` built its filters as correlated `EXISTS`/`NOT EXISTS` subqueries, so a filter on a common key re-scanned every matching attribute row once per flow - O(flows x matching-attributes).
On the arm-F capture (32,473 flows, 946,421 attribute rows) that is ~1e9 index probes.
A single such call measured 83-152 s through the live MCP path; several shapes exceed 300 s.
Combined with the old client's unbounded wait, a minutes-long call became a permanent stall.
The fix is a semi-join rewrite in `kali/http_history/store.py` `_filter_sql`; it turns the same filters into sub-40 ms calls.
Recorded filters were never flushed to Langfuse (the process was killed mid-call), so the exact model args are unknown - which is now immaterial, because the fix removes the blowup for ANY filter.

## 1. Phase 1 - the feedback loop (red-capable, deterministic, fast, agent-runnable)

The loop drives the real MCP tool `search_http_history` on the live kali server, over the same store that hung.
It is a minimal MCP client (`mcp.client.streamable_http` + `ClientSession`), run inside the app container so `kali:8000` resolves.
Each call is bounded by `asyncio.wait_for`, so a hung server surfaces as `TIMEOUT` instead of blocking the harness.

Command (run at least once; secrets stay in the container env, nothing printed):

```bash
docker exec -i -e CALL_TIMEOUT=240 ph-dd131acc-agent-1 python3 - < mcp_loop.py
```

Harness (verbatim, redaction-free - no creds used):

```python
import asyncio, json, time, os
URL = os.environ.get("KALI_MCP_URL", "http://kali:8000/mcp")
PROJECT = "73ec2669-f9cf-4d65-912f-6be3b9e633e9"
CALL_TIMEOUT = float(os.environ.get("CALL_TIMEOUT", "180"))
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def call(session, label, args):
    t0 = time.monotonic()
    try:
        res = await asyncio.wait_for(session.call_tool("search_http_history", args),
                                     timeout=CALL_TIMEOUT)
        print(f"  {label:<52} {time.monotonic()-t0:8.3f}s")
    except asyncio.TimeoutError:
        print(f"  {label:<52} TIMEOUT after {CALL_TIMEOUT}s  <-- would hang the proposer")

def contains(side, ns, key, val):
    return [{"side": side, "namespace": ns, "key": key, "op": "contains", "value": val}]
def absent(side, ns, key):
    return [{"side": side, "namespace": ns, "key": key, "op": "absent"}]

async def main():
    async with streamablehttp_client(URL, sse_read_timeout=CALL_TIMEOUT + 30) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            await call(s, "unfiltered limit=50", {"project_id": PROJECT, "limit": 50})
            await call(s, "absent response/header/server", {"project_id": PROJECT, "filters": absent("response","header","server")})
            await call(s, "contains response/body/marker 'zzqqxx' (no match)", {"project_id": PROJECT, "filters": contains("response","body","marker","zzqqxx")})

asyncio.run(main())
```

Redacted output (exact, no secrets present):

```
  unfiltered limit=50                                     0.043s summaries=50 next_cursor=True err=None
  absent response/header/server                          85.071s summaries=1 next_cursor=False err=None
  contains response/body/marker 'zzqqxx' (no match)     152.470s summaries=0 next_cursor=False err=None
```

Red evidence: the unfiltered search is instant, while a single `absent`/`contains` filter takes 85-152 s on the live store.
The signal is the user's exact symptom (a `search_http_history` call that does not return promptly); it is deterministic (same verdict every run) and fast enough to iterate (one query, seconds to minutes).

## 2. Phase 2 - reproduce + minimise

Reproduced through the live MCP path (loop above) and, tighter, directly at the store seam on a copy of the live DB (see section 5's `patched_check`).
Minimal trigger: any single filter whose `(side, namespace, key)` matches a large number of attribute rows.

The minimised element is the query PLAN, not the data:
`EXPLAIN QUERY PLAN` for the old filter shows `SCAN f USING INDEX flows_created` followed by a per-flow correlated subquery:

```
SCAN f USING INDEX flows_created
CORRELATED SCALAR SUBQUERY 1
SEARCH a USING COVERING INDEX attributes_numeric_cov (side=? AND namespace=? AND key=?)
```

The correlated subquery is re-evaluated for every one of the 32,473 flows, and each evaluation walks all attribute rows sharing the key, so cost is quadratic in the flow count when the key is common.
The two common keys that make it bite: `response/header/server` (32,472 rows) and `response/body/marker` (15,845 rows, values up to the 20,000-char `_MARKER_LIMIT`).

I could not retrieve the model's exact filter arguments: the proposer's hung turn was never flushed to Langfuse (its last flushed observation is 11:39:14, before the freeze), and the serer never logged POST bodies.
This does not block the fix, because the defect is in the query shape for ANY filter, not in one input.

## 3. Ranked hypotheses

Operator candidates (1-4) plus the store-plan candidate (H1).

| # | Hypothesis | Prediction | Outcome |
| --- | --- | --- | --- |
| H1 | **Filter query plan is quadratic** (`_filter_sql` correlated subqueries) | A broad `absent`/`contains` filter on a common key takes minutes; rewriting to a semi-join is instant | **CONFIRMED** - 85-152 s live; rewrite 0.03-0.005 s |
| H2 | Project-scoping filter failed (returns everything, or matches nothing and loops) | Removing/altering `project_id` changes the result; cross-project rows leak | **REJECTED** - `WHERE f.project_id = ?` is always applied (`store.py:296,298`); `tests/kali/test_http_history_search.py::test_search_never_leaves_the_project` passes; direct count shows all 32,473 flows belong to the project |
| H3 | Network connectivity error between agent and kali | Sockets fail/timeout; kali logs connection errors | **REJECTED** - kali was healthy; connections were ESTABLISHED; no error lines; the loop reaches kali instantly for unfiltered calls |
| H4 | Kali flooded with leaked/abandoned MCP sessions -> thread/FD exhaustion | Server worker pool saturates; new calls queue forever; many ESTABLISHED sessions | **PLAUSIBLE SECONDARY, not the trigger observed** - at the hang the app held ~4 ESTABLISHED connections, not a pool's worth; now 0; no FD/thread pressure. Untested at load, needs a concurrency test |
| H1b | Huge response / large-payload serialization | Response body is enormous; serialization stalls | **REJECTED as stated** - `limit` is capped at 200 (`store.py:31`), rows are sanitized summaries; the unfiltered 50-row page returns in 0.04 s. The driver is query COST, not payload size |
| H1+H4 | A minutes-long query, retried by the unbounded old client, accumulates server workers over ~3h | The stall duration is set by the client's unbounded wait, not by one query | **CONSISTENT with the 3h45m** - a single query measures <=152 s, so the full duration is the product of the slow query class and the unbounded/retrying client, not one query alone |

Note on the 3h45m: a single filter of this class tops out around 152 s on this store, so the query alone does not account for 3h45m.
The permanent stall is the combination of (a) a minutes-long query class and (b) the old client's unbounded wait (`async_bridge.py run_coro_blocking` with no timeout, per the client ADR).
The client fix bounds the wait; this fix removes the slow query class, so neither half survives.

## 4. Root cause, with the evidence that pins it

**Cause: `HttpHistoryStore._filter_sql` built correlated `EXISTS`/`NOT EXISTS` subqueries, which SQLite evaluates once per candidate flow, making a filter on a common attribute key O(flows x matching-attributes).**

Evidence chain:
- The py-spy stack pins the hang in `search_http_history` (`default_http_search_fn -> _call_tool -> async_bridge.run_coro_blocking`).
- The live loop reproduces it: `absent` on `response/header/server` = 85.07 s; `contains` on `response/body/marker` = 152.47 s; unfiltered = 0.04 s.
- `EXPLAIN QUERY PLAN` shows `SCAN f ... CORRELATED SCALAR SUBQUERY`, i.e. the per-flow re-scan.
- The store held 32,473 flows and 946,421 attribute rows; `response/header/server` has 32,472 rows and `response/body/marker` 15,845 rows, so the correlated loop is ~1e9 probes.
- Scaling is quadratic: on a synthetic store the old plan's VM-step checkpoints were 1,041 (N=200) -> 4,082 (N=400) -> 16,164 (N=800) for `absent`, exactly 4x per doubling.
- The tool description actively invites the triggering filters: `SEARCH_HTTP_HISTORY_DESCRIPTION` advertises `contains` and tells the model that `absent` "is how you build the control group" (`src/polymerhus/attack/hunting/http_history_contract.py:51-68`).

Code path: `kali/mcp_server.py:161` (`search_http_history`) -> `_offload` (`:25`) -> `service.search` (`kali/http_history/service.py:143`) -> `store.search` (`kali/http_history/store.py:256`) -> `_filter_sql` (`:322`).
The `attributes` schema declares `artifact_id TEXT NOT NULL` (`store.py:54`), so the semi-join `NOT IN` is NULL-safe.

## 5. The fix

Local and narrow: it changes only `_filter_sql` in `kali/http_history/store.py` (no global decision).
The correlated subqueries become semi-joins:

- `absent`: `f.artifact_id NOT IN (SELECT a.artifact_id FROM attributes a WHERE a.side=? AND a.namespace=? AND a.key=?)`
- `eq`/`contains`/`prefix`/`gte`/`lte`: `f.artifact_id IN (SELECT a.artifact_id FROM attributes a WHERE a.side=? AND a.namespace=? AND a.key=? AND <op>)`

SQLite then materialises the matching attribute ids once (LIST SUBQUERY / bloom filter) and probes the flow primary key, which is linear in the result set.

Measured (same live store):

| filter | old plan | new plan |
| --- | --- | --- |
| `absent response/header/server` | 83-85 s | 0.03 s |
| `contains response/body/marker 'zzqqxx'` | >90 s (152 s via MCP) | 0.006 s |

Regression test (correct seam = `HttpHistoryStore.search`, `tests/kali/test_http_history_search.py`):
`test_search_filter_does_not_scan_attributes_per_flow` seeds 800 flows that all carry `response/header/server`, runs the filter under a SQLite progress handler, and asserts the query does not abort at a 5,000-checkpoint budget and stays linear.
It is deterministic (VM-step counts, not wall clock).
Red before the fix (both params), green after: old plan crosses 16,164 / 32,120 checkpoints at N=800; new plan crosses 128 / 40.

Post-fix validation of the PATCHED method against a copy of the live 387 MB DB (non-invasive: DB copied, container not restarted):

```
  unfiltered                                            0.002s rows=50
  absent response/header/server                         0.031s rows=1
  contains response/body/marker zzqqxx                  0.006s rows=0
  contains request/header/host comfy                    0.008s rows=0
  eq request/core/url x                                 0.000s rows=0
  4 conjunctive filters                                 0.006s rows=0
```

Test runs: `tests/kali` store/search/service/normalize = 53 passed; `tests/attack/test_http_history_tools.py` + `test_http_history_wiring.py` = 9 passed.
(`tests/kali/test_http_history_mcp_tools.py` cannot run locally: `fastmcp` is not installed in this checkout - an environment limitation, not a regression.)

Design record: `docs/design/http-history-search-filter-plan-adr.md`.

## 6. Post-fix cleanup + confirmed hypothesis

- The Phase 1 loop re-run is the `patched_check` table above: the exact bad filters are now sub-40 ms.
- No `[DEBUG-*]` instrumentation was added; nothing to remove.
- Throwaway artifacts removed: the container overlays `/tmp/patched` and `/tmp/livecopy` and the host `/tmp/store_patched.py` were deleted; the live kali container was never restarted and its data was not mutated.
- Confirmed hypothesis: **H1 - the correlated-subquery filter plan is the upstream cause**; it is local and narrow, and is fixed.
- What would have prevented it: the store had no performance regression test for `search` on a store with realistic cardinality. The new test locks the plan in. A broader guard (a statement-level time/budget on model-issued searches, or an index/plan review for every filter op) is the architectural follow-up; H4 (server worker-pool exhaustion under sustained concurrent tool calls) remains untested and should be covered by a concurrency test if the operator wants that half closed too.
