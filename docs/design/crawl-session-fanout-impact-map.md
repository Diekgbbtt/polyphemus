# Crawl session fan-out: impact map

**Status:** implemented in the `feat/crawl-auth-sessions` worktree, 2026-11-09.
**Design record:** `docs/design/crawl-session-fanout-adr.md`.
**Method:** one row at a time, red test at the named seam, then the minimal implementation.

## The change in one line

One auth-store account is one browser session.
Each session carries `role`, `root_url`, `auth_probe`, and `browser_context.ref`.
One `steel_crawl` pod runs one lifecycle per valid account, bounded by the pool, joins all, parses every manifest, and lets the curator deduplicate.
No anonymous session runs when accounts exist; the zero-account store is the only anonymous fallback.

## Impact map

| # | Component | Impact | Change | TDD seam | Status |
|---|---|---|---|---|---|
| 1 | `src/polymerhus/app/auth/records.py` | Account schema | `role`, `root_url`, `auth_probe` validation; empty root/probe defaults | `tests/app/test_auth_records.py` | Done |
| 2 | `src/polymerhus/app/auth/store.py` | Record persistence | New optional fields round-trip; no store logic change | `tests/app/test_auth_store.py` | Done |
| 3 | `src/polymerhus/app/auth/tool.py` | Agent-facing auth-store client | Contract names one account per session; summary shows role/root/probe; read resolves relative root/probe to the canonical origin | `tests/app/test_auth_store_tool.py`, `test_auth_store_tool_origin.py`, `test_auth_store_tool_readonly.py` | Done |
| 4 | `kali/steel_pool/store.py` | Durable session context | `BrowserSessionRecord` round-trips role/root/probe | `tests/kali/test_steel_pool_store.py` | Done |
| 5 | `kali/steel_pool/lease.py` | Loaded session view | `LeaseView` exposes role/root/probe; capture preserves them | `tests/kali/test_steel_pool_lease.py` | Done |
| 6 | `kali/steel_pool/server.py` | Browser-start payload | `browser_start` returns role/root/probe | `tests/kali/test_steel_pool_server.py` | Done |
| 7 | `src/polymerhus/app/llm/browser_client.py` | MCP start parser | `BrowserStart` carries role/root/probe | `tests/recon/crawl/steel/test_mcp_client.py` | Done |
| 8 | `src/polymerhus/recon/crawl/steel/session.py` | Session client | `StartResult` carries role/root/probe; start report exposed | `tests/recon/crawl/steel/test_mcp_client.py` | Done |
| 9 | `src/polymerhus/recon/crawl/steel/auth.py` | Auth verdict | Adds the first-class `anonymous` classification | `tests/recon/crawl/steel/test_auth.py` | Done |
| 10 | `src/polymerhus/recon/control/auth_feed.py` | Session projection | `project_sessions`, `resolve_accounts`; account probe/root; `not_valid` skip; `project_browser_auth` prefers the account probe/root | `tests/recon/test_auth_feed.py` | Done |
| 11 | `src/polymerhus/recon/control/pipeline.py` | Per-job assembly | Hands every valid account to `steel_crawl`; keeps the selected account for request jobs; accounts-present marker | `tests/recon/test_pipeline_gateway.py`, `tests/recon/crawl/test_crawl_auth.py` | Done |
| 12 | `src/polymerhus/recon/control/authn_loop.py` | Gateway hints | Oracle hint names the account probe/root | `tests/recon/test_authn_loop.py` | Done |
| 13 | `src/polymerhus/recon/control/orchestrator_agent.py` | Gateway brief | Branch manners name the account probe/root | `tests/recon/test_steel_session_only_surfaces.py`, `tests/recon/test_auth_oracle.py` | Done |
| 14 | `src/polymerhus/recon/control/prompts/auth-gateway.md` | Gateway prompt | Account-level oracle and root fallback; one account one session | `tests/recon/test_steel_session_only_surfaces.py` | Done |
| 15 | `src/polymerhus/recon/crawl/sessions.py` | Session orchestrator | Bounded thread pool, join all, ordered results, per-session failure isolation | `tests/recon/crawl/test_sessions.py` | Done |
| 16 | `src/polymerhus/recon/crawl/crawl_pod.py` | Pod graph and live collaborator | One lifecycle per session; batch manifest; per-session coverage; all-failed observations; no anonymous with accounts | `tests/recon/crawl/test_crawl_pod.py`, `tests/recon/crawl/steel/test_live_run.py` | Done |
| 17 | `src/polymerhus/recon/crawl/steel/live.py` | Single lifecycle | Per-session root/probe; loaded start report; anonymous verdict | `tests/recon/crawl/steel/test_live_run.py` | Done |
| 18 | `src/polymerhus/recon/crawl/steel/run.py` | Lifecycle wiring | Restored single-root run; no multi-seed coupling | `tests/recon/crawl/steel/test_run.py` | Rolled back |
| 19 | `src/polymerhus/recon/crawl/steel/frontier.py` | Traversal | Restored single-root DFS; no `run_many` | `tests/recon/crawl/steel/test_frontier.py` | Rolled back |
| 20 | `src/polymerhus/recon/crawl/steel/manifest.py` | Manifest evidence | `RunBlock` carries role/root/probe | `tests/recon/crawl/steel/test_manifest*.py` | Done |
| 21 | `tools/bootstrap/DATA-DEPENDENCIES.md` | External bootstrap contract | One account per session; role/root/probe; one oracle per role; highest privilege first | Content contract in `tests/recon/test_steel_session_only_surfaces.py` | Done |
| 22 | `tools/bootstrap/prompts/data-dep-authn.md` | External bootstrap prompt | Mints one session per role, highest privilege first; per-account oracle; role coverage | `tests/recon/test_steel_session_only_surfaces.py` | Done |
| 23 | `tools/bootstrap/validate_data_dependencies.py` | Bootstrap gate | Session fields validate through the app seam; overview probe optional with accounts; absolute session URLs refused | `tests/tools/test_validate_data_dependencies_origins.py` | Done |
| 24 | `tools/bootstrap/assessment/RUBRIC.md` | Bootstrap assessment rubric | D1 rewards sessions, roles, high privilege, account probes/roots | `tests/test_bootstrap_assessment.py` | Done |
| 25 | `tools/bootstrap/assessment/assess.py` | Bootstrap assessment client | D1 metrics and anchors for the session model | `tests/test_bootstrap_assessment.py` | Done |
| 26 | `tools/bootstrap/assessment/llm_judge_prompt.md` | Semantic assessment | L5 asks for one verified session per role, highest privilege first | Content contract review | Done |
| 27 | `tools/bootstrap/runner/*` | Mechanised runner | No code change: it consumes the updated prompt and validator | Existing runner tests | Unchanged |
| 28 | `tools/bootstrap/publish_data_dependencies.py` | Publisher | No schema change: it moves the auth pair and skill bundle as bytes | Existing publish tests | Unchanged |
| 29 | `skills/meta/authn-skill-writing/SKILL.md` | Authn authoring meta skill | Seed-face contract, per-account oracle/root, role coverage and privilege priority | `tests/recon/test_steel_session_only_surfaces.py` | Done |
| 30 | `skills/meta/authn-skill-writing/references/bootstrap-workflow.md` | Reusable bootstrap prompt | Role enumeration, highest privilege first, one session per role, per-role oracle | `tests/recon/test_steel_session_only_surfaces.py` | Done |
| 31 | `skills/meta/authn-skill-writing/references/worked-example.yaml` | Authoring example | Two-role, high-privilege-first account seeds; role-labelled conditions | Reference review | Done |
| 32 | `docs/experiments/.../seed_iteration_e.py` | Experiment preflight | Mints every credential-bearing account; writes role/root/probe; sets valid/not_valid | `tests/eval/test_seed_iteration_e_sessions.py` | Done (experiment-specific) |
| 33 | Live `/root/eval-dd/data/siyucms` | Operative data dependency | Per-account fields, member context ref, overview role labels, authn prose; backups `.pre-session-model` | Live inspection | Done |
| 34 | `src/polymerhus/recon/CONTEXT.md` | Domain vocabulary | Account is a session; per-account oracle/root; fan-out | Documentation review | Done |
| 35 | `docs/design/*` | System design specs | Fan-out ADR; steel-crawl, auth-store, gateway, data-dependency amendments | Documentation review | Done |
| 36 | `tools/bootstrap/prompts/data-dep-l1.md` | Phase-2 L1 bootstrap prompt | Chooses the highest-privilege usable account; account probe/root oracle | Content contract review | Done |
| 37 | `docs/design/steel-auth-client-impact-map.md`, `steel-crawl-workbench.md`, `steel-session-only-impact-map-395.md` | Historical design records | Marked historical; point to the current fan-out ADR and spec | Documentation review | Done |

## Dependencies left unchanged, and why

- The request-based jobs (`httpx`, `katana`, `arjun`, and the rest) still receive the gateway-selected account's request material. The new session set is crawl-only.
- The app data-dependency placement endpoints already delegate to `validate_account`; the new optional fields need no new route.
- The `tools/bootstrap/runner` and `publish_data_dependencies.py` move the prompt, validator, and auth bundle as bytes; they inherit the new contract without a code branch.
- The experiment preflight is target-specific by design. It now follows the general `tools/bootstrap` contract; it is not the contract owner.

## Residual validation

The unit and contract seams are green: 3,871 passed, 42 skipped across the affected suites.
The full live validation is still pending: merge and deploy the branch, run the all-session preflight, and confirm one admin lifecycle and one member lifecycle in the same `steel_crawl` run.
The expected manifest has two session run ids, one admin console page, one member centre page, and the admin menu endpoints.
