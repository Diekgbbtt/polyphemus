# Residual failure-mode risk analysis - session-based Steel browser system (#395 follow-up)

Status: analysis complete.
Date: 2026-10-22.
Scope: the residual failure modes from the #395 end-to-end report.
Sources: `docs/design/e2e-steel-session-395-report.md`, `eval/steel-e2e-395/evidence/`, and the current source tree.
No code was changed.
No remote repository was pushed.

This document is a risk analysis.
The trace-backed factual failure ledger is in `docs/design/e2e-steel-session-395-factual-failures.md`.
It narrows the run-fatal set and separates eval/operational failures from product/runtime failures.

## 1. Method and reading guide

This analysis is qualitative.
It rates likelihood, impact, detectability, and residual risk.
It does not pretend to a quantitative probability.
The ratings are judgments from the live evidence and the code paths.

Residual means after the controls that were actually present in the E2E run.
A high residual rating means the control is a workaround, a test-only override, or a post-hoc cleanup.
It does not mean the control is absent.

Each mode has four parts:

- The observed failure and its trigger.
- The risk profile and the practical blast radius.
- The upstream structural causes that make the failure possible.
- The controls, the residual gap, and a leading indicator.

Confirmed means the live evidence or the source code shows the mechanism.
Inferred means the behavior is observed but the runtime internals were not available for inspection.
The Steel API, the Steel CLI, and the Chromium profile manager are external artifacts here.

Rating scale:

- Likelihood: High, Medium, Low.
- Impact: High, Medium, Low.
- Detectability: High means loud and early; Low means silent until a downstream consumer acts.
- Residual risk: Critical, High, Medium, Low.

## 2. Residual failure-mode register

| ID | Residual failure mode | Trigger | Impact | Likelihood | Detectability | Residual |
|---|---|---|---|---|---|---|
| R1 | Reasoning-contract break on the default thinking model | A multi-turn tool loop on `opencode-go:deepseek-v4.1-flash` | No verdict; role degrades; pipeline fail-open may run unauthenticated | High | High (400 after several calls) | High |
| R2 | Session-lease expiry while a turn or lap is paused | 10 to 20 minutes without CDP input, despite `--inactivity-timeout 0` | Session disappears mid-scenario; lost evidence; wrong terminal verdict | High | Medium (poll only) | High |
| R3 | Fresh-session state isolation failure | A session is created with a partial `sessionContext` | Foreign cookies enter the session and the state file; cross-account contamination | Medium | Low (the test passes) | High |
| R4 | Pod verdict overwritten by the last lap | A strong negative lap is followed by a variant whose environment fails | Confirmed negative is hidden behind `technical-infeasibility` | High | Medium (export keeps the trail) | High |
| R5 | CDP target and session identity diverge | The target resets while the API session stays live | Mid-turn errors; misread as a dead session; stray retries | Medium | Medium (specific error) | High |
| R6 | Secrets propagate into checkpoints and evidence | Cookie or token reads are captured by the trace, state, or pod memory | Credential exposure beyond the intended consumer | High | Low (post-hoc scan only) | Critical |
| R7 | Actor posts a duplicate no-decision reply | The real result is delivered, then the turn closes with a transport error | A second reply races the real verdict | Medium | High (warning and inbox) | Medium |
| R8 | Broad agent loop fails to converge | A broad prompt with no call budget and no done predicate | Recursion error; no final answer; session burn | High for broad prompts | High (recursion error) | Medium |
| R9 | CLI and skill contract drift | Hand-authored commands meet a changed CLI or target router | Wasted calls; wrong routes; stray sessions; policy conflict | High | High (command errors) | Medium |
| R10 | Provider content filter or model variance | A security-test prompt hits a provider safety filter | Pod degrades before the first tool call | Medium | High (provider error) | Medium |
| R11 | Modal dialog freezes the browser session | A target calls `alert` or another blocking dialog | `eval` times out; later commands time out; session blocked | Medium | High (timeout) | Medium |
| R12 | Checkpoint serde fallback loses structured types | A stateful call resolves the shared fallback without the app serde | Structured decision degrades to a dict; resume loses type fidelity | Low to Medium | Low (warning only) | Medium |
| R13 | Pod evidence schema asymmetry | A consumer expects a top-level command; the export nests it under `request` | Weaker audit and replay from the export alone | High | Medium | Low |
| R14 | Gateway loop state under-reports its own evidence | The summary reads a different state surface than the loop middleware | Operators cannot trust the loop record | High | Low | Low |
| R15 | Primitive-matrix evidence gap | The E1 matrix JSONL was not persisted | The primitive findings are less reproducible | Certain for this run | High | Low |

## 3. Release-blocking modes

### R1. Reasoning-contract break on the default thinking model

