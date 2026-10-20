# Steel session-only change: exhaustive impact map (#395)

*Status: recorded 2026-10-20.*
*Decision record: `docs/design/steel-session-only-395-decisions.md`.*
*Fingerprint evidence: `docs/design/evidence/steel-359/t395-fingerprint-consistency.md`.*
*Scope: every component in this repository that uses the Steel browser, plus the documentation bank that describes it.*

## 1. Method

The sweep ran on the session-only worktree at `32ece656`.
The search terms were:

```
steel_profile
steel.profile
profile_id
persist_profile
profileId
persistProfile
--profile
--update-profile
profile-mount
sessionContext
session_context
session state
steel_exec
steel-browser
```

The sweep found:

| Area | Matching lines | Files |
|---|---:|---:|
| Non-documentation source, skills, eval | 81 | 15 |
| Tests | 81 | 22 |
| Documentation | 214 | 38 |
| `sessionContext` or session state in non-documentation | 35 | 12 |

The documentation count includes historical plans, experiments, and evidence records.
Historical records are not rewritten.
They are marked as historical where they can mislead a reader.

## 2. Change classes

| Code | Change |
|---|---|
| R | Remove the profile path. |
| S | Add or reshape session state. |
| A | Add auth-material replication and the verification gate. |
| U | Stabilise the local user agent. |
| K | Make the runtime keyless-aware. |
| W | Hide runtime mode from the skill and scripts. |
| D | Documentation update. |
| T | Test update. |
| M | Migration or compatibility handling. |

## 3. Runtime and state

| Component | Current role | Required change | Class | Risk | Tests |
|---|---|---|---|---|---|
| `src/polymerhus/recon/crawl/steel_provider.py` | Creates sessions with random UA, viewport, region, stealth, and `profile_id`; mounts profile; seeds cookies; releases without capture. | Remove `_UAS`, `_VIEWPORTS`, `_REGIONS`, `_random_session_opts` randomness, and `profile_id`; accept a state path and browser auth material; merge auth cookies and storage tokens into `session_context`; scope header material to the target origin; run the auth gate; capture state before release; never send a random user agent; keep `use_proxy` as caller input. | R, S, U, A | High | `test_steel_provider_cookies.py`, `test_steel_provider_endpoint.py`, new state and gate provider tests |
| `src/polymerhus/recon/crawl/steel_client.py` | Requires `STEEL_API_KEY`; threads `steel_profile`. | Treat endpoint presence as configured; thread `steel_state` and browser auth material; remove profile docs and arguments. | K, S, R, A | High | `test_steel_client.py` |
| `src/polymerhus/recon/crawl/crawl_agent.py` | Threads `steel_profile` and auth cookies. | Thread `steel_state` and browser auth material; update docs. | S, R, A | Medium | `test_crawl_agent.py` |
| `src/polymerhus/recon/crawl/crawl_pod.py` | Reads `extra["steel_profile"]`; passes profile and cookies. | Read `extra["steel_state"]` and `extra["browser_auth"]`; pass both; remove profile; update the module docstring. | S, R, A | High | `test_crawl_pod.py`, `test_crawl_auth.py`, `test_crawl_e2e.py` |
| New `src/polymerhus/recon/crawl/auth_gate.py` | Does not exist. | Verify application state or an authenticated-surface response; verify the target or a recorded authenticated landing, with the login endpoint as a negative marker; return a typed pass or `auth_replication_failed`; never pass on a cookie name alone. | A | High | New `test_auth_replication_gate.py` |
| `src/polymerhus/recon/crawl/crawl_agentic.py` | Loads the crawl prompt; no profile logic. | No code change; verify the prompt contract. | D | Low | `test_crawl_agentic` through existing suites |
| `src/polymerhus/recon/crawl/prompts/steel-crawl.md` | Claims a fresh session is a new fingerprint and a new region; requests up to three rotations. | Remove the fingerprint and region claims; state that a local fresh session is a fresh context only; allow at most one fresh context retry; keep the blocked and captcha signals. | D, R | Medium | Prompt content test or review |
| `src/polymerhus/app/steel_session_state.py` | Captures and stores the full context; no field projection; no per-account path helper. | Store only cookies, localStorage, sessionStorage, and indexedDB; add a per-account path helper; keep atomic write, release-always, and typed errors; add owner-only permissions. | S | High | `test_steel_session_state.py`, `test_steel_session_state_http.py` |
| `src/polymerhus/app/steel_endpoint.py` | Resolves `STEEL_BROWSER_API_URL`. | No change; remains the one generic address seam. | None | Low | `test_steel_endpoint_contract.py` |
| `src/polymerhus/recon/config.py` | `STEEL_API_KEY` only. | No code change; the key becomes optional when the endpoint is set. | K | Medium | Config tests if any |
| `src/polymerhus/app/atomic_write.py` | Atomic write helper. | No change. | None | Low | Existing tests |
| `src/polymerhus/recon/crawl/requirements.txt` | Playwright and Steel SDK. | No change. | None | Low | Build check |

