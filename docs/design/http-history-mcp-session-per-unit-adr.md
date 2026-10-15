# ADR: the HTTP-history MCP session lives per analysis unit

**Status:** FIX, operator-directed (2026-10-13; branch `exp/endpoint-first-prefix`).
Amended 2026-10-14 (FM-D heal; branch `fix/fm-toolcall-fixes`): a transport death now re-handshakes silently in the client layer - see "Change 4".
Amended 2026-10-15 (arm H follow-up; branch `fix/streamed-pipeline-corrections`): the boundary close landed, the install became install-or-yield, and the heal became identity-checked - see "Change 5".
**Related:** `docs/design/endpoint-first-prefix-adr.md` (the arm F trial whose stall exposed this), `docs/design/proposer-per-batch-cache-adr.md` (the per-batch session address this reuses).
**Touches:** `app/clients/kali_http_history.py`, `recon/control/async_bridge.py`, `analysis/proposer_turn.py`.

---

## 1. The decision, in one line

Keep ONE kali HTTP-history MCP session alive per analysis unit - opened on the unit's first HTTP call, reused for the unit's remaining calls, closed at the unit boundary - instead of opening a fresh MCP session on every tool call, and bound every wait so no failure can stall a proposer turn.

## 2. Why (the arm F stall)

The arm F trial (endpoint-first prefix) froze: usage stopped at 195,038 capped tokens and the analysis run sat in `draining` for 3h45m. A live stack dump (py-spy) placed the proposer thread inside `run_coro_blocking` under `default_http_search_fn` - a hung HTTP-history MCP call - with the worker thread in the loop's `select` forever.

Two defects, both in the old `_call_tool` shape:

- **A fresh MCP session per tool call.** `_call_tool` built a new `MultiServerMCPClient` and called `get_tools()`; the adapter opens a NEW session per call ("A new session will be created for each tool call"). Kali logged 280 `POST /mcp` and 85 `GET /mcp` for roughly two units - a full handshake per call, and the latency that stretched unit 1's turns to 8-12 minutes.
- **An unbounded bridge.** `run_coro_blocking` was `ex.submit(...).result()` with no timeout, so a call that never reached a terminal blocked the turn forever. The adapter's own 300s read timeout did not save it, which is why the stall outlived every read bound.

The recon exec seam (`recon.domain.pod.default_exec_fn`) already did more: it set `sse_read_timeout` and re-handshook once on a broken session. The HTTP-history seam did neither.

## 3. Change 1 - one MCP session per unit, on a process background loop

**Rule.** An MCP `ClientSession` is bound to the event loop it was opened on, so a per-call bridge (a fresh loop each time) can never reuse one. The client therefore owns ONE background event loop for the process, and keeps ONE session per analysis unit on it.

**Implementation.** `_UnitSession` opens `client.session("kali")` + `load_mcp_tools(session)` on the background loop and holds the loaded tools; `_session(project_id)` keys it on `(project_id, current_batch())` - the existing `proposer_batch` discriminator - opening on first use and replacing the prior unit's on a key change.

## 4. Change 2 - the unit boundary closes the session

**Rule.** The teardown point is the unit, not the process.

**Implementation.** `proposer_turn.proposer_batch` - already the unit scope - calls `close_unit_session()` in its `finally` (landed in Change 5; documented here as the section-4 rule). A unit therefore carries exactly one handshake and never leaks a connection into the next unit. Fail-open: an unimportable client never breaks the proposer body.

## 5. Change 3 - every wait is bounded

**Rule.** No single HTTP-history failure may stall a turn.

**Implementation.** The client carries a streamable-HTTP read timeout (`sse_read_timeout`), and bounds the session open, the tool call, and the session close. `run_coro_blocking` gains an optional `timeout_s`; on expiry it raises `TimeoutError` and abandons the worker without joining it - `shutdown(wait=True)` would re-block on the very task just given up on. The HTTP seam fail-opens to its `http_history_failed` bundle, so the turn always terminates.

## 6. What this does NOT change

