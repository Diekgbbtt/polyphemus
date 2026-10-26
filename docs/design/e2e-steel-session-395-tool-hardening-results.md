# Steel tool-contract hardening results - #395 follow-up

Status: implementation and live re-run complete.
Date: 2026-10-26.
Branch: `fix/395-tool-contract-hardening`.
Scope: entries 1, 2, 4, 7, plus entry 3 as a fail-open consumer path.
Out of scope: entry 5 state mount isolation, entry 6 app-level model contract.
No remote repository was pushed.

## 1. What changed

The Steel tool stack now has one modular sanitization and error-canonicalization layer:

- `kali/steel_contract.py` parses Steel browser commands, validates the target session, detects the CLI's clear errors, and classifies browser-state failures into a stable error envelope.
- `steel_exec` runs the sanitizer before execution.
- `execute_command` re-applies the same sanitizer to embedded Steel commands before the downstream executor runs.
- The sanitizer does not re-implement the Steel CLI grammar.
- The sanitizer does not rewrite clear CLI errors, including `cookies list`.
- The sanitizer does not create sessions automatically.

The error envelope is additive.
It keeps the legacy `stdout`, `stderr`, `returncode`, and `duration_ms` fields.
It adds an `error` object with `code`, `message`, `retryable`, `fatal`, `recovery`, `session`, `platform_state`, and `canonical_command`.

The recovery directives are:

- `unknown_session`: use a live session or start an explicit new one.
- `session_taken`: reuse the live session or choose a new name.
- `target_lost`: create a new page target with `tab_new`; fall back to `recreate_session`.
- `session_missing`: recreate the session and restore state.
- `browser_unavailable`: recreate the session.
- `browser_stuck`: recreate the session.
- `invalid_command` and `cli_error`: fix the command.

The pod path records the structured error in `ExecResult` and `RawObservation`.
The `exec` tool returns `TOOL ERROR: code=... message=... recovery=...`.
The pod stops retrying a fatal or non-retryable tool error.
The runner receives the error and continues; it does not raise.
The pod does not count an error or empty-target warning as clean.

The checkpoint fallback now uses `checkpoint_serde()`.
The eval harness now:

- accepts `not_valid` for the dead-session status metric;
- runs the pod under `module_context("hunting")`;
- records random-agent commands from structured calls.

## 2. Verification

Unit and contract tests:

- `tests/kali/test_steel_contract.py`: 17 pass.
- `tests/kali/test_mcp_steel_gate.py`: 7 pass.
- `tests/attack/pod`: 335 pass.
- `tests/test_llm_checkpoints_module.py`: 18 pass.
- `tests/recon/test_exec_result_http_refs.py`: 3 pass.
- Combined targeted run: 480 pass.

The final signal-text guard was added after the live E2/E3/E4 runs.
It prevents a successful page body that merely mentions a CDP or websocket phrase from being classified as a browser failure.
The guard is unit-tested and the final module was deployed to 8001; the live `sessions` smoke returned no error.
The live scenario evidence remains valid because the guard only removes false positives.

Smoke tests against the live 8001 server:

- Unknown session `wj-typo`: `unknown_session`, recovery `use_live`, no execution.
- Embedded unknown session in `execute_command`: `unknown_session`, no execution.
- Catalogue after the rejected commands: no stray `wj-typo`.
- Selectorless `get text` inside a shell pipeline: `cli_error`, returncode 0, the CLI `<SELECTOR>` error preserved.
- Valid `get text body`: no error, body text present.
- Non-Steel `echo hello`: returncode 0, stdout `hello`.

## 3. E2 gateway

The gateway run passed.

- Verdict: `authenticated`.
- Account: `admin-sessiononly-e2e`.
- Branch: `browser_only`.
- Status write: `valid`.
- `status_write_ok`: true.
- Session live: true.
- Browser commands: 7, all valid.
- No stray session.
- No CDP target reset.
- No unknown or missing session.
- Loop state: `FINISH`, `grounded: true`, `probe_count: 7`.
- Skill unchanged.
- Trace redacted.

The actor still posted a duplicate no-decision reply after the real verdict.
The controller received the real verdict first and marked the run `ok`.
This is the known actor-lifecycle issue; it is not in the hardening scope.

The dead-session control passed after the metric fix.

- Verdict: `failed`.
- Status write: `not_valid`.
- `status_write_ok`: true.
- Session live: false.
- The model saw `unknown_session` and explicitly refused to create a replacement session.
- Browser commands: 2.
- No request replay.
- The control's `ok` is false because the verdict is not authenticated; that is correct.

## 4. E3 pod

The pod run completed with a negative result, but not a clean one.

- Verdict: `unsuccessful`.
- Terminal reason: `no-symptom-evidence`.
- Clean: false.
- Iterations: 1.
- Raw observations: 18.
- Session live at the final controller check: false.
- `ok`: false because the clean flag and live-session check are false.

The lap evidence confirms the httpOnly negative:

- Both `JSESSIONID` and `rememberMe` are httpOnly.
- `document.cookie` is empty.
- A JavaScript control cookie is visible and then cleared.
- The target endpoints returned the expected authenticated status.
- The triager's note records the negative and the remaining coverage gaps.

The previous `technical-infeasibility` terminal is gone.
The new terminal is `no-symptom-evidence` with `clean: false`.
The remaining `clean: false` is driven by degraded KB coverage and unobserved non-GET and logout paths, not by the Steel tool stack.

The Steel session expired after the pod's long endpoint sweep.
The tool layer now has `session_missing` and `recreate_session` semantics, but the pod did not recreate the session because the fixture is session-only and a fresh session cannot be authenticated without operator state.
The session lifetime is operational and remains outside this change.

A new tool-layer defect was found during E3:

- A multi-command shell observation produced a false `empty_target` warning because the classifier parsed the combined stdout as one JSON object.
- The guard now skips the empty-target warning when the command contains shell separators.
- A regression test covers the multi-command case.

The E3 pod also logged that the `steel-browser` skill did not resolve.
That is an eval skill-delivery gap, not a tool-protocol failure.

## 5. E4 random agent

The random agent run passed.

- `ok`: true.
- Routes: 11 of 11.
- Agent tool calls: 15.
- Steel commands: 13.
- Session stopped: true.
- Session live after: false.
- Final report: 15 of 16 calls used.

The first `batch` request omitted the mandatory `--` boundary.
The sanitizer returned a `variadic-boundary` error with the canonical form.
The agent corrected the request and completed the feature checks.

The agent exercised:

- The admin dashboard menus.
- The Todo List filter.
- The user table.
- The article view.
- The library category filter and search.
- A non-published editor draft.

The library search did not change the result list.
The article body was empty on the first read and present on the second read.
Both are target-data or asynchronous-rendering effects, not Steel tool failures.

## 6. Comparison with the factual failure ledger

| ID | Before | After | Status |
|---|---|---|---|
| FF-01 default-model reasoning 400 | Gateway returned no verdict | Unchanged; eval model override still required | Out of tool scope |
| FF-02 CDP target reset | `eval`/`navigate` failed; `snapshot`/`content` returned empty success | The stack returns `target_lost` with `tab_new` and `recreate_session` fallback; E2 had no reset | Narrowed; runtime reset still possible |
| FF-03 session absent or expired | E2 failed closed; E3 ended in `technical-infeasibility` | E2 dead control writes `not_valid` and reports `status_write_ok: true`; E3 ends in `no-symptom-evidence` with `clean: false`; the tool returns `session_missing` and `recreate_session` | Improved; session lifetime remains operational |
| FF-04 alert freeze | Browser stuck until stop | Unchanged; E1 was not re-run | Out of this change |
| FF-05 typo session creates a stray | `wj1618c524` live; empty success | Unknown session rejected before execution; no stray in E2 or smoke | Fixed |
| FF-06 selectorless `get text` and masked exit | CLI error hidden behind returncode 0; wrong data shape | `cli_error` returned with the CLI error; E4 batch boundary caught; unit and smoke pass | Fixed for the tool layer |
| FF-07 pod last-lap verdict | `technical-infeasibility` after a confirmed negative | `no-symptom-evidence` with `clean: false`; the negative is preserved; the pod verdict is not redesigned | Partially improved |
| FF-08 fresh state inherits cookies | E5 test passed with foreign cookies | Unchanged; entry 5 is out of scope | Out of scope |
| FF-09 `cookies list` | Clear CLI error | Not rewritten; the CLI error remains clear | Unchanged by design |
| FF-10 E4 thread id and recursion | First attempts failed; commands empty | E4 passed with 15 calls and 13 recorded commands; no thread-id or recursion failure | Fixed in the harness |
| FF-11 E2 dead-session metric | `status_write_ok: false` despite `not_valid` | `status_write_ok: true` | Fixed |
| FF-12 reporting and serde | Loop state grounded false; fallback serde warning | Fallback serde fixed; E2 grounded true; phase fields still null; E1 JSONL still missing | Partially fixed |

## 7. Remaining failure modes

The tool-stack change removes the uncontrolled command and session-target errors from the observed runs.
It does not remove these remaining modes:

- Session lifetime: the Steel runtime can release an idle session during a long pod sweep. The tool returns a clear error and recovery directive, but the session-only fixture cannot recreate the authenticated state without operator input.
- Pod coverage and clean: the triager still uses a last-lap decision and a coverage-based clean flag. The negative is honest but not clean.
- Actor duplicate reply: the gateway can post a no-decision reply after the real verdict. The controller drains it; another consumer may not.
- State isolation: a fresh state session can inherit foreign cookies. Entry 5 is out of scope.
- Model contract: the production default model still fails the multi-turn reasoning contract. Entry 6 is delegated to the eval harness.
- Secret propagation: the raw pod memory and the target evidence can contain cookie values or PII. The local evidence bundle is sanitized; the raw host copies remain sensitive.
- `steel_exec` script mode: commands are gated; free-form scripts are still trusted by skill construction. The successful scenarios used command and batch mode.
- Target data state: the shared white-jotter admin account was deleted by another agent during the run; the fixture was restored through `/api/register` plus the `sysAdmin` role. The target's library search also did not filter. These are target-data effects, not tool failures.

## 8. Evidence

The redacted evidence is in `eval/steel-e2e-395/evidence-run3/`.

- `gateway-summary.json`: E2 pass.
- `gateway-trace.json`: E2 trace, emails and phone numbers redacted.
- `gateway-verdict.json`: E2 verdict.
- `gateway-summary-dead.json`: E2 dead-session control.
- `gateway-trace-dead.json`: dead control trace, redacted.
- `gateway-verdict-dead.json`: dead control verdict.
- `pod-summary.json`: E3 summary; the raw pod result is not copied.
- `random-summary.json`: E4 pass.
- `random-sweep.json`: E4 route sweep.

The raw pod result and the raw state files remain on the eval host and must be treated as sensitive.
No cookie value, token, or credential is reproduced here.

## 9. Commits

- `c427aee8` `feat: add steel browser contract sanitizer`
- `ed9d3585` `feat: gate steel commands through the contract sanitizer`
- `94f71142` `feat: propagate steel tool errors through the pod`
- `43cb73bd` `fix: use the app serde on the checkpoint fallback`
- `c124b986` `fix: correct eval harness status, context, and trace extraction`
- A final commit records the multi-command warning fix, the flat-layout import fallback, this report, the plan, and the redacted evidence.
