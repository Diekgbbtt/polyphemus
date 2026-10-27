# Steel runtime stress campaign - five iterations

Status: complete.
Date: 2026-10-27.
Branch: `fix/395-runtime-stress-hardening`, based on `019da8ad`.
Scope: the live Steel tool stack, the pod exec path, the gateway actor, and the auth-store model view.
No remote repository was pushed.

## 1. Method

Each iteration followed the same loop:

1. Run a live E2E scenario that changes runtime state or composes the tool call in a realistic way.
2. Record the exact observed result, including the legacy envelope, the error code, the recovery, and the session catalogue.
3. Identify the most upstream structural cause, not the first visible symptom.
4. Add a failing test, implement the smallest structural fix, and run the targeted suites.
5. Deploy the fix to the isolated 8001 server, keep 8000 untouched, and rerun the scenario.
6. Keep the evidence only when the live result matches the test.

The repeatable suite is `eval/steel-e2e-395/run_runtime_scenarios.py`.
It produces `runtime-scenarios.json` and runs 13 scenarios.
The final run passes 13 of 13.

## 2. Iteration 1: shell composition bypassed the string gate

### Observed failure

The MCP sanitizer parsed the command string.
The real execution used `shell=True`.
Seven of eight compositions executed a Steel command with a typo session and created a stray session.

| Shape | Before: error | Before: stray | After: error | After: stray |
|---|---|---|---|---|
| `steel_exec` script mode | none, rc 0 | `wj-bp-script` | `unknown_session` | none |
| `bash -c 'steel ...'` | none, rc 0 | `wj-bp-bash` | `unknown_session` | none |
| `env steel ...` | none, rc 0 | `wj-bp-env` | `unknown_session` | none |
| `command steel ...` | none, rc 0 | `wj-bp-command` | `unknown_session` | none |
| `sh -c 'steel ...'` | none, rc 0 | `wj-bp-sh` | `unknown_session` | none |
| `PATH=... steel ...` | none, rc 0 | `wj-bp-path` | `unknown_session` | none |
| `xargs ... steel ...` | none, rc 0 | `wj-bp-xargs` | `unknown_session` | none |
| `/opt/localbin/steel ...` | `unknown_session` | none | `unknown_session` | none |

The absolute path was the only shape the string scanner caught.

### Root cause

The gate validated a string, but the shell executed a process tree.
A string-level parser cannot see a nested shell, `env`, `command`, `xargs`, a script, or a variable expansion.
The defect is the parse/execute mismatch, not a missing grammar rule.

### Structural fix

`kali/steel_guard.py` is a Python executable placed behind the deployed `steel` wrapper as `STEEL_REAL_BINARY`.
Every real CLI invocation now passes through one policy and telemetry point.
The guard:

- reuses `kali.steel_contract` for the policy;
- refuses a missing, unknown, or colliding session before the real binary runs;
- records one JSON event per invocation, including the true exit code and output tails;
- classifies the real result with the same classifier.

`kali/mcp_server._run` and `kali/http_history.service.default_runner` set `KALI_STEEL_TRACE` per exec.
The MCP layer merges the trace events into the tool result.
`kali/steel_guard.py` is also the chokepoint for `steel_exec` script mode.
The first deployment failed because the guard file had no shebang; the wrapper executed it as a shell script.
A regression test now asserts the shebang and the executable bit.

### Verification

- The final composition suite passes 9 of 9.
- No stray session remains after any shape.
- `steel browser sessions --json` still succeeds.
- A script with no Steel call still runs normally.
- `tests/kali/test_steel_guard.py`, `tests/kali/test_mcp_steel_gate.py`, and `tests/kali/test_steel_contract.py` cover the policy.

## 3. Iteration 2: session loss was indistinguishable from a typo

### Observed failure

A live session was stopped and then addressed again.
The tool returned `unknown_session`, `fatal: false`, recovery `use_live`.
That tells the agent to pick a live session, not to recreate the lost authenticated state.

### Root cause

The sanitizer had one live-set input and no memory.
It could not tell `wj-typo`, which never existed, from `wj-live`, which existed and disappeared.

### Structural fix

