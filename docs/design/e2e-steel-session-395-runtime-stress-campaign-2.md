# Steel runtime stress campaign 2 - five further iterations

Status: complete.
Date: 2026-10-28.
Branch: `fix/395-runtime-stress-hardening`, based on `019da8ad`.
Scope: the Steel binary boundary, the MCP tool envelope, session identity and lifetime, the gateway actor, and the E2 fixture.
No remote repository was pushed.

## 1. Method and acceptance posture

This campaign continues the first five iterations with a stricter rule: an acceptance criterion names the exact error code, the policy return code, the composition return code, and the gate that must catch the shape.
The earlier suite accepted sets such as `{unknown_session, session_missing}` and `{invalid_command, cli_error}`.
Those sets are now removed.
A scenario passes only when the observed contract equals the declared contract.

Every iteration used the same loop:

1. Run a live scenario that changes runtime state or composes the tool call.
2. Record the exact envelope, the guard event, and the session catalogue.
3. Name the most upstream structural cause.
4. Add a failing test, implement the fix, and run the targeted suites.
5. Deploy to the isolated 8001 server, keep 8000 untouched, and rerun the scenario.
6. Keep evidence only when the live result matches the test.

The repeatable suite is `eval/steel-e2e-395/run_runtime_scenarios.py`.
It now runs 18 scenarios and records one explicit known limit.
The final run passes 18 of 18.

## 2. Iteration 6: the real CLI was reachable by name

### Observed failure

The MCP string gate and the guard both covered the `steel` wrapper.
The real binary was installed beside the wrapper as `/opt/localbin/steel-real`, which is on `PATH`.
A nested shell bypassed both layers:

```text
bash -c 'steel-real browser eval "1" --session wj-c2-real-bash --json'
```

The command returned rc 0, created `wj-c2-real-bash`, and produced no guard event.
The CLI's own usage text advertised `steel-real` as the command name.
A direct `steel-real` command typed at the top level was caught by the MCP string gate, but the nested shell was not.

### Root cause

The guard sat behind the wrapper, but the real binary was reachable by name.
This is a name-resolution failure, not a parsing failure.
A parser cannot protect a binary that the shell can resolve directly.

### Structural fix

The real CLI now lives at `/opt/localbin/.steel/steel`.
The directory is a private subdirectory of the persisted binary volume.
It is not a `PATH` directory, so neither `steel` nor `steel-real` resolves to the real CLI.
`steel-real` is now a symlink to the `steel` wrapper.
Both public names therefore pass through the guard.
`postrun.sh` migrates the pre-hardening layout before it replaces `steel-real` with the shim.

### Acceptance

| Shape | Gate | Result |
|---|---|---|
| `steel-real browser ...` | MCP pre-check | `unknown_session`, rc 2, no stray |
| `bash -c 'steel-real ...'` | binary guard | `unknown_session`, rc 2, one event, no stray |
| `/opt/localbin/steel-real browser ...` | MCP pre-check | `unknown_session`, rc 2, no stray |
| `steel browser ...` | normal path | unchanged |

A deliberate absolute path to the private core still bypasses the guard.
The suite records this as a known limit instead of hiding it.
Closing that path needs OS-level isolation outside this stack.

## 3. Iteration 7: the envelope contradicted its own error

### Observed failures

Two contradictions were visible in the same probe:

- `printf ... | xargs ... steel ...` returned `returncode: 123` while the error object said `unknown_session` with policy rc 2.
- `steel browser sessions --json` recorded `catalogue: unavailable` even though the command needs no catalogue and the catalogue was healthy.

The strict suite also exposed that a typo-only `shell_continue` command is stopped by the MCP pre-check before the shell runs, so `echo pre` and `echo post` never execute.
The earlier suite had accepted that shape without naming the gate.

### Root cause

The envelope let the shell's return code override the authoritative policy error.
The trace inferred the catalogue state from a missing live set instead of the verification fact.
The suite did not distinguish the whole-command pre-check from the per-invocation binary guard.

