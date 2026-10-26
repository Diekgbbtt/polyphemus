# E2E verification of the session-based Steel browser system (#221, #245, #359, #393, #395) - report

Status: complete.
Date: 2026-10-22.
Owner: autonomous e2e operator.
Scope: live verification of the browser system through three agents and one primitive matrix.
No browser-system code was changed.
No remote repository was pushed.

**Verdict.**
The browser path works.
The session-only gateway authenticated through a live reused session.
The httpOnly check passed in the pod's first lap.
The broad route sweep reached all 11 declared routes.
The state round-trip and the deployment channel passed.
The release is not production-ready.
Five findings are high severity.
The production default role model cannot complete a multi-turn browser loop.
The Steel runtime releases sessions that the start command marked as non-expiring.
The pod's final verdict is `technical-infeasibility` after its own v1 sweep outlived the session.
A fresh state session inherited cookies the caller did not provide.
The CDP target reset while the catalogue still reported the session live.

## 1. Environment and harness

The eval server is `46.224.225.245` (`eval-server-polyphemus`).
The Steel API is `http://192.33.91.87:3000/v1` on `dj-viscon-workshop-1`.
The white-jotter target is `http://t-1618c524.target/`.
The polymerhus instance is `ph-dd131acc`.
The agent container is `ph-dd131acc-agent-1`.
The Kali exec container is `ph-dd131acc-kali-1`.
The Steel CLI is `0.5.0-preview.6`.
The wrapper is installed at `/opt/localbin/steel`; the raw binary is `/opt/localbin/steel-real`.
The current source is delivered to `/tmp/polymerhus-e2e` inside the agent.
The canonical `/opt/polymerhus-dev` worktree is untouched.
The second MCP server runs on port 8001; the first server on port 8000 is untouched.

The auth fixture is a deliberate browser-only overlay.
The target is actually request-replayable.
The overlay sets `anti-bot: steel-e2e-browser-only-fixture` and `http-client-replayability: false`.
The overlay is test configuration, not a target fact.
The session-only account is `admin-sessiononly-e2e`.
The account stores a fresh `JSESSIONID` token and a cookie snapshot, with no credentials.
The project authn skill names the live session `wj-gateway-e2e`.

The successful E2 and E4 runs used `opencode-go:qwen3.8-max` as a config-layer role-model override.
The successful E3 run used `opencode-go:glm-5.3`.
The production default `opencode-go:deepseek-v4.1-flash` failed the gateway turn.
The model overrides are stated so the results are not read as the production model configuration.
The production default failure is finding F1.

## 2. Result summary

| Scenario | Result | Key evidence |
|---|---|---|
| E1 primitive matrix | Pass with four tool gaps | Operator matrix; the raw JSONL was not persisted |
| E2 auth gateway | Pass with Qwen; default model failed | `gateway-summary.json`, `gateway-verdict.json`, `gateway-trace.json` |
| E2 dead-session control | Pass (correct `not_valid` degradation) | `gateway-summary-session-expired.json` |
| E2 default model | Fail (reasoning-content 400) | `gateway-summary-reasoning-400.json` |
| E3 pod | Partial: lap-1 httpOnly pass; final `technical-infeasibility` | `pod-summary.json`, `pod-result.json` |
| E4 broad navigation | Pass: 11/11 routes, 13 tool calls, session stopped | `random-sweep.json`, `random-summary.json`, `random-result.json` |
| E5 state round-trip | Pass; provider path not run live; extra inherited cookies found | `e5-summary.json`, `e5-state.json` |
| E6 deployment | Pass: health, alias, negative alias, UA, raw-UA control, port | `e6-summary.json` |

The E2 authenticated verdict was:

- `outcome: authenticated`
- `account: admin-sessiononly-e2e`
- `branch: browser_only`
- `replayability_resolved: false`
- `loop_phase: FINISH`
- `accounts.admin-sessiononly-e2e.status: valid`
- `session_live: true`
- `verdict_secret_leak: false`

The E2 dead-session control returned `outcome: failed`.
It wrote `status: not_valid`.
It did not attempt request replay.
That is the intended E2.4 fail-closed behaviour.

The E3 lap-1 evidence was:

- Both `JSESSIONID` and `rememberMe` reported `httpOnly: true`.
- `document.cookie` had length 0.
- A JavaScript-set control cookie `wj_probe` was visible and then cleared.
- The control proves the read channel worked.
- A fresh fetch returned `/api/authentication` 200 with `身份认证成功`.
- The same fetch returned `/api/admin/user` 200.
- The final pod verdict was `unsuccessful` / `technical-infeasibility` / `clean: false`.
- The v1 sweep could not run because the Steel session expired between laps.

The E4 deterministic sweep reached:

- `/` and `/home`, which redirect to `/index`.
- `/index`
- `/jotter`
- `/jotter/article`
- `/library`
- `/login`
- `/register`
- `/admin`
- `/admin/dashboard`
- `/admin/content/editor`

The E4 agent exercised the admin menus, the user table filter, an article, the library category filter and search, and a non-published editor draft.
The agent stopped the session.
The final report was 3206 characters; the tool trace had 13 browser calls.

The E5 state round-trip captured and restored `cookies`, `localStorage`, `sessionStorage`, and `indexedDB`.
The test cookie `ph_e2e_state` round-tripped.
The state file was 1686 bytes before redaction.
The restored session was released.

The E6 checks were:

- `GET /v1/health` returned 200.
- The wrapper start reported `mode: local` and `remainingMs: ~86,400,000`.
- The connect and live hosts were `ws://192.33.91.87:3000` and `http://192.33.91.87:3000`.
- The target alias returned the title `白卷 - White Jotter`.
- The bogus host negative control returned returncode 1 and no title.
- The wrapper UA was `Chrome/155.0.0.0`.
- The raw CLI UA was `Chrome/142.0.0.0`.
- Port 9223 was closed.

## 3. Contract misalignment

The contract findings describe a disagreement between the documented or declared surface and the live behaviour.
They are not browser-transport failures.

| ID | Severity | Finding | Evidence | Reproduction | Layer |
|---|---|---|---|---|---|
| C1 | Medium | The shipped authn skill names `/#/login` and `/#/register`; the target uses history-mode `/login` and `/register` | `random-sweep.json`; the plan's route note; E1 matrix | Navigate `/#/login`; it loads `/index#/login` and the public index. Navigate `/login`; the authenticated session renders the admin shell. Navigate `/register`; it renders the registration form. | Skill and docs |
| C2 | Medium | `steel browser wait --load-state load` and `--load-state domcontentloaded` fail even with a short timeout | E1 operator matrix | Run `steel browser wait --load-state load --timeout 5000 --session <name> --json`; it returns `Timeout waiting for Page.loadEventFired`, returncode 1, and about 25 seconds. | CLI and skill |
| C3 | Low | `steel browser get text` requires a `<SELECTOR>`; a selectorless call is a clap error | `pod-result.json` raw observation 2 stderr; the pod's `get text body` succeeded | Run `steel browser get text --session <name> --json`; it reports the missing `<SELECTOR>`. Use `get text body` or a snapshot instead. | CLI and skill |
| C4 | Low | `steel browser cookies` has no `list` subcommand | `gateway-summary.json` browser commands; the agent's rationale | Run `steel browser cookies list --session <name> --json`; it fails. Use `steel browser cookies --session <name> --json`. | CLI and skill |
| C5 | Medium | An unknown `--session` name silently creates a new session | `gateway-summary.json` rationale; `gateway-trace.json` browser commands | Run `steel browser start --session <typo> --json`; it returns a new live session and success. The `steel_exec` gateway only refuses a start on a name the catalogue already reports live. | CLI and tool guard |
| C6 | High | `--inactivity-timeout 0` did not prevent idle release | `gateway-summary-session-expired.json`; `pod-summary.json`; `e6-summary.json` | Start with `--session-timeout 86400000 --inactivity-timeout 0`; leave the session idle for 10 to 20 minutes; the catalogue is empty although the start reported about 24 hours remaining. | Steel runtime, CLI, wrapper |
| C7 | Low | An account-root write is create-only; the status must use the leaf path | `src/polymerhus/app/auth/store.py`; `gateway-summary.json` status valid | Write `accounts.<name>` with a record on an operator-seeded account; it refuses with `duplicate_auth`. Write `accounts.<name>.status`; it merges and records the origin. | Prompt, skill, store |
| C8 | Medium | The turn brief directs `write_skill`, but the loaded skill protocol forbids it and reserves revisions to the SkillEvolver | `gateway-summary.json` tools; `skill.modified: false`; the verdict rationale | Run the gateway; the model records `record_skill_lesson` calls, flags the conflict, and does not modify the skill. | Prompt and skill |

