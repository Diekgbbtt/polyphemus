# Steel browser tool-contract hardening plan

Status: active.
Date: 2026-10-26.
Branch: `fix/395-tool-contract-hardening`.
Goal: remove the run-fatal and trial-degrading failure modes that are owned by the Steel browser tool stack.

## 1. Scope and ownership

In scope:

- Entry 1: the browser tool surface in `kali/mcp_server.py`.
- Entry 2: the downstream exec surface in `kali/mcp_server.py` and the pod `ExecTool`.
- Entry 3: the pod tool-error and clean path, kept fail-open.
- Entry 4: structured browser-error semantics and recovery directives.
- Entry 7: the checkpoint fallback serde.
- Entry 6: eval-harness corrections only.

Out of scope:

- Entry 5: state mount isolation in `steel_session_state.py`.
- App-level model-contract fallback in `transient.py` and `actor.py`.
- Steel CLI/API internals.

Ownership model:

- `steel_exec` is the tool-stack entry and the owner of the modular sanitization layer.
- The sanitizer lives in `kali/steel_contract.py`.
- `execute_command` is the downstream executor.
- `execute_command` re-applies the same sanitizer to embedded `steel browser` commands, so the pod path cannot bypass the gate.
- The sanitizer does not replicate the Steel CLI grammar and does not rewrite clear CLI errors.
- The sanitizer covers contextual and state gaps the bare CLI does not cover.

## 2. Error contract

Every refusal or classified browser failure adds these fields to the existing envelope:

```json
{
  "error": {
    "code": "target_lost",
    "message": "The session is live but its page target is missing.",
    "retryable": false,
    "fatal": false,
    "session": {"name": "wj-example", "live": true},
    "recovery": {
      "action": "tab_new",
      "reason": "Create a fresh page target in the same browser context.",
      "command": "steel browser tab new --session wj-example --json",
      "fallback": "recreate_session"
    }
  }
}
```

The existing `stdout`, `stderr`, `returncode`, and `duration_ms` fields stay unchanged.

The codes:

| Code | Meaning | Fatal | Recovery |
|---|---|---|---|
| `missing_session` | A session-bound browser command has no `--session` | false | `fix_command` |
| `unknown_session` | The named session is not in the live catalogue | false | `start_session` or `reuse_live` |
| `session_taken` | An explicit `start` names a live session | false | `reuse_live` or choose a new name |
| `session_missing` | The session disappeared after the check | true | `recreate_session` with state restore |
| `target_lost` | The session is live but its CDP page target is gone | false | `tab_new`, fallback `recreate_session` |
| `browser_unavailable` | The runtime or websocket is unreachable | true | `recreate_session` |
| `browser_stuck` | A browser command timed out or the page is blocked | true | `recreate_session` |
| `invalid_command` | The CLI rejects the command arguments | false | `fix_command` |
| `cli_error` | A composed shell command hid a CLI error behind a zero exit | false | `fix_command` |
| `empty_target` | A page read succeeded against a blank target | false | `tab_new` |
| `command_failed` | A non-browser command failed | false | `inspect` |

The sanitizer never creates a session automatically.
The sanitizer returns `recovery.command` and `recovery.requires_state_restore` for the agent to execute.
The pod runner remains fail-open: a tool error is recorded and returned to the model, not raised.

## 3. File structure

- Create `kali/steel_contract.py`: pure parsing, contextual validation, result classification, error envelope.
- Modify `kali/mcp_server.py`: call the sanitizer from `steel_exec` and `execute_command`; classify results; extend `_refused`.
- Modify `src/polymerhus/recon/domain/types.py`: additive `ExecResult` error fields.
- Modify `src/polymerhus/recon/domain/pod.py`: map the structured artifact fields into `ExecResult`.
- Modify `src/polymerhus/attack/hunting/pod/types.py`: additive `RawObservation` error fields.
- Modify `src/polymerhus/attack/hunting/pod/tools.py`: record errors, return `TOOL ERROR`, stop retrying fatal results.
- Modify `src/polymerhus/attack/hunting/pod/graph.py`: record the contract-tier error fields; keep the runner fail-open; make `_clean_from_trail` reject tool-error observations.
- Modify `src/polymerhus/app/llm/checkpoints.py`: pass `checkpoint_serde()` to the fallback.
- Modify eval harness controllers for the re-run: status metric, pod module context, random-agent thread id and trace extraction.
- Create `tests/kali/test_steel_contract.py`.
- Create `tests/kali/test_mcp_steel_gate.py`.
- Extend `tests/attack/pod/test_tools.py`, `tests/attack/pod/test_graph.py`, `tests/test_llm_checkpoints_module.py`.

