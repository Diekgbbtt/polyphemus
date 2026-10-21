# Steel session-only change: exhaustive impact map (#395)

*Status: implemented and audited 2026-10-21.*
*Implementation commit: `894711c1`. The close-out commit adds the client audit and documentation disposition recorded here.*
*Decision record: `docs/design/steel-session-only-395-decisions.md`.*
*Fingerprint evidence: `docs/design/evidence/steel-359/t395-fingerprint-consistency.md`.*
*Scope: every repository component that uses, teaches, or documents the Steel browser.*

## 1. Final contract

- Profiles are retired in cloud and local deployments.
- A retired `steel.profile` key is silently disregarded.
- There is no warning, alias, migration, or compatibility path.
- There is one `steel-browser` skill.
- The skill is runtime-agnostic and blind to cloud versus local.
- The runtime is selected below the skill, the tool wrapper, and the provider.
- The durable browser state is exactly cookies, localStorage, sessionStorage, and indexedDB.
- The account reference is `steel.state`.
- The state file is `<data_root>/<project_id>/steel-state/<account>.json`.
- The state file is owner-only, atomic, and single-writer.
- `STEEL_API_KEY` is the only cloud-specific credential.
- A local deployment is keyless and configured by `STEEL_BROWSER_API_URL`.
- `steel_configured()` accepts a key or an endpoint.
- Cloud-native fingerprint jitter is accepted.
- The tool never randomises the user agent, viewport, or region.
- The crawl retry budget is one fresh browser context.
- Auth material is replicated with a verification gate.
- A failed gate produces `auth_replication_failed`, an empty manifest, and reduced coverage.
- A failed gate never overwrites previously valid account state.
- The interactive CLI cannot restore state because `start` has no state field.
- Live-session reuse is the interactive fallback.
- Only the programmatic crawl provider restores and captures state.

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
| H | Historical record, marked but not rewritten. |
| N | No change after audit. |

## 3. Model-facing client components

These are the components that teach an agent how to use the browser.
Every row has a positive drift test or an explicit no-change reason.

| Component | Surface it reaches | Old contract | Final contract | Status | Drift test |
|---|---|---|---|---|---|
| `skills/steel-browser/SKILL.md` | Every browser role, including hunting and exploit roles | Cloud and self-hosted sections, profile mount, `--profile`, local API wording | One runtime-blind body; teaches the `steel_exec` gateway and a bare shell `exec`; four-field state; live-session reuse; auth gate signals | Implemented | `tests/test_steel_skill_rule.py`, `tests/recon/test_steel_session_only_surfaces.py` |
| `skills/meta/authn-skill-writing/SKILL.md` | External authn bootstrapper | Profile discipline, profile store key, profile scripts | State discipline, `steel: {state}`, live-session reuse, no profile vocabulary | Implemented | `tests/recon/test_authn_skill_writing.py`, `tests/recon/test_steel_session_only_surfaces.py` |
| `skills/meta/authn-skill-writing/references/bootstrap-workflow.md` | External authn bootstrapper | Profile mount, profile key, persisted-session claim | Live-session reuse, no restore claim, `steel.state` only when a state file exists | Implemented | `tests/recon/test_authn_skill_writing.py` |
| `skills/README.md` | Skill catalogue readers | "no profile mounts" | Session state and one runtime-agnostic skill | Implemented | Content review |
| `src/polymerhus/recon/control/prompts/auth-gateway.md` | Orchestrator gateway turn | Mount the persisted profile, `--update-profile`, fingerprint replay | Start or reuse a live session, replicate recorded auth material, never write a state reference | Implemented | `tests/recon/test_steel_session_only_surfaces.py` |
| `src/polymerhus/recon/control/orchestrator_agent.py` (`_BRANCH_MANNER`) | Gateway branch directives | Mount a profile, mint with `--update-profile` | Start or reuse a live session, verify, never write a state reference | Implemented | `tests/recon/test_steel_session_only_surfaces.py` |
| `src/polymerhus/recon/control/authn_loop.py` | Injected loop hints | Mount its Steel profile, never write a profile key | Start or reuse a live session, never write a state reference | Implemented | `tests/recon/test_steel_session_only_surfaces.py` |
| `src/polymerhus/recon/crawl/prompts/steel-crawl.md` | Recon crawl role | Steel cloud browser, three fresh sessions, new region and fingerprint claims | Runtime-blind Steel browser, one fresh-context retry, no region or fingerprint claim | Implemented | `tests/recon/test_steel_session_only_surfaces.py` |
| `src/polymerhus/app/auth/tool.py` (`AUTH_STORE_CONTRACT`) | Every agent bound to `auth_store` | Taught `steel: {state}` and the ignored old `profile` key | Teaches `steel: {state}` only | Implemented | `tests/app/test_auth_store_tool.py` |
| `tools/bootstrap/prompts/data-dep-authn.md` | External authn bootstrapper prompt | `steel? ({profile})`, persisted-session claim | `steel? ({state})`, recorded auth material | Implemented | `tests/recon/test_steel_session_only_surfaces.py` |
| `eval/OPERATOR.md` | Operators running the local Steel stack | Teardown destroys profiles | Teardown destroys the cache, snapshots, and session state | Implemented | Content review |
| `src/polymerhus/attack/hunting/` | Hunting roles bind the `steel-browser` skill; their pod surface is generic `exec` | Skill wording assumed a `steel_exec` gateway only | The one skill teaches the gateway and a bare shell `exec`; no hunting code change | Implemented in the skill | `tests/test_steel_skill_rule.py` |
| `SurfaceContextStore` (`src/polymerhus/attack/hunting/hunt_orchestrator.py`) | Hunt `surface_context` persistence | No Steel dependency | No change; it stores hunt surface context, not browser state | No change | Existing `tests/attack/test_hunt_orchestrator.py` |

