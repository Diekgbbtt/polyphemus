# E2E verification of the session-based Steel browser system (#221, #245, #359, #393, #395) - plan

Status: active.
Date: 2026-10-22.
Owner: autonomous e2e operator.
Scope: live verification of the browser system through three agents and one primitive matrix.

## 1. Sources and scope

The requirement sources are the minted design specs, not the thin issue bodies.
The issue bodies are trackers or evidence records.
The authoritative sources are:

- `docs/design/browser-cli-221-spec.md` and `docs/design/browser-cli-221-decisions.md`.
- `docs/design/steel-local-deployment-359-spec.md` and `docs/design/steel-local-deployment-359-decisions.md`.
- `docs/design/steel-session-only-395-decisions.md` and `docs/design/steel-session-only-impact-map-395.md`.
- `docs/design/steel-session-first-395.md` and `docs/design/steel-session-lifecycle-395-decisions.md`.
- `docs/design/steel-local-deployment-359-assertions.md` and `docs/design/browser-cli-221-assertions.md`.
- `eval/ASSERTIONS.md`, `eval/OPERATOR.md`, and `eval/E2E-SCAFFOLD.md`.
- The white-jotter data dependency at `/root/eval-dd/data/white-jotter`.
- The issue evidence in #393 and the current #395 implementation.

In scope:

- The live Steel API on `dj-viscon` and the white-jotter target on the eval server.
- The session lifecycle and every browser primitive named in the ticket: start, reuse, navigate, click, eval, URL navigation, form submit, and arbitrary JS.
- The recon orchestrator auth gateway with a session-only auth store.
- The pod test executor with a `TestImplementationSpec` for `alert(document.cookie)`.
- A broad-navigation agent that reaches white-jotter routes and features.
- A defect report that separates tool-call contract misalignment, functional failure, and agent quality defects.

Out of scope:

- Changes to the browser system code in this phase.
- Cloud Steel, profile migration, or the retired `steel.profile` surface.
- A full pass@k eval run, hunting verdicts, or issue filing.
- Any push or remote mutation of the repository.

## 2. Environment and boundaries

The runtime is the eval server at `46.224.225.245` (`eval-server-polyphemus`).
The Steel API is at `192.33.91.87:3000` on `dj-viscon-workshop-1`.
The white-jotter target is live behind the eval front at `http://t-1618c524.target/`.
The polymerhus instance is `ph-dd131acc`.
The agent container is `ph-dd131acc-agent-1`.
The Kali exec container is `ph-dd131acc-kali-1`.
The Steel CLI is `0.5.0-preview.6`.
The white-jotter admin credential is `admin` / `123` from the shipped target seed.
The white-jotter `JSESSIONID` is an in-JVM Shiro session and is process-bound.

The environment boundaries are:

- The Steel container on `dj-viscon` must alias `t-1618c524.target` to `46.224.225.245`.
  The current alias covers only `t-1fc05262.target`.
  The alias is the designed channel from the browser host to the eval front.
- The Kali container already aliases `t-1618c524.target` to `172.17.0.1`, the eval host gateway.
  This covers the request path inside the eval instance.
- The running Kali image has the raw CLI at `/opt/localbin/steel`.
  The current wrapper at `kali/steel_wrapper.sh` must be installed as `/opt/localbin/steel`, with the raw binary moved to `/opt/localbin/steel-real`.
  Without the wrapper the skill's no-runtime-flag contract is not testable.
- The running agent image is eight days old and its bind-mounted source is behind the session-only merge.
  The current source and skills are copied to a temporary root inside the agent container.
  The temporary root is used only by the e2e controller.
  The canonical `/opt/polymerhus-dev` worktree and its uncommitted files are not changed.
- The e2e controller runs inside the agent container with `PYTHONPATH` set to the temporary source.
  A second MCP server is started from the current `kali/mcp_server.py` on port 8001.
  The first MCP server on port 8000 is left untouched.
- One named Steel session is owned by one scenario at a time.
  Every scenario has a stop owner.
  A live session is stopped when its assertions are complete.
- Secret values never enter the report.
  Cookie names, counts, and lengths may enter the report.
  Session values, API keys, and passwords do not.
- The white-jotter auth context is copied from the data dependency, not re-authored.
  The browser-only fixture is a deliberate scenario overlay.
  The overlay is recorded so its branch is not mistaken for a target fact.

## 3. Requirements

R1. The browser path selects the local runtime from `STEEL_BROWSER_API_URL`.
The wrapper supplies the runtime mode; the skill and the agent never add a runtime flag.

