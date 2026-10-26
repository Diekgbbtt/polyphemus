# Trace-backed factual failure ledger - session-based Steel browser system (#395 follow-up)

Status: investigation complete.
Date: 2026-10-22.
Scope: factual failures observed in the saved traces, not risk projections.
Sources: `eval/steel-e2e-395/evidence/` and the current source tree.
No code was changed.
No remote repository was pushed.

## 1. Correction to the previous risk analysis

The previous document was a risk analysis.
It rated possible futures, so it grouped operational and eval-harness issues with runtime defects.
That framing was too broad for the question of what actually failed at runtime.

The trace-backed result is narrower.
Four failures are run-fatal in the observed runs:

- The default model's reasoning-content 400.
- The CDP target reset that broke the live session's page binding.
- The missing or expired session that left the trial with no browser.
- The `alert` freeze that blocked the browser until the session was stopped.

The rest are trial-degrading, recoverable, or eval/reporting errors.
Most of their root causes are in the eval system or operational context, as the user noted.

This ledger uses four classes:

- Run-fatal: the scenario or trial cannot produce a result without a restart or recovery.
- Trial-degrading: the run completes, but the verdict, state, or evidence is wrong or incomplete.
- Recoverable: a tool call fails, and the agent retries or adapts within the run.
- Reporting-only: the runtime is fine, but the summary, metric, or trace is wrong.

## 2. Trace inventory and coordinates

| Artifact | Content | Coordinates used here |
|---|---|---|
| `gateway-trace.json` | Successful E2 gateway checkpoint, 49 messages | Message indices 0 to 48 |
| `gateway-trace-session-expired.json` | Dead-session control, 17 messages | Message index 5, `sessions` empty |
| `gateway-trace-reasoning-400.json` | Default-model run, 14 messages | Last tool call, then the 400 outside the checkpoint |
| `gateway-summary.json` | Successful E2 summary | `tools`, `loop_state`, `skill` |
| `gateway-summary-reasoning-400.json` | Default-model summary | `verdict: null`, `loop_phase`, `tools` |
| `gateway-summary-session-expired.json` | Dead-session summary | `verdict`, `account_after`, `status_write_ok` |
| `pod-result.json` | E3 export, 10 raw observations | Observation indices 0 to 9 |
| `pod-summary.json` | E3 summary | `verdict`, `terminal_reason`, `clean`, `steel_commands` |
| `random-result.json` | E4 agent messages, 28 entries | Agent tool calls and page results |
| `random-summary.json` | E4 success summary | `agent_tool_calls`, `agent_steel_commands` |
| `random-summary-threadid.json` | E4 failed attempt | `ValueError` traceback |
| `random-summary-recursion.json` | E4 failed attempt | `GraphRecursionError` traceback |
| `e5-summary.json` | State round-trip | Captured and restored cookie names |
| `e5-state.json` | Redacted state file | Cookie names only in the local copy |
| `e6-summary.json` | Deployment checks | Health, alias, UA, port |

The E1 primitive matrix has no raw JSONL.
Its alert and wait results are operator-recorded in the main report.
They are included here with that limitation marked.

## 3. Failure ledger

