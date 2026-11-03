# steel_crawl integration impact map

**Status:** convergence record, 2026-11-03.
**Scope:** the `steel_crawl` phase identity, its default chain in the recon pipeline, the recon-orchestrator interface, and the HTTP-history database change.
**Sources:** `docs/design/steel-crawl-spec.md`, `docs/design/recon-pipeline-design.md`, `docs/design/recon-auth-gateway-223-spec.md`, `docs/design/recon-pipeline-forward-decisions.md`, `src/polymerhus/recon/CONTEXT.md`, `eval/steel-crawl-e2e/ASSERTIONS.md`, `eval/steel-crawl-e2e/NFR-REPORT.md`.

## 1. The phase identity

`steel_crawl` is one registered job with one identity:

| attribute | value | source |
| - | - | - |
| job name | `steel_crawl` | `src/polymerhus/recon/control/jobs.py` |
| parser key | `steel_crawl` -> `parse_steel_crawl` | `src/polymerhus/recon/domain/parsers/__init__.py` |
| skill label | `agentic_crawl` | `src/polymerhus/recon/control/jobs.py` |
| consumes | `BaseURL` | `src/polymerhus/recon/control/jobs.py` |
| produces | `BaseURL`, `Endpoint`, `Parameter` | `src/polymerhus/recon/control/jobs.py` |
| auth | `use_auth=True`; browser state plus browser auth material | `src/polymerhus/recon/control/pipeline.py`, `control/auth_feed.py` |
| configurator | `configurator_mode="agent"` | `src/polymerhus/recon/control/jobs.py` |
| external scope | `consumption.skip_external=True` | `src/polymerhus/recon/control/jobs.py` |
| phase | phase index 5, displayed Phase 5, with `katana` and `ffuf` | `src/polymerhus/recon/control/jobs.py` |

The default plan has 12 phases and 17 scheduled jobs.
`build_phase_plan()` returns `PHASES` unchanged, so `steel_crawl` is in the default plan.
`_gate_plan_by_scope` drops only discovery jobs, host-mode-suppressed jobs, and host-mode-only jobs, so `steel_crawl` survives `exact`, `host`, and `wildcard` scope.
`validate_job_subset(["steel_crawl"])` passes because the BaseURL can be pre-curated.
`validate_job_subset` passes for the full plan.
`prune_plan(plan, "browser_only")` keeps `steel_crawl` alone through `BROWSER_ONLY_KEEP`.

## 2. The default chain

The chain is correct by construction and by test:

1. `httpx` (phase 3) mints the target `BaseURL` and root `Endpoint`.
2. `httpx_services` (phase 4, host mode only) can mint additional `BaseURL`s.
3. `steel_crawl` (phase 5) consumes `BaseURL`, attaches to the pre-authenticated Steel session, and mints `BaseURL`, `Endpoint`, and `Parameter` records.
4. `webpack_chunks` (phase 6) consumes the `.js` and `.mjs` endpoints and resolves lazy chunks.
5. `jsluice` (phase 7) scans the crawled and resolved bundles.
6. `httpx_reprofile` (phase 8) profiles the endpoints the crawlers and JS phases produced.
7. `kiterunner` (phase 9), `arjun` (phase 10), and `graphql-cop` (phase 11) consume the profiled surface.

`job_agent.default_pod_invoke` routes `configurator_mode="agent"` to `crawl_pod.crawl_pod_invoke`.
`crawl_pod_invoke` builds the crawl pod and calls `live_run_crawl_fn`.
`live_run_crawl_fn` calls `run_live_crawl`, which assembles `CrawlJob` and `CrawlRun`.
The crawl pod then rejoins the shared `parse -> triager -> curator` shape, so the curator remains the single graph writer.

Evidence:

- `tests/recon/test_jobs.py::test_build_phase_plan_full`
- `tests/recon/test_jobs.py::test_steel_crawl_job_tool_matches_registered_parser`
- `tests/recon/test_jobs.py::test_steel_crawl_job_is_agent_configurator_mode`
- `tests/recon/test_jobs.py::test_steel_crawl_job_consumes_baseurl_and_is_placed_after_httpx`
- `tests/recon/test_jobs.py::test_validate_job_subset_steel_crawl_alone_reads_a_pre_curated_baseurl`
- `tests/recon/test_pipeline.py::test_feed_absent_without_a_verdict_account`
- `tests/recon/test_pipeline_gateway.py::test_browser_only_verdict_prunes_to_the_steel_crawl`
- `tests/e2e/test_steel_crawl_e2e.py`: one `steel_crawl` job with `status=success` and `pods>=1` on all three targets.