## 4. Control, auth, and pipeline

| Component | Current role | Required change | Class | Risk | Tests |
|---|---|---|---|---|---|
| `src/polymerhus/recon/control/auth_feed.py` | Projects `steel.profile`; projects cookies for browser seeding. | Replace `project_steel_profile` with `project_steel_state`; add `project_browser_auth` returning cookies, required and header-located headers, and storage-located tokens grouped by target origin; keep `project_request_auth` for request tools. | S, R, A | High | `test_auth_feed.py`, new browser-auth projection tests |
| `src/polymerhus/recon/control/pipeline.py` | Injects `extra["steel_profile"]`. | Inject `extra["steel_state"]` and `extra["browser_auth"]`; import the new projectors; update comments. | S, R, A | High | `test_pipeline.py`, `test_crawl_auth.py` |
| `src/polymerhus/app/auth/records.py` | `_check_steel` requires `steel.profile`. | Accept `steel.state` when present; silently disregard `steel.profile`; no warning, alias, or migration branch (Q5). | S, R, M | High | `test_auth_records.py` |
| `src/polymerhus/app/auth/tool.py` | Contract teaches `steel: {profile}`. | Teach `steel: {state}`; remove browser-profile vocabulary; keep the no-browser-state rule. | D, R | Medium | Auth tool contract tests |
| `src/polymerhus/app/auth/store.py` | Merges `steel`; no profile-specific logic. | No code change; verify merge and null removal for `steel.state`. | None | Low | `test_auth_store` |
| `src/polymerhus/app/auth/seams.py` | Read-only auth view. | No change; the `steel` field remains non-secret. | None | Low | `analysis-auth-store-view-364` tests |
| `src/polymerhus/recon/control/orchestrator_agent.py` | Prompt says mount a profile and mint with `--update-profile`. | Prompt says restore session state and verify; remove profile commands. | D, R | High | `test_orchestrator_actor` |
| `src/polymerhus/recon/control/authn_loop.py` | Prompt says mount a Steel profile and persist its key. | Prompt says restore state, verify, capture state, and persist `steel.state`; remove profile vocabulary. | D, R | High | `test_authn_loop` |
| `src/polymerhus/recon/control/prompts/auth-gateway.md` | Profile mount and `steel.profile` instructions. | Session state restore and `steel.state` instructions. | D, R | High | Gateway prompt tests |
| `src/polymerhus/recon/control/job_agent.py` | No profile logic. | Verify no change. | None | Low | Existing tests |
| `src/polymerhus/recon/control/jobs.py` | `steel_crawl` job definition. | No change. | None | Low | `test_jobs.py` |

## 5. Tool, wrapper, and deployment