Observed behavior.
The default gateway role ran on `opencode-go:deepseek-v4.1-flash`.
The first responses carried no reasoning payload.
The trace shows `additional_kwargs: {}` and `usage_metadata.output_token_details.reasoning: 0`.
The app logged a reasoning-gap warning on each response.
After five browser tool calls, the next model call returned HTTP 400.
The provider message said the `reasoning_content` in thinking mode must be passed back.
The turn produced no verdict.
The account status remained unset.
The actor degraded to a no-decision reply.
The run stopped.

Why the app could not replay the field.
The replay middleware is fail-open.
It parses each assistant message.
When the field is absent, it logs a gap and returns no replacement.
The next request therefore carries no `reasoning_content`.
The client's wire capture is correct for the fields it knows.
The observed response simply had no reasoning field to capture.
The provider then enforced a conversation-level requirement that the response did not satisfy.

Why the fallback did not fire.
`app/llm/transient.py` lists `reasoning_content` as an actionable contract marker.
A 400 carrying that marker is classified as `contract`, not `transient`.
`actor._turn` breaks on a non-retryable error before the fallback branch.
The configured fallback model is attempted only after the transient schedule is exhausted.
A recoverable provider-contract mismatch therefore never reaches the fallback.

Risk profile.
Likelihood is high because the default model is the production default for the role.
Impact is high because the gateway is the entry point for every authenticated scenario.
A missing verdict fails open, so the pipeline can run every phase unauthenticated.
That turns a model-contract failure into a coverage and correctness failure.
Detectability is high at the 400, but only after several successful calls.
The failure is silent before that point.
The blast radius is every stateful role on the same model, not only the gateway.
The condition is repeatable, not a one-off.
The test used a model override, so the successful E2 result does not exercise the default.

Upstream structural causes.

- The capability profile is a static registry claim.
  It says the model returns reasoning, but it is not a runtime handshake.
- The app models reasoning as an optional per-message artifact.
  The provider models it as a mandatory conversation-state field.
- The parser is fail-open by design.
  A missing field is a warning, not a turn-level precondition failure.
- The error classifier deliberately excludes `reasoning_content` from the transient and fallback path.
  The exclusion protects against retry storms on malformed requests.
  It also blocks the one recovery path that would work here.
- The model selection is a single per-role default.
  The deployment has no per-workload health check for multi-turn thinking behavior.
- The eval overrides are a config-layer workaround.
  They hide the production default from the E2E result unless the reviewer reads the model labels.

Existing controls and residual gap.
The override to `qwen3.8-max` completes the scenario.
That is a test control, not a production fix.
The reasoning-gap warning is the only early signal.
There is no preflight multi-turn probe.
There is no placeholder, thinking-off retry, or contract-error fallback.
Residual risk is high.

Leading indicators.

- Count of `reasoning gap` warnings per role and model.
- Count of 400 responses containing `reasoning_content`.
- Share of turns where `output_token_details.reasoning` is zero on a thinking role.
- Fallback activations by error class.

### R2. Session-lease expiry while a turn or lap is paused

Observed behavior.
The session start requested `--session-timeout 86400000` and `--inactivity-timeout 0`.
The start record reported about 86,400,000 ms remaining.
The wrapper passed the arguments through to the raw CLI.
The E2 first turn still lost its session before the gateway started.
The E3 pod still lost its session between lap 1 and lap 2.
The E4 run survived only because the session was prepared immediately before the sweep and the agent.
The idle gaps were roughly 10 to 20 minutes.
The exact threshold was not measured.

Why this matters more than a normal timeout.
The caller has a positive signal that the session should last 24 hours.
The runtime has a different, invisible idle policy.
The caller checks the catalogue at the start of a scenario and then trusts it.
A model turn can be slow, a pod lap can sleep, and a retry can pause.
The session can disappear without a command failing at the moment of loss.
The next command sees an empty catalogue or a stale target.
The E2 dead-session branch handled the absence correctly.
The E3 pod did not have a typed session-expired terminal, so the loss became `technical-infeasibility`.

Risk profile.
Likelihood is high for any long-running browser scenario.
Impact is high because the loss can invalidate a whole trial or a multi-lap pod.
Detectability is medium because the catalogue is pollable, but no component polls continuously.
The blast radius includes gateways, pods, crawlers, and random agents.
The failure is more likely with slower reasoning models and longer tool loops.
The condition is not tied to a single target.
Residual risk is high.

Upstream structural causes.

- Session lifetime has two authorities.
  The start command sets an absolute lifetime, while the runtime owns an independent idle reaper.
- The `0` sentinel is ambiguous.
  The CLI help says it disables the idle release.
  The runtime behavior is consistent with `0` meaning "use the default" or with a separate hard reaper.
- The app has no lease or heartbeat.
  The session is an operator-owned artifact, not a leased resource with an owner and a renewal path.
- `remainingMs` exposes the absolute lifetime, not the idle budget.
  A 24-hour value is a misleading liveness indicator.
- The pod budget is an iteration and tool-call budget.
  `HUNT_POD_MAX_ITERS` and `HUNT_POD_MAX_TOOL_CALLS` do not model wall-clock time or session lifetime.