## 3. The recon-orchestrator interface

The orchestrator is the `job_orchestrator` role, run as `ReconOrchestratorActor`.
It takes exactly one pre-pipeline turn and emits the structured `GatewayVerdict`.
The verdict carries `outcome`, `account`, `branch`, `replayability_resolved`, `replayability`, and `rationale`.
The pipeline obeys it before phase 0.
The only plan-shaping branch is `browser_only`, which prunes to `BROWSER_ONLY_KEEP = {"steel_crawl"}`.
The prompt names the Steel path and the browser-only branch, but it does not enumerate the phase plan.

This is the current interface agreement:

- The orchestrator never builds the plan; `build_phase_plan` owns it.
- The orchestrator may prune the plan only through `prune_plan`.
- The orchestrator never names a job outside `JOBS`.
- The orchestrator never starts or repairs a Steel session; the crawl attaches only.

The target-type job-set decision node is not built.
It is tracked by issue #336 and recorded as `D-JOBSET` in `docs/design/recon-pipeline-forward-decisions.md`.
When it is built, it must consume the same `JOBS` and `PHASES` registry, and it must treat `steel_crawl` as a first-class job with the identity in section 1.
It must keep `steel_crawl` for CMS, SPA, JavaScript-heavy, and browser-only targets, and it must not select it for a target with no reachable web origin.
It must never hardcode a phase or job list that can drift from `JOBS` and `PHASES`.
The acceptance cases are a CMS target, a REST/GraphQL target, and an auth-only `browser_only` target.

The current gap is explicit: the prompt is auth-focused, and the decision node is still an open design item.
The convergence for this batch is the recorded interface, the identity test, and the `browser_only` prune test, not a new planner.

## 4. The HTTP-history database change

The change adds the crawler as a producer of `http-artifact/v1` records and adds an authenticated ingest edge.
The database remains the per-project SQLite store with content-addressed bodies.

| component | change | impact |
| - | - | - |
| `RequestRecord` in `src/polymerhus/recon/crawl/steel/capture/history.py` | adds `url_truncated` and `url_original_length` | the cap fact survives normalization |
| `HttpHistoryStore.record_if_absent` | idempotent insert | a duplicate is a counted result, not an overwrite |
| `kali/http_history/edge.py` | bearer-authenticated `POST /v1/ingest`; batch bounds 100 artifacts and 8 MiB; real store `record_if_absent` | a separate process, never an MCP tool |
| `kali/http_history/sanitize.py` | exposes the URL-cap fact in the get and summary views | the read tools see the fact |
| `kali/entrypoint.sh` | starts the edge only with a token; logs a failed start loudly | a missing edge is visible |
| `docker-compose.yml`, `.env.example` | edge URL and token; edge port 8002 | no collision with the MCP port |
| `src/polymerhus/recon/crawl/crawl_pod.py` | reads `KALI_HTTP_HISTORY_EDGE_URL` and `KALI_HTTP_HISTORY_EDGE_TOKEN` | the live crawl flushes to the edge |
| `kali/http_history/store.py` | unchanged schema, additive JSON fields | no migration and no destructive rebuild |
| `kali/http_history/service.py`, `mcp_server.py` | unchanged read tools | `search_http_history`, `get_http_artifact`, `replay_http_request` keep their contract |

### 4.1 Defects found and fixed

1. **The URL-cap fact was silently dropped.**
   The normalizer passed `url_truncated` and `url_original_length` into the local `RequestRecord`, but the model did not declare the fields.
   Pydantic's default `extra=ignore` discarded them, so the edge stored a clipped URL as if it were the real one.
   The fields are now declared, the read views expose them, and a cross-model field-set test prevents the next drift.
2. **The edge port collided with the eval MCP server.**
   The edge defaulted to 8001, but the eval instance runs a second MCP server on 8001.
   The edge now defaults to 8002 in the model, the entrypoint, the compose file, and the environment example.
   The deployment test asserts the edge port is distinct from the MCP port.
3. **A failed edge start was silent.**
   The entrypoint started the edge in the background and never reported a bind failure.
   It now tracks readiness and logs `HTTP-history edge FAILED to start` to stderr.
