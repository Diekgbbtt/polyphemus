# Analysis-proposer tool-call failure modes (Langfuse harvest)

Status: FM-A, FM-B, FM-C, FM-D and FM-E fixed 2026-10-14 (see the fix notes); FM-F recorded (probe-only, mechanism diagnosed, operator chose record-only).
Window: 2026-10-13T00:00Z .. 2026-10-14T09:35Z.
Source: Langfuse v2 observations (`GET /api/public/v2/observations`), project polyphemus (`cmv6cdk12000sad0nbechto7t`).
Scope: the three L0-grounding tools bound on every analysis proposer turn - `graph_view`, `search_http_history`, `get_http_artifact`.

## Method

Query parameters that filter (empirically verified): `name`, `level`, `type`, `sessionId`, `traceId`, `userId`, `environment`, `version`, `fromStartTime`, `toStartTime`.
Pagination is cursor-based: pass `meta.cursor` back as `cursor`; the `page` parameter is accepted but ignored.
The scalar `tags` parameter is accepted but ignored; only array syntax `tags[]` / `traceTags[]` is honored.
A proposer session is named `{recon_run_id}:{pod}:{proposer}` - for example `5be67569-...:katana_10:mechanism_typist`.
Two recent runs dominate the window: `a1c1f6ea-...` and `5be67569-...`.

## Observed volume

| tool | calls | ok | failed |
| --- | --- | --- | --- |
| `search_http_history` | 1293 | 1076 | 217 |
| `get_http_artifact` | 488 | 452 | 36 |
| `graph_view` | 744 | 742 | 2 (plus 6 refusals across all seams) |
| `tools` (MCP chain) | 1989 | 1986 | 3 |

By proposer: assigner, mechanism_typist, data_modeller dominate; the triager makes almost no tool calls.

## Failure modes

### FM-A - `graph_view` write-guard false positive (FIXED 2026-10-14)

Fix applied as proposed, on both seams (the 4 chain-surfaced refusals share the hunting guard): the write-shape guard now scans `_strip_cypher_for_guard` output - string literals, backtick-quoted identifiers and `//`/`/* */` comments blanked - single-sourced in `attack/hunting/graph_view_tool.py` and reused by the analysis seam through a lazy import (fail-closed fallback to the raw text), plus the literal-safety verbatim in both contracts. An unbalanced quote still fails closed. Known residual: an unquoted identifier that IS a write word (`RETURN e.create`) still refuses - quoting is the model's lever. Regression: literal/comment/backtick acceptance + genuine-keyword refusal on both seams; red pre-fix, green post-fix.

Count: 6 refusals (2 as `graph_view` ERROR observations, 4 surfaced in the parent `tools` chain).
Example cypher that was refused (it is a pure read):

```
MATCH (b:BaseURL {project_id: $project_id})-[:HAS_ENDPOINT]->(e:Endpoint)
WHERE e.path CONTAINS 'account' OR e.path CONTAINS 'create' OR e.path STARTS WITH '/users'
RETURN b.url AS baseurl, e.method, e.path LIMIT 50
```

The guard matched the write word `create` **inside the string literal `'create'`**.
`src/polymerhus/analysis/graph_tools.py:31` is `_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")` and line 106 applies it to `cypher.upper()` with no literal stripping.
The agent loses a legal surface harvest turn; the refusal message does not say the filter was legal.

Missing semantics: the description warns that write keywords are refused, but never that the match is literal-blind.
The correct fix is code (strip quoted literals and `//`/`/* */` comments before the search), and the message should state that a `CONTAINS '<word>'` filter is always allowed.

Proposed verbatim (append to `_QUERY_PRIMITIVES` in `graph_tools.py`):

> Text inside a string literal is DATA, not Cypher. A path or value filter that happens to contain a write word is legal and always allowed: `WHERE e.path CONTAINS 'create'`, `WHERE e.path STARTS WITH '/users'`. The guard refuses a write word only where it stands as a Cypher keyword. Always quote your literals.

### FM-B - `search_http_history` filter-vocabulary misuse (FIXED 2026-10-14)

Fix applied as proposed (prompt-only): the search description now teaches the side/namespace axes split, the closed op enum with no `present`, and the `eq`-no-booleans rule, each pinned by a contract assertion. No code change - the store already rejects misspellings with a denoted error, now categorized `invalid_filter` by the FM-C mapping.

Count: 12.

| error | count | cause |
| --- | --- | --- |
| `unknown side 'core'` | 6 | a `namespace` value placed in `side` |
| `unknown op 'present'` | 4 | invented op (`present`; the enum has `absent`) |
| `eq does not accept booleans` | 2 | a boolean `value` passed to `eq` |