### Structural fix

- When a guard event carries an error, the envelope's `returncode` follows that event.
- The composition's own return code is preserved as `shell_returncode` when it differs.
- The guard event records `catalogue` as `live`, `unavailable`, or `not-required`, never inferred from `None`.
- The scenario suite declares the exact gate for every composition shape.

### Acceptance

The final suite checks:

- exact error code per shape;
- policy rc 2 for every refused invocation;
- exact shell rc (`123` for `xargs`, `2` for an unexecuted shell continuation);
- the expected gate (`mcp_precheck` or `binary_guard`);
- no stray session;
- direct-versus-masked equality of code, message, and stderr.

The `xargs` case now returns rc 2 with `shell_returncode: 123`.
The `sessions` trace now says `not-required`.

## 4. Iteration 8: creation was not recorded, and the registry could lose writes

### Observed failures

A session started through the tool was not remembered until the next catalogue query.
The catalogue is queried before the start, so it cannot contain the new name.
If the session died before the next query, the loss classified as `unknown_session`, not `session_missing`.
The registry also performed an unlocked read-modify-write from the MCP process and from one short-lived guard process per command.

### Root cause

The creation event was not a registry input.
The registry had atomic replacement but no serialization, so concurrent writers could drop each other's sessions.

### Structural fix

- The guard records a successful `start` immediately.
- The guard event carries the runtime `session_id` and `remaining_ms` from the start response.
- The MCP records a successful start as a belt-and-braces path for an unguarded deployment.
- `record_live_sessions` takes an advisory `flock` around the read-modify-write.
- A failed start is never recorded.

### Live verification

A session was started through the tool, then stopped through the private core, which bypasses the guard and the catalogue.
The start event carried `session_id: 103683eb-...` and `remaining_ms: 58783`.
The next command returned `session_missing`, `fatal: true`, recovery `recreate_session`, and `requires_state_restore: true`.
The repeatable suite covers the same chain as `session_lifecycle/start_then_loss`.

### Tests

- A successful start is recorded.
- A failed start is not recorded.
- The start trace carries the runtime id and lifetime.
- A start followed by a catalogue-invisible stop classifies as a loss.
- Eight concurrent registry writers keep every name.

## 5. Iteration 9: the saver closed while the turn was still settling

### Observed failure

The gateway log repeatedly showed:

```text
actor turn degraded on ...: the connection is closed (the actor survives)
```

The real verdict was delivered first, then the duplicate no-decision reply was suppressed by the earlier turn-id fix.
The underlying close remained.

### Root cause

The delivery middleware posts the reply at the end of the graph turn.
The graph's final checkpoint write lands a moment later.
The E2 controller closed the `AsyncPostgresSaver` context before it called `actor.stop()`.
The actor's last write therefore raced a closed connection.
The controller also read the checkpoint before the actor stopped.

### Structural fix

- `run_session_agent` gains `on_turn_complete(turn_id)`, which fires after every turn returns or degrades, including on cancellation.
- `ReconOrchestratorActor` waits for that signal after a reply, bounded by `TURN_SETTLE_TIMEOUT_S` (30s).
- The E2 controller stops the actor inside the saver context and reads the trace only after the stop.
- A graceful stop still has its 120s bound and the explicit `cancel()` fallback.

### Additional live findings in this iteration

The first E2 attempts produced two separate harness defects.

- The run used `--session wj-c2-gateway` while the seeded skill designates `wj-gateway-e2e`.
  The model refused to reuse the differently named session and emitted a correct `failed` verdict.
  The harness now fails fast when the seeded skill does not name the run session.
- The skill metadata version was `2.0-steel-e2e`, which is not a bumpable semver.
  The model's `write_skill` write-back failed with `skill_invalid`.
  The version is now `2.0.0`, and the live run returns `{"ok": true, "skill": "authn", "target": "procedure"}`.