| Component | Current role | Required change | Class | Risk | Tests |
|---|---|---|---|---|---|
| `kali/mcp_server.py` | Injects `--local` into command mode with a shell tokenizer. | Move mode selection to the `steel` wrapper; remove `_local_mode`, `_inject_local_command`, and their tests; keep version, timeout, session-name, and variadic guards. | W | Medium | `test_steel_exec.py`, `test_steel_exec_scaffold.py`, `test_steel_exec_live.py` |
| `kali/postrun.sh` | Installs the pinned `steel` binary at `/opt/localbin/steel`. | Install the real binary and the wrapper at the PATH location; pin both; verify the wrapper passes `--version`. | W | Medium | Kali scaffold and live tests |
| New wrapper (for example `/opt/localbin/steel` with the real binary at `/opt/localbin/steel-real`) | Does not exist. | Inject `--local` for `browser` and `scrape` when the endpoint is set; after a local `browser start`, run `set useragent` with the fixed value; pass through `--version` and login; avoid recursion by calling the real binary. | W, U | Medium | New wrapper unit tests |
| `eval/deploy/steel/docker-compose.steel.yml` | No fingerprint setting. | Add `SKIP_FINGERPRINT_INJECTION=1`; document the fixed user agent contract. | U | High | `test_steel_deployment_contract.py` |
| `docker-compose.yml` | Passes `STEEL_API_KEY` and `STEEL_BROWSER_API_URL`. | Keep both; document that either configures the runtime; no key is required locally. | K | Medium | Compose contract tests |
| `docker-compose.dev.yml` | Passes `STEEL_BROWSER_API_URL`. | No structural change; verify local no-key path. | K | Low | Dev compose contract |
| `eval/docker-compose.eval.yml` | Passes `STEEL_BROWSER_API_URL`. | No structural change; verify local no-key path. | K | Low | Eval compose contract |
| `.env.example` | `STEEL_API_KEY` only. | Document the endpoint and the keyless local case. | D, K | Low | Review |
| `eval/OPERATOR.md` | Documents local state and profile absence. | Document session-only state, the state reference, the fixed user agent, and the keyless local runtime. | D, S, U | Medium | Review |
| `tests/eval/test_steel_deployment_contract.py` | Asserts `init: true`. | Add the skip-injection assertion and the fixed user-agent contract assertion. | T, U | Medium | Itself |

## 6. Skill and reference surface

| Component | Current role | Required change | Class | Risk | Tests |
|---|---|---|---|---|---|
| `skills/steel-browser/SKILL.md` | One body but a local-runtime section, a profiles section, profile mount, `steel profile`, and `--profile` command forms. | One runtime-agnostic body; no cloud, local, endpoint, API key, `--local`, profile, or `sessionContext` text; add state restore and capture as an operation; remove profile families; update the description and version. | D, R, S, W | High | `test_steel_skill_rule.py`, content review |
| `skills/steel-browser/references/catalogue.sh` | Lists live sessions and saved profiles. | List live sessions only. | R | Medium | `test_steel_canonical_actions_mocked.py` |
| `skills/steel-browser/references/profile-mount.sh` | Mounts a profile and probes the local route. | Delete. | R | High | `test_steel_profile_guard.py` deleted |
| New `skills/steel-browser/references/session-state.sh` | Does not exist. | Capture, store, and restore the four state fields; bounded output; no value echo; owner-only store. | S | High | New unit and mocked e2e |
| `skills/steel-browser/references/session-lifecycle.sh` | Starts, navigates, stops. | Add optional state restore on start and capture on close; keep the trap and catalogue proof. | S | Medium | `test_steel_canonical_actions_mocked.py` |
| `skills/steel-browser/references/extract-reads.sh` | Reads cookies and storage. | Feed the state capture path; keep name and count projection. | S | Medium | Mocked e2e |
| `skills/steel-browser/references/stop-owner.sh` | Stop ownership only. | No change. | None | Low | Existing tests |
| `skills/steel-browser/references/eval-inline.sh` | Inline JS. | No change. | None | Low | Existing tests |
| `skills/steel-browser/references/eval-interact.sh` | Form interaction. | No change. | None | Low | Existing tests |
| `skills/steel-browser/references/interact-batch.sh` | Batch interaction. | No change. | None | Low | Existing tests |
| `skills/steel-browser/references/navigate-read.sh` | Navigation read. | No change. | None | Low | Existing tests |
| `skills/steel-browser/references/scrape-page.sh` | One-shot scrape. | No change; the wrapper hides local mode. | None | Low | Existing tests |
| `skills/steel-browser/references/spider-bounded.sh` | Bounded spider. | No change; the wrapper hides local mode. | None | Low | Existing tests |
| `skills/meta/authn-skill-writing/SKILL.md` | Profile discipline, profile store key, profile scripts, local cloud distinction implied by the mechanics skill. | Session state discipline; `steel.state`; remove profiles and profile scripts; keep one mechanics skill; no runtime branch; update the store contract and report fields. | D, R, S | High | `test_authn_skill_writing.py` |
| `skills/meta/authn-skill-writing/references/bootstrap-workflow.md` | Profile name input, mount by profile, record profile key, `steel login`. | State reference input, restore state, record `steel.state`; remove profile commands; make the login guidance runtime-neutral. | D, R, S | High | `test_authn_skill_writing.py` |
| `skills/README.md` | Describes profile mounts. | Describe session state and the one runtime-agnostic skill. | D, R | Low | Review |