Example input: `{"filters":[{"side":"core","namespace":"request","key":"url","op":"contains","value":".map"}]}` - `side` must be one of request|response|connection|context|timing, never a namespace.

Missing semantics: `SEARCH_HTTP_HISTORY_DESCRIPTION` (`src/polymerhus/attack/hunting/http_history_contract.py:51`) already lists both enums, but does not separate the two axes or forbid invented ops.
The agent conflates `side` with `namespace`, which are listed on adjacent lines.

Proposed verbatim (insert into `SEARCH_HTTP_HISTORY_DESCRIPTION` before the artifact model):

> Filter vocabulary is exact. `side` and `namespace` are TWO DIFFERENT AXES of one filter `{side, namespace, key, op, value}`: `side` is one of request|response|connection|context|timing, `namespace` is one of core|header|cookie|query|form|body|tls. Never put a namespace value in `side`. Example: `{side:'request', namespace:'query', key:'filename', op:'contains', value:'x'}`. `op` is exactly one of eq|contains|prefix|gte|lte|absent; to require that a key IS present, exclude its `absent` complement - there is no `present` op. `value` is a string or a number; `eq` does not accept booleans. A misspelled op, side or namespace is a filter error (`invalid_filter`), not an empty result.

### FM-C - raw backend errors leak with no actionable category (FIXED 2026-10-14)

Fix applied: the replay harness proved all four manifestations share one root cause - the MCP server runs tool calls on concurrent worker threads against one cached store connection per project, and the store's reads took no lock, so a read racing a write surfaced SQLITE_MISUSE as `bad parameter` (plus transient tuple-index and validation errors); the FTS phrase handling is innocent (every failing phrase succeeds single-threaded). The fix serializes every connection access on the store's existing RLock, the search skips unreadable rows fail-open (empty page when none survive), `get_raw` raises the typed `CorruptRecordError`, blob GC defers when any row is unreadable, and `_error_payload` maps ValueError to `invalid_filter`, `CorruptRecordError` to `corrupt_artifact`, `sqlite3.Error` to `unavailable` (fallback `invalid_request` kept). Regression: `test_concurrent_readers_and_writer_share_one_connection` (78k race reads, zero errors), skip/corrupt/GC tests, `_error_payload` category test; `tests/kali` + `tests/attack` 902 passed.

Count: 76.

| error detail | count | cause |
| --- | --- | --- |
| `bad parameter or other API misuse` | 40 | the store's free-text `text` search fails on certain phrases |
| `1 validation error for HttpArtifact ... Invalid JSON: EOF` | 28 | a stored artifact whose body JSON is empty/corrupt |
| `tuple index out of range` | 6 | a backend crash surfaced raw |
| `1 validation error for HttpArtifact ... JSON input should be string` | 2 | a stored artifact with a null body slot |

Example: input `{"text":"/scripts","limit":10}` returns `{"error":"invalid_request","detail":"bad parameter or other API misuse"}`.

Missing semantics: the description promises "a rejected filter degrades to a denoted error object", but the object carries a raw exception string with no category.
The model cannot tell "my filter is wrong, fix it" from "this stored record is unusable, skip it" from "the store is down, continue without history".

Proposed verbatim (insert into `SEARCH_HTTP_HISTORY_DESCRIPTION`):

> Every failure is a denoted error with a `category`, never a raise, and the category tells you what to do: `invalid_filter` - your filter or `text` is malformed; fix it and retry. `not_found` - the artifact id is unknown or belongs to another project; pick another id. `corrupt_artifact` - the stored record cannot be parsed; skip it and continue, it is not evidence about the target. `unavailable` - the history store could not be reached for this call; this is NOT evidence that the surface is empty, so continue with other evidence and retry later.

Proposed code fix: in `_call_tool` (`src/polymerhus/app/clients/kali_http_history.py:189`), map the backend exception to that `category` and never emit an empty `detail`.

### FM-D - MCP session death poisons the rest of the unit (FIXED 2026-10-14)

Fix applied (operator-steered: heal-forward, healing entirely in the client layer, no heartbeat): `_heal_unit_session` tears the dead session down and re-handshakes up to 3 times (1/2/4s backoff), installing the fresh session under the unit key on success - one transport death costs exactly one call, and the failed call is never retried (the seam also serves the non-idempotent `replay`). Covers the hunting caller too (it shares the seam outside `proposer_batch`). Regression: transport-death heal, exhausted-heal, and no-heal-on-programming-error tests (red pre-fix, green post-fix); `http_history_failed` missing-evidence verbatim added to the search description; ADR `http-history-mcp-session-per-unit` amended with Change 4.