- The shared target's `/api/admin/user` route returns `{"code":400}` even after the orphan role rows were removed.
  The exact cause was not isolated; the route remained broken after that repair.
  The fixture now proves the same `sysAdmin` capability through `/api/admin/role`, which returns code 200.
  The `prepare` script now gates on code 200 and `sysAdmin` and exits non-zero otherwise.

### Acceptance

The final E2 run returned:

- `ok: true`
- `verdict_ok: true`
- `status_write_ok: true`
- `secret_leak: false`
- `stop_error: null`
- `error: null`
- `verdict: authenticated`
- 7 `steel_exec` calls
- 1 `write_skill` call, returned ok
- 1 `record_skill_lesson` call, base version `2.0.0`
- session live true

The trace contains no `connection is closed` and no `no-decision` line.

## 6. Iteration 10: the zero inactivity value reaped fixtures

### Observed failure

Sessions prepared with `--inactivity-timeout 0` disappeared after roughly two minutes of idle time.
A fresh fixture could be live during preparation and absent by the next suite run.
A re-preparation with the same name sometimes found a stale live entry, skipped the start, and then failed the cookie set.
A piped `prepare ... | tail -1` also hid the non-zero prepare exit.

### Root cause

The deployed Steel daemon does not treat `0` as the fixture expects.
A session created with zero is still reaped on the default inactivity window.
The run needs a positive, explicit inactivity window.
The harness also needs to treat the prepare exit as an acceptance gate.

### Structural fix

- The fixture starts with `--inactivity-timeout 86400000` (24 hours).
- The prepare summary records `inactivity_timeout_ms`.
- The prepare exits non-zero unless the session is live, both cookies are set, the auth marker is present, the admin role probe returns 200 with `sysAdmin`, and the document cookie stays empty.
- The start-then-loss scenario uses the same finite window.

### Live verification

A session started with `--inactivity-timeout 86400000` reported `inactivityTimeoutMs: 86400000`.
It survived 241 seconds idle and was then stopped cleanly.
The final strict suite then passed 18 of 18 with `wj-c2-masked` and `wj-c2-loss` both prepared at `inactivity_timeout_ms: 86400000`.

## 7. Strict acceptance matrix

The final suite result is `eval/steel-e2e-395/evidence-runtime-stress-2/scenarios/runtime-scenarios.json`.

| Scenario group | Count | Acceptance |
|---|---|---|
| Composition, public names | 12 | exact code `unknown_session`, rc 2, expected gate, no stray |
| Masked failure | 2 | same code, message, stderr as unmasked, rc 2, shell rc 0 |
| Known session loss | 1 | `session_missing`, fatal, `recreate_session`, rc 2 |
| Start then loss | 1 | created session recorded, then `session_missing` with state restore |
| Timeout cleanup | 1 | rc 124, no surviving child |
| Catalogue trace | 1 | `not-required`, never `unavailable` |
| Known limit | 1 | private-core absolute path recorded and cleaned |

The private-core probe created a session, stopped it, and recorded the residual bypass.
It is not counted as a pass for the guard.
It is an explicit limit of name-based isolation.

## 8. Verification totals

The final targeted suite passes 690 tests.
It covers:

- `tests/kali`
- `tests/attack/pod`
- the auth-store read/write and read-only tiers
- `tests/test_llm_actor.py`
- `tests/recon/test_orchestrator_actor.py`
- `tests/recon/test_pipeline_gateway.py`
- `tests/recon/test_skill_task_binding.py`
- `tests/recon/test_exec_result_http_refs.py`
- `tests/test_llm_checkpoints_module.py`
- `tests/test_steel_wrapper.py`
- `tests/test_steel_cli_delivery.py`
- `tests/integration/test_steel_endpoint_contract.py`

Live verification:

- E2 gateway: authenticated, `secret_leak: false`, no duplicate reply, no connection close, clean stop.
- Runtime scenarios: 18 of 18.
- Start-then-loss: `session_missing` with `requires_state_restore: true`.
- Four-minute idle session: alive with the finite inactivity window.
- 8001 runs the final local package; 8000 remains untouched.