- The prep is a point-in-time check.
  It proves the session is live now; it does not keep it live.

Existing controls and residual gap.
The E4 approach, prepare immediately before use, works for short runs.
The E2 prep and the E3 prep each checked the session before the run.
There is no keepalive, no lease renewal, and no typed expired state.
A long model turn can still exceed the idle window.
Residual risk is high.

Leading indicators.

- Time since the last CDP command per session.
- Catalogue presence polled during model turns.
- `remainingMs` versus the elapsed idle time.
- Count of trials that end with an empty catalogue.
- Count of `technical-infeasibility` verdicts whose trail shows a live lap 1.

### R3. Fresh-session state isolation failure

Observed behavior.
The E5 state test created a session with only the `ph_e2e_state` cookie.
The captured context returned `JSESSIONID`, `rememberMe`, and `ph_e2e_state`.
The restored context returned the same three names.
The test passed because it asserts only the test cookie.
The state file was 1686 bytes before redaction.
The other two cookies were live target cookies, not test fixtures.
The local evidence was redacted after the run.

Why this is an isolation failure, not a projection bug.
The projection kept the four durable fields correctly.
The input context already contained the foreign cookies.
The browser profile or the session create path merged them into the new session.
The state module then captured the merged set honestly.
A caller that supplies one cookie receives a session with more cookies than it owns.
The compose comment says the browser state is carried explicitly through `sessionContext`, not by a shared profile.
The observed result contradicts that claim.
The shared Chromium profile under `/tmp/steel-chrome` and the named volume are the likely mechanism.
The exact API merge semantics were not available for inspection.

Risk profile.
Likelihood is medium to high for any state restore or partial context.
Impact is high because the session can be authenticated as a different account.
A test can pass for the wrong reason.
A state file can persist cookies the caller did not own.
Cross-account contamination invalidates trial isolation and evidence.
Detectability is low because the presence-only assertion passes.
The blast radius includes every state round-trip, account switch, and parallel crawl.
Residual risk is high.

Upstream structural causes.

- The browser identity is process/profile-level, not session-level.
  The named volume persists the Chromium profile.
- `sessionContext` is additive.
  There is no clear or replace mode in the create call.
- The state module has no "expected cookie set" input.
  It projects whatever the browser context contains.
- The E5 test asserts presence, not exact set or absence of foreign cookies.
- The per-account state path is a file-layout boundary, not a browser-profile boundary.
- The provider restore path uses the same merge semantics.
  A restored account can inherit the previous account's cookies.

Existing controls and residual gap.
The state file is written owner-only.
The local evidence bundle was sanitized.
Those controls protect the file after capture.
They do not prevent the foreign cookies from entering the session.
The test still passes.
Residual risk is high.

Leading indicators.

- Cookie-set diff at create and restore.
- Count of state files containing cookies outside the expected account set.
- Count of restored sessions whose authenticated identity differs from the account.
- State file size drift for the same test input.

### R4. Pod verdict overwritten by the last lap

Observed behavior.
Lap 1 read the cookie inventory and the JavaScript cookie string.
Both session cookies were httpOnly.
`document.cookie` was empty.
A JavaScript control cookie was visible and then cleared.
Two authenticated endpoints returned 200.
The triager classified the lap as `symptom-absent-partial-coverage`.
It minted a v1 sweep over more endpoints.
The Steel session expired before lap 2.
Lap 2 saw an empty catalogue.
The final decision was `technical-infeasibility`.
The export retained the lap-1 evidence.
The verdict did not.

Why the final verdict is structurally wrong for this evidence.
The triager's terminal decision is taken from the last observation and the last decision.
The terminal node exports that decision.
There is no monotonic aggregation of prior laps into the final verdict.
The v1 variant was a legitimate coverage idea.
It had no budget check against the session lease.
The pod's caps are iteration and tool-call counts, not wall-clock or session lifetime.
The empty lap then produced an infeasibility signal.
`technical-infeasibility` means the test cannot be implemented.
The actual condition was that the environment expired.
The two are different, and the export does not separate them.
The `clean` flag follows the last decision or a trail helper for some terminals.
It does not preserve the lap-1 negative as the best available result.

Risk profile.
Likelihood is high for multi-lap pods with slow models.
Impact is high because a confirmed negative can be discarded.
A downstream hunter reads the terminal reason, not the full trail.
A false `technical-infeasibility` can suppress a valid security conclusion.
Detectability is medium because the export keeps all observations.
It requires a reviewer to read the trail and override the verdict.
The blast radius includes all negative tests that need more than one lap.
Residual risk is high.

Upstream structural causes.

- The pod verdict is last-writer.
  The `terminal` node uses `state["decision"]`.
- The triager's variant policy is coverage-first.
  It does not treat the session lease as an input.
- The pod budget is iteration and tool-call count.
  It is not wall-clock time or remaining session lifetime.
- `technical-infeasibility` conflates no response, an unimplementable test, and an expired environment.
- `clean` is not a monotonic property of the best evidence.
- The export is an evidence log, but the verdict is a scalar that loses the lap history.
- The model can mint a variant without an explicit environment-budget check.