`kali/steel_guard.py` now maintains a bounded session registry at `KALI_STEEL_SESSION_REGISTRY`.
The default is `/tmp/kali-steel-sessions.json` with a 24-hour TTL.
The guard and `_live_session_names` record every live catalogue result.
`sanitize_steel_command` accepts `known_sessions`.
A known name that is no longer live returns `session_missing` with `fatal: true` and recovery `recreate_session` plus `requires_state_restore: true`.
A never-seen name still returns `unknown_session` with recovery `use_live`.

### Verification

Live sequence:

1. `get url --session wj-stress-3` returns rc 0.
2. `stop --session wj-stress-3` returns rc 0.
3. `eval --session wj-stress-3` returns `session_missing`, fatal true, recovery `recreate_session`, `requires_state_restore: true`.
4. `eval --session wj-never-seen` returns `unknown_session`, fatal false, recovery `use_live`.
5. The same loss through `bash -c` returns `session_missing` from the guard event.

The repeatable suite covers this as `session_loss/known_session_disappears`.

### Additional result in this iteration

The guard trace also fixed masked failures.
A selectorless `get text` behind `2>/dev/null || true` returned `invalid_command` with the CLI error, even though the shell exit was 0.
A second-command failure in `echo pre; steel ...; echo post` returned `invalid_command` while preserving `pre` and `post` in stdout.
The suite covers both as `masked/output_suppression` and `masked/second_command`.

## 4. Iteration 3: a timeout killed the shell but not its children

### Observed failure

`execute_command` ran `bash -c 'sleep 137 & wait'` with `timeout_s=2`.
The tool returned rc 124.
The `sleep 137` child survived after the shell was killed.

### Root cause

`subprocess.run(timeout=...)` kills only the direct child.
It does not create a process group and does not kill descendants.
The same shape existed in `_run`, `default_runner`, and the guard's real-binary call.

### Structural fix

`kali/process_group.py` starts every command with `start_new_session=True`.
On timeout it kills the whole process group with `SIGKILL`, reaps the child, and returns rc 124.
The MCP `_run`, the HTTP-history `default_runner`, the guard's real-binary call, and the guard's catalogue query all use it.
A normal exit does not kill the group, so an intentional background job is not destroyed.

### Verification

- `tests/kali/test_process_group.py` proves the background child is gone after a timeout.
- Live `bash -c 'sleep 211 & wait'` with `timeout_s=2` returns rc 124 and the Kali container has no surviving `sleep` process.
- The pre-fix `sleep 137` process was found and removed during the iteration.

## 5. Iteration 4: turn delivery was not idempotent, and the first attempt was unbounded

### Observed failures

The gateway log showed two symptoms:

- `actor turn degraded ... the connection is closed (the actor survives)`
- `... posting a no-decision reply`

The controller received the real `GatewayVerdict` first, then a second no-decision reply for the same turn.
A later gateway run also hung for the full 25-minute tool timeout.
The first model attempt had `read_timeout_s=None`, so it was not bounded by the attempt schedule.

### Root cause

The delivery middleware posts the real result at `after_agent`.
A checkpointer connection close after that post marked the turn degraded.
The degraded hook then posted a second reply for the same logical turn.
The delivery had no turn identity.
The first attempt was also outside the schedule, and the harness stop waited on the stuck actor.

### Structural fix

- `actor.py` sets a `_CURRENT_TURN_ID` context variable for every logical turn.
- The delivery middleware and the degraded hook share a per-pair delivery set.
- A turn that already delivered its real result never posts a no-decision or a retry duplicate.
- A new turn still posts its own degraded reply.
- The first model attempt now uses `schedule[attempt]`; all attempts are bounded.
- `ReconOrchestratorActor.cancel()` cancels a stuck actor task.
- The gateway controller calls `cancel()` only after a 120-second graceful `stop()` times out.

### Verification

- `tests/test_llm_actor.py` covers the real-then-degraded duplicate, the retry duplicate, a new-turn degraded reply, and the first-attempt budget.
- The live E2 run shows the `connection is closed` degrade line but no `posting a no-decision reply` line.
- The controller receives one real verdict.
- The 25-minute hang is gone; the short-budget run returns with a clear timeout and a written summary.