The idle-release finding is the most consequential contract defect.
The start record granted about 24 hours.
The runtime still released the session after a long idle gap.
The E2 first turn lost its session before the gateway started.
The E3 pod lost its session between lap 1 and lap 2.
The E4 run only survived because the session was prepared immediately before the sweep and the agent.

The unknown-session finding is a safety defect.
A typographical error creates a live browser context and a billable session.
The model stopped the stray session in the E2 run.
The tool guard did not prevent the creation.

The account-root finding is a prompt hazard, not a store bug.
The store correctly treats a root write as a create.
The skill correctly teaches the leaf write.
The turn brief and the verdict wording should not suggest a root write.

## 4. Functional failures

A functional failure is a required capability that did not work in the live path.

| ID | Severity | Finding | Evidence | Reproduction | Layer |
|---|---|---|---|---|---|
| F1 | High | The default `opencode-go:deepseek-v4.1-flash` role model cannot replay reasoning across a multi-turn browser loop | `gateway-summary-reasoning-400.json`; the E2 run log | Run E2 with the default `LLM_JOB_ORCHESTRATOR`. The model completes about five browser calls and then returns HTTP 400: the reasoning content in thinking mode must be passed back. The gateway yields no verdict. | App LLM reasoning replay and provider |
| F2 | High | A long idle gap releases the Steel session even when the start requested no inactivity release | `gateway-summary-session-expired.json`; `pod-summary.json`; `e6-summary.json` | Prepare a session. Wait 10 to 20 minutes without CDP input. Poll `sessions`; the name is absent. The E3 pod saw the catalogue empty at 15:14:57 and 15:16:26 UTC. | Steel runtime and CLI |
| F3 | Medium | The E3 pod's final verdict is `technical-infeasibility` after a strong lap-1 negative | `pod-summary.json`; `pod-result.json` interpretations | Run E3 with the current spec. Lap 1 reports both cookies httpOnly, `document.cookie` empty, and the control cookie working. The triager mints a v1 endpoint sweep. The session expires before lap 2. The final verdict is `unsuccessful` / `technical-infeasibility` / `clean: false`. | Pod runner and session budget |
| F4 | Medium | A raw `alert()` blocks the page and the CLI has no dialog command | E1 operator matrix | Run `steel browser eval "alert(document.cookie)" --session <name> --json`. It returns code 124 after 20 seconds. The next command times out at 30 seconds. `steel browser stop` recovers it in 556 ms. | CLI and runtime |
| F5 | High | The CDP target can reset while the session catalogue still reports the session live | `gateway-summary.json` rationale; `gateway-trace.json` `tab list` and `tab new` commands | Run a gateway turn. `navigate` and `eval` fail with `Session with given id not found`. The tab is at `about:blank`; the catalogue still lists the session. `steel browser tab new` creates a fresh target and preserves the httpOnly cookies. | Steel runtime, CLI, and skill |
| F6 | Medium | `opencode-go:qwen3.8-max` rejects the pod's security-test prompt with a content filter | E3 first-run log; the later `glm-5.3` run produced `pod-summary.json` | Run E3 with `LLM_POD_RUNNER=opencode-go:qwen3.8-max`. The provider returns `data_inspection_failed` before the first tool call. The pod degrades to `technical-infeasibility`. | Model and provider selection |
| F7 | Medium | The gateway actor posts a duplicate no-decision reply after a successful verdict | E2 run log; `gateway-summary.json`; the actor's `on_turn_degraded` path | Run the gateway with Qwen. After the verdict is delivered, the actor logs that the connection is closed and posts a no-decision reply. The controller receives the real verdict first and drains the stale reply. | Actor lifecycle |
| F8 | High | A fresh state session inherited the runtime's target cookies that the caller did not provide | `e5-summary.json`; `e5-state.json` | Call `create_session` with only `ph_e2e_state`. The captured context returns `JSESSIONID` and `rememberMe` in addition to the test cookie. The test still passes because it only asserts the test cookie. | Steel runtime session isolation |