| ID | Failed action | Trace fact | Execution effect | Class | Layer |
|---|---|---|---|---|---|
| FF-01 | Default thinking model fails the reasoning contract | `gateway-summary-reasoning-400.json`: `verdict: null`, 5 `steel_exec` calls; the next model call returns HTTP 400 | No gateway verdict; pipeline fail-open; account status unset | Run-fatal | Product/model integration |
| FF-02 | CDP target binding is stale while the session is live | `gateway-trace.json` msg 15-16: `Runtime.evaluate` returns `Session with given id not found`; msg 17 lists the session live; msg 21-26 show `about:blank`; msg 30-31 `tab new` recovers | The browser action fails; `snapshot` and `content` return empty success; the agent spends about 15 calls on recovery | Run-fatal without recovery | Steel CLI/runtime plus app guard |
| FF-03 | Session is absent or expired at trial start or between laps | `gateway-trace-session-expired.json` msg 5: `sessions` is `{"data":[],"success":true}`; `pod-result.json` obs 7-9: sessions empty at 15:14:57 and 15:16:26 | The gateway fails closed; the pod runs out of browser and returns `technical-infeasibility` | Run-fatal | Eval/operational session lifecycle |
| FF-04 | A modal dialog blocks the page | E1 matrix: `alert(document.cookie)` returns 124 after 20s; the next command times out at 30s; `stop` recovers in 556ms | The session is stuck until stopped; all later browser actions fail | Run-fatal until stop | Steel CLI/runtime |
| FF-05 | A mistyped session name mounts a stray session | `gateway-trace.json` msg 13-14: `eval --session wj1618c524` returns `{"data":"","success":true}`; msg 17 lists `wj1618c524` live; msg 18-19 stops it | The command succeeds against the wrong session; the result is empty; a stray session exists | Recoverable, but trial-degrading | Eval tool contract plus model |
| FF-06 | `get text` is called without a selector; `get text body` has a different shape | `pod-result.json` obs 2: missing `<SELECTOR>` plus a Python `KeyError`; obs 3: `data` is a dict with `text`, and `t[:300]` raises `KeyError`; both observations have `returncode: 0` | The probe fails; the shell pipeline masks the exit code; the pod can treat the observation as clean | Recoverable for the model; trial-degrading for the pod | Eval tool contract plus pod clean logic |
| FF-07 | The pod verdict is taken from the last lap | `pod-result.json` interpretations: lap 1 is `symptom-absent-partial-coverage`; lap 2 is `structural-blocker-session-expired`; `pod-summary.json` is `technical-infeasibility`, `clean: false` | The confirmed httpOnly negative is buried behind a structural blocker | Trial-degrading | Product pod verdict |
| FF-08 | A fresh state session inherits foreign cookies | `e5-summary.json`: `captured_cookie_names` and `restored_cookie_names` include `JSESSIONID` and `rememberMe`; only `ph_e2e_state` was supplied; `ok: true` | The test passes, but the session is not isolated; the state file carries foreign cookies | Trial-degrading | Steel API state mount plus eval assertion |
| FF-09 | `cookies list` is an invalid CLI shape | `gateway-trace.json` msg 27-28: `error: unrecognized subcommand 'list'`, returncode 2; msg 31-32 shows `cookies` supports only `set`, `clear`, `help` | The call fails; the model reads help | Recoverable | Eval tool contract |
| FF-10 | The E4 harness loses the first two attempts | `random-summary-threadid.json`: `ValueError: Checkpointer requires ... thread_id`; `random-summary-recursion.json`: `GraphRecursionError` at 80 steps; `random-summary.json`: success with 13 calls | The first two E4 attempts produce no agent result | Eval-run-fatal | Eval harness |
| FF-11 | The dead-session summary reports a false status metric | `gateway-summary-session-expired.json`: `account_after.status` is `not_valid`; `status_write_ok` is `false` | The control is correct, but the summary marks the write wrong | Reporting-only | Eval harness |
| FF-12 | The E2 loop record under-reports; E4 command extraction is empty; E1 JSONL is missing; the pod serde warning is unhandled | `gateway-summary.json`: `loop_state.probe_count` 22, `grounded: false`, `attempt_count: 0`, phase fields null; `random-summary.json`: 13 calls, commands all empty; `pod-result` warning `TriagerDecision` blocked; E1 has no JSONL | The verdict can be right while the audit trail is wrong | Reporting-only | Eval harness |

## 4. Run-fatal failures

### FF-01. Default thinking model fails the reasoning contract

Trace fact.
The run used `opencode-go:deepseek-v4.1-flash`.
The trace messages show five `steel_exec` calls.
The summary reports `verdict: null` and `loop_phase: VALIDATION`.
The subsequent model call returned HTTP 400.
The error said the `reasoning_content` in thinking mode must be passed back.
The trace responses carried no reasoning field.
The `gateway-summary-reasoning-400.json` `trace.messages` is 14; the 400 is outside the checkpoint.