## 4. Task 1: pure contract module

Files:

- Create `kali/steel_contract.py`.
- Create `tests/kali/test_steel_contract.py`.

Public interface:

```python
@dataclass(frozen=True)
class ContractError:
    code: str
    message: str
    retryable: bool
    fatal: bool
    recovery: dict | None = None
    suggestion: str | None = None
    session: str | None = None
    platform_state: dict | None = None
    canonical_command: str | None = None

    def envelope(self) -> dict: ...

@dataclass(frozen=True)
class BrowserCommand:
    verb: str
    session: str | None
    tokens: tuple[str, ...]
    canonical: str

def sanitize_steel_command(
    command: str,
    *,
    live_sessions: set[str] | None,
) -> BrowserCommand | ContractError: ...

def sanitize_shell_command(
    command: str,
    *,
    live_sessions: set[str] | None,
) -> tuple[BrowserCommand, ...] | ContractError: ...

def classify_result(
    command: str,
    result: dict,
    *,
    session: str | None,
    live_sessions: set[str] | None,
) -> dict: ...
```

Rules:

- Parse with `shlex` and shell separators.
- Do not validate verb-specific positional arguments; the Steel CLI owns that grammar.
- Do not rewrite `cookies list`; the CLI error is clear.
- Require `--session` for every browser verb except `sessions` and `live`.
- Reject a missing `--session` with `missing_session`.
- Reject a session not in the live catalogue for a non-start command with `unknown_session`.
- Allow an explicit `start` only when the name is not live.
- Refuse a `start` on a live name with `session_taken`.
- Keep the variadic `--` boundary guard.
- Keep the existing wait-ordering guard in `mcp_server.py`.
- Recognize `Session with given id not found` and `CDP error` as `target_lost` when the session is live.
- Recognize missing-session errors as `session_missing`.
- Recognize timeouts and returncode 124 as `browser_stuck`.
- Recognize connection and websocket failures as `browser_unavailable`.
- Recognize CLI `error:` and `Usage:` text as `cli_error` when the shell returncode is zero.
- Add `empty_target` as a warning only when a later target probe confirms `about:blank`.

Tests:

1. `test_missing_session_is_rejected_before_execution`
2. `test_unknown_session_is_rejected_without_creating_a_session`
3. `test_live_session_is_allowed_for_navigate`
4. `test_start_on_live_session_is_refused`
5. `test_start_on_absent_session_is_allowed`
6. `test_cookies_list_is_not_rewritten_and_passes_the_cli_error`
7. `test_target_lost_returns_tab_new_recovery`
8. `test_session_missing_returns_recreate_session`
9. `test_browser_stuck_returns_fatal_recreate_session`
10. `test_connection_refused_returns_browser_unavailable`
11. `test_shell_scan_validates_embedded_steel_commands`
12. `test_clear_cli_error_behind_zero_exit_is_classified`
13. `test_error_envelope_is_additive`

Red-green steps:

- [ ] Write test 1.
- [ ] Run `tests/kali/test_steel_contract.py::test_missing_session_is_rejected_before_execution`; expect failure.
- [ ] Add the minimum parser and `ContractError`; run the test; expect pass.
- [ ] Repeat for tests 2 to 13, one test at a time.
- [ ] Run `tests/kali/test_steel_contract.py -q`; expect all pass.
- [ ] Commit: `feat: add steel browser contract sanitizer`.

## 5. Task 2: MCP gate integration

Files:

- Modify `kali/mcp_server.py`.
- Create `tests/kali/test_mcp_steel_gate.py`.

Behavior:

- `_steel_exec_sync` calls `sanitize_steel_command` before any execution.
- On a contract error, return `error.envelope()` plus an empty `stdout` and a nonzero `returncode`; never call `_run`.
- `execute_command` calls `sanitize_shell_command` when the command contains a `steel` token; on error, return the error envelope; never call the service.
- After a successful run, call `classify_result` and merge the result fields.
- Extend `_refused` to include `error.code`, `error.message`, `error.fatal`, and `error.recovery`.
- Keep the existing `not-steel-command`, `steel-version-mismatch`, `timeout-ordering`, `session-taken`, and `variadic-boundary` refusals.
- Do not add a `cookies list` rewrite.

Tests:

1. `test_steel_exec_rejects_unknown_session_without_running`
2. `test_steel_exec_allows_live_session_and_classifies_target_lost`
3. `test_execute_command_rejects_embedded_unknown_session_without_running`
4. `test_execute_command_passes_non_steel_shell`
5. `test_steel_exec_preserves_cli_error_for_cookies_list`
6. `test_refused_envelope_carries_recovery`

Red-green steps:

- [ ] Write test 1 with monkeypatched `_run` and `_live_session_names`; assert the runner is not called.
- [ ] Run; expect failure.
- [ ] Add the `_steel_exec_sync` gate; run; expect pass.
- [ ] Add tests 2 to 6 one at a time.
- [ ] Run `tests/kali/test_mcp_steel_gate.py -q`; expect pass.
- [ ] Commit: `feat: gate steel commands through the contract sanitizer`.

## 6. Task 3: pod error propagation and fail-open runner

Files:

- Modify `src/polymerhus/recon/domain/types.py`.
- Modify `src/polymerhus/recon/domain/pod.py`.
- Modify `src/polymerhus/attack/hunting/pod/types.py`.
- Modify `src/polymerhus/attack/hunting/pod/tools.py`.
- Modify `src/polymerhus/attack/hunting/pod/graph.py`.
- Extend `tests/attack/pod/test_tools.py`, `tests/attack/pod/test_graph.py`.

`ExecResult` gains:

```python
error_code: str = ""
error_message: str = ""
retryable: bool | None = None
fatal: bool | None = None
recovery: dict | None = None
canonical_command: str | None = None
session_state: dict | None = None
```

`RawObservation` gains the same fields, all optional with empty defaults.

Behavior:

- `_exec_result_from_artifact` maps the new keys.
- `ExecTool._record` copies the fields into the observation.
- `ExecTool._record` returns `TOOL ERROR: code=... message=... recovery=...` when `error_code` is set.
- `run_with_retry` stops immediately when `fatal is True` or `retryable is False`.
- The contract-tier `tool_exec` copies the fields and returns the same `TOOL ERROR` shape.
- `_clean_from_trail` returns false when an observation has an `error_code`.
- The runner does not raise; it sees the error and continues.
- No pod terminal vocabulary change.
- No automatic session creation.
- A fatal browser error tells the agent to recreate the session through the error's recovery directive.

Tests:

1. `test_exec_result_maps_structured_error_fields`
2. `test_exec_tool_records_error_and_returns_tool_error`
3. `test_run_with_retry_stops_on_fatal_error`
4. `test_clean_from_trail_rejects_error_observation`
5. `test_runner_receives_recovery_directive_and_continues`
6. `test_contract_tier_tool_exec_records_error_fields`

Red-green steps:

- [ ] Write test 1; run; expect failure.
- [ ] Add the `ExecResult` fields and mapping; run; expect pass.
- [ ] Repeat tests 2 to 6 one at a time.
- [ ] Run `tests/attack/pod/test_tools.py tests/attack/pod/test_graph.py -q`; expect pass.
- [ ] Commit: `feat: propagate browser tool errors through the pod fail-open path`.

## 7. Task 4: checkpoint fallback serde

Files:

- Modify `src/polymerhus/app/llm/checkpoints.py`.
- Extend `tests/test_llm_checkpoints_module.py`.

Behavior:

- Change `_fallback = InMemorySaver()` to `_fallback = InMemorySaver(serde=checkpoint_serde())`.
- Add a test that the fallback uses the app serde and round-trips a `TriagerDecision` value through a compiled graph.

Tests:

1. `test_fallback_checkpointer_uses_the_one_serde`
2. `test_fallback_round_trips_a_triager_decision`

Red-green steps:

- [ ] Write test 1; run; expect failure.
- [ ] Change the fallback construction; run; expect pass.
- [ ] Write test 2; run; expect pass.
- [ ] Run `tests/test_llm_checkpoints_module.py -q`; expect pass.
- [ ] Commit: `fix: use the app serde on the checkpoint fallback`.

## 8. Task 5: eval-harness corrections

Files:

- Modify `eval/steel-e2e-395/run_gateway_e2e.py`.
- Modify `eval/steel-e2e-395/run_pod_e2e.py`.
- Modify `eval/steel-e2e-395/run_random_e2e.py`.

Behavior:

- The dead-session status metric accepts `not_valid` for the failed branch.
- The pod controller opens `module_context("hunting")` around `arun_pod`.
- The random controller always sets a `thread_id`.
- The random summary records tool commands from the structured calls, not from stringified messages.
- The E2E still uses the working model for the success gate and records the production default failure separately.
- No model-contract code change.

Tests:

1. Run the controller unit/compile checks.
2. Re-run the dead-session control and confirm `status_write_ok` is true for `not_valid`.
3. Re-run the pod and confirm no `TriagerDecision` blocked warning.
4. Re-run the random agent and confirm `agent_steel_commands` is non-empty.

## 9. Task 6: deploy and smoke test

Steps:

- [ ] Copy `kali/steel_contract.py` and `kali/mcp_server.py` into `ph-dd131acc-kali-1`.
- [ ] Restart the port 8001 MCP server only.
- [ ] Keep port 8000 untouched.
- [ ] Call `steel_exec` with a missing session and confirm the structured error; confirm no execution.
- [ ] Call `steel_exec` with a live session and confirm the normal envelope.
- [ ] Call `execute_command` with a shell command containing `steel browser get text` and confirm the gate.
- [ ] Call a non-steel `execute_command` and confirm it still runs.

## 10. Task 7: E2E re-run

Steps:

- [ ] Re-mint the white-jotter session and re-seed the session-only account.
- [ ] Prepare `wj-gateway-e2e`.
- [ ] Run E2 with `qwen3.8-max`; confirm the authenticated verdict, the status leaf, and no stray session.
- [ ] Run E2 with the default model as a recorded failure; confirm the failure is unchanged and classified as an eval-harness/model issue, not a tool-stack failure.
- [ ] Prepare the pod session.
- [ ] Run E3 with `glm-5.3`; confirm no blocked `TriagerDecision`, no masked `get text` error, and a clear token error/recovery in the trace.
- [ ] Run E4 with the focused prompt; confirm the 11-route sweep, the agent calls, and no thread-id or recursion failure.
- [ ] Compare every failure with FF-01 to FF-12 and mark each as fixed, narrowed, or unchanged.
- [ ] Write the updated evidence bundle and the comparison report.

Acceptance criteria:

- No stray session from a mistyped `--session`.
- No command executes with an unknown or missing session.
- A stale CDP target produces `target_lost` with a `tab_new` recovery directive.
- A missing session produces `session_missing` with a `recreate_session` directive.
- A stuck or unavailable browser produces a fatal error with a `recreate_session` directive.
- The pod records the error and continues; it does not raise.
- The pod does not count a tool-error observation as clean.
- The fallback checkpointer uses `checkpoint_serde()`.
- The E2E evidence shows the same successful browser capabilities as before.

## 11. Commit discipline

- One commit per task.
- Tests and implementation in the same commit.
- No agent co-author.
- No push.
- No source change outside the files listed above without a plan update.

## 12. Status log

| Task | State | Evidence |
|---|---|---|
| Baseline suite | complete | 60 tests passed before changes |
| Pure contract module | complete | `tests/kali/test_steel_contract.py`, 16 pass |
| MCP gate integration | complete | `tests/kali/test_mcp_steel_gate.py`, 7 pass |
| Pod error propagation | complete | `tests/attack/pod`, 335 pass |
| Checkpoint fallback serde | complete | `tests/test_llm_checkpoints_module.py`, 18 pass |
| Eval harness corrections | complete | E2 dead metric true; E4 commands recorded; pod module context |
| Live deployment | complete | 8001 restarted on the new source; 8000 untouched |
| E2 gateway | complete | authenticated, status true, no stray, no CDP reset |
| E2 dead control | complete | failed, not_valid, status true, no replacement |
| E3 pod | partial | no-symptom negative, clean false, session expired after the sweep |
| E4 random agent | complete | 11 of 11 routes, 15 calls, batch boundary recovered, session stopped |
| Comparison report | complete | `docs/design/e2e-steel-session-395-tool-hardening-results.md` |

Known remaining issues:

- The E3 session expired after the pod's long sweep. The tool now returns `session_missing` and `recreate_session`, but the session-only fixture cannot restore authentication without operator input.
- The pod verdict remains coverage-based and last-lap. The negative is preserved, but `clean` is false.
- The actor duplicate no-decision reply remains.
- The production default model reasoning contract remains an eval-harness issue.
- `steel_exec` script mode is trusted by skill construction; command and batch mode are gated.
- The shared target admin account was deleted by another agent during the run; it was restored through `/api/register` and the `sysAdmin` role.