R2. The `steel_exec` gateway accepts exactly one of a `steel` command or a `.sh`/`.py` script.
It performs the version check, the script-language check, the variadic boundary check, the timeout-ordering check, and the session-collision check.
A refusal is typed and nothing runs.

R3. A named session is the browser unit.
`start` attaches to a live name or creates a new one.
`stop` is owned and the catalogue proves liveness.
A fresh CLI session is a fresh browser context.
The four durable state fields are cookies, localStorage, sessionStorage, and indexedDB.

R4. The `steel-browser` skill is runtime-agnostic.
It teaches refs from a fresh snapshot, the mandatory variadic `--` boundary, bounded reads, no secret output, and a stop owner.
A shell `exec` and the `steel_exec` gateway run the same commands.

R5. The browser on `dj-viscon` reaches the eval target through the eval front.
The synthetic host `t-1618c524.target` resolves to the eval server IP for the Steel container.

R6. The crawl provider restores account state into a fresh session and captures the four durable fields on release.
The CLI cannot restore state; only the provider captures and restores it.

R7. The auth gateway re-attaches to a live session when browser continuity is required.
It never claims that a new CLI session restored state.
It validates before sign-in, asserts the account status in the store, and emits the structured verdict.

R8. The pod runner consumes a `TestImplementationSpec` and carries the `steel-browser` skill.
It can run a shell `steel browser eval` on the target and record the raw observation.
The httpOnly check is a browser-state check, not a UI claim.

R9. A broad-navigation agent can reach the white-jotter SPA routes, click links, fill forms, submit, eval JS, read cookies and storage, and stop its session.

R10. The local Steel API is reachable from the eval server and returns a healthy response.
The API publishes the configured domain and the session websocket URL.

R11. The Steel container reaches the white-jotter target after the alias is added.
The target title and the SPA routes are readable through the browser.

R12. The wrapper fixes the local user agent after a named `browser start`.
The user agent is observable in the session record and in `navigator.userAgent`.

R13. A session-only auth store runs the gateway without credentials.
The gateway re-attaches to the live session and probes the privileged feature.

R14. A pod spec for `alert(document.cookie)` records the eval output.
The test distinguishes an httpOnly session cookie from a script-readable cookie.

R15. Broad navigation reaches all declared routes and triggers the main features.
The coverage is recorded as reached routes, actions, and observed states.

R16. The final report classifies every finding as contract misalignment, functional failure, or quality defect.
Each finding has evidence, a reproduction, and a severity.

## 4. E2E catalogue

The catalogue follows the `/to-assertions` split.
Contract predicates live at the tool and CLI seam.
Walkthrough predicates exercise one full path through a real agent.

### E1. Primitive matrix (contract + live)

E1.1 Session catalogue.
Assertion: `steel browser sessions --json` returns a JSON catalogue, including the foreign idle session.
The call must not create a session.

E1.2 Named session start and user agent.
Assertion: `start --session wj-primitive-e2e` returns a live session, and `navigator.userAgent` equals the wrapper's fixed local user agent.
The session name is unique and owned.

E1.3 Target navigation.
Assertion: `navigate http://t-1618c524.target/` returns success; `get title` equals `白卷 - White Jotter`; `get url` ends at the SPA root.

E1.4 Snapshot and refs.
Assertion: `snapshot -i` returns an accessibility tree with interactive refs.
A ref taken from the snapshot resolves in a following `click` or `get text`.

E1.5 Click and history.
Assertion: a click on a SPA link changes the URL or the visible route.
`back`, `forward`, and `reload` return success and restore the expected page.

E1.6 Arbitrary JS eval.
Assertion: `eval 'document.title'` returns the white-jotter title.
`eval 'location.href'` returns the current URL.
A multi-statement expression follows the inline-JS contract.
The raw result is recorded.

E1.7 Form fill and submit.
Assertion: the login route exposes username and password inputs.
A fill with the variadic `--` boundary changes the input values.
A submit reaches the authenticated state or an application-level login envelope.
The form is not submitted twice without a new observation.

E1.8 Cookies and storage.
Assertion: `cookies` returns names and counts without values.
`cookies set` with `--http-only` sets a named httpOnly cookie.
`storage local` and `storage session` return bounded reads.
`document.cookie` does not expose the httpOnly cookie.

E1.9 Tabs.
Assertion: `tab new`, `tab list`, `tab switch`, and `tab close` return success.
The active-tab read matches the switch.

E1.10 Variadic boundary and typed refusal.
Assertion: a `fill` with a missing top-level `--` is refused by `steel_exec` with `refused:variadic-boundary`.
A corrected command with the boundary runs.
A command that is not a `steel` command is refused with `refused:not-steel-command`.
An ambiguous command/script pair is refused with `refused:ambiguous-input`.