Why it is run-fatal.
The gateway cannot emit a verdict.
The pipeline fail-open then runs the phases unauthenticated.
That is a real runtime failure, not an eval-only artifact.
The E2 success used a model override, so the production default remains unverified.

Source to bug.
`src/polymerhus/app/llm/reasoning.py` lines 173-207 and 438-465: the parser logs a gap and returns no replay when the response has no reasoning field.
`src/polymerhus/app/llm/transient.py` lines 62-72: `reasoning_content` is a contract marker, so the 400 is not transient.
`src/polymerhus/app/llm/actor.py` lines 326-363: a non-retryable contract error breaks before the fallback branch.
The configured fallback is attempted only after the transient schedule is exhausted.
The provider enforces a conversation-level field that the previous response did not carry.
The app treats the missing field as a benign gap, not a hard precondition.

What is not the bug.
The five browser calls themselves succeeded.
The CDP/session path was healthy in this run.
The failure is model and reasoning-contract handling.

### FF-02. CDP target binding is stale while the session is live

Trace fact.
`gateway-trace.json` message 13 calls `eval` on the mistyped session.
Message 15 calls `eval` on `wj-gateway-e2e`.
Message 16 returns `CDP error (Runtime.evaluate): Session with given id not found`, `success: false`, `returncode: 1`.
Message 17 lists `wj-gateway-e2e` as `live`.
Message 20 returns `CDP error (Page.navigate): Session with given id not found`.
Message 23 returns `snapshot` data `(no interactive elements)` with `success: true`.
Message 25 returns `content` data `<html><head></head><body></body></html>` with `success: true`.
Message 26 returns one tab at `about:blank`.
Message 30 calls `tab new`.
Message 31 returns a new tab.
Messages 33-40 repeat navigation and authentication successfully.

Why it is run-fatal without recovery.
The session record is live, but the page target is gone.
`navigate` and `eval` fail.
`snapshot` and `content` return empty success, so a naive health check can pass.
The browser action cannot reach the target.
The cookie jar survives because only the target is replaced.
`tab new` re-mounts a page in the same browser context.
The agent found this by experimentation.
The `authn` skill had no failure branch for this case.
The two lessons were recorded, but the skill body was not updated.

Source to bug.
The primary defect is in the Steel CLI/runtime target state: the session name resolves to a stale CDP target, while the session record remains live.
The CLI exposes `tab list` and `tab new`, but `navigate`/`eval` do not reconcile the target.
The `snapshot`/`content` success is a page-level success on the blank target, not a session-level failure.
In this repository, `kali/mcp_server.py` `steel_exec` validates only command shape and a live start guard; it does not check target liveness.
The `authn` skill's failure branch covers a missing session, not a live session with a dead target.
`src/polymerhus/app/steel_session_state.py` and `prepare_steel_session.py` do not mount a fresh target or check `tab list` before use.
The exact CLI/API fix belongs upstream; the app-side guard is missing.

### FF-03. Session is absent or expired at trial start or between laps

Trace fact.
`gateway-trace-session-expired.json` message 5 returns `{"data":[],"success":true}`.
The model checks the default, named, and local views and gets the same empty data.
`gateway-summary-session-expired.json` writes `status: not_valid` and returns `failed`.
`pod-result.json` observations 7, 8, and 9 return empty sessions at 15:14:57 and 15:16:26.
The pod's lap 1 had a live session and the httpOnly negative.
Lap 2 had no session.
The pod returned `technical-infeasibility`.

Why it is run-fatal.
The trial has no browser.
The gateway correctly fails closed.
The pod cannot complete its v1 sweep.
The E3 export still contains the lap-1 evidence, but the terminal verdict is not the negative.