The "with_context store" in the audit brief resolves to `SurfaceContextStore`.
No `with_context`, `with-context`, or `withcontext` symbol exists in the repository or recent history.
`SurfaceContextStore` never invokes Steel and holds no browser state.

## 4. Runtime and state

| Component | Old role | Final role | Status | Tests |
|---|---|---|---|---|
| `src/polymerhus/recon/crawl/steel_provider.py` | Random UA, viewport, region, stealth, and `profile_id`; mount profile; seed cookies; release without capture | Deterministic options; restore the state file; merge cookies, scoped headers, and storage tokens; run the gate; capture state before release | Implemented | `tests/recon/crawl/test_steel_provider_cookies.py`, `test_steel_provider_endpoint.py`, `test_auth_replication_gate.py` |
| `src/polymerhus/recon/crawl/steel_client.py` | Required `STEEL_API_KEY`; threaded `steel_profile` | Keyless-aware `steel_configured()`; threads `steel_state` and `browser_auth`; no profile arguments | Implemented | `tests/recon/crawl/test_steel_client.py` |
| `src/polymerhus/recon/crawl/crawl_agent.py` | Threaded `steel_profile` and cookies | Threads `steel_state` and browser auth material | Implemented | `tests/recon/crawl/test_crawl_agent.py` |
| `src/polymerhus/recon/crawl/crawl_pod.py` | Read `extra["steel_profile"]`; passed profile and cookies | Reads `extra["steel_state"]` and `extra["browser_auth"]`; failed gate reduces coverage | Implemented | `tests/recon/crawl/test_crawl_pod.py`, `test_crawl_auth.py`, `test_crawl_e2e.py` |
| New `src/polymerhus/recon/crawl/auth_gate.py` | Did not exist | Gates on application state or an authenticated-surface response; rejects login and 401 or 403 responses; typed `auth_replication_failed` | Implemented | `tests/recon/crawl/test_auth_replication_gate.py` |
| `src/polymerhus/recon/crawl/crawl_agentic.py` | Loaded the crawl prompt | No code change; the prompt contract changed | No code change | Existing crawl-agentic tests |
| `src/polymerhus/app/steel_session_state.py` | Captured the full context; no projection; no per-account path | Four-field projection; per-account path; owner-only atomic write; release always | Implemented | `tests/test_steel_session_state.py`, `tests/integration/test_steel_session_state_http.py`, `tests/e2e/test_steel_session_state_live.py` |
| `src/polymerhus/analysis/anatomy.py` (`_steel_available`) | Checked `STEEL_API_KEY` only | Accepts `STEEL_API_KEY` or `STEEL_BROWSER_API_URL` | Implemented | `tests/analysis/test_anatomy.py` |
| `src/polymerhus/recon/config.py` | Cloud-only comment | Runtime-neutral credential comment; code unchanged | Implemented | Existing config imports |
| `src/polymerhus/recon/crawl/requirements.txt` | Cloud-browser comment | Runtime-neutral dependency comment; code unchanged | Implemented | Build check |
| `src/polymerhus/app/steel_endpoint.py` | One generic address seam | No change | No change | `tests/test_steel_endpoint.py`, `tests/integration/test_steel_endpoint_contract.py` |
| `src/polymerhus/app/atomic_write.py` | Atomic write helper | No change | No change | Existing tests |