F1 detail.
The app logs a reasoning-gap warning on every default-model response.
The warning says the profile expects `reasoning_content` but the response carries no matching value.
The first few tool calls work.
The next model call fails because the assistant history lacks the reasoning field the provider requires.
The successful E2 run used a config-layer model override.
The default role model remains a production blocker.

F2 detail.
The start record reported `remainingMs` near 86,400,000.
The flag help says `--inactivity-timeout 0` disables the idle release.
The observed sessions were released after 10 to 20 minutes without CDP input.
The exact idle threshold was not measured.
The impact is that a prepared session is not durable across a long model turn or a multi-lap pod.

F3 detail.
The lap-1 negative result is strong.
The pod read the cookie inventory, the JavaScript cookie string, a JavaScript control cookie, and two authenticated API responses.
The result is `symptom-absent-partial-coverage`.
The triager then mints a v1 sweep to cover more endpoints.
The session expires before the sweep.
The final verdict therefore records the structural blocker, not the confirmed httpOnly condition.
The httpOnly property itself is confirmed.

F5 detail.
The gateway agent recovered the target with `tab new`.
The cookies survived.
The skill's failure branch has no case for this target reset.
Without the recovery, the agent would have misread the target as a dead session.

F8 detail.
The E5 state projection kept the four durable fields as designed.
The problem is the input context, not the projection.
A caller that supplies a test cookie receives the runtime's existing target cookies as well.
This breaks the R3 claim that a fresh session is a fresh browser context.
It also means a captured state file can carry cookies the caller did not own.
The local evidence file was redacted after the run.

## 5. Quality defects

A quality defect is a result the agent or the harness reported with wrong, incomplete, or misleading evidence.

| ID | Severity | Finding | Evidence | Reproduction | Layer |
|---|---|---|---|---|---|
| Q1 | Medium | The broad E4 prompt ran 80 steps without a final answer | `random-summary-recursion.json`; the successful focused run in `random-summary.json` | Run E4 with the full route list as the task and recursion limit 80. The graph raises `GraphRecursionError` and returns no final report. A focused 16-tool task completes in 13 calls. | Prompt and harness |
| Q2 | Low | The pod export records the raw observation command as empty | `pod-result.json` raw observations; `pod-summary.json` commands list | Run E3 and inspect `evidence.raw_observations[*].command`. The stdout contains the echoed command, but the command field is empty. | Pod evidence |
| Q3 | Low | The E2 loop state reports `FINISH` with `grounded: false`, `attempt_count: 0`, and null phase fields | `gateway-summary.json` `loop_state`; `gateway-trace.json` tool calls | Run E2 and read `actor.loop_state`. The trace shows 22 probes, but the phase-specific fields are null. | Authn loop observability |
| Q4 | Low | The E4 final report undercounts its own tool calls | `random-summary.json` `agent_tool_calls: 13`; the final preview says "10 of 16 tool calls" | Read the final agent report and compare it with the trace count. | Agent self-report |
| Q5 | Low | The E2 rationale is very long and repeats operator details | `gateway-verdict.json` rationale; no secret present | Read the verdict rationale. It is about 5 KB and includes the session name and stray-session history. | Agent output style |
| Q6 | Medium | The pod experiment log can contain raw cookie values | `pod-result.json` raw observations; the redacted export; the pod memory path `/srv/data/steel-e2e-395/hunting/test-executor-pod` | Run E3 and inspect the raw experiment log before redaction. The cookie inventory carries values. The export controller redacts the known session values, but the memory log is sensitive. | Pod evidence handling |
| Q7 | Low | The E2 gateway did not write the procedure body as the brief suggested | `gateway-summary.json` `skill.modified: false`; the two `record_skill_lesson` calls; the rationale | Run the gateway. The model follows the skill's usage protocol and records lessons instead of calling `write_skill`. The brief and the skill disagree. | Prompt and skill |

Q1 is the main agent-quality finding.
The broad prompt encouraged exhaustive exploration but gave no convergence rule.
The focused follow-up used a 16-call budget and a clear stop condition.
The second approach is the recommended pattern for this class of agent.

Q6 is a secret-handling constraint, not a report leak.
The local evidence export is redacted.
The pod memory log remains on the agent host and must be treated as sensitive.
The state file in the evidence bundle was sanitized after the run.

## 6. Harness and evidence limitations

The harness findings do not describe product defects.
They limit what the evidence proves and they explain some first-attempt failures.