Source to bug.
The Steel runtime released the session despite the start request for `--session-timeout 86400000` and `--inactivity-timeout 0`.
The wrapper passes the arguments through.
The `remainingMs` record reports about 24 hours.
The idle release is therefore not the absolute session timeout.
The app has no lease or heartbeat.
The pod budget is iteration and tool-call count, not wall-clock time.
The E3 controller prepared the session once, before the run.
The E2 controller did the same.
The root cause is operational: the session lifetime is not owned by the trial.

### FF-04. A modal dialog blocks the page

Trace fact.
The E1 primitive matrix ran `steel browser eval "alert(document.cookie)"`.
The command returned code 124 after 20 seconds.
The next command timed out at 30 seconds.
`steel browser stop` recovered the session in 556 ms.
The raw JSONL was not saved.

Why it is run-fatal until stop.
The alert blocks the page's JavaScript thread.
The command timeout kills the exec process, not the dialog.
The browser stays blocked.
The next browser command inherits the blocked page.
The session has to be stopped; the state is lost.

Source to bug.
The Steel CLI has no dialog handler.
`kali/mcp_server.py` `steel_exec` has no dialog command and no `Page.handleJavaScriptDialog`.
The skill warns against alert, but a target-triggered dialog can still occur.
The E1 evidence gap means the exact command output is not replayable from a saved trace.

## 5. Trial-degrading failures

### FF-05. A mistyped session name mounts a stray session

Trace fact.
`gateway-trace.json` message 13 calls `steel browser eval "document.body.innerText" --session wj1618c524 --json`.
Message 14 returns `{"data":"","success":true}` with `returncode: 0`.
Message 17 lists two live sessions: `wj-gateway-e2e` and `wj1618c524`.
Message 18 stops the stray session.
Message 19 returns `stoppedSessions: ["wj1618c524"]`.

Why it is a factual error.
The command did not address the operator session.
The CLI created or attached to a new session.
The empty data looks like a valid empty page.
The model initially read it as an empty body, then noticed the session list.
The session was stopped, but the evidence in that turn was against the wrong browser context.
A typo can also stop the wrong session if the recovery command is wrong.

Source to bug.
`kali/mcp_server.py` `_session_name` detects only the `browser start` shape.
`_START_SHAPE` is used to refuse a start on a live name.
A `navigate`, `eval`, `snapshot`, `content`, `cookies`, or `get text` with an unknown `--session` is not checked.
The CLI's `eval` on the unknown name created a session.
The `steel_exec` tool's `session_id` is the workspace, not the browser session.
The browser session is only a CLI flag inside the command string.
The model typed the wrong name and did not verify the catalogue first.
The `authn` skill says to confirm the session, but the model skipped the check for this call.

Class.
Recoverable and trial-degrading.
The stray session is cleaned up, but the command's empty success is false evidence about the target.

### FF-06. `get text` is called without a selector; its output shape is misread

Trace fact.
`pod-result.json` observation 2 executes `steel browser get text --session wj-gateway-e2e --json` without a selector.
The stderr contains `error: the following required arguments were not provided: <SELECTOR>` and a Python `KeyError: slice(None, 300, None)`.
The observation records `returncode: 0`.
Observation 3 executes `steel browser get text --session wj-gateway-e2e --json body`.
The data is a dict with a `text` field of 7,746 characters.
The model's Python code does `t[:300]` and raises `KeyError`.
The observation again records `returncode: 0`.
Observation 4 inspects the shape and handles the `text` field correctly.

Why it is a factual error.
The first call is a malformed tool request; the CLI requires a selector.
The second call uses the right selector but the wrong result-shape assumption.
Both failures are masked by the shell pipeline.
The pod records a zero exit code and the stderr is not used by the clean logic.