## 7. Tests

| Test file | Current coverage | Required change | Class |
|---|---|---|---|
| `tests/app/test_auth_records.py` | Rejects a bad `steel.profile`. | Validate `steel.state`; a profile-only record validates, projects no state, and emits no warning. | T, S, R |
| `tests/conftest.py` | May seed a profile fixture. | Replace with a state reference fixture where used. | T |
| `tests/e2e/gateway_stack.py` | Profile environment in the gateway stack. | State path and keyless local environment. | T |
| `tests/e2e/harness/recaptcha_challenge_probe.py` | Optional profile path. | Optional state path; no profile mount. | T, R |
| `tests/e2e/test_authn_bootstrap_walkthrough.py` | Profile workflow. | State workflow. | T, R |
| `tests/recon/crawl/test_crawl_agent.py` | Threads `steel_profile`. | Threads `steel_state`. | T, S |
| `tests/recon/crawl/test_crawl_auth.py` | Pipeline binds profile and cookies. | Pipeline binds state and browser auth material; no profile. | T, S, R, A |
| `tests/recon/crawl/test_crawl_e2e.py` | `run_crawl_fn` signature with profile. | State and browser-auth signature. | T, S, A |
| `tests/recon/crawl/test_crawl_pod.py` | Profile and cookie seeding. | State plus auth-material seeding; gate failure path. | T, S, R, A |
| `tests/recon/crawl/test_full_stack_live_llm_e2e.py` | Profile signature. | State signature. | T, S |
| `tests/recon/crawl/test_login_host_and_scope.py` | Profile signature. | State signature. | T, S |
| `tests/recon/crawl/test_steel_client.py` | Profile forwarding. | State forwarding; keyless configured check. | T, S, K |
| `tests/recon/crawl/test_steel_crawl_real_e2e.py` | Profile environment. | State environment; local no key. | T, K |
| `tests/recon/crawl/test_steel_provider_cookies.py` | Random options, profile mount, cookie seeding. | No random options; state restore and capture; no profile; auth-material replication and gate; header scoping. | T, R, S, U, A |
| `tests/recon/crawl/test_steel_provider_endpoint.py` | Endpoint and SDK client kwargs. | Keep; add keyless endpoint check. | T, K |
| `tests/recon/test_auth_feed.py` | Projects `steel.profile`. | Projects `steel.state` and browser auth material; storage-token grouping; profile silently ignored. | T, S, A |
| `tests/recon/test_authn_skill_writing.py` | Profile content. | State content; no profile; one skill. | T, D |
| `tests/recon/crawl/test_auth_replication_gate.py` | Does not exist. | Gate passes on an authenticated-surface response or application state; fails on a login redirect, 401, or 403; header material is scoped. | T, A |
| `tests/recon/test_pipeline.py` | Asserts `steel_profile`. | Asserts `steel_state` and browser auth material. | T, S, A |
| `tests/support/steel_cli_scaffold.py` | CLI scaffold, profile args. | Wrapper-aware scaffold; remove profile args; add `set useragent`. | T, W, U |
| `tests/test_steel_cli_scaffold.py` | CLI scaffold fidelity. | Add wrapper behavior and user-agent call. | T, W, U |
| `tests/test_steel_exec.py` | Local mode injection. | Wrapper handles mode; remove injection tests; keep guards. | T, W |
| `tests/test_steel_exec_scaffold.py` | Gateway against scaffold. | Wrapper-aware gateway. | T, W |
| `tests/test_steel_exec_live.py` | Live gateway without cloud key. | Live local no-key path. | T, K, W |
| `tests/test_steel_profile_guard.py` | Refuses local profile mount. | Delete with the profile script. | T, R |
| `tests/test_steel_session_state.py` | Full context capture and restore. | Four-field projection; per-account path; owner-only. | T, S |
| `tests/test_steel_skill_rule.py` | Asserts local `sessionContext` text and profile rule. | Asserts one runtime-agnostic skill; no profile, cloud, local, endpoint, or `sessionContext`; state rule. | T, D |
| `tests/integration/test_steel_session_state_http.py` | Full context over HTTP. | Four-field projection. | T, S |
| `tests/e2e/test_steel_session_state_live.py` | Cookie round trip. | Four-field round trip; owner-only. | T, S |
| `tests/e2e/test_steel_canonical_actions_mocked.py` | Runs skill scripts. | Run the one skill and state scripts; no profile script. | T, D |
| `tests/eval/test_steel_deployment_contract.py` | `init: true`. | Add skip-injection assertion. | T, U |