## 5. Control and auth data plane

| Component | Old role | Final role | Status | Tests |
|---|---|---|---|---|
| `src/polymerhus/recon/control/auth_feed.py` | Projected `steel.profile` and browser cookies | Projects `steel.state` and `browser_auth`; profile is silently disregarded | Implemented | `tests/recon/test_auth_feed.py` |
| `src/polymerhus/recon/control/pipeline.py` | Injected `extra["steel_profile"]` | Injects `extra["steel_state"]` and `extra["browser_auth"]` | Implemented | `tests/recon/test_pipeline.py`, `test_crawl_auth.py` |
| `src/polymerhus/app/auth/records.py` | Required `steel.profile` | Accepts `steel.state`; silently disregards `steel.profile` | Implemented | `tests/app/test_auth_records.py` |
| `src/polymerhus/app/auth/tool.py` | Taught the old profile key | Teaches `steel: {state}` only | Implemented | `tests/app/test_auth_store_tool.py` |
| `src/polymerhus/app/auth/store.py` | Merged `steel` | No profile-specific logic; state merge verified | No code change | `tests/app/test_auth_store.py` |
| `src/polymerhus/app/auth/seams.py` | Read-only auth view | `steel` remains a non-secret reference | No change | `tests/app/test_auth_store_tool_readonly.py` |
| `src/polymerhus/recon/control/job_agent.py` | No profile logic | No change | No change | Existing tests |
| `src/polymerhus/recon/control/jobs.py` | Registered the `steel_crawl` job | No change | No change | `tests/recon/test_jobs.py` |

## 6. Tool, wrapper, and deployment

| Component | Old role | Final role | Status | Tests |
|---|---|---|---|---|
| `kali/mcp_server.py` | Injected `--local` into command mode | Passes command text unchanged; mode lives in the wrapper | Implemented | `tests/test_steel_exec.py`, `tests/test_steel_exec_scaffold.py` |
| `kali/postrun.sh` | Installed the pinned binary | Installs the wrapper and the real binary at the PATH location | Implemented | `tests/test_steel_cli_delivery.py`, `tests/test_steel_wrapper.py` |
| `kali/steel_wrapper.sh` | Did not exist | Owns `--local` when `STEEL_BROWSER_API_URL` is set; fixes the user agent after a local `browser start`; passes `--version` through | Implemented | `tests/test_steel_wrapper.py` |
| `eval/deploy/steel/docker-compose.steel.yml` | No fingerprint setting | Sets `SKIP_FINGERPRINT_INJECTION=1`; no implicit shared user-data-dir | Implemented | `tests/eval/test_steel_deployment_contract.py` |
| `docker-compose.yml` | Passed `STEEL_API_KEY` and `STEEL_BROWSER_API_URL` | Unchanged; either configures the runtime | Verified | Compose contract tests |
| `docker-compose.dev.yml` | Passed `STEEL_BROWSER_API_URL` | Unchanged keyless path | Verified | Dev compose contract |
| `eval/docker-compose.eval.yml` | Passed `STEEL_BROWSER_API_URL` | Unchanged keyless path | Verified | Eval compose contract |
| `.env.example` | `STEEL_API_KEY` only | Documents both the key and the keyless endpoint | Implemented | Content review |