| ID | Finding | Resolution or status |
|---|---|---|
| H1 | A raw `AsyncPostgresSaver` without `serde=checkpoint_serde()` blocked `GatewayVerdict` deserialization | The controller now passes the app serde; the production pooled saver already uses it |
| H2 | The E3 pod ran outside `module_context("hunting")`, so the fallback in-memory saver logged a blocked `TriagerDecision` | The production entry point opens the module context; the harness should do the same on the next run |
| H3 | The first E4 run omitted the `thread_id` required by `InMemorySaver` | Fixed in the controller |
| H4 | The pod import needed `/srv` on `PYTHONPATH` for `lightrag` | Added to the pod controller path |
| H5 | The E1 primitive matrix JSONL was not persisted | The matrix results are recorded in this report; the next run must persist the JSONL |
| H6 | The E5.2 live provider crawl was not run | The state module is exercised live; the provider code path is reviewed only |
| H7 | The E3 Qwen content-filter attempt was overwritten by the GLM re-run | The error is in the run log; the final GLM evidence is persisted |

H2 needs care in the report reading.
The `TriagerDecision` warning did not by itself cause the E3 final verdict.
The final verdict is explained by the session expiry between laps.
The warning is still a test-fidelity gap because the production hunting entry sets the module context.

## 7. Scenario details

### E1. Primitive matrix

The matrix passed start, navigate, snapshot, ref fill and click, form submit, arbitrary JavaScript values and errors, local and session storage, back, forward, reload, `get count`, cookie read, and stop.
The target title was `白卷 - White Jotter`.
The cookie read returned the names and flags, not the values.
Both `JSESSIONID` and `rememberMe` were `httpOnly: true`.
`document.cookie` was empty.

The matrix found four tool gaps.
`wait --load-state` failed with `Timeout waiting for Page.loadEventFired`.
`wait --selector` and `wait --text` passed.
A raw `alert()` blocked the page; `steel browser stop` recovered it.
`get text` required a selector.
`cookies` had no `list` subcommand.

The duplicate-start guard worked.
A second `start` on `wj-probe-e2e` returned `refused:session-taken: wj-probe-e2e is already used` and returncode 2.
The probe session was stopped.
The catalogue was clean.

The E1 raw JSONL was not persisted.
This is evidence limitation H5.
The results above are the operator matrix from the live run.

### E2. Auth gateway

The project store was seeded with the browser-only overlay and the session-only account.
The account had a fresh `JSESSIONID` and `rememberMe` snapshot, no credentials, and no roles.
The project authn skill loaded with the live-session name and the history-route note.
The live session `wj-gateway-e2e` was authenticated before the turn.
The prep evidence showed `/api/authentication` 200, `/api/admin/user` 200 with `admin` and `sysAdmin`, `document.cookie` empty, both cookies httpOnly, and no password field in the admin response.

The successful turn used `opencode-go:qwen3.8-max`.
It loaded the authn skill.
It read the overview and the accounts.
It reused the live session.
It navigated the dashboard, read the authentication marker, read the admin user envelope, and wrote the status leaf.
It wrote `accounts.admin-sessiononly-e2e.status = valid`.
The verdict was authenticated, named the account, and released `browser_only`.
The loop reached `FINISH`.
The skill file was unchanged.
The session stayed live.

The default-model turn is finding F1.
The dead-session control is the first E2 run.
That run found the catalogue empty, wrote `status: not_valid`, and returned `failed`.
It did not attempt request replay.
That is the correct E2.4 degradation.

The successful turn also exposed three operational issues.
A typo created a stray session `wj1618c524`; the agent stopped it (C5).
The CDP target reset and `tab new` recovered it (F5).
The actor posted a duplicate no-decision reply after the verdict (F7).

### E3. Pod

The pod spec named the target, listed the safe cookie-visibility symptoms, carried `skills: ["steel-browser"]`, and used the live session.
The pod runner used the Kali `execute_command` surface and the `steel-browser` skill.
The spec passed the INIT gate.

Lap 1 ran the cookie inventory and the JavaScript cookie reads.
It found both cookies httpOnly.
It found `document.cookie` empty.
It set and cleared a JavaScript control cookie to prove the read channel worked.
It fetched `/api/authentication` and `/api/admin/user` with the session, and both returned 200.
The lap-1 classification was `symptom-absent-partial-coverage`.
The triager minted a v1 endpoint sweep.