Existing controls and residual gap.
The export keeps the raw observations and the interpretations.
A reviewer can see the lap-1 negative.
The terminal scalar still says `technical-infeasibility` and `clean: false`.
No automatic consumer can recover the negative without special logic.
Residual risk is high.

Leading indicators.

- Terminal reason after a prior `symptom-absent` lap.
- Count of pods with a live lap 1 and an expired lap 2.
- Count of `technical-infeasibility` verdicts with at least one clean negative observation.
- Variant mint rate versus remaining session time.

### R5. CDP target and session identity diverge

Observed behavior.
The catalogue reported `wj-gateway-e2e` live.
A `navigate` or `eval` command failed with `Session with given id not found`.
The tab was at `about:blank`.
The agent ran `steel browser tab list` and then `steel browser tab new`.
The new target worked.
The httpOnly cookies survived.
The catalogue still reported the session live.

Why the two identities diverge.
The API session is a browser process and a session record.
The CDP target is a tab or page inside that process.
The CLI resolves a session name to a target.
If the target is replaced or crashes, the session record can remain live.
The CLI has no explicit target health check before each command.
The `steel_exec` guard checks the live session names before a start.
It does not check that the named session has a usable target.
The skill's failure branch has no case for this reset.
The agent found the recovery by experimentation.
A less capable agent may misread the error as a dead session.

Risk profile.
Likelihood is medium for long sessions or unstable pages.
Impact is high because a mid-turn failure can lose the turn and the evidence.
A misread can trigger a request replay or a stray session.
Detectability is medium because the error is specific.
The recovery is not tool-enforced.
The blast radius includes every browser command after a target reset.
Residual risk is high.

Upstream structural causes.

- Two identities have no reconciliation layer.
  The session record is process-level; the target is tab-level.
- The CLI treats the session name as a stable handle.
  The underlying target is not stable.
- The tool guard trusts the catalogue as a proxy for usability.
- The skill encodes a failure branch for a missing session, not for a missing target.
- `tab new` is a manual recovery, not a retry policy.
- The agent's context can lose the target without a session-level event.

Existing controls and residual gap.
The gateway agent recovered manually.
The cookies survived, so the recovery did not need a re-authentication.
The skill does not teach the recovery.
The `steel_exec` guard does not detect the condition.
Residual risk is high.

Leading indicators.

- Count of `Session with given id not found` errors.
- Count of `tab new` recoveries per run.
- Catalogue live but target command failing.
- Time between target reset and recovery.

### R6. Secrets propagate into checkpoints and evidence

Observed behavior.
The E2 trace carried the auth-store token on the store read.
The controller marked `trace.secret_leak: true` and redacted it.
The E2 verdict itself had no secret.
The E5 state file carried the live `JSESSIONID` and `rememberMe` values.
The local evidence bundle was sanitized after the run.
The pod experiment log can carry raw cookie values in its observation stdout.
The pod export was redacted by the controller.
The pod memory log remains on the agent host and is sensitive.

Why this is a residual mode, not a report formatting issue.
The token and cookie values reach the model-facing tool result by design.
The state capture persists the browser context by design.
The evidence layer captures tool outputs by design.
The redaction happens after capture, in a controller or a manual step.
The raw copies remain in checkpoints, logs, or memory stores.
A different consumer, a different export path, or a missed field can expose them.
R6 aggregates three observed paths: the E2 trace token, the E5 state cookies, and the pod memory log.

Risk profile.
Likelihood is high because the data path routinely handles secrets.
Impact is high because a session cookie or token is a credential.
Detectability is low because the test and the agent do not fail on a leak.
The existing scan is a text scan for known values, not a field-level policy.
The blast radius includes traces, checkpoint stores, pod memory, Langfuse, and evidence bundles.
Residual risk is critical.

Upstream structural causes.

- The auth store returns the token to the agent as a tool result.
  The skill says not to print it, but the model still holds it.
- The browser cookie command returns values.
  The command has no names-and-flags-only mode by default.
- The state module captures the full context.
  The docstring says never log it, but the caller stores it.
- The trace and checkpoint layers capture raw tool outputs.
  There is no field-level secret classification at the capture boundary.
- Redaction is a post-hoc controller step.
  It depends on knowing every secret value and every serialization path.
- The pod memory log is a plain store with no redaction at the source.
- The evidence bundle is assembled by scripts, not by a typed export policy.

Existing controls and residual gap.
The state file is owner-only.
The local bundle is redacted.
The controller scans for known values.
Those controls are after the fact.
A raw state or log remains in the runtime.
A new evidence path can bypass the scan.
Residual risk is critical.

Leading indicators.

- Count of evidence files containing cookie or token patterns.
- Count of checkpoint values containing a secret field.
- State file size and cookie-set diff.
- Pod memory log permissions and retention.
- Redaction test coverage per export path.

## 4. Operational and harness modes