## 7. Skill reference files

| Component | Old role | Final role | Status | Tests |
|---|---|---|---|---|
| `skills/steel-browser/references/catalogue.sh` | Listed live sessions and saved profiles | Lists live sessions only | Implemented | `tests/e2e/test_steel_canonical_actions_mocked.py` |
| `skills/steel-browser/references/profile-mount.sh` | Mounted a profile | Deleted | Implemented | File absent |
| `skills/steel-browser/references/session-state.sh` | Proposed in the first map | Not created; the provider owns capture and restore, and the CLI cannot restore | No script by design | `tests/test_steel_session_state.py`, `tests/test_steel_skill_rule.py` |
| `skills/steel-browser/references/session-lifecycle.sh` | Started, navigated, stopped | No state restore; the CLI has no flag; live reuse is the interactive path | No change | `tests/e2e/test_steel_canonical_actions_mocked.py` |
| `skills/steel-browser/references/extract-reads.sh` | Read cookies and storage | No change; state capture belongs to the provider | No change | Mocked e2e |
| `skills/steel-browser/references/stop-owner.sh` | Stop ownership only | No change | No change | Existing tests |
| `skills/steel-browser/references/eval-inline.sh` | Inline JS | No change | No change | Existing tests |
| `skills/steel-browser/references/eval-interact.sh` | Form interaction | No change | No change | Existing tests |
| `skills/steel-browser/references/interact-batch.sh` | Batch interaction | No change | No change | Existing tests |
| `skills/steel-browser/references/navigate-read.sh` | Navigation read | No change | No change | Existing tests |
| `skills/steel-browser/references/scrape-page.sh` | One-shot scrape | No change; the wrapper hides mode | No change | Existing tests |
| `skills/steel-browser/references/spider-bounded.sh` | Bounded spider | No change; the wrapper hides mode | No change | Existing tests |

## 8. Tests