- The tool contracts, the three seam signatures, and `structured_payload` are unchanged; the hunting module's use of the same seams is unchanged.
- The per-batch session address, the constant request shape, and the endpoint-first prefix are untouched.
- Fail-open stays: a session that cannot open degrades to the error bundle, never a raise into the turn.

## 7. Consequences and the confirmation step

The per-unit session removes the per-call handshake churn (one connection per unit) and the bounded waits remove the stall class entirely. The confirmation step is the re-run arm F trial: units must complete (no freeze) and the kali MCP call count must fall from one-per-call to roughly one-per-unit.

## 8. Change 4 (FM-D, 2026-10-14) - a transport death heals in the client layer

**Rule.** One dead session costs exactly one call, never the rest of the unit. Healing lives entirely in the client layer: silent, no tool result carries healing chatter, and the failed call is never retried (the seam also serves the non-idempotent `replay` - a retry could mint a duplicate artifact).

**Implementation.** `_heal_unit_session` (`app/clients/kali_http_history.py`): on `ClosedResourceError`, a timeout, or an `OSError` out of a call, tear the unit session down and re-handshake - up to 3 attempts with exponential backoff (1s, 2s, 4s), each bounded by the open timeout - installing the fresh session under the unit key on success. Compare-and-swap under the session lock: a concurrent heal that already installed a session wins and the loser closes its surplus. When every attempt fails nothing is cached and the next call heals again. Non-transport errors never heal (the live session is kept). No heartbeat: deaths are occasional (73 in 33h across many units), so heal-on-death bounds the blast radius without a background task to own.

The compare-and-swap as landed was KEY-based, not session-identity-based: a healer tore down whatever sat under the unit key. Change 5 corrects that - see "Change 5".

## 9. Change 5 (2026-10-15) - the per-unit lifecycle holds under parallel calls

**Why.** The arm H trial (sha `a088730d`) exposed the shapes this ADR assumed wrong. The kali access log for the analysis window shows 268 sessions opened, 267 clean `DELETE /mcp` 200s, and exactly one `POST /mcp` 404; the log carries bursts of three `GET /mcp` in the same instant - three session opens from ONE turn's parallel tool calls. The proposer trace shows `ClosedResourceError` in 14 of 14 assigner turns and 39 error-level tool results. Three defects compounded:

1. `_session()` opened outside the lock and the install retired whatever sat under the key, so parallel callers that missed the cache together closed EACH OTHER's live sessions.
2. `_heal_unit_session()` was key-checked, not identity-checked, so a second healer (or a healer racing a fresh install) tore down a live replacement; that death healed again: a kill cascade.
3. `close_unit_session()` was never called: the section-4 boundary hook was documented but had not landed, so sessions closed only on key change or heal.

**Change.** `_session()` is install-or-yield: the open stays outside the lock (the slow network path); under the lock the first same-key session to land wins, and every later opener closes only its OWN surplus and returns the winner - a caller never closes a same-key session it did not open. `_heal_unit_session(project_id, dead)` is identity-checked: only the session the failing call USED is torn down, and only while it is still the cached one; a session already replaced is left alive, and a stale healer spends no handshake. `proposer_turn.proposer_batch` calls `close_unit_session()` in its `finally` (for a real batch id; a None scope stays a no-op), so the session closes at the same boundary where the agent session is reset - reset, not torn down - and the next chunk opens fresh.

**Assessment the operator asked for.** Closing at the unit boundary is reliable. The kali server acknowledged every one of the 267 DELETEs with 200 (only one session in the window was never closed), the close is bounded (`_MCP_CLOSE_TIMEOUT_S` 15s) and best-effort, and a failed close costs nothing but a session the server reaps anyway. The arm H failures came from the conflicting installs and the stale heals, not from closing - so the per-unit close plus a fresh session per chunk is the lifecycle this version carries.

**Confirmation step for the next trial.** Proposer traces show zero `ClosedResourceError`; kali session opens are on the order of units plus the exec seam's per-call sessions, not multiples per unit.