### R7. Actor posts a duplicate no-decision reply

Observed behavior.
The E2 gateway delivered the real `GatewayVerdict`.
The actor then logged that the connection was closed.
It posted a no-decision reply.
The controller received the real verdict first.
It drained the stale reply.
A different consumer could have read the no-decision reply first.

Why the duplicate is possible.
`build_inbox_delivery` returns two delivery paths.
The normal middleware posts the real result at `after_agent`.
The degraded hook posts a no-decision reply when a turn exhausts its retry budget.
The two paths have no shared per-turn latch.
The real result can be posted before the turn is fully committed.
A late transport error then runs the degraded hook.
The inbox has no idempotency key or turn token.
The docstring says "exactly one reply per turn", but the implementation does not enforce it.

Risk profile.
Likelihood is medium because the real result and the late error can coincide.
Impact is medium because a consumer may act on the no-decision reply.
It can wake a parent twice, race a pipeline, or overwrite a state assertion.
Detectability is high because the warning is logged and the second inbox item is observable.
The controller's drain is a local control.
The blast radius includes every actor built with `build_inbox_delivery`.
Residual risk is medium.

Upstream structural causes.

- Two delivery paths, one turn, no latch.
- Delivery happens inside the graph, before the turn's caller records success.
- The degraded hook cannot know that the real result was already posted.
- The inbox has no idempotency or turn identity.
- The "exactly one" invariant is documented, not enforced.

Existing controls and residual gap.
The gateway controller drains the reply inbox after the await.
It also cancels the reply waiter.
A consumer that does not drain can see the duplicate.
Residual risk is medium.

Leading indicators.

- Replies per turn, expected one.
- A no-decision reply after a real verdict.
- Actor degrade warnings after `after_agent` delivery.
- Inbox length at turn end.

### R8. Broad agent loop fails to converge

Observed behavior.
The broad E4 prompt with the thread-id fix ran to the graph recursion limit.
The graph raised `GraphRecursionError` after 80 steps.
The run returned no final report.
The focused follow-up used a 16-call task and finished in 13 calls.
The session was still live for the successful run.

Why the loop did not stop.
The prompt asked for broad coverage and feature exercise.
It gave no call, time, or token budget.
The only external bound was the graph recursion limit.
The agent decides when to stop by returning no tool call.
There is no external done predicate.
The harness catches the recursion error but has no partial result.
The session lease can expire during the loop, which turns a convergence problem into an R2 problem.

Risk profile.
Likelihood is high for broad prompts.
Impact is medium because the run burns time and tokens and returns no answer.
Detectability is high at the recursion error.
The blast radius is the evaluation agent and any custom `create_agent` harness.
The production pod has its own 200-call harness cap and its own variant cap.
The E4 controller did not use that production harness.
Residual risk is medium.

Upstream structural causes.

- The graph recursion limit is a blunt last resort, not a task budget.
- The prompt has no explicit stop rule or call budget.
- The agent's termination is model-decided.
- The harness does not preserve a partial result on budget exhaustion.
- The session lifetime is not part of the agent's budget.

Existing controls and residual gap.
The focused prompt with 16 calls is the workaround.
The deterministic route sweep is the coverage control.
A general agent still needs an external budget and a partial-result path.
Residual risk is medium.

Leading indicators.

- Tool calls per agent run versus the budget.
- Recursion errors.
- Runs that end without a final message.
- Time from first to last tool call versus the session idle window.

### R9. CLI and skill contract drift

Observed behavior.
The default/shipped authn procedure and the plan use hash routes.
The target uses history-mode `/login` and `/register`.
The scenario overlay in `eval/steel-e2e-395/skills/authn/SKILL.md` contains the correction.
The correction is local, not upstream.
`wait --load-state` failed with `Timeout waiting for Page.loadEventFired`.
`get text` without a selector returned a clap error.
`cookies` had no `list` subcommand.
A mistyped `--session` name created a stray live session.
An account-root write is create-only; the leaf write is required.
The brief armed `write_skill`, while the loaded skill protocol reserved revisions to the SkillEvolver.

Why the drift is structural.
The skill is hand-authored prose.
The CLI help is the only command schema.
There is no generated command reference and no skill/CLI contract test.
The start guard is a narrow regex plus a live-catalogue check.
It cannot distinguish a typo from an intentional new session.
Route assumptions are target-specific but stored in a shared procedure.
The skill has no router probe or route-table discovery step.
`write_skill` is armed by `auth_capable_binding(..., with_write_skill=True)`.
The skill policy says the SkillEvolver owns revisions.
Two authorities can disagree without a runtime error.

Risk profile.
Likelihood is high because the agent follows the skill and the CLI changes independently.
Impact is medium: wasted calls, wrong routes, stray billable sessions, policy conflict.
C5 is a safety issue because a typo creates a live context.
C8 is a governance issue because a write capability is armed but not allowed.
Detectability is high for command errors and low for route or policy drift.
The blast radius is every agent that loads the authn or pod skill.
Residual risk is medium.