The underlying post-delivery connection close still exists.
It is now contained: it cannot produce a second reply.

## 6. Iteration 5: the auth-store model view leaked session secrets

### Observed failure

The E2 trace contained `secret_leak: true`.
The `auth_store read` tool returned the full account record, including:

- `tokens.JSESSIONID.value`
- `snapshot.cookies[].value` for `JSESSIONID` and `rememberMe`

The same run then received a provider 400:

```
[data_inspection_failed] Input text data may contain inappropriate content
```

The gateway degraded and timed out after 180 seconds.

### Root cause

The read-only `auth_store` binding applied `redact_auth_state`.
The read/write binding used by the gateway did not.
The model saw the raw session token.
The provider content filter rejected the prompt.
The secret leak was upstream of the model 400 and the gateway timeout.

### Structural fix

The read/write `auth_store` read path now calls `redact_auth_state` before the dotted projection.
The model-facing view carries names, shapes, and statuses, never token, password, cookie, header, or param values.
The store keeps the material for the gateway's internal replay seam.
The write echo still returns the model's own input; it is not a stored-secret read.

### Verification

- `tests/app/test_auth_store_tool.py` covers password, token, cookie, header, and param redaction.
- The tests also prove the store still holds the raw values.
- The final live E2 run returns:
  - `ok: true`
  - `verdict_ok: true`
  - `status_write_ok: true`
  - `secret_leak: false`
  - `error: null`
  - session live true
  - 7 browser commands
- The content-filter 400 did not recur after the redaction.
  The causal link is strong but observational: the raw-token run failed, the redacted run succeeded.

## 7. Repeatable scenario suite

`eval/steel-e2e-395/run_runtime_scenarios.py` runs 13 scenarios:

- 9 composition shapes: script, `bash -c`, `env`, `command`, `sh -c`, `PATH=`, absolute path, `xargs`, shell continuation.
- 2 masked-failure shapes: output suppression and a second-command failure.
- 1 session-loss shape: known live, then stopped, then `session_missing`.
- 1 timeout shape: background-child cleanup.

The final run passes 13 of 13.
The suite requires two freshly prepared sessions:

- `--session` for the masked scenarios.
- `--loss-session` for the loss scenario; the suite stops it.

The first suite run failed for two harness reasons, both fixed:

- The stray check matched every `wj-scenario-*` name and stopped the prepared loss session.
  It now checks only the exact session used by the current case.
- The masked session had expired before the suite ran, so the scenarios correctly returned `session_missing`.
  The runner now fails a live precondition instead of treating the missing session as a masked-failure result.

## 8. Verification totals

The final targeted suite passes 628 tests:

- `tests/kali`
- `tests/attack/pod`
- `tests/app/test_auth_store_tool.py`
- `tests/app/test_auth_store_tool_readonly.py`
- `tests/app/test_auth_account_facts.py`
- `tests/test_llm_actor.py`
- `tests/recon/test_skill_task_binding.py`
- `tests/recon/test_exec_result_http_refs.py`
- `tests/test_llm_checkpoints_module.py`

One unrelated stale test fixture was fixed:
`tests/recon/test_skill_task_binding.py` passed only `skills` to `SpecWrite`, which now requires `status`, `fault_keyword`, `strategy_keyword`, and `target_identity`.

Live verification:

- E2 gateway: authenticated, `status_write_ok: true`, `secret_leak: false`, one verdict, no duplicate.
- Runtime scenarios: 13 of 13.
- 8001 runs the final local package; 8000 remains untouched.

## 9. Failure ledger mapping