`tests/recon/test_jobs.py` has `profile` matches for endpoint profiling, not Steel profiles.
It is not a Steel-profile consumer.

## 8. Documentation bank

### 8.1 Authoritative documents to update

| Document | Current profile content | Required change | Class |
|---|---|---|---|
| `docs/design/browser-cli-221-decisions.md` | D17 selects profiles; D17 amendment marks local profiles cloud-only. | Supersede D17 and the amendment; add D20 for session-only, one skill, runtime-agnostic wiring, state shape, wrapper, and fingerprint policy. | D, R, S, U |
| `docs/design/browser-cli-221-spec.md` | Data-plane split says profile refs; Profiles implementation decision. | Replace with session state and `steel.state`; remove profile lifecycle language. | D, R, S |
| `docs/design/browser-cli-221-assertions.md` | No direct profile assertion; references live Steel and skill behavior. | Add one-skill assertions; verify the profile-free command surface. | D |
| `docs/design/steel-local-deployment-359-decisions.md` | D359-7 lists Profiles API absent; D359-11 state. | Add D359-12 for keyless local configuration and session-only state; add D359-13 for the wrapper and fixed local user agent; amend D359-7. | D, S, K, U, W |
| `docs/design/steel-local-deployment-359-spec.md` | D359-7 description; state requirement. | Note that profiles are retired from the tool; keep local state as session state. | D, R |
| `docs/design/steel-local-deployment-359-assertions.md` | E9 proves local profile absence. | Keep as historical capability proof; add a session-only assertion and a fixed-user-agent assertion. | D, T |
| `docs/design/steel-session-lifecycle-395-decisions.md` | Section 5 says profiles are cloud-only; state client full context. | Replace with profiles retired; four-field state; per-account store; one writer; owner-only. | D, S, R |
| `docs/design/steel-session-first-395.md` | Historical session-first revision; proposes two primitive packs. | Mark superseded in part; point to this decision record; keep as history. | D |
| `docs/design/steel-profile-replacement-impact-map-395.md` | Historical profile replacement map; keeps cloud profiles. | Mark superseded; cloud profiles are retired too. | D |
| `docs/design/steel-session-only-395-decisions.md` | New. | Authoritative decision record. | D |
| `docs/design/steel-session-only-impact-map-395.md` | New. | This file. | D |
| `docs/design/evidence/steel-359/t395-fingerprint-consistency.md` | New. | Fingerprint evidence. | D |
| `docs/design/evidence/steel-359/t395-local-capability-profile-gap.md` | Evidence that local profiles are absent. | Keep as historical capability evidence; add a note that the tool no longer uses profiles. | D |
| `docs/design/evidence/steel-359/t395-oss-profile-research.md` | OSS history proof. | Keep as historical evidence; add a note that profiles are retired from the tool. | D |
| `docs/design/evidence/steel-359/t395-cli-timeout-root-cause.md` | Notes state and profiles. | Add a note that the state path is session-only. | D |
| `docs/design/auth-store-220-decisions.md` | `steel.profile` is the durable reference. | Add an amendment: `steel.state`; profiles retired; browser state remains out of the store. | D, R, S |
| `docs/design/analysis-auth-store-view-364-adr.md` | `steel.profile` kept in the read-only view. | Replace with `steel.state`; a reference key, not a secret. | D, S |
| `docs/design/recon-job-auth-223-decisions.md` | D223-14, D223-19, IR-11 are profile-mount designs. | Add an amendment: state restore; no profile; no browser cookie seeding; `steel.state`. | D, R, S |
| `docs/design/recon-auth-gateway-223-spec.md` | Profile mount and profile key. | Add an amendment: state restore and `steel.state`. | D, R, S |
| `docs/design/authn-antiblock-replayability-237-decisions.md` | D237 profile discipline and profile scripts. | Add an amendment: state discipline; remove profile scripts; one skill. | D, R, S |
| `docs/design/recon-pipeline-design.md` | Feed carries `steel_profile`; create uses `profile_id` and cookie seeding. | Update the feed and sequence to `steel_state`; remove profile and cookie browser seeding. | D, R, S |
| `docs/design/agent-context-architecture.md` | Feed carries `extra["steel_profile"]`. | Update to `extra["steel_state"]`. | D, S |
| `src/polymerhus/recon/CONTEXT.md` | Browser-profile reference and browser profiles entries; feed profile key; local sessionContext note. | Replace with session-state reference and browser session state; update feed and profile-free entries. | D, R, S |
| `src/polymerhus/app/CONTEXT.md` | State seam says local has no profile store. | State seam says profiles are retired; four fields; per-account state. | D, R, S |
| `skills/README.md` | Steel-browser description says profile mounts. | Session state and one runtime-agnostic skill. | D, R, S |
| `eval/OPERATOR.md` | Local state section; profile absence. | Session-only state; state reference; fixed user agent; keyless local. | D, S, U, K |