Source to bug.
`kali/mcp_server.py` `execute_command` runs a shell string; the pod's `ExecTool` uses it.
The shell command composes multiple commands; the exit status is the last command's, not the failed middle command's.
`src/polymerhus/attack/hunting/pod/graph.py` lines 170-176 `_clean_from_trail` checks `returncode` only.
It does not check `stderr` or the CLI's JSON `success: false`.
The `steel-browser` skill did not make the selector and `data` shape explicit enough for the model.
The model is the direct source of the malformed payload.
The pod clean logic is the product bug that hides it.

Class.
Recoverable for the model because it adapts.
Trial-degrading for the pod because a failed probe can be counted as clean.

### FF-07. The pod verdict is taken from the last lap

Trace fact.
`pod-result.json` interpretations show lap 1 as `symptom-absent-partial-coverage`.
The lap-1 note records both cookies as httpOnly, `document.cookie` empty, and a working control cookie.
The triager minted a v1 sweep.
`pod-result.json` observations 7, 8, and 9 show the session gone.
The lap-2 interpretation is `structural-blocker-session-expired`.
`pod-summary.json` reports `verdict: unsuccessful`, `terminal_reason: technical-infeasibility`, `clean: false`.

Why it is trial-degrading.
The httpOnly negative is confirmed in the export.
The terminal verdict names a structural blocker, not the negative.
The export is evidence, but the verdict is the scalar the parent consumes.
The lap-1 negative is not promoted to the final result.
A downstream consumer can discard a valid security conclusion.

Source to bug.
`src/polymerhus/attack/hunting/pod/graph.py` lines 680-755: the triager consumes the last observation and the last decision.
`graph.py` lines 803-812: the terminal exports the last decision.
`graph.py` lines 170-176: the clean helper is a trail check, not a monotonic verdict.
`src/polymerhus/attack/hunting/pod/pod.py` lines 120-147: the fail-open wrapper maps an exception to `technical-infeasibility`.
The pod budget is `HUNT_POD_MAX_ITERS` and `HUNT_POD_MAX_TOOL_CALLS`, not wall-clock or session lifetime.
`technical-infeasibility` conflates an unimplementable test with an expired environment.
The session expiry itself is operational (FF-03).

Class.
Trial-degrading, not run-fatal.
The trial completes, but the terminal verdict is wrong for the confirmed negative.

### FF-08. A fresh state session inherits foreign cookies

Trace fact.
`e5-summary.json` says the test supplied only `ph_e2e_state`.
The captured cookie names are `JSESSIONID`, `ph_e2e_state`, and `rememberMe`.
The restored names are the same three.
The test reports `ok: true`.
The state file is 1,686 bytes before redaction.
The local state file is sanitized.

Why it is trial-degrading.
The test proves the state projection round-trips.
It does not prove a fresh session is isolated.
The new session contains target cookies the caller did not supply.
The test's presence-only assertion passes.
A state restore can carry an authenticated identity from another session.

Source to bug.
`src/polymerhus/app/steel_session_state.py` lines 221-240 `create_session` passes `sessionContext` to the API.
The API applies the context additively over the browser profile.
The compose file claims state is carried explicitly through `sessionContext`, not a shared profile.
The observed result contradicts the isolation claim.
The state capture at lines 165-202 projects whatever the browser context contains.
The test asserts the test cookie only.
The per-account state path is a file boundary, not a browser-profile boundary.
The exact API merge semantics were not inspected; the behavior is observed.

Class.
Trial-degrading and state-invalidating.
The run completes, but a fresh-session claim is false.

## 6. Recoverable and reporting failures

### FF-09. `cookies list` is an invalid CLI shape

Trace fact.
`gateway-trace.json` message 27 calls `steel browser cookies list --session wj-gateway-e2e --json`.
Message 28 returns `error: unrecognized subcommand 'list'` with `returncode: 2`.
Message 31-32 shows `cookies` supports only `set`, `clear`, and `help`.
The model uses `--help` and does not retry the invalid shape.

Why it is factual but not fatal.
The CLI surface is narrower than the model expected.
The model recovers by reading help.
The call is a wrong tool payload, not a browser failure.