Count: 73 `http_history_failed` = 58 `ClosedResourceError: ` + 15 `TimeoutError: `, spread over assigner (31), mechanism_typist (17), data_modeller (10).
Every one has an EMPTY exception string and `output: null` (level ERROR, empty `statusMessage`).

Root: `_UnitSession` (`kali_http_history.py:97`) opens one MCP session per unit and reuses it for the whole unit.
When the streamable-HTTP session closes, every later call of the unit reuses the dead session and fails, so one transport death cascades into tens of failed searches.

Missing semantics: the model cannot tell a transient session death (retry / other evidence still valid) from a genuine absence of history.

Proposed code fix: on `ClosedResourceError` (and transport `TimeoutError`), drop the unit session and reopen once before failing, exactly as the recon seam does.
Proposed verbatim (append to the `http_history_failed` contract in the description):

> A `http_history_failed` result means the history store could not be reached for THIS call. The target may still have history: treat it as missing evidence, never as proof of an empty surface, and continue with `graph_view` and the rest of your evidence.

### FM-E - `graph_view` returns opaque node reprs (FIXED 2026-10-14)

Fix applied as proposed: the analysis read seam projects Node-likes to `{labels, properties}` (recursive through dicts/lists, scalars untouched) and the contract teaches RETURN-scalars. Regression: `tests/analysis/test_graph_tools.py` (also pins the write-guard parity with the hunting seam the module comment claims); red pre-fix, green post-fix.

Count: 26 of 744 `graph_view` results returned raw Neo4j node reprs (`<Node element_id=... labels=frozenset({...}) properties={...}>`), because the query was `RETURN s` or `RETURN o`.

Missing semantics: `_RETURN_SHAPE` promises "a list of dict rows", but a returned node serializes to an opaque repr the model must scrape.

Proposed verbatim (append to `_RETURN_SHAPE` / `_EXAMPLE` in `graph_tools.py`):

> RETURN scalars or maps, never a whole node. `RETURN properties(e) AS props, labels(e) AS labels` reads back as a real row; `RETURN e` comes back as an opaque node repr you cannot index. Prefer `RETURN e.method, e.path, properties(e) AS props`.

Proposed code fix: project `Node` values to `{labels: [...], properties: {...}}` in the read seam before returning.

### FM-F - `StructuredTool does not support sync invocation` (RECORDED 2026-10-14, no code change)

Single occurrence, probe session `lat-probe2:assigner` only. Mechanism now precisely diagnosed (no LLM needed to reproduce): the prose-bound `AnalysisTurn` tool is the raw `OutputToolBinding` derivation - a wire-shape-only tool with neither sync nor async func, so even `ainvoke` raises. It is always intercepted by `ToolStrategy` before `ToolNode` on structured turns; but a `schema=None` prose turn binds it via `tools=` with no `response_format`, so a model-emitted `AnalysisTurn` call reaches `ToolNode`, which tries to execute it and the turn crashes - on both streams. Fix options (echo shim vs teaching rejection vs record-only) were put to the operator, who chose record-only: the trigger needs a prose turn emitting a structured call, seen once in a probe. Revisit if it ever appears in a real trial.

(Supersedes the original count of 3: two of those rows are FM-A write-guard refusals surfacing in the parent chain, leaving one true FM-F occurrence.)

### Context - provider rate limit (not a tool-call failure)

Count 69 ERROR observations on `model` / `ReasoningPreservingChatOpenAI` / `LangGraph`: `Go usage limit exceeded` (HTTP 429).
Environmental, not a tool contract issue; the affected turns abort and are retried by the surfer.

## Summary of proposed changes

| id | type | target | change |
| --- | --- | --- | --- |
| FM-A | code + prompt | `graph_tools.py` | strip literals/comments before the write-guard; add the literal-safety verbatim |
| FM-B | prompt | `http_history_contract.py` | add the side/namespace/op/value anti-pattern verbatim |
| FM-C | code + prompt | `kali_http_history.py`, `http_history_contract.py` | error `category` mapping + the category verbatim |
| FM-D | code + prompt | `kali_http_history.py` | reopen the unit session on `ClosedResourceError`; add the missing-evidence verbatim |
| FM-E | code + prompt | `graph_tools.py` | project nodes to `{labels, properties}`; add the RETURN-scalars verbatim |
| FM-F | recorded | - | probe-only `AnalysisTurn` sync execution; mechanism diagnosed, operator chose record-only |