| Test file | Coverage | Status |
|---|---|---|
| `tests/recon/test_steel_session_only_surfaces.py` | New drift guard for the gateway prompt, branch manner, loop hints, crawl prompt, auth-store contract, meta skill, and bootstrapper prompt | Implemented |
| `tests/test_steel_skill_rule.py` | Strengthened: forbidden runtime and identity words, both exec surfaces, four state fields, CLI limit, gate signals | Implemented |
| `tests/analysis/test_anatomy.py` | Added the keyless endpoint case for `_steel_available` | Implemented |
| `tests/app/test_auth_store_tool.py` | Added the no-profile-vocabulary contract assertion; fixtures use `steel.state` | Implemented |
| `tests/app/test_auth_records.py` | A profile-only record validates, projects no state, and emits no warning; state fixtures renamed | Implemented |
| `tests/app/test_auth_store.py` | The state fixture replaces the profile fixture | Implemented |
| `tests/app/test_auth_store_tool_readonly.py` | The state fixture replaces the profile fixture | Implemented |
| `tests/recon/test_authn_skill_writing.py` | Asserts no profile vocabulary and the live-session and state contract | Implemented |
| `tests/recon/test_pipeline_gateway.py` | Gateway fixture carries `steel.state` | Implemented |
| `tests/recon/crawl/test_crawl_auth.py` | Pipeline binds state and browser auth material; comments corrected | Implemented |
| `tests/recon/crawl/test_steel_crawl_real_e2e.py` | Wording corrected; the live tier is still gated | Implemented; live gated |
| `tests/e2e/test_authn_bootstrap_walkthrough.py` | E4 asserts `steel.state`; E5 checks the owner-only four-field state file instead of a profile mount | Implemented; live gated |
| `tests/e2e/harness/recaptcha_challenge_probe.py` | Historical profile probe; explicit banner says it is not a current client | Historical |
| `tests/support/steel_cli_scaffold.py` | Models the real CLI, including its profile family; not a product client | No change |
| `tests/test_steel_cli_scaffold.py` | Pins CLI scaffold fidelity, including the profile family | No change |
| `tests/conftest.py` | No Steel profile fixture; the `profile` matches are endpoint or compose terms | No change |
| `tests/e2e/gateway_stack.py` | No Steel profile environment; the `profile` match is a compose profile | No change |
| `tests/recon/test_jobs.py` | `profile` matches are endpoint profiling, not Steel state | No change |
| `tests/recon/crawl/test_auth_replication_gate.py` | Gate pass and fail predicates, header scoping, no state overwrite | Implemented |
| `tests/recon/test_auth_feed.py` | State projection, browser auth projection, silent profile disregard | Implemented |
| `tests/recon/crawl/test_steel_provider_cookies.py` | No random options, no `profile_id`, state restore and capture, gate, header scoping | Implemented |
| `tests/recon/crawl/test_steel_provider_endpoint.py` | Endpoint and SDK kwargs; no profile options | Implemented |
| `tests/recon/crawl/test_steel_client.py` | State forwarding and keyless configured check | Implemented |
| `tests/recon/crawl/test_crawl_agent.py` | State and browser-auth threading | Implemented |
| `tests/recon/crawl/test_crawl_pod.py` | State and auth-material seeding; gate failure path | Implemented |
| `tests/recon/crawl/test_crawl_e2e.py` | State and browser-auth signature | Implemented |
| `tests/recon/crawl/test_full_stack_live_llm_e2e.py` | State signature | Implemented; live gated |
| `tests/recon/crawl/test_login_host_and_scope.py` | State signature | Implemented |
| `tests/recon/test_pipeline.py` | State and browser-auth injection | Implemented |
| `tests/test_steel_session_state.py` | Four-field projection, per-account path, owner-only write | Implemented |
| `tests/integration/test_steel_session_state_http.py` | Four-field projection over HTTP | Implemented |
| `tests/e2e/test_steel_session_state_live.py` | Four-field live round trip | Implemented; live gated |
| `tests/e2e/test_steel_canonical_actions_mocked.py` | One skill and reference scripts; no profile script | Implemented |
| `tests/test_steel_exec.py` | Wrapper owns mode; gateway guards remain | Implemented |
| `tests/test_steel_exec_scaffold.py` | Wrapper-aware gateway | Implemented |
| `tests/test_steel_exec_live.py` | Keyless live gateway path | Implemented; live gated |
| `tests/test_steel_cli_delivery.py` | Wrapper and real binary installation | Implemented |
| `tests/test_steel_wrapper.py` | Local mode, fixed user agent, passthrough | Implemented |
| `tests/eval/test_steel_deployment_contract.py` | `init: true`, skip-fingerprint-injection, fixed-user-agent contract | Implemented |
| `tests/test_steel_profile_guard.py` | Guarded the deleted profile mount | Deleted with the script |

## 9. Documentation bank