Source to bug.
`kali/mcp_server.py` `steel_exec` does not validate per-verb subcommands.
The `steel-browser` skill does not list the `cookies` surface.
The CLI has no `list`; the bare `cookies` command lists.

Class.
Recoverable.
Eval tool contract and prompt.

### FF-10. The E4 harness loses its first two attempts

Trace fact.
`random-summary-threadid.json` records `ValueError: Checkpointer requires ... thread_id`.
`random-summary-recursion.json` records `GraphRecursionError` at the 80-step limit.
`random-summary.json` records a successful run with 13 calls.
The successful trace has no `success: false` and no nonzero `returncode` in the agent tool outputs.
`agent_steel_commands` is empty for all 13 calls.
The final report says 10 of 16 calls.

Why it is an eval failure.
The first attempt fails before the agent can act.
The second attempt fails at the graph boundary.
The third attempt succeeds.
The browser path itself is healthy in the successful attempt.

Source to bug.
`eval/steel-e2e-395/run_random_e2e.py` omitted the `thread_id` on the first attempt.
The broad task had no external call budget; the graph recursion limit was the only stop.
The final summary's `agent_steel_commands` extractor reads `args` as a dict; the recorded args are not in that shape, so the command list is empty.
The agent's final self-count is wrong.

Class.
Eval-run-fatal for the first two attempts.
Not a product runtime failure.

### FF-11. The dead-session summary reports a false status metric

Trace fact.
`gateway-summary-session-expired.json` shows `account_after.status: "not_valid"`.
It shows `status_write_ok: false`.
The `auth_store_writes` list contains the leaf write `accounts.admin-sessiononly-e2e.status = not_valid`.
The verdict is `failed`, which is the correct dead-session outcome.

Why it is a reporting failure.
The control's write is correct.
The metric hard-codes `status == "valid"` as success.
The dead-session control is supposed to write `not_valid`.
The summary therefore marks a correct control as a failed write.

Source to bug.
`eval/steel-e2e-395/run_gateway_e2e.py` line 300:
`status_write_ok = account_after.get("status") == "valid"`.
The check should depend on the expected verdict, or accept `not_valid` for the failed branch.

Class.
Reporting-only.
Eval harness.

### FF-12. Reporting and evaluation-context gaps

The E2 loop state reports `probe_count: 22`, `grounded: false`, `attempt_count: 0`, and null phase fields.
The trace shows the probes.
The projection in `run_gateway_e2e.py` does not expose the loop's phase-specific state.
The result is a weaker audit record, not a runtime failure.

The E4 summary reports 13 tool calls and an empty `agent_steel_commands` list.
The `random-result.json` messages are serialized as strings.
The command extractor loses the args, so the summary cannot reconstruct the commands.
The final agent report says 10 of 16 calls.
This is a trace-extraction defect.

The pod logs a blocked `TriagerDecision` deserialization warning.
The E3 controller did not open `module_context("hunting")`.
The shared fallback `InMemorySaver` in `src/polymerhus/app/llm/checkpoints.py` lines 545-561 is constructed without `checkpoint_serde()`.
The app's serde allow-list includes `TriagerDecision`.
The warning is a type-fidelity signal.
The production hunting entry opens the module context; the harness did not.
The fallback construction is still a product defect for direct pod/admin calls.

The E1 primitive matrix has no JSONL.
The alert and wait findings are operator-recorded.
The main report states this limitation.
The missing raw trace is an evidence gap, not a runtime failure.

The first E2 controller used a raw `AsyncPostgresSaver` without the app serde.
The first trace blocked `GatewayVerdict` deserialization.
The controller was fixed to pass `checkpoint_serde()`.
This is a harness error, not a product runtime failure.

## 7. Source-to-bug summary