Upstream structural causes.

- Prose contract instead of a generated command/route schema.
- The start guard is check-then-start and name-based, not intent-based.
- The route list is hand-authored, not derived from the target's router.
- The `write_skill` capability and the skill policy have different owners.
- The CLI's wait, selector, and cookies surfaces are not reflected in the skill until a live failure.
- The scenario overlay corrects the route note, but the default procedure is unchanged.

Existing controls and residual gap.
The scenario skill warns about hashes, alerts, and `wait --load-state`.
The gateway agent reasoned around `cookies list`, `get text`, and the stray session.
The `write_skill` conflict was resolved in favor of the skill policy.
These are model-reasoning controls, not contract controls.
Residual risk is medium.

Leading indicators.

- Command error rate by verb and CLI version.
- Stray sessions created per run.
- Route 404 or wrong-shell rate.
- `write_skill` attempts versus accepted revisions.
- Skill command tests against the pinned CLI.

### R10. Provider content filter or model variance

Observed behavior.
The E3 pod first ran on `opencode-go:qwen3.8-max`.
The provider returned `data_inspection_failed` before the first tool call.
The pod degraded to `technical-infeasibility`.
The GLM-5.3 re-run completed the browser work.
The E2/E4 Qwen runs completed on benign browser tasks.
The filter is prompt- and workload-dependent.

Why this is a model-selection risk.
The role model is a config-layer choice.
The provider's safety policy is opaque and can reject a security-test prompt.
The pod's system prompt and spec describe attack testing.
No preflight probe checks the model against the workload content.
The pod's fail-open wrapper turns the provider error into a domain-like verdict.
A quota or filter failure can look like a test result.

Risk profile.
Likelihood is medium for security-testing roles.
Impact is medium because the pod can report a false infeasibility.
Detectability is high at the provider error.
The blast radius is every security-testing workload on a filtered model.
Residual risk is medium.

Upstream structural causes.

- Model selection is per-role configuration, not workload-aware.
- The provider's content policy is not part of the capability profile.
- There is no preflight prompt probe for the role's actual workload.
- The pod's fail-open path can encode an infrastructure condition as a domain verdict.
- The fallback model is not selected on content-policy grounds.

Existing controls and residual gap.
The GLM override completes the run.
The provider error is visible in the run log.
The first E3 summary was overwritten, so the artifact is weak (H7).
Residual risk is medium.

Leading indicators.

- Provider error classes by model and role.
- `data_inspection_failed` count.
- Pod `technical-infeasibility` rate with no raw observations.
- Model fallback activations.

### R11. Modal dialog freezes the browser session

Observed behavior.
A raw `alert(document.cookie)` blocked the page.
The `eval` command returned code 124 after 20 seconds.
The next command timed out at 30 seconds.
`steel browser stop` recovered the session in 556 ms.
The CLI has no dialog command.
The pod spec was changed to read `document.cookie` and the cookie inventory instead.

Why the freeze is possible.
An alert blocks the page's JavaScript thread.
The CLI's eval command waits for the expression.
The command timeout kills the exec process, not the dialog.
The browser stays blocked.
The next command inherits the blocked page.
The skill warns against alert, but a real target can call one.

Risk profile.
Likelihood is medium because security tests often trigger dialogs.
Impact is medium because the session can be lost or stalled.
Detectability is high at the timeout.
The blast radius is any page with alert, confirm, prompt, or beforeunload.
Residual risk is medium.

Upstream structural causes.

- The CLI has no `Page.handleJavaScriptDialog` path.
- The eval surface runs on the page thread with no dialog guard.
- The command timeout does not dismiss the dialog.
- The skill warning is a policy, not a runtime control.
- The spec originally used alert, which shows the hazard is easy to reintroduce.

Existing controls and residual gap.
The skill says do not use alert.
The pod spec uses a non-blocking cookie read.
`steel browser stop` is a recovery.
A target-triggered dialog still freezes the session.
Residual risk is medium.

Leading indicators.

- `eval` timeouts on a page that was previously healthy.
- Commands timing out after an eval.
- Dialog events in the browser log, if available.
- Recovery time after a timeout.

### R12. Checkpoint serde fallback loses structured types

Observed behavior.
The E3 pod ran outside `module_context("hunting")`.
The fallback checkpointer logged a blocked `TriagerDecision` deserialization.
The app's `checkpoint_serde()` allow-list includes `TriagerDecision`.
The fallback `InMemorySaver` is constructed without that serde.
The pod still produced interpretations.
The warning is a type-fidelity signal, not a total failure.

Why the fallback is a latent defect.
`get_session_checkpointer()` returns the shared fallback when no module context is set.
The fallback is `InMemorySaver()` with the default serializer.
The `_ALLOWED_MSGPACK_MODULES` list is only applied through `checkpoint_serde()`.
Under strict msgpack, an unlisted type is blocked and degrades to a dict.
The docstring says every construction point uses the ONE serializer.
The fallback is a construction point that does not.
The production hunting entry opens the module context.
A direct pod call, an admin read, or a test can still hit the fallback.