E1.11 Script mode and timeout ordering.
Assertion: a `.sh` script with a bounded `eval` runs through `steel_exec(script, script_lang="sh")`.
A wait whose timeout equals or exceeds the tool timeout is refused with `refused:timeout-ordering`.
The script prints only bounded results.

E1.12 Stop owner and catalogue clean.
Assertion: the scenario stops its named session.
The post-stop catalogue does not contain the owned name.
A foreign session is not stopped by `stop --all`.

### E2. Recon-orchestrator auth gateway (walkthrough)

E2.1 Session-only store.
The project `steel-e2e-395` carries an auth overview with a browser-only fixture and one account with a fresh JSESSIONID token and snapshot.
The account has no credentials.
The project authn skill names the live session `wj-gateway-e2e` and the privileged probe `/api/admin/user`.
The live session is created and authenticated before the gateway runs.

E2.2 Gateway run.
The production `ReconOrchestratorActor.run_gateway` runs with the current source, the real role model, the real auth store, the real skill store, and the real Kali MCP tools.

E2.3 Gateway assertions.
The turn loads the `authn` skill.
The turn reads the overview and the accounts.
The turn surveys the live sessions.
The turn reuses `wj-gateway-e2e` and does not start a new session.
The turn navigates or evaluates against the target and reads `/api/admin/user`.
The admin evidence is present (`admin`, `sysAdmin`).
The turn writes `accounts.<name>.status: valid`.
The verdict is `authenticated`, names the account, and releases `browser_only`.
The rationale contains no cookie value or credential.

E2.4 Gateway degradation.
If the live session is dead, the turn asserts `not_valid` and either re-runs the browser sign-in procedure or returns `failed`.
A silent anonymous verdict is a failure.

### E3. Pod test executor (walkthrough)

E3.1 Valid spec.
The `TestImplementationSpec` names `http://t-1618c524.target/`, carries `skills: ["steel-browser"]`, and asks for `alert(document.cookie)` or `document.cookie` on the authenticated page.
The verification symptom is that the raw eval result does not contain the JSESSIONID value.
The spec passes `validate_spec`.

E3.2 Real pod run.
`arun_pod` runs with the real `default_exec_fn`, the real role model, a `PodMemoryStore` under the project, and a unique spec id.
The pod runner carries the `steel-browser` skill.

E3.3 Pod assertions.
The runner issues a `steel browser` command through the Kali exec surface.
The command navigates to the target or reuses the live session.
The command evaluates `document.cookie` or the requested alert expression.
The raw stdout is recorded in the experiment log.
The JSESSIONID is absent from the script-readable cookie string.
The pod stops or releases what it owns.
The export is a valid `PodExport` with a terminal reason and evidence.

### E4. Broad-navigation agent (walkthrough)

E4.1 Agent run.
A real session agent runs with the `steel-browser` skill and the `steel_exec` and `execute_command` tools.
The prompt asks for broad white-jotter exploration and a named session `wj-random-e2e`.
The agent has a bounded turn count.

E4.2 Coverage assertions.
The agent starts or surveys one session.
The agent navigates to the root and the SPA routes: `#/`, `#/login`, `#/register`, `#/jotter`, `#/library`, and the reachable `#/admin/**` routes.
The agent takes a snapshot and clicks at least one discovered link or control.
The agent fills and submits at least one form.
The agent evaluates at least one arbitrary JS expression.
The agent reads cookie names or storage names without values.
The agent uses back, forward, or reload at least once.
The agent stops its session.
The trace shows no repeated defective call without a changed input.

E4.3 Deterministic route sweep.
A scripted sweep enumerates the SPA links and navigates each reachable route.
The sweep is the coverage floor when the model misses a route.
The sweep records status, title, URL, and a bounded text slice per route.

### E5. Provider state and local runtime (contract + live)

E5.1 Live state round-trip.
Run `tests/e2e/test_steel_session_state_live.py` against `STEEL_BROWSER_API_URL=http://192.33.91.87:3000/v1`.
The test captures, stores, releases, and restores the four durable fields.
The assertion is a cookie name/value round-trip and a live session after restore.

E5.2 Provider path.
The current `steel_provider` starts a session through the local runtime, restores an account state, navigates the target, captures the state, and releases the session.
The state file lives under `data/<project>/steel-state/`.
The provider never uses `steel.profile`.

### E6. Deployment and channel (contract + live)

E6.1 Health and domain.
`GET http://192.33.91.87:3000/v1/health` returns 200.
The session record reports the configured domain and a websocket URL.
Port 9223 is not published on the host.

