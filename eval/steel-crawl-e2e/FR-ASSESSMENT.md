# steel_crawl functional and invariant assessment

**Status:** final assessment, 2026-11-03.
**Scope:** the 64 functional requirements A1-O8 in `docs/design/steel-crawl-spec.md` section 2, the technical invariants, and the HTTP-history database change.
**Gate:** `eval/steel-crawl-e2e/ASSERTIONS.md` (C1-C14, E1-E3, N1-N10) and `tests/e2e/test_steel_crawl_e2e.py`.
**Evidence:** the three final live runs, the contract suites, and the live database transcript in `docs/design/steel-crawl-integration-impact-map.md` section 4.2.

## 1. Verdict

The steel crawl e2e gate is complete for the crawl plane.
63 of the 64 functional requirements have a contract predicate, a live walkthrough, or both; O3 (observability page and action records) is the one unsupported item.
The HTTP-history database change was the one under-assessed area.
It had three real defects: a silently dropped URL-cap fact, an edge port collision with the eval MCP server, and a silent edge-start failure.
All three are fixed and covered.
The deployed edge and the `/data` SQLite store were verified live with a real ingest, a real duplicate, and a real read through the MCP-facing service.

The remaining items are named, not hidden:

- O3 (observability page and action records) is contract-only; the live gate reads the manifest and the recon job, not Langfuse.
- C5 (WebSocket frames) and C6 (HTTP/3) are contract-tested; the final three-target runs do not prove both live.
- A9 and A10 (resurrection and session loss) are contract-tested; no live session loss was induced.
- The target-type job-set decision node (#336) is still open.
- The eval instance still needs the new Kali image or mount and a non-empty `KALI_HTTP_HISTORY_EDGE_TOKEN`.

## 2. Status key

- **L**: verified live on at least one of the three final targets.
- **C**: verified by a contract or unit predicate.
- **L+C**: both.
- **D**: not exercised live; the contract predicate is the evidence.

## 3. Functional requirements

### 3.1 Session and authentication

| id | requirement | status | evidence |
| - | - | - | - |
| A1 | Attach to one live session by name and runtime id | L+C | `test_session.py`; all three runs attach and stop cleanly |
| A2 | Never start a session | C | `test_session.py`; the crawl has no `start` call |
| A3 | Run the authenticated-context oracle once | L+C | `test_auth.py`; `verdict.probe_source` on PrestaShop and SiyuCMS |
| A4 | The oracle is a browser fetch to `overview.auth_probe.url` | L+C | `test_auth.py`; PrestaShop and SiyuCMS probes answer 200 without a redirect |
| A5 | 401, 403, any 3xx, or a redirect fails | C | `test_auth.py` |
| A6 | Anything else is indeterminate and fails closed | C | `test_auth.py` |
| A7 | A missing oracle is loud and uses the legacy gate | L+C | `test_auth.py`; ComfyUI runs the legacy surface gate |
| A8 | The legacy gate rejects login redirects, 401, 403, and 3xx | L+C | `test_auth.py`; ComfyUI root 200 with no login form |
| A9 | A failure returns a typed failure and the orchestrator resurrects once | C | `test_session_boundary.py`; no live loss induced |
| A10 | A known loss is `session_missing` | C | `test_session.py`, `test_session_boundary.py` |

### 3.2 Traversal

| id | requirement | status | evidence |
| - | - | - | - |
| T1 | Seed the frontier with the target root | L+C | `test_frontier.py`; every run visits the root |
| T2 | Scope is the base host plus subdomains | L+C | `test_frontier.py`; N3 scans every graph endpoint |
| T3 | One unified DFS | L+C | `test_frontier.py`; SiyuCMS visits 7 pages and backtracks |
| T4 | Jev owns the next choice | L+C | `test_policy.py`, `test_policy_jev.py`; the live runs use the real TypeSafe policy |
| T5 | A navigation is a normal candidate | L+C | `test_frontier.py`; the live runs navigate menus and links |
| T6 | A local action is a normal candidate | L+C | `test_frontier.py`; the live runs click and restore |
| T7 | A page with no candidate is a leaf | L+C | `test_frontier.py`; SiyuCMS backtracks through the menu |
| T8 | The root is the last page popped | C | `test_frontier.py`; the authenticated runs stop at the deadline, not the root |
| T9 | The consumed set survives a local state change | L+C | `test_frontier.py`; the live runs do not re-offer consumed elements |
| T10 | The stop reason is recorded | L+C | `test_frontier.py`; `frontier_empty` and `session_deadline` on the live runs |

### 3.3 Interaction

| id | requirement | status | evidence |
| - | - | - | - |
| I1 | Enumerate from the cached DOM snapshot | L+C | `test_snapshot.py`; the live runs project the snapshot |
| I2 | The projection is compact and the refs are document-scoped | L+C | `test_snapshot.py`; the restore fix re-snapshots after a reload |
| I3 | The element map decides offer, collect, or ignore | L+C | `test_enumerate.py`; no element is both offered and collected |
| I4 | The exclusion set drops certainly non-interactable elements | L+C | `test_enumerate.py`; the live runs do not offer hidden or external nodes |
| I5 | The policy chooses only from the offer set | L+C | `test_policy.py`; removed and collected nodes are never chosen |
| I6 | A stale ref is `stale_element` and is consumed | C | `test_enumerate.py`, `test_session_boundary.py`; the live restore path exercised the ref refresh |
| I7 | Every variadic verb carries `--` | C | `test_command.py` |
| I8 | `select` is proven by a read-back | C | `test_command.py` |
| I9 | `press` takes one key | C | `test_command.py` |
| I10 | Form submission uses `requestSubmit()` | L+C | `test_command.py`; the live PrestaShop and SiyuCMS forms submit once per state |

### 3.4 Safety

| id | requirement | status | evidence |
| - | - | - | - |
| S1 | The forbidden categories are auth state, payment, and destruction | L+C | `test_policy.py`; the live runs remove login, logout, and destructive controls |
| S2 | `choose_removed` depletes the unsafe set | L+C | `test_policy.py`; 6 removed elements on SiyuCMS, 1 on PrestaShop |
| S3 | A removed element is consumed and collected in place | L+C | `test_forms.py`; SiyuCMS declares the login form and never submits it |
| S4 | `choose_chosen` only sees the remaining set | L+C | `test_policy.py`; N4 verifies the removed and executed fingerprints are disjoint |
| S5 | There is no probability threshold | C | `test_policy.py` |
| S6 | There is no post-submit oracle and no per-navigation auth gate | L+C | `test_policy.py`; the live runs use the one precondition oracle |
| S7 | The removal is the structural guard | L+C | `test_policy.py`; N4 on all three runs |
| S8 | A stale removal answer is a protocol error | C | `test_policy.py` |

### 3.5 Capture

| id | requirement | status | evidence |
| - | - | - | - |
| C1 | A passive CDP client receives events and sends no action method | L+C | `test_capture.py`; the live sidecar captures every flow |
| C2 | Network, Page, Runtime, and Debugger are enabled | L+C | `test_capture.py`; the live runs capture documents, XHR, scripts, and frames |
| C3 | The request and response lifecycle, headers, status, mime, timing, initiator, and type are captured | L+C | `test_capture.py`; the edge artifacts carry the full record |
| C4 | Bodies are captured for Document, XHR, Fetch, and Script with a byte cap | L+C | `test_capture.py`; N5 checks bodies on every run |
| C5 | The WebSocket handshake and both frame directions are captured | C | `test_capture_surface.py`; ComfyUI records 14 realtime records, but the final gate does not assert a frame pair |
| C6 | HTTP/3 is captured | C | `test_capture_surface.py`; the prototype run captured h3, the final three-target runs do not assert it |
| C7 | `Debugger.scriptParsed` is a `ScriptAsset` with an absolute URL | L+C | `test_capture.py`; ComfyUI 482 scripts, SiyuCMS 67, PrestaShop 71 |
| C8 | No source map is fetched or stored | L+C | N2 on all three runs; no `.map` or `sourceMappingURL` in the edge |
| C9 | Every flow carries a page visit and, when possible, an action | L+C | `test_capture.py`; the unattributed flows keep `attribution="unknown"` |
| C10 | A sidecar failure fails the run | C | `test_capture.py`; `capture_unavailable` |

### 3.6 Parameters and forms

| id | requirement | status | evidence |
| - | - | - | - |
| P1 | Observe parameters only from network flows | L+C | `test_parameters.py`; the graph counts come from the observed and declared records |
| P2 | Record the name, location, and shape, never the value | L+C | N1; the graph has no parameter value |
| P3 | A collected form records a declared endpoint and field | L+C | `test_forms.py`; SiyuCMS declares the login endpoint |
| P4 | A form is submitted once per state | L+C | `test_forms.py`; the SiyuCMS forms ledger shows one registration submit |
| P5 | The form projection carries the field contract | L+C | `test_forms.py`; the live forms fill fields and succeed |
| P6 | Jev chooses a value catalogue key per field | L+C | `test_policy_jev.py`; the live PrestaShop and SiyuCMS forms use the selected values |
| P7 | A single matching catalogue entry skips the Jev call | L+C | `test_forms.py`; the live forms use the single-match path |
| P8 | No match uses `none` and skips the field | C | `test_forms.py` |

### 3.7 Output and operations

| id | requirement | status | evidence |
| - | - | - | - |
| O1 | Emit manifest v2 with the graph-bearing records | L+C | `test_manifest.py`; every run validates `steel-crawl/v2` |
| O2 | Keep v1 parsing compatible | C | `test_parser_v2.py`; N7 replays the v1 vocabulary |
| O3 | Pages and actions live in the observability platform | D | The manifest references page and action ids; the live gate does not read Langfuse |
| O4 | Flush the HTTP-history ledger on every exit | L+C | `test_ledger.py`; every run flushes and reports `flush.rejected=0` |
| O5 | Start partial graph ingestion on every exit | L+C | `test_ledger.py`; the partial SiyuCMS and PrestaShop runs still ingest |
| O6 | Return a typed error and a recovery directive for every failure | C | `test_ledger.py`, `test_session_boundary.py`; no live failure path was forced |
| O7 | Never log the connect URL, cookies, storage values, or credentials | L+C | N1; the summary, phase result, and recon stats are secret-free |
| O8 | Stop the owned session and prove the catalogue clean | L+C | `test_session.py`; `session_closed=true` on every run |

### 3.8 Status count

The 64 requirements split as follows:

- **L+C:** 44.
- **L:** 0.
- **C:** 19.
- **D:** 1 (O3).

The one D is an observability-surface gap, not a crawl-behaviour gap.
The 19 C items are contract-tested and are either failure paths that were not induced live, browser primitives the live targets did not expose, or the resurrection path that needs a deliberate session loss.

## 4. Technical invariants

| invariant | status | evidence |
| - | - | - |
| Auth precondition before traversal | L+C | The oracle passes on PrestaShop and SiyuCMS; the legacy gate passes ComfyUI |
| No anonymous continuation | L+C | The oracle fails closed; the live runs never continue after a failed verdict |
| No unsafe action executed | L+C | N4: removed and executed fingerprints are disjoint |
| No unsafe crawl endpoint observed | L+C | The removed forms are declared, never submitted |
| No safe endpoint removed by mistake | C | The policy and forms suites; the live removed set is small and intentional |
| Form submission success is dispatch plus 2xx | L+C | Every submitted form has a 2xx edge artifact |
| Every submitted field reaches the network | C | `test_forms.py`; the live gate does not parse the submitted body for every field |
| XHR response and body capture | L+C | N5: every page has a document flow and every run has a body |
| Manifest phase isolation | C | The bootstrap auth flow is tagged and excluded |
| Session stopped and catalogue clean | L+C | `session_closed=true`; the catalogue has no entry after the stop |

## 5. The HTTP-history database change

The database change adds the crawler producer, the `record_if_absent` idempotent write, the authenticated edge, and the URL-cap fact.
The per-project SQLite schema is unchanged; the new fields ride the existing `record_json` column, so no migration is required.

| id | requirement | status | evidence |
| - | - | - | - |
| DB-1 | The artifact stores `url_truncated` and `url_original_length` | L+C | `test_history.py`, the live transcript |
| DB-2 | A duplicate id is counted and never overwrites the first record | L+C | `test_http_history_store.py`, `test_http_history_edge.py`, the live transcript |
| DB-3 | The edge returns created, duplicates, rejected, and errors | L+C | `test_http_history_edge.py`; the three runs |
| DB-4 | A body is durable before its record is visible | C | `test_http_history_store.py` |
| DB-5 | Projects are isolated on disk | C | `test_http_history_store.py` |
| DB-6 | A schema-version mismatch fails loudly | C | `test_http_history_store.py` |
| DB-7 | WAL and a busy timeout allow shared readers and writers | C | `test_http_history_store.py` |
| DB-8 | The edge requires the bearer token and is not an MCP tool | C | `test_http_history_edge.py`, `test_http_history_deployment.py` |
| DB-9 | A batch is capped at 100 artifacts and 8 MiB | C | `test_http_history_edge.py` |
| DB-10 | The existing read tools return a crawler artifact | L+C | The live transcript; `test_http_history_edge.py` |
| DB-11 | The edge is a separate process and does not collide with the MCP port | L+C | The live transcript; `test_http_history_deployment.py` |
| DB-12 | Retention and the project byte cap still apply | C | `test_http_history_store.py`, `test_http_history_service.py` |
| DB-13 | The content id is deterministic and replay keeps lineage | C | `test_history.py` |
| DB-14 | A failed flush retries from the cursor | C | `test_history.py`, `test_ledger.py` |
| DB-15 | Each distinct body is sent once | L+C | The three e2e edge counts; `test_ledger.py` |
| DB-16 | The local and Kali artifact models agree on every field | C | `test_history.py` |

The live verification used the deployed Kali container, the real `/data` volume, the real edge process on port 8002, and the MCP-facing `HttpHistoryService`.
The exact transcript is in `docs/design/steel-crawl-integration-impact-map.md` section 4.2.

## 6. Live run evidence

| target | run | stop | wall | flows | endpoints | parameters | graph | session_closed |
| - | - | - | - | - | - | - | - | - |
| ComfyUI | `e2e-comfyui-20261103T135159Z` | `frontier_empty` | 29.8 s | 560 | 538 | 32 | 57 endpoints, 6 parameters | true |
| SiyuCMS | `e2e-siyucms-20261103T091856Z` | `session_deadline` | 941.3 s | 12,863 | 184 | 16 | 78 endpoints, 6 parameters | true |
| PrestaShop | `e2e-prestashop-20261103T075740Z` | `session_deadline` | 950.7 s | 10,654 | 117 | 68 | parsed endpoints and parameters | true |

The ComfyUI run is the post-database-fix regression gate. The SiyuCMS and PrestaShop runs predate the additive URL-cap fields and the edge port move; neither change affects the crawl path or the graph projection.
The three runs have zero edge rejections and zero unrecoverable pages.
Each run has one `steel_crawl` job with `status=success`.
The edge created plus duplicate counts equal the ledger artifact count.

## 7. What changed because of this assessment

1. The URL-cap fact is no longer silently dropped; the local `RequestRecord` and the Kali model agree, and the read views expose the fact.
2. The edge default port moved from 8001 to 8002 to avoid the eval MCP server.
3. A failed edge start is loud.
4. The crawler-to-edge-to-read-service roundtrip is a test.
5. The schema-version guard is a test.
6. The deployed edge and `/data` store were verified live.
7. The impact map and the job-set decision record are written.

## 8. Residual items

- O3 observability records: contract-only.
- C5 WebSocket frames and C6 HTTP/3: contract-only.
- A9 and A10 resurrection: contract-only.
- The target-type job-set decision node (#336).
- The targeted-recon browser-state extension.
- The eval instance Kali image or mount and the edge token.
- Multi-process SQLite contention.
- Retention on a large crawl artifact set.
- The eval operator subset deliberately excludes `steel_crawl`; the pipeline default includes it.

## 9. Closure

The steel crawl implementation tickets SC-00 through SC-21 can close.
Their acceptance criteria are met by the contract suites and the three live walkthroughs.
The HTTP-history database change is verified in the contract tier and on the deployed topology.
The remaining items are follow-ups, not incomplete acceptance criteria.