The Steel session expired before lap 2.
The catalogue was empty at 15:14:57 and 15:16:26 UTC.
The pod returned `unsuccessful` / `technical-infeasibility` / `clean: false`.
The httpOnly property itself is confirmed by the lap-1 evidence.
The final verdict is a session-budget failure, not an httpOnly failure.
This is finding F3.

The first E3 attempt used `opencode-go:qwen3.8-max`.
The provider rejected the pod prompt with `data_inspection_failed` before the first tool call.
The GLM-5.3 re-run completed the browser work.
The content filter is finding F6.
The pod export is `pod-result.json`; the summary is `pod-summary.json`.
The pod memory path is `/srv/data/steel-e2e-395/hunting/test-executor-pod/cookie_httponly_exposure/`.

### E4. Broad navigation

The deterministic sweep reached all 11 declared routes.
The root and `/home` redirected to `/index`.
`/login` under the authenticated session rendered the admin shell.
`/register` rendered the registration form.
`/jotter/article` without an id rendered the shell; the agent clicked the article link and reached `/jotter/article?id=3`.

The random agent used `qwen3.8-max`.
The first attempt failed on the missing `thread_id` (H3).
The second attempt used the broad prompt and hit the recursion limit (Q1).
The third attempt used a focused 16-call task and completed in 13 browser calls.

The agent exercised:

- The admin user, content, and system menu entries.
- The user table status sort and the row materialization.
- The article link and the article body.
- The library category filter and the search box.
- A non-destructive editor title and body.

It did not publish or save the draft.
It did not log out.
It stopped the session.
The final report was 3206 characters.
The final report undercounts its tool calls (Q4).
The route sweep is `random-sweep.json`; the final agent run is `random-summary.json` and `random-result.json`.

### E5. State round-trip

The direct state script ran the same sequence as the live test:

1. Create a session with the `ph_e2e_state` cookie.
2. Capture the context.
3. Store it in `e5-state.json`.
4. Release the session.
5. Restore a new session from the state.
6. Capture the restored context.
7. Release the restored session.

The captured and restored fields were `cookies`, `localStorage`, `sessionStorage`, and `indexedDB`.
The test cookie name was present before and after.
The state file was 1686 bytes before redaction.
The test passed.

The fresh session also carried `JSESSIONID` and `rememberMe` from the runtime's existing context.
This is finding F8.
The state file was redacted in the local evidence bundle.

The E5.2 live provider crawl was not run.
The provider state path is `/srv/data/steel-e2e-395/steel-state/admin-sessiononly-e2e.json`.
The provider code uses the same state module for restore and capture.
The live provider path remains a coverage gap (H6).

### E6. Deployment channel

`GET /v1/health` returned 200.
The wrapper start reported `mode: local`, `remainingMs: 86398913`, a connect host of `ws://192.33.91.87:3000`, and a live host of `http://192.33.91.87:3000`.
The target alias returned the title `白卷 - White Jotter`.
The bogus-host negative control returned returncode 1 and no title.
The wrapper UA was `Mozilla/5.0 ... Chrome/155.0.0.0 Safari/537.36`.
The raw CLI UA was `Mozilla/5.0 ... Chrome/142.0.0.0 Safari/537.36`.
Port 9223 was closed on the host.
Both test sessions were stopped and the catalogue was clean.

## 8. Requirement coverage