| Layer | Source | Bug | Failure IDs |
|---|---|---|---|
| Eval browser tool | `kali/mcp_server.py` lines 274-283, 395-417 | `_session_name` checks only `browser start`; other `--session` verbs are not validated; an unknown name can create a session; the tool returns MCP success even when the CLI returns nonzero | FF-05, FF-09 |
| Eval exec tool | `kali/mcp_server.py` line 138 `execute_command`; `src/polymerhus/attack/hunting/pod/tools.py` `ExecTool` | Shell string; multi-command pipelines mask a middle failure; no structured browser action | FF-06 |
| Pod clean logic | `src/polymerhus/attack/hunting/pod/graph.py` lines 170-176 | `_clean_from_trail` checks only `returncode`; it ignores `stderr` and the CLI's `success: false` | FF-06, FF-07 |
| Pod verdict | `src/polymerhus/attack/hunting/pod/graph.py` lines 680-755 and 803-812; `pod.py` lines 120-147 | Last observation and last decision produce the terminal; the fail-open path maps an environment failure to `technical-infeasibility` | FF-07 |
| State mount | `src/polymerhus/app/steel_session_state.py` lines 165-202 and 221-240 | `sessionContext` is additive; the capture projects the merged context; no clear/replace or exact-set assertion | FF-08 |
| Model contract | `src/polymerhus/app/llm/transient.py` lines 62-72; `actor.py` lines 326-363; `reasoning.py` lines 173-207 | `reasoning_content` 400 is a contract error; the actor breaks before fallback; the parser is fail-open | FF-01 |
| Checkpoint fallback | `src/polymerhus/app/llm/checkpoints.py` lines 545-561 | The shared fallback is `InMemorySaver()` without `checkpoint_serde()` | FF-12 |
| E2 summary | `eval/steel-e2e-395/run_gateway_e2e.py` line 300 | `status_write_ok` accepts only `valid`; the dead-session control correctly writes `not_valid` | FF-11 |
| E4 harness | `eval/steel-e2e-395/run_random_e2e.py` | Missing `thread_id`; broad prompt with no external budget; trace args lost in serialization | FF-10, FF-12 |
| E3 harness | `eval/steel-e2e-395/run_pod_e2e.py` | No `module_context("hunting")` around `arun_pod`; the fallback serde warning is exposed | FF-12 |
| External Steel CLI/API | Steel CLI 0.5.0-preview.6 | Stale CDP target while the session stays live; unknown-session `eval` creates a session; no dialog handler; `wait --load-state` event timeout; idle release despite the flag | FF-02, FF-03, FF-04, FF-05 |

## 8. Product versus eval scope

The user's correction is supported by the trace split.

Runtime or product failures:

- FF-01: the default model and the reasoning-contract handling.
- FF-02: the CDP target reset, plus the app's missing target guard.
- FF-04: the modal dialog freeze, plus the app's missing dialog guard.
- FF-07: the pod's last-lap verdict and its conflation of environment expiry with test infeasibility.
- FF-08: the state mount's lack of isolation, plus the test's weak assertion.

Eval or operational failures:

- FF-03: the session lifetime and the operator prep cycle.
- FF-05: the untyped session argument and the model typo.
- FF-06: the malformed browser command and the masked shell exit.
- FF-09: the invalid `cookies list` shape.
- FF-10: the E4 thread id and recursion limits.
- FF-11: the E2 status metric.
- FF-12: the loop projection, trace extraction, module context, serde fallback, and E1 evidence.

The fatal runtime set is smaller than the previous risk analysis implied:

- Run-fatal product/runtime: FF-01, FF-02, FF-04.
- Run-fatal operational: FF-03.
- Trial-degrading: FF-05, FF-06, FF-07, FF-08.
- Recoverable: FF-09.
- Eval-run-fatal: FF-10.
- Reporting-only: FF-11, FF-12.

## 9. What the successful traces actually prove

The E2 gateway turn is a real authenticated browser turn.
The dashboard, `/api/authentication`, and `/api/admin/user` all succeeded.
The final verdict and the status write are valid.
The failed calls in that trace are a wrong session name, a stale CDP target, and one invalid `cookies list` call.
The agent recovered from all three.
The success does not prove that the default model or a fresh session works.