Risk profile.
Likelihood is low to medium in production and high in direct harnesses.
Impact is medium because a resumed turn can lose the typed decision.
The value may degrade to a dict, which changes behavior downstream.
Detectability is low because the warning is easy to miss.
The blast radius is every stateful agent call outside a module context.
Residual risk is medium.

Upstream structural causes.

- The ONE-serializer invariant is documented but not enforced at the fallback.
- The checkpointer resolution depends on an ambient module context.
- The fallback is a convenience path for bootstrap and admin reads.
- There is no startup assertion that every construction point uses the app serde.
- The harness did not open the production module context (H2).

Existing controls and residual gap.
The production entry points open the module context.
The raw Postgres saver in the E2 controller was fixed to pass `checkpoint_serde()`.
The fallback remains.
Residual risk is medium.

Leading indicators.

- `msgpack_blocked` warnings.
- Count of stateful calls outside a module context.
- Structured decisions that resume as dicts.
- Serde construction-point test coverage.

### R13. Pod evidence schema asymmetry

Observed behavior.
The pod export has no top-level `command` on a raw observation.
The exec observation carries the command under `request.command`.
The replay observation carries `request.artifact_id` and `request.overrides`.
The summary extracts a `steel_commands` list from text.
A consumer that looks for `command` sees empty.

Why this is a schema risk.
`RawObservation` is a union of HTTP fields and exec fields.
It models the result, not the invocation.
The invocation shape differs by tool.
There is no canonical `invocation` field.
The export is usable if the consumer knows the nested shape.
It is not uniformly replayable from the evidence alone.

Risk profile.
Likelihood is high for any generic evidence consumer.
Impact is low to medium: weaker audit, replay, and debugging.
Detectability is medium because the data is present under another key.
Residual risk is low.

Upstream structural causes.

- A union-shaped observation instead of a tagged invocation record.
- The command is an input to the tool, not a first-class evidence field.
- The summary and the export use different extraction paths.
- Redaction is applied at the export controller, not at the observation source.

Existing controls and residual gap.
The nested `request.command` is present for exec observations.
The pod summary lists the commands for the run.
A generic consumer still needs a schema adapter.
Residual risk is low.

### R14. Gateway loop state under-reports its own evidence

Observed behavior.
The E2 summary reports `loop_phase: FINISH`.
It reports `probe_count: 22`.
It reports `attempt_count: 0`.
It reports `grounded: false`.
The phase fields `loop_observed`, `loop_probe`, and `loop_validate` are null.
The trace shows the reads and the browser probes.

Why the loop record diverges.
The loop middleware tracks phase transitions and counters.
The summary reader projects a subset of that state.
The `grounded` flag is not updated by the browser evidence in the projection.
The phase-specific fields are optional and null.
There is no consistency assertion between the trace and the loop record.

Risk profile.
Likelihood is high because the projection is a separate read path.
Impact is low for the verdict, medium for operator trust and regression detection.
Detectability is low because the verdict is correct.
Residual risk is low.

Upstream structural causes.

- Two state surfaces: middleware state and summary projection.
- No single typed loop record persisted with the trace.
- `grounded` is a flag with no evidence link in the summary.
- The phase fields are optional, so null is indistinguishable from missing.

Existing controls and residual gap.
The trace and the browser commands are preserved.
The verdict and the status write are correct.
The loop summary is not a reliable audit record.
Residual risk is low.

### R15. Primitive-matrix evidence gap

Observed behavior.
The E1 matrix passed the core primitives.
The raw JSONL was not persisted.
The report records the operator matrix.
The wait and alert results cannot be replayed from a saved artifact.

Why this is a risk.
The primitive matrix is the lowest-level evidence for the browser path.
Without the JSONL, a future regression cannot be compared against it.
The report's findings are still valid, but the evidence is narrative.

Risk profile.
Likelihood is certain for this run.
Impact is low because the behavior is reproduced by the report and the code.
Detectability is high because the gap is documented.
Residual risk is low.

Upstream structural causes.

- The matrix was an ad hoc script, not a first-class evidence producer.
- The harness did not define a saved-result contract for the primitive tier.
- The report has to rely on operator notes.

Existing controls and residual gap.
The report records the commands and results.
The E6 evidence covers the deployment primitives.
The E1 JSONL remains a gap.
Residual risk is low.

## 5. Cross-cutting structural causes

These causes recur across the modes.
Fixing one mode without the cause leaves the next mode available.

T1. Static capability contracts replace runtime handshakes.
The reasoning profile, the model content policy, and the account write shape are asserted in configuration.
They are not probed against the live provider or store.
When the live behavior differs, the failure is discovered mid-run.
R1, R10, and C7 are instances.

T2. Lifecycle ownership is fragmented.
The session is created by an operator script, used by a CLI, reaped by the runtime, budgeted by the pod, and cleaned by the actor.
No component owns the lease from create to release.
R2, R4, and R5 are instances.