| ID | Finding | State after the campaign |
|---|---|---|
| FF-02 | CDP target reset | `target_lost` with `tab_new` and `recreate_session` fallback; not re-triggered in the final runs |
| FF-03 | Session absent or expired | Improved: known loss returns `session_missing` with `recreate_session`; session idle lifetime remains operational |
| FF-05 | Typo creates a stray session | Fixed at the binary boundary for 9 composition shapes |
| FF-06 | Masked CLI failure | Fixed: the guard trace reports the true failure behind suppression and multi-command shells |
| FF-07 | Pod last-lap verdict | Unchanged; the pod verdict is outside this campaign |
| FF-08 | Fresh state inherits cookies | Unchanged; state mount isolation is still out of scope |
| FF-10 | E4 thread and trace extraction | Unchanged from the prior fix; not rerun in this campaign |
| FF-11 | E2 dead-session metric | Unchanged from the prior fix; not rerun in this campaign |
| FF-12 | Reporting and serde | Serde remains fixed; loop phase fields still null |
| RS-01 | Shell composition bypass | Fixed |
| RS-02 | Masked and multi-command failure | Fixed |
| RS-03 | Session loss misclassified as a typo | Fixed |
| RS-04 | Timeout orphan process | Fixed |
| RS-05 | Duplicate actor reply | Fixed at the delivery boundary |
| RS-06 | Unbounded first attempt and hung shutdown | Fixed |
| RS-07 | Auth-store secret leak and provider content filter | Fixed for the model read path |
| RS-08 | Scenario runner false stray and expired-session precondition | Fixed in the runner |
| RS-09 | Stale `SpecWrite` fixture | Fixed |

## 10. Remaining issues

- The Steel session still expires after a long idle period. The tool now reports a known loss correctly, but the session-only fixture cannot recreate the authenticated state without operator input.
- The session registry is process-local on disk and has a 24-hour TTL. A fresh runtime with an empty registry still reports `unknown_session` for a session that died before any catalogue query.
- The guard fails open when the live catalogue is unavailable. The MCP pre-check has the same policy. A catalogue outage can still let a direct command through to the real CLI, which then reports the runtime failure.
- The `xargs` composition returns the shell's rc 123 while the error object is `unknown_session`. The error object is authoritative, but the legacy returncode is not normalized.
- The gateway log still shows a post-delivery `connection is closed` degrade. The duplicate reply is suppressed, but the underlying checkpointer connection close remains.
- The pod E3 `clean: false` remains coverage-driven. The negative is honest, but the pod verdict is outside this campaign.
- The shared white-jotter target account remains mutable by other agents. The fixture must be checked before a campaign.
- State mount isolation remains out of scope; E5 foreign-cookie inheritance is unchanged.
- The production default model's reasoning-content 400 is unchanged; the eval model override still masks it.
- Raw pod memory and raw auth state remain sensitive on the eval host. The committed evidence is redacted.
- Script mode is now guarded at the binary boundary. The MCP pre-check still treats script text as trusted; the guard is the enforcement point.

## 11. Artifacts

- `kali/steel_guard.py`: binary-boundary policy, registry, trace.
- `kali/process_group.py`: process-group timeout cleanup.
- `kali/steel_contract.py`: known-session loss semantics.
- `kali/mcp_server.py`: trace merge and session registry.
- `kali/http_history/service.py`: trace-aware runner.
- `src/polymerhus/app/llm/actor.py`: turn-scoped delivery dedupe and first-attempt bound.
- `src/polymerhus/recon/control/orchestrator_agent.py`: forced actor cancellation.
- `src/polymerhus/app/auth/tool.py`: redacted read/write model view.
- `eval/steel-e2e-395/run_runtime_scenarios.py`: repeatable 13-scenario suite.
- `eval/steel-e2e-395/evidence-runtime-stress/e2-gateway/`: E2 summary, verdict, and redacted trace.
- `eval/steel-e2e-395/evidence-runtime-stress/scenarios/runtime-scenarios.json`: final 13 of 13 result.

## 12. Commits

- `129f28c0` `fix: enforce steel sessions at the binary boundary`
- `c8812f9d` `fix: distinguish a lost steel session from a typo`
- `f635564a` `fix: kill the whole process group on a tool timeout`
- `20e1db78` `test: refresh the SpecWrite required-field fixture`
- `9a3b3615` `fix: bound the first model turn and retire a stuck actor`
- `33a59eba` `fix: redact auth store secrets from the model view`
- `692de1f2` `chore: mark the steel guard executable`
- `d7bbba2e` `test: isolate the runner tier from the deployed guard`

The branch is local only.
No remote was pushed.