4. **The deployed eval instance does not run the edge.**
   Its Kali mount is a stale `dev` copy and its `KALI_HTTP_HISTORY_EDGE_TOKEN` is empty.
   This is an operator deployment prerequisite, not a code path; a production image built from this branch carries the edge and the token starts it.

### 4.2 Live database verification

The deployed topology was verified on the eval server with a temporary edge process in the Kali container:

- The edge started from the new `kali` tree on `0.0.0.0:8002` with a bearer token and `KALI_HTTP_HISTORY_ROOT=/data`.
- The agent normalized a CDP flow with `url_truncated=True` and `url_original_length=4096`.
- The first `HistoryClient.ingest` returned `created=1, duplicates=0, rejected=0`.
- The second returned `created=0, duplicates=1, rejected=0`.
- The store at `/data/edge-verify-20261103/http-history/history.sqlite3` reported `artifact_count=1`, `body_count=1`, `schema_version=http-artifact/v1`.
- `HttpHistoryStore.get_raw` returned `url_truncated=True` and `url_original_length=4096`.
- `HttpHistoryStore.get_body` returned the original `{"ok":true}` bytes.
- `HttpHistoryService.get` returned the same cap fact.
- `HttpHistoryService.search` with the `request.core.method eq GET` filter returned the artifact.
- The temporary project and edge process were removed after the check; the MCP server on 8001 was untouched.

This closes the database read path on the deployed topology for the crawl producer.
The full three-target walkthrough still uses the in-process edge in `eval/steel-crawl-e2e/phase_runner.py`, which is the same `create_edge_server` and `HttpHistoryStore` code.

### 4.3 Functional requirements for the database change

| id | requirement | status | evidence |
| - | - | - | - |
| DB-1 | The artifact stores `url_truncated` and `url_original_length` | verified live and contract | `test_history.py::test_the_normalizer_keeps_the_url_cap_fact`, `test_the_local_and_kali_request_records_agree_on_every_field`, the live transcript above |
| DB-2 | A duplicate id is a counted duplicate and never overwrites the first record | verified live and contract | `test_http_history_store.py::test_recording_an_existing_artifact_id_is_rejected`, `test_http_history_edge.py::test_the_real_store_record_if_absent_is_idempotent`, `test_a_crawler_artifact_roundtrips_through_the_edge_and_the_read_service`, the live transcript |
| DB-3 | The edge response carries `created`, `duplicates`, `rejected`, and `errors` | verified contract and live | `test_http_history_edge.py::test_the_edge_counts_created_and_duplicates`, the three e2e runs |
| DB-4 | A body is durable before its record is visible | verified contract | `test_http_history_store.py::test_record_is_invisible_until_bodies_are_durable` |
| DB-5 | Projects are isolated on disk | verified contract | `test_http_history_store.py::test_projects_are_isolated_on_disk` |
| DB-6 | A schema-version mismatch fails loudly and never rebuilds destructively | verified contract | `test_http_history_store.py::test_a_schema_version_mismatch_fails_loud` |
| DB-7 | WAL and a busy timeout allow the addon, edge, and read tools to share the file | verified contract | `test_http_history_store.py::test_sqlite_uses_wal`, `test_concurrent_readers_and_writer_share_one_connection` |
| DB-8 | The edge requires the bearer token and is not an MCP tool | verified contract and deployment source | `test_http_history_edge.py::test_the_edge_requires_the_bearer_token`, `test_http_history_deployment.py` |
| DB-9 | The edge caps a batch at 100 artifacts and 8 MiB | verified contract | `test_http_history_edge.py::test_the_edge_rejects_too_many_artifacts`, `test_the_edge_rejects_an_oversized_payload` |
| DB-10 | The existing read tools return a crawler artifact | verified live and contract | `test_a_crawler_artifact_roundtrips_through_the_edge_and_the_read_service`, the live transcript |
| DB-11 | The edge starts as a separate process on the compose network and does not collide with the MCP port | verified live and deployment source | the live transcript, `test_http_history_deployment.py::test_kali_exposes_the_edge_to_the_agent_without_a_port_collision` |
| DB-12 | Retention and the project byte cap still apply | verified contract | `test_http_history_store.py`, `test_http_history_service.py::test_enforce_limits_applies_the_configured_caps` |
| DB-13 | The crawler content id is deterministic and a replay keeps its lineage | verified contract | `test_history.py::test_the_content_id_is_deterministic_and_ignores_volatile_headers`, `test_a_replay_keeps_the_caller_provided_id_and_lineage` |
| DB-14 | A failed flush retries from the cursor and the ledger stays durable | verified contract | `test_history.py::test_the_history_client_retries_from_the_failed_batch`, `test_ledger.py` |
| DB-15 | The flush sends each distinct body once | verified live and contract | the three e2e edge counts, `test_ledger.py` |
| DB-16 | The local and Kali artifact models agree on every field | verified contract | `test_history.py::test_the_local_and_kali_request_records_agree_on_every_field` |