| Document | Disposition | Status |
|---|---|---|
| `docs/design/browser-cli-221-decisions.md` | D17 marked superseded; D20 added for session-only, one skill, state, wrapper, and fingerprint policy | Implemented |
| `docs/design/browser-cli-221-spec.md` | Profile references replaced by session state and `steel.state` | Implemented |
| `docs/design/browser-cli-221-assertions.md` | Session-only assertions marked implemented and cited to tests | Implemented |
| `docs/design/steel-local-deployment-359-decisions.md` | D359-12 and D359-13 added; D359-7 amended | Implemented |
| `docs/design/steel-local-deployment-359-spec.md` | Profiles retired; local state is session state | Implemented |
| `docs/design/steel-local-deployment-359-assertions.md` | C10 keeps the profile-absence proof; session-only assertion added | Implemented |
| `docs/design/steel-session-lifecycle-395-decisions.md` | Section 5 records profiles retired and the four-field state | Implemented |
| `docs/design/steel-session-first-395.md` | Partial-superseded note at the top | Historical |
| `docs/design/steel-profile-replacement-impact-map-395.md` | Superseded note at the top; cloud profiles retired too | Historical |
| `docs/design/steel-session-only-395-decisions.md` | Authoritative decision record | Implemented |
| `docs/design/steel-session-only-impact-map-395.md` | This file; every row carries a disposition | Implemented |
| `docs/design/evidence/steel-359/t395-fingerprint-consistency.md` | Fingerprint evidence | Implemented |
| `docs/design/evidence/steel-359/t395-local-capability-profile-gap.md` | Historical capability evidence; top note records profile retirement | Historical |
| `docs/design/evidence/steel-359/t395-oss-profile-research.md` | Historical OSS evidence; top note records profile retirement | Historical |
| `docs/design/evidence/steel-359/t395-cli-timeout-root-cause.md` | Historical root cause; note records the session-only state path | Historical |
| `docs/design/auth-store-220-decisions.md` | Amendment and inline D220-4 note: `steel.state`; profiles silently disregarded; state stays out of the store | Implemented |
| `docs/design/analysis-auth-store-view-364-adr.md` | Read-only view keeps `steel.state`; `steel.profile` retired | Implemented |
| `docs/design/recon-job-auth-223-decisions.md` | Amendment and inline notes on D223-14, D223-19, and IR-11: state restore, no profile | Implemented |
| `docs/design/recon-auth-gateway-223-spec.md` | Top amendment: state restore, auth-material replication, gate, silent profile disregard | Implemented |
| `docs/design/authn-antiblock-replayability-237-decisions.md` | Amendment and inline D237-4 note: profile discipline retired; profile script gone | Implemented |
| `docs/design/recon-pipeline-design.md` | Feed and sequence updated to `steel_state`; no profile or browser cookie seeding | Implemented |
| `docs/design/agent-context-architecture.md` | Feed carries `extra["steel_state"]`; amendment records the state and auth material | Implemented |
| `src/polymerhus/recon/CONTEXT.md` | Glossary records `steel.state`, silent profile retirement, and the session-only browser | Implemented |
| `src/polymerhus/app/CONTEXT.md` | State seam records session-only state and four fields | Implemented |
| `skills/README.md` | Session state and one runtime-agnostic skill | Implemented |
| `eval/OPERATOR.md` | Session-only state, state reference, fixed user agent, keyless local runtime | Implemented |
| `tests/e2e/harness/recaptcha_challenge_probe.py` | Historical banner only; not modernised | Historical |

### 9.1 Historical records that keep their original bodies

These records are not rewritten.
They carry a top or inline supersession note where their body could mislead.

| Record | Note |
|---|---|
| `docs/design/steel-profile-replacement-impact-map-395.md` | Superseded; cloud profiles retired too |
| `docs/design/steel-session-first-395.md` | Partial supersession; two primitive packs not adopted |
| `docs/design/browser-cli-221-decisions.md` D17 and its amendment | Superseded in place; D20 is current |
| `docs/design/recon-job-auth-223-decisions.md` D223-14, D223-19, IR-11 | Inline notes plus the end amendment |
| `docs/design/auth-store-220-decisions.md` D220-4 | Inline note plus the end amendment |
| `docs/design/authn-antiblock-replayability-237-decisions.md` D237-4 | Inline note plus the end amendment |
| `docs/design/authn-recaptcha-fix-237-hypotheses.md` | Historical experiment; no rewrite |
| `docs/superpowers/plans/2026-07-04-recon-pipeline-agentic-crawl.md` | Historical plan; no rewrite |
| `docs/design/evidence/steel-359/t395-local-capability-profile-gap.md` | Historical evidence; top note added |
| `docs/design/evidence/steel-359/t395-oss-profile-research.md` | Historical evidence; top note added |
| `docs/experiments/*` and `docs/ingestion-*` | Not Steel-profile consumers; no change |

## 10. Verified non-consumers