| Requirement | Result | Evidence and notes |
|---|---|---|
| R1 local runtime selection | Pass | E6 wrapper start `mode: local`; E2/E3/E4 used the wrapper |
| R2 `steel_exec` guards | Pass | E1 matrix; duplicate-start returncode 2; variadic boundary and version guards |
| R3 named session and durable state | Partial | E5 round-trip pass; F8 shows a fresh session can inherit cookies |
| R4 runtime-agnostic skill | Pass with gaps | Gateway and pod loaded the skill; C1, C3, C4 are skill/CLI gaps |
| R5 Steel-to-target channel | Pass | E6 alias title; bogus-host negative control |
| R6 provider restore and capture | Partial | State module pass; live provider crawl not run; F8 |
| R7 gateway re-attach and verdict | Pass with F1 and F5 | Authenticated verdict with Qwen; default model fails; target reset recovered |
| R8 pod spec and httpOnly check | Partial | Lap-1 httpOnly confirmed; final verdict technical-infeasibility (F3); raw alert hangs (F4) |
| R9 broad navigation | Pass | E4 11 routes, 13 browser calls, session stopped |
| R10 health and runtime record | Pass | E6 health 200; connect and live hosts; port 9223 closed |
| R11 target title and routes | Pass | E6 title; E4 sweep |
| R12 fixed user agent | Pass | Wrapper 155.0.0.0; raw CLI 142.0.0.0 negative control |
| R13 session-only gateway | Pass | E2 authenticated verdict; no credentials in the account |
| R14 alert/document.cookie distinction | Partial | `document.cookie` empty and httpOnly confirmed; raw alert blocks the page |
| R15 full route coverage | Pass | E4 deterministic sweep reached 11/11 routes |
| R16 classified report | Pass | This report separates contract, functional, quality, and harness findings |

## 9. Evidence index

The live evidence is in `eval/steel-e2e-395/evidence/`.
The bundle is redacted.
The E5 state file is sanitized.
The prep start records are host-only for the connect and live URLs.

- `gateway-summary.json`, `gateway-verdict.json`, `gateway-trace.json` - successful E2 turn.
- `gateway-summary-reasoning-400.json` - default-model failure.
- `gateway-summary-session-expired.json` - dead-session control.
- `gateway-prep.json`, `gateway-prep-e2.json` - E2 and E3 session prep.
- `pod-summary.json`, `pod-result.json` - E3 export and experiment interpretations.
- `random-sweep.json` - deterministic route sweep.
- `random-summary.json`, `random-result.json` - successful E4 agent.
- `random-summary-recursion.json`, `random-summary-threadid.json` - E4 failed iterations.
- `e5-summary.json`, `e5-state.json` - state round-trip; state values redacted.
- `e6-summary.json` - health, alias, UA, raw-UA control, port 9223.

The controller scripts are in `eval/steel-e2e-395/`.
The risk analysis is in `docs/design/e2e-steel-session-395-risk-analysis.md`.
The trace-backed factual failure ledger is in `docs/design/e2e-steel-session-395-factual-failures.md`.
The plan and status log are in `docs/design/e2e-steel-session-395-plan.md`.
The E1 primitive matrix has no JSONL; the operator matrix is summarized above.

## 10. Next actions

1. Fix the default-model reasoning replay, or route the gateway role to a model that supports the contract.
2. Re-run E2 with the production default model and the same session-only fixture.
3. Fix the Steel idle-release contract; make `--inactivity-timeout 0` effective or report the granted idle budget.
4. Prepare every live session immediately before its scenario until the idle release is fixed.
5. Fix the fresh-session isolation so a caller's `sessionContext` does not inherit unrelated cookies.
6. Bound the pod's variant sweep to the session budget, and preserve a clean lap-1 `no-symptom-evidence` verdict when the bounded check is complete.
7. Add the CDP target-reset class and the `tab new` recovery to the `steel-browser` skill.
8. Fix the duplicate no-decision reply in the actor lifecycle.
9. Correct the authn skill routes to `/login` and `/register`, and note the authenticated admin-shell behaviour.
10. Document the `wait --load-state` failure, the `get text` selector, the `cookies` no-list surface, and the unknown-session start hazard.
11. Clarify the `write_skill` and `record_skill_lesson` ownership.
12. Update the harness to open `module_context("hunting")` for the pod, pass `checkpoint_serde()` to the raw Postgres saver, and persist the E1 JSONL.
13. Keep the evidence redacted and the pod memory log restricted.

## 11. Conclusion

The browser system works on the live path.
The session-based gateway completed a real authenticated turn.
The pod proved the httpOnly property in its first lap.
The explorer reached the full history-mode route set and exercised the main UI features.
The state round-trip and the deployment channel passed.

The release is not production-ready.
The default role model cannot complete a multi-turn browser loop.
The session idle release defeats long turns and multi-lap pods.
The pod's final verdict loses the strong lap-1 negative.
The fresh state session is not isolated.
The CDP target can reset while the catalogue says the session is live.
The actor can post a duplicate no-decision reply.

These findings are configuration and lifecycle issues, not a failure of the Steel browser path itself.
The evidence bundle is local.
No remote repository was pushed.