### 8.2 Historical documents

These documents describe past designs or experiments.
They should not be rewritten as current truth.
They should carry a pointer to this decision record where a reader could otherwise follow stale instructions.

| Document family | Action |
|---|---|
| `docs/design/steel-profile-replacement-impact-map-395.md` | Add a superseded note at the top. |
| `docs/design/steel-session-first-395.md` | Add a partial-superseded note at the top. |
| `docs/design/browser-cli-221-decisions.md` D17 and D17 amendment | Mark superseded in place; do not delete the history. |
| `docs/design/recon-job-auth-223-decisions.md` D223-14, D223-19, IR-11 | Mark superseded in the amendment; keep the original records. |
| `docs/design/authn-antiblock-replayability-237-decisions.md` profile discipline | Mark superseded in the amendment; keep the original records. |
| `docs/design/authn-recaptcha-fix-237-hypotheses.md` | Historical experiment; no rewrite. |
| `docs/superpowers/plans/2026-07-04-recon-pipeline-agentic-crawl.md` | Historical plan; no rewrite. |
| `docs/design/evidence/steel-359/t395-local-capability-profile-gap.md` | Keep; add a tool-retirement note only. |
| `docs/design/evidence/steel-359/t395-oss-profile-research.md` | Keep; add a tool-retirement note only. |
| `docs/experiments/*` and `docs/ingestion-*` | Not Steel-profile consumers; no change. |

## 9. Verified non-consumers

These areas were checked and need no change:

| Area | Reason |
|---|---|
| `frontend/` | No Steel browser usage. |
| `gateway/` | No Steel browser usage. |
| `src/polymerhus/project_management/` | No Steel browser usage. |
| `src/polymerhus/analysis/anatomy.py` | Uses `steel_crawl` as a job name and a capability check; no profile or state. |
| `src/polymerhus/recon/domain/parsers/steel_parser.py` | Parses the crawl manifest; no browser session or profile. |
| `src/polymerhus/recon/control/jobs.py` | Registers the `steel_crawl` job; no profile. |
| `src/polymerhus/attack/` | No Steel browser usage. |
| `docs/ingestion-*` and `docs/design/lightrag/*` | `profile` there means a compose profile or document profile, not a Steel profile. |
| `tests/recon/test_jobs.py` `profile` matches | Endpoint profiling, not Steel profiles. |