E6.2 Target channel.
From the Kali container, a Steel session navigates `http://t-1618c524.target/` and reads the white-jotter title.
The same navigation fails or is unreachable without the alias, which is the negative control.

E6.3 Fixed user agent.
The wrapper's `browser start` sets the fixed local user agent.
`eval 'navigator.userAgent'` matches the wrapper value.
A session created without the wrapper is the negative control.

## 5. Harness and controllers

The harness is a small Python package under `tests/e2e/steel_runtime/`.
It is not a unit-tier test.
It is a live walkthrough harness with explicit gates.

The controller files are:

- `config.py` - the runtime endpoints, the project id, the session names, the timeouts, and the evidence root.
- `steel.py` - a thin client for the `steel_exec` and `execute_command` MCP tools, plus a bounded command runner.
- `trace.py` - tool-call trace capture from the checkpointer and the pod memory store.
- `seed.py` - project creation, auth-store seeding through `AuthStore.write`, and the browser-only authn skill.
- `primitive_matrix.py` - E1, E5, and E6.
- `auth_gateway.py` - E2.
- `pod_executor.py` - E3.
- `random_agent.py` - E4.
- `report.py` - evidence collection and the defect table.

The harness runs inside `ph-dd131acc-agent-1`.
The controller source is copied to `/tmp/polymerhus-e2e/src`.
The skills are copied to `/tmp/polymerhus-e2e/skills`.
The project data is seeded under `/srv/data/steel-e2e-395`.
The evidence is written to `/tmp/polymerhus-e2e/evidence` and copied back to the repo.

The MCP choice is:

- The current `kali/mcp_server.py` runs on port 8001 inside the Kali container.
- The controller sets `KALI_MCP_URL=http://kali:8001/mcp`.
- The current `kali/steel_wrapper.sh` is installed at `/opt/localbin/steel`.
- The raw CLI is moved to `/opt/localbin/steel-real`.
- The existing MCP server on port 8000 is not changed.

The trace capture is:

- The gateway's `run_session_agent` writes its messages to the Postgres checkpointer.
  The harness reads the checkpoint state for the actor thread.
- The pod's `PodMemoryStore` writes the experiment log.
  The harness reads the YAML slices.
- The random agent is invoked through `create_agent` and the final `messages` list is printed.
- Every controller call also writes a JSONL line with the tool name, arguments, result summary, duration, and return code.
  Argument values are redacted when they are secret-shaped.

## 6. Execution sequence and feedback loops

Phase 0. Preconditions.

- Verify the eval server, the Steel API, and the white-jotter front.
- Add the white-jotter alias to the Steel container on `dj-viscon`.
- Restart the Steel API container only after the alias is persisted in its compose file.
- Install the current wrapper in the Kali container.
- Mint a fresh white-jotter JSESSIONID and verify the admin feature through the front.
- Copy the current source, skills, and MCP server to the temporary root.
- Verify the current package imports and the two MCP tools are reachable.

Phase 1. Primitive matrix.

- Run E1, E5, and E6.
- Record every command, result, and timing.
- Stop the owned sessions.
- Fix only environment-level defects.
- Record code-level defects and continue.

Phase 2. Auth gateway.

- Seed the session-only store and the browser-only skill.
- Start and authenticate `wj-gateway-e2e`.
- Run E2.
- Read the checkpoint trace and the auth store after the turn.
- Stop the session.
- If the model fails on a contract, rerun once with the same fixture and a corrective note.
- Record the first and second traces.

Phase 3. Pod.

- Write the valid spec.
- Run E3 with the real exec surface and the real model.
- Read the experiment log and the export.
- Stop any pod-owned session.
- Record the command trace.

Phase 4. Broad navigation.

- Run E4 with the real crawler role.
- Run the deterministic route sweep.
- Stop `wj-random-e2e`.
- Record the route coverage and the tool-call trace.

Phase 5. Report.

- Merge the evidence.
- Classify findings by the taxonomy in section 7.
- Separate contract, functional, and quality findings.
- Include severity, reproduction, evidence path, and the responsible layer.

The feedback loop is:

1. Run the smallest live check that can falsify the next assumption.
2. Record the raw evidence before interpreting it.
3. Change only the environment when the failure is an environment precondition.
4. Do not edit the browser system code to make a test pass.
5. Retry a transient transport failure once.
6. Escalate a repeated refusal or a wrong-schema result immediately.
7. Keep the plan and the status log current.

## 7. Defect taxonomy and report

Contract misalignment:

- The agent calls a tool with a shape the tool does not accept.
- The agent uses a retired runtime flag, profile field, or cloud-only command.
- The agent omits the variadic `--` boundary or puts it after the value.
- The agent uses `fill` or another variadic verb without the gateway boundary.
- The agent treats a typed refusal as a transient and repeats it.
- The agent starts a new session when the procedure says to reuse a live one.
- The tool returns a schema the agent cannot parse.
- The skill and the CLI disagree on a flag, a default, or a result shape.

Functional failure:

- The browser cannot reach the target.
- A primitive returns a transport or CDP error.
- A cookie or storage read is empty when the page sets state.
- The form submit does not navigate or change the app state.
- The session state does not round-trip.
- The session cannot be stopped or the catalogue is stale.
- The wrapper does not set the fixed user agent.
- The API is unhealthy or the websocket domain is wrong.

Quality defect:

- The agent misreads the skill, the store, or the target surface.
- The agent repeats a defective call without changing one variable.
- The agent claims a success the evidence does not support.
- The agent ignores the auth branch or the account selection.
- The agent leaks a secret value into its rationale or output.
- The agent leaves a session without a stop owner.
- The agent uses a blind resubmit or a silent anonymous fallback.
- The agent chooses a route sweep that misses declared routes.

Severity:

- Blocker: no live browser path at all.
- High: a required primitive or a required agent scenario cannot complete.
- Medium: a scenario completes with a wrong branch, wrong evidence, or a repeated defect.
- Low: a documentation mismatch or a cosmetic result-shape issue.

## 8. Assumptions and risks

The white-jotter target is request-replayable by design.
The browser-only fixture is an overlay to force the Steel path.
The overlay is not a claim that the target needs a browser.
The real request path is still covered by the auth context and the request primitives.

The white-jotter JSESSIONID is process-bound and short-lived.
A fresh session is minted immediately before E2 and E3.

The live Steel runtime has a single idle session from 2026-10-20.
The stale session is released at the start of Phase 0 if it blocks a new session.
A foreign session is never stopped by name or by `stop --all`.

The real role models may be slow or rate-limited.
Each scenario has a bounded turn count and a wall-clock timeout.
A provider failure is recorded as a provider condition, not a browser failure.

The current source is not pushed.
The temporary copy inside the agent container is the delivery channel.
The canonical eval worktree is not edited.

The white-jotter login credential is operator data.
It is not copied into the report.
The cookie values are not copied into the report.

## 9. Status log

| step | state | evidence |
|---|---|---|
| Plan written | complete | this file |
| Environment inventory | complete | eval server, Steel API, white-jotter, agent, Kali |
| Steel alias | complete | E6 alias check in `eval/steel-e2e-395/evidence/e6-summary.json` |
| Wrapper install | complete | E6 wrapper UA `155.0.0.0`; raw CLI UA `142.0.0.0` |
| Fresh JSESSIONID | complete | seed and prep evidence; no value stored |
| Source delivery | complete | agent `/tmp/polymerhus-e2e`; no canonical worktree change |
| E1 primitive matrix | complete with evidence gap | operator matrix; the raw JSONL was not persisted |
| E2 auth gateway | complete with model override | `gateway-summary.json`; default model failure in `gateway-summary-reasoning-400.json`; dead-session control in `gateway-summary-session-expired.json` |
| E3 pod | partial | `pod-summary.json` and `pod-result.json`; lap-1 httpOnly pass, final `technical-infeasibility` after session expiry |
| E4 broad navigation | complete | `random-sweep.json`, `random-summary.json`, `random-result.json`; two earlier iterations recorded |
| E5 provider state | partial | `e5-summary.json`; live state round-trip pass, provider crawl not run |
| E6 deployment channel | complete | `e6-summary.json`; health, alias, negative alias, fixed UA, raw UA, port 9223 |
| Final report | complete | `docs/design/e2e-steel-session-395-report.md` |

Known findings at close:

- The production default `opencode-go:deepseek-v4.1-flash` role model fails a multi-turn browser loop with the reasoning-content 400.
- The Steel runtime releases idle sessions even when the start requested `--inactivity-timeout 0`.
- The pod's final E3 verdict is `technical-infeasibility` because the session expired between its lap-1 negative result and its own v1 sweep.
- The gateway actor can post a duplicate no-decision reply after the real verdict.
- The CDP target can reset while the catalogue reports the session live; `steel browser tab new` recovers it.
- The shipped authn skill uses `/#/login` and `/#/register`; the target uses history-mode `/login` and `/register`.
- The report classifies every finding and cites its evidence in `docs/design/e2e-steel-session-395-report.md`.