### 4.4 Residual database risks

- Multi-process write contention is unit-tested, not stress-tested with the mitmproxy addon, the edge, and the MCP read tools running concurrently.
- The eval instance still needs the new Kali image or mount and a non-empty `KALI_HTTP_HISTORY_EDGE_TOKEN` for the deployed edge to run.
- Retention and the project byte cap are not exercised on a large crawl artifact set.

## 5. Dependent clients

| client | dependency | status |
| - | - | - |
| `project_management/api.py` | `POST /projects/{id}/recon` accepts a `jobs` subset and validates it through `validate_job_subset` | aligned; `steel_crawl` is a valid subset with a BaseURL |
| `frontend` | displays `current_phase` and job counts only | no change; the frontend does not touch a job list |
| `analysis/anatomy.py` | `_DEEP_PROBE_JOB = "steel_crawl"` for the webpage-profile probe | **gap**: the targeted-recon seam does not carry `steel_state` or `browser_auth` |
| `recon/control/targeted.py` | `request_targeted_recon` builds `extra` with `auth_context` only | **gap**: a targeted `steel_crawl` would run without the stored browser state |
| `app/observability/langfuse_tracing.py` | heavy phase list includes `steel_crawl` | aligned |
| `curator` | sole graph writer; `filter_deltas` scope and vendor rule | aligned |
| `analysis` feed | consumes the curator's `PodExport` assets and observations | aligned |
| `eval/orchestrator` | `recon_jobs` is an explicit subset; the operator contract excludes `steel_crawl` to keep trials cheap | deliberate divergence, documented in `eval/OPERATOR.md` |
| `eval/steel-crawl-e2e` | runs `job_subset=["steel_crawl"]` and starts the edge in-process | aligned |

### 5.1 Targeted recon disposition

The targeted-recon seam can request any registered job, including `steel_crawl`.
`ReconScope` carries `targets`, `unit_id`, `auth_context`, and `note`.
It does not carry the browser state reference or the browser auth material that the crawl needs.
`analysis/anatomy.py` emits the deep probe request but does not execute it, so no anonymous crawl runs today.
The interface must be extended before a caller dispatches a targeted `steel_crawl`.
The minimum safe shape is:

- `ReconScope.steel_state: str | None`
- `ReconScope.browser_auth: dict | None`
- `ReconScope.auth_account: str | None`
- `request_targeted_recon` copies them into `extra` when the job is `use_auth`.
- A targeted `steel_crawl` without a state reference degrades with a coded `targeted_auth_required` error instead of crawling anonymously.

This is recorded as a follow-up, not implemented in this batch.

## 6. Convergence actions in this batch

- Fixed the silent URL-cap field drop and exposed the fact in the read views.
- Moved the edge default port from 8001 to 8002 and asserted the port separation.
- Made a failed edge start loud.
- Added the crawler-to-edge-to-read-service roundtrip test.
- Added the schema-version mismatch test.
- Added the cross-model field-set test.
- Verified the deployed edge and `/data` store live on the eval server.
- Recorded the FR assessment in `eval/steel-crawl-e2e/FR-ASSESSMENT.md`.
- Recorded the orchestrator interface and the open job-set decision node in `docs/design/recon-pipeline-forward-decisions.md` as `D-JOBSET`.
- Updated the stale crawl sections of the pipeline design and the technological architecture.

## 7. Open items

- `#336`: the target-type job-set decision node.
- The targeted-recon browser-state extension in section 5.1.
- The eval instance Kali image or mount refresh and the edge token.
- Langfuse page and action records are not asserted by the live e2e (O3).
- HTTP/3 and the WebSocket frame path are contract-tested; the final three-target runs do not prove them live (C5/C6).
- A live session-loss resurrection is not induced (A9/A10).
- Multi-process SQLite contention is not stress-tested.