## 10. Complexity

| Work package | Files | Code lines | Test lines | Notes |
|---|---:|---:|---:|---|
| Provider and crawl threading | 5 | 170 to 250 | 280 to 390 | Remove random options and profile; add state restore, auth-material replication, gate, and capture. |
| State client and store | 2 | 80 to 140 | 100 to 160 | Four-field projection, path helper, permissions. |
| Auth material and gate | 4 | 70 to 110 | 100 to 160 | Browser projection, header scoping, gate predicates. |
| Control, auth, and prompts | 8 | 80 to 120 | 120 to 180 | State and auth projections, schema, prompt changes. |
| Wrapper, gateway, deployment | 5 | 80 to 140 | 80 to 140 | Wrapper, keyless check, compose. |
| One skill and references | 8 | 100 to 180 | 40 to 80 | Mostly Markdown and shell; delete profile script. |
| Documentation bank | about 20 | 0 | 0 | Amendments and glossary. |
| **Repository total** | **about 50** | **580 to 840** | **720 to 1,010** | Excludes the upstream CLI flag. |

The upstream CLI `--session-state` flag is the critical path for interactive state restore.
It is 120 to 180 Rust lines plus 60 to 100 test lines.
Without it, the interactive path is live-reuse only.

The user-agent consistency package alone is:

| Work | Code lines | Test lines |
|---|---:|---:|
| Wrapper `set useragent` after local start | 25 to 45 | 30 to 50 |
| Provider random-option removal | 25 to 40 removed | 30 to 50 |
| Compose skip-injection line | 1 | 2 to 5 |
| **Total** | **25 to 45 net** | **62 to 105** |

## 11. Sequence

1. Record the decisions and supersede D17. Done in this change set.
2. Add the one-skill rule and remove profile text from the skill.
3. Add `steel.state` to the auth schema and the feed.
4. Add `project_browser_auth` for cookies, headers, and storage tokens.
5. Add state restore and auth-material replication to the provider; remove the profile path.
6. Add the auth gate: authenticated-surface response or application state.
7. Make `steel_configured` endpoint-or-key.
8. Add the wrapper with `--local` and `set useragent`.
9. Remove the gateway local-mode tokenizer.
10. Add the local skip-injection setting.
11. Update the crawl prompt.
12. Update tests and docs in the same change set.
13. Add the upstream CLI `--session-state` flag, or accept live-only interactive state.

## 12. Resolved decisions that shape this map

| Decision | Resolution | Files affected |
|---|---|---|
| Q1 state reference shape | `steel.state` key | `auth/records.py`, `auth/tool.py`, `auth_feed.py`, `pipeline.py`, tests |
| Q2 CLI state flag | Required; live-only is fallback | `steel-browser` skill, interactive state helper, upstream CLI |
| Q3 local UA value | Chrome 155, matching the image | wrapper env, local compose, evidence |
| Q4 fresh-context retry | At most one | `steel-crawl.md` only |
| Q5 old profile records | Silently disregard; no warning, alias, or migration | `auth/records.py`, tests only; no operator warning |
| Q6 crawl auth source | Auth-material replication with the gate | provider, crawl pod, auth feed, pipeline, tests |
| Q7 cloud UA | Native jitter | none |
| Q8 local mode seam | Wrapper owns mode; gateway keeps guards | `kali/mcp_server.py`, `kali/postrun.sh`, wrapper tests |

## 13. Search proof

The sweep is reproducible with:

```
rg -n "steel_profile|steel\.profile|profile_id|persist_profile|profileId|persistProfile|--profile|--update-profile|profile-mount" src kali skills eval tests docs
rg -n "sessionContext|session_context|session state" src kali skills eval tests docs
rg -n "steel_provider|steel_client|steel_session_state|steel_exec|steel-browser" src kali skills eval tests docs
```

The counts in section 1 were taken with `rg -o` and `wc -l`.
The historical documentation count is intentionally not treated as a change list.