## 9. Failure ledger mapping

| ID | Finding | State after this campaign |
|---|---|---|
| RS-10 | `steel-real` reachable by name in a nested shell | Fixed: private core plus wrapper shim |
| RS-11 | Envelope rc contradicts the guard error | Fixed: authoritative rc plus `shell_returncode` |
| RS-12 | Trace says `catalogue: unavailable` for a command that skips it | Fixed: explicit catalogue fact |
| RS-13 | Created session not recorded before the next query | Fixed at the guard and MCP |
| RS-14 | Registry read-modify-write loses concurrent writes | Fixed with `flock` |
| RS-15 | Saver closed before the actor's final checkpoint write | Fixed with turn settlement and in-context stop |
| RS-16 | Skill version is not semver, so `write_skill` fails | Fixed: `2.0.0` |
| RS-17 | Harness session name contradicts the seeded skill | Fixed with a fail-fast name check |
| RS-18 | Shared-target `/api/admin/user` returns code 400 | Fixture moved to the healthy `/api/admin/role` route |
| RS-19 | Zero inactivity timeout reaps fixtures after about two minutes | Fixed with a finite 24h window |
| RS-20 | Piped prepare hides its non-zero exit | The prepare now exits non-zero and the suite fails its precondition; the operator must not pipe it |

## 10. Remaining issues

- A deliberate absolute path to the private core still bypasses the guard.
  Closing it needs process or filesystem isolation, not a parser rule.
- The guard and the MCP pre-check fail open when the catalogue is unavailable.
  The real CLI then reports the runtime failure.
- A fresh runtime with an empty registry still classifies a loss that happened before any catalogue query as `unknown_session`.
- The shared target's `/api/admin/user` route remains broken.
  The fixture no longer depends on it, but the target defect is still present.
- The provider's content filter rejects some admin-probe prompts intermittently.
  The successful run and the redacted auth-store view show this is not a secret leak.
- The shared Steel runtime can lose sessions to other agents' cleanup.
  The finite inactivity window fixes the fixture's own lifetime, not external stops.
- State mount isolation, the pod E3 `clean: false` result, the production default-model contract, and raw evidence sensitivity remain outside this campaign.
- The raw target session and the pod memory remain sensitive on the eval host.
  The committed evidence contains no token or cookie value.

## 11. Artifacts

- `kali/steel_wrapper.sh`: private-core default and public-name routing.
- `kali/steel_guard.py`: private real binary, start recording, registry lock, catalogue fact, start metadata.
- `kali/postrun.sh`: private-core install and `steel-real` shim migration.
- `kali/mcp_server.py`: authoritative error rc, `shell_returncode`, start recording, compact start metadata.
- `src/polymerhus/app/llm/actor.py`: turn-completion signal.
- `src/polymerhus/recon/control/orchestrator_agent.py`: gateway settlement wait.
- `eval/steel-e2e-395/run_gateway_e2e.py`: in-context stop, trace after settle, session-name guard.
- `eval/steel-e2e-395/prepare_steel_session.py`: finite inactivity window, role probe, strict exit gate.
- `eval/steel-e2e-395/skills/authn/SKILL.md`: semver version and role probe.
- `eval/steel-e2e-395/run_runtime_scenarios.py`: 18-scenario strict suite with the gate matrix.
- `eval/steel-e2e-395/evidence-runtime-stress-2/e2-gateway/`: final E2 summary, verdict, and trace.
- `eval/steel-e2e-395/evidence-runtime-stress-2/scenarios/runtime-scenarios.json`: final 18 of 18 result.

## 12. Commits

- `e4656e61` `fix: keep the steel cli off path behind the guard`
- `2f99fa74` `fix: make the tool envelope agree with the guard error`
- `7e490290` `fix: record a session at creation and serialize the registry`
- `a66cdee7` `fix: settle the gateway turn before the saver closes`
- `578bd275` `fix: keep the fixture session alive with a finite inactivity window`

The branch is local only.
No remote was pushed.
