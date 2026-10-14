# ADR: HTTP-history search filters are semi-joins, not correlated subqueries

**Status:** FIX, operator-directed (2026-10-13; branch `exp/endpoint-first-prefix`).
**Related:** `docs/design/http-history-mcp-session-per-unit-adr.md` (the client-side half of the same arm-F stall), `docs/experiments/mcp-http-history-hang-diagnosis.md` (the full diagnosis).
**Touches:** `kali/http_history/store.py` (`_filter_sql`), `tests/kali/test_http_history_search.py`.

---

## 1. The decision, in one line

A search filter is compiled to a semi-join - `f.artifact_id IN (SELECT ...)` / `NOT IN (SELECT ...)` - and never to a correlated `EXISTS`/`NOT EXISTS` subquery.

## 2. Why (the arm-F stall, upstream half)

The arm-F analysis froze with the proposer thread inside a `search_http_history` MCP call.
The client-side ADR covers the unbounded wait; this ADR covers why the call itself was minutes long.

`_filter_sql` built `EXISTS (SELECT 1 FROM attributes a WHERE a.artifact_id = f.artifact_id AND a.side=? AND a.namespace=? AND a.key=? ...)`.
SQLite evaluates that subquery once per candidate flow, and each evaluation walks every attribute row sharing the key.
On a filter over a common key the cost is therefore O(flows x matching-attributes) - quadratic.
On the capture that stalled (32,473 flows, 946,421 attribute rows; `response/header/server` 32,472 rows, `response/body/marker` 15,845 rows) that is ~1e9 index probes.
Measured through the live MCP path: unfiltered 0.04 s, `absent` on `response/header/server` 85 s, `contains` on `response/body/marker` 152 s.
The tool description invites exactly these filters (`absent` is documented as "how you build the control group"), so every model turn can trip it.

## 3. The change

`kali/http_history/store.py::_filter_sql` replaces the two correlated forms:

- `absent`: `f.artifact_id NOT IN (SELECT a.artifact_id FROM attributes a WHERE a.side=? AND a.namespace=? AND a.key=?)`.
- `eq`/`contains`/`prefix`/`gte`/`lte`: `f.artifact_id IN (SELECT a.artifact_id FROM attributes a WHERE a.side=? AND a.namespace=? AND a.key=? AND <op>)`.

The planner materialises the matching attribute ids once and probes the flow primary key, so the query is linear in the result set.
`attributes.artifact_id` is `NOT NULL`, so `NOT IN` carries no NULL hazard.

## 4. What this does NOT change

- The filter vocabulary, the `op` semantics, the cursor/ordering contract, and the sanitized summary shape are unchanged.
- The unfiltered search path is untouched (`_filter_sql` returns "" for no filters).
- `text_search` (FTS) is untouched.

## 5. Consequences and the confirmation step

Measured on the same live store: `absent` 85 s -> 0.03 s; no-match `contains` 152 s -> 0.006 s; every probed filter sub-40 ms.
The confirmation step is the re-run arm-F trial: unit turns must not stall on `search_http_history`.
The regression is locked by `test_search_filter_does_not_scan_attributes_per_flow`, a deterministic VM-step-budget test on a 800-flow store (red on the correlated plan, green on the semi-join).