T3. Identity is process-level, not session-level.
The browser profile, the API session, the CDP target, and the account state are different identities.
They have no reconciliation layer.
R3, R5, and R6 are instances.

T4. Verdicts and evidence are last-writer.
The pod uses the last decision.
The loop summary uses a projected subset.
The actor posts the first result and can post a second.
There is no monotonic aggregate or per-turn idempotency.
R4, R7, and R14 are instances.

T5. Capability arming and policy have different authorities.
`write_skill` is armed while the skill forbids revisions.
A session start is allowed while the skill says reuse.
An account root write is create-only while the prompt says assert the account.
The agent must reconcile the conflict in prose.
R9 is the main instance.

T6. The test harness is not production-shaped.
The successful runs used model overrides.
The pod ran outside the module context.
The raw Postgres saver needed the app serde.
The E4 agent used a direct `create_agent` harness.
A green scenario can therefore miss the default-model, default-context, and default-serde failure.
R1, R8, R12, and R15 are instances.

T7. The CLI and skill contract is prose.
There is no generated command reference and no route-table probe.
The CLI's wait, text, cookies, and session-start shapes drift from the skill.
R9 and R11 are instances.

T8. Security is post-hoc.
The raw tool results, state files, and memory logs carry secrets by design.
Redaction happens at the export boundary or after the run.
There is no field-level taint policy at capture.
R6 and R13 are instances.

T9. Agent termination is model-decided.
The graph recursion limit is the only external bound in the E4 harness.
There is no external done predicate or partial-result contract.
R8 is the instance.
R2 and R4 interact with it because a slow loop can outlive the session.

## 6. Priority and treatment sequence

The ratings cluster into three treatment groups.

Contain before production use:

1. R6: remove cookie values from model-facing and evidence paths at the source.
   Add a names-and-flags-only cookie mode.
   Classify state and memory fields.
   Rotate any session exposed in the raw evidence.
2. R1: add a contract-error fallback or a thinking-off retry.
   Add a multi-turn preflight probe for each thinking role.
3. R2: add a session lease or heartbeat.
   Treat a released session as a typed expired state.
   Keep the prepare-before-use control until the lease exists.
4. R3: add a clear or replace mode to `sessionContext`.
   Assert the exact cookie set at create and restore.
   Diff the set before saving state.
5. R5: probe target liveness before a stretch.
   Encode the `tab new` recovery in the tool or skill.
6. R7: add a per-turn reply latch.
   Post the real result only after the turn commits.
   Give each turn an idempotency key.

Correct in the next iteration:

1. R4: aggregate the pod evidence monotonically.
   Add a session-expired terminal.
   Treat the best clean negative as a first-class result.
   Add a wall-clock and session-lifetime budget.
2. R8: add an external call and time budget.
   Return a partial report on budget exhaustion.
3. R9: generate the command and route references from schemas.
   Add a skill/CLI contract test.
   Make the start guard intent-aware.
   Give `write_skill` one authority.
4. R10: select models per workload and preflight the security prompt.
   Classify content-filter errors separately from domain infeasibility.
5. R11: add a dialog handler or a dismiss-dialogs default.
6. R12: pass `checkpoint_serde()` to the fallback.
   Assert every construction point at startup.

Harden after the correctness work:

1. R13: add a canonical invocation record.
2. R14: persist one typed loop record with the trace.
3. R15: persist the primitive JSONL.
4. Address T1 through T9 as platform invariants, not per-scenario patches.

The safest overall sequence is R6, R1, R2, R3, R5, R7, then R4, R8, R9, R10, R11, R12, then the evidence modes.

## 7. Caveats and evidence notes

The report's C1 refers to the upstream/default authn procedure and the plan's route list.
The scenario overlay in `eval/steel-e2e-395/skills/authn/SKILL.md` already contains the history-mode correction.
The residual risk is that the upstream/default skill still carries the hash assumption.

The report's Q2 says the pod observation `command` field is empty.
The command is present under `request.command` for exec observations.
The replay observation uses `request.artifact_id` and `request.overrides`.
The residual risk is schema asymmetry, not total data loss.

The exact idle-reaper threshold and the exact CDP reset mechanism were not inspected.
The behavior is observed; the mechanism is inferred.
The `--inactivity-timeout 0` pass-through was inspected in the wrapper.
The wrapper does not drop the flag.

The E4 random agent is an evaluation harness.
The production pod has its own 200-call harness cap and its own variant cap.
The E4 recursion finding is a harness and prompt risk, not a claim about the production pod.

The successful E2 and E4 runs used `qwen3.8-max`.
The successful E3 run used `glm-5.3`.
The production default failed.
The E5 state file and the prep start URLs are redacted in the local bundle.
The raw state and the pod memory log remain on the eval host and must be treated as sensitive.

The risk ratings are qualitative.
They are intended to prioritize review and containment, not to replace a formal security or reliability assessment.