The E3 lap 1 is a real httpOnly check.
Both cookies were httpOnly, `document.cookie` was empty, and the control cookie proved the read channel.
The final `technical-infeasibility` is a session-budget and last-lap verdict failure, not an httpOnly failure.
The `get text` calls in the same lap were malformed and masked.
The pod's clean logic could have hidden them.

The E4 route sweep is real.
The 11 routes and the focused agent's 13 calls are real.
The first two E4 attempts are harness failures.
The summary's command list is empty because of trace extraction, not because the agent failed to call the browser.

The E5 state round-trip is real.
The isolation claim is not.
The test's `ok: true` must be read as "the test cookie round-tripped", not "the session was fresh".

The E6 checks are clean.
Health, alias, fixed UA, raw-UA negative control, and the closed port all passed.

## 10. Recommended corrections

For the eval harness:

- Make the E2 status metric branch-aware.
- Persist the E1 JSONL.
- Wrap the pod call in `module_context("hunting")`.
- Pass `checkpoint_serde()` to every saver, including the fallback.
- Give `create_agent` a `thread_id` and an external call budget.
- Record the tool call args in the random summary.
- Count failed tool commands in every scenario summary.
- Run at least one gate with the production default model.

For the eval browser surface:

- Validate `--session` for every verb, not only `start`.
- Reject an unknown session unless the command is an explicit `start`.
- Enforce `get text <selector>` and the `cookies` subcommand surface.
- Return a tool-level failure when the CLI returns nonzero or `success: false`.
- Prefer a typed browser action over a composed shell string.
- Use `pipefail` or one command per observation.

For the product and pod:

- Make `_clean_from_trail` check `stderr` and the CLI `success` flag.
- Aggregate the pod evidence instead of using the last decision.
- Add a session-expired terminal.
- Add a wall-clock and session-lifetime budget.
- Add a target-liveness check and `tab new` recovery.
- Fix the state mount isolation and assert the exact cookie set.
- Add a dialog handler or a dismiss-dialogs default.
- Fix the reasoning-contract fallback.

## 11. Evidence appendix

Gateway coordinates:

- Message 13-14: mistyped `eval` on `wj1618c524`; empty success.
- Message 15-16: `eval` on `wj-gateway-e2e`; `Session with given id not found`.
- Message 17: both sessions live.
- Message 18-19: stray session stopped.
- Message 20: `navigate` fails with the same CDP error.
- Message 21-26: help, empty snapshot, empty content, `about:blank` tab list.
- Message 27-28: `cookies list` invalid.
- Message 30-31: `tab new` creates a fresh target.
- Message 33-40: navigation and authentication succeed after the recovery.
- Message 44-46: two skill lessons recorded; the skill body is unchanged.
- Message 47-48: `GatewayVerdict` authenticated.

Pod coordinates:

- Observation 0: session live.
- Observation 1: cookie inventory; both httpOnly.
- Observation 2: selectorless `get text`; clap error and Python `KeyError`; returncode 0.
- Observation 3: `get text body` returns a dict; wrong-shape `t[:300]`; returncode 0.
- Observation 4: `get text body` shape handled; admin body present.
- Observation 5-6: fetch and cookie checks.
- Observation 7-9: sessions empty at 15:14:57 and 15:16:26.

E4 coordinates:

- `random-summary-threadid.json`: missing `thread_id`.
- `random-summary-recursion.json`: 80-step recursion.
- `random-summary.json`: 13 calls, `ok: true`, empty command list.
- `random-result.json`: 28 entries; no browser error markers; final report says 10 of 16.

E5 and E6:

- `e5-summary.json`: three cookie names before and after restore; only one supplied.
- `e5-state.json`: sanitized local copy.
- `e6-summary.json`: health 200, alias title, negative alias, fixed UA, raw UA, port closed.

No cookie values, tokens, or admin credentials are reproduced here.
The raw state and pod memory log remain sensitive on the eval host.