| Area | Reason |
|---|---|
| `frontend/` | No Steel browser usage. |
| `gateway/` | No Steel browser usage. |
| `src/polymerhus/project_management/` | No Steel browser usage. |
| `src/polymerhus/recon/domain/parsers/steel_parser.py` | Parses the crawl manifest; no browser session or state. |
| `src/polymerhus/recon/control/jobs.py` | Registers the `steel_crawl` job; no profile or state logic. |
| `src/polymerhus/attack/` | Hunting roles bind the skill, but no code opens a Steel session and `SurfaceContextStore` is Steel-free. |
| `tests/support/steel_cli_scaffold.py` | Models the real CLI; its `--profile` flags are fidelity, not a product client. |
| `tests/recon/test_jobs.py` | `profile` matches are endpoint profiling. |
| `docs/ingestion-*` and `docs/design/lightrag/*` | `profile` means a compose or document profile. |

The first map wrongly listed `src/polymerhus/analysis/anatomy.py` as a non-consumer.
Its `_steel_available` gate is a Steel consumer and now accepts a keyless endpoint.
It is recorded in section 4.

## 11. Verification

### 11.1 Test evidence at close-out

| Tier | Result |
|---|---|
| Focused client and contract tests | 175 passed |
| Focused provider, state, and e2e collection tests | 102 passed, 9 skipped |
| `tests/recon` | 1093 passed, 20 skipped |
| `tests/app` | 285 passed, 20 skipped |
| `tests/analysis` | 389 passed |
| `tests/eval` | 783 passed |

The four broad tiers total 2550 passed and 40 skipped.
The close-out report carries the final counts.
Live local Steel verification is still pending and is listed below.

### 11.2 Live local verification pending

- State capture and restore on the local Steel runtime.
- Fixed user agent after local `browser start`, observed across two sessions.
- Auth gate pass on the authenticated surface.
- Auth gate fail on a login redirect, 401, or 403, with no state overwrite.

### 11.3 Repository-wide blockers

- Full repository verification needs `langfuse` in the local environment.
- `test_arjun_consumption_contracts.py` and `test_llm_sync_key_rotation.py` fail outside this change.
- Merging into `dev` is blocked by a local merge conflict in the `dev` worktree.
- No push or merge happens without operator approval.

## 12. Decisions and open items

| Decision | Resolution | Current evidence |
|---|---|---|
| Q1 state reference shape | `steel.state` | `auth/records.py`, `auth_feed.py`, pipeline, and tests |
| Q2 CLI state flag | Open upstream item: `start` has no state field; live reuse is the implemented interactive fallback | `skills/steel-browser/SKILL.md`, `tests/test_steel_skill_rule.py`, Q2 in the decision record |
| Q3 local user agent | Chrome 155, matching the image | wrapper, compose, deployment contract test |
| Q4 fresh-context retry | At most one | `steel-crawl.md`, surface drift test |
| Q5 old profile records | Silently disregard; no warning, alias, or migration | `auth/records.py`, `tests/app/test_auth_records.py` |
| Q6 crawl auth source | Auth-material replication with the gate | provider, crawl pod, auth feed, pipeline, gate tests |
| Q7 cloud user agent | Native jitter; the tool does not randomise | provider options and fingerprint evidence |
| Q8 local mode seam | Wrapper owns mode; gateway keeps guards | `kali/mcp_server.py`, `kali/postrun.sh`, wrapper tests |

## 13. Search proof

The sweep is reproducible with:

```bash
rg -n -i "profile-mount|steel\.profile|steel_profile|--update-profile|profile_id|persist_profile|profileId|persistProfile" src skills tools kali eval tests
rg -n -i "cloud|self-hosted|local deployment|local runtime|local API|STEEL_API_KEY|STEEL_BROWSER_API_URL|--local" skills/steel-browser skills/meta/authn-skill-writing
rg -n "steel_state|browser_auth|auth_replication_failed|steel\.state" src tests docs
rg -n "with_context|with-context|withcontext|SurfaceContextStore" src tests docs
```

The remaining `steel.profile` matches are deliberate:
they are the silent-disregard tests, the retirement notes in the glossary and decision records, the deleted-script history, and the historical reCAPTCHA probe banner.
No model-facing client teaches the retired path.
