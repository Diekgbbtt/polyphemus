# Canonical Failure Fix Plan - 2026-10-21

## Header

- **Goal:** harvest every unfixed failure from the comfyui canary 4 and the comfyui hunting retest that sits in the canonical recon, analysis, or hunting path.
- **Goal:** fix the local, narrow defects under TDD before the white-jotter trial.
- **Goal:** return the global or design-level defects to the operator with concrete options and a planned experiment catalog.
- **Branch:** `fix/utm-canonical-failures`, branched from `d17560e0`.
- **Worktree:** `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/utm-canonical-fixes`.
- **Companion document:** `PLANNED-EXPERIMENTS.md` in this directory.
- **Gate:** do not launch `white-jotter-utm-retest.yaml` until the local fixes pass and the teardown root-cause decision is settled.

## Operator Decisions

- **F-018:** increase the default risk threshold from `12` to `250` and use the default in the next eval trial.
- **F-019:** this is a quality defect, not a runtime process failure that yields a degraded state; it is out of scope for this gate.
- **F-020:** do not solve the residual by widening the status model; diagnose the hunter teardown and controller behavior first.
- **F-025:** write one spec per call with a threat-modeller-style data contract, distinct fields, explicit required and optional semantics, and internal schema validation.
- **F-020 diagnosis:** see `HUNTER-TEARDOWN-DIAGNOSIS.md` in this directory.
- **Teardown fix:** pending the operator's choice between at-least-once loop dispatch (F-022), a narrower #331 stop policy, or both.

## Scope

- **In scope:** F-009, F-010, F-011, F-012, F-014, F-018, F-020, F-021, F-025.
- **In scope after diagnosis:** the teardown durability fix selected by the operator.
- **Out of scope:** F-019 is a quality defect, not a runtime process failure that yields a degraded state.
- **Out of scope:** F-016 is eval-harness budget durability, not a canonical pipeline defect.
- **Out of scope:** F-017 is fixed and its residual is resumption-specific.
- **No mocking:** every trial remains one real trial per target.
- **One change at a time:** every work package follows red test, green test, targeted suite, live or artifact evidence, then commit.

## Evidence Corrections

The retest record has three inaccuracies that must be corrected before the next trial.
These corrections are part of this plan, not a later cleanup.

1. **The 15 loops did not all dispatch a hunter.**
   - The retest produced 15 loop files.
   - The LangGraph checkpoint table has 13 hunter threads, `RESTApi-core-http__loop-1` through `loop-13`.
   - Loops 14 and 15 were still produced and undispatched when the cap stopped the run.
   - Nine of the 13 hunters produced specs.
   - Four hunters, loops 3, 6, 9, and 12, produced no specs and were cut off or failed before a terminal set.
2. **The report line "0 terminal pod exports" is false.**
   - The retest has 19 pod directories.
   - Two pod directories contain terminal run exports.
   - Both exports are `unsuccessful`.
   - The remaining pod directories have no terminal export.
   - The correct statement is: 19 pods started, 5 pod runs measured, 2 terminal exports, 0 confirmed.
3. **F-025 is not a 3,686-character truncation.**
   - The captured `hunts_store` argument payload is 13,338 characters.
   - The JSON is complete at the end.
   - It is malformed at the first spec boundary: a nested object is left open, so the parser reaches the second spec while still inside the first spec object.
   - The error position is 3,685; the payload is not truncated there.
   - The F-025 title and body in `FAILURES.md` must be corrected.
4. **Both terminal pod exports are F-009, not domain evidence.**
   - The two exports are `active-type-denylist-omission_userdata-blob-serve` and `type-selects-privileged-area_temp-read`.
   - Both report `verdict: unsuccessful`, `terminal_reason: technical-infeasibility`, and `iterations: 0`.
   - Both carry the same upstream 400: `The reasoning_content in the thinking mode must be passed back to the API`.
   - The pod runner never reached a domain probe.
   - The retest's 0 pod confirmations are therefore partly a false negative from F-009.

The retest still proves the normal handoff up to the cap:
- 39 specs: 22 ratified, 16 hypothesised, 1 dropped.
- 22 ratified specs were moved to `consumed/`, which is the admission marker.
- 19 pods started.
- The three missing pods are the three loop-5 specs; they were admitted but the cap stopped the run before their pod session.
- The 16 hypothesised specs belong to the four in-flight hunters; they are abandoned by the stop, not omitted by a terminal write.
- The F-020 terminal-set guard was not exercised by the retest because those hunters never wrote a terminal set.
- The F-020 canary evidence remains valid: the terminal write at 00:27:02 omitted the `/view` draft written at 00:10:24, and the provider pause was 28 seconds later.

## Failure Inventory

| ID | Status | Canonical | Evidence | Decision |
| --- | --- | --- | --- | --- |
| F-009 | Open | Yes | 28 provider 400s; both terminal pod exports failed at iteration 0 | Local fallback, WP1 |
| F-010 | Open | Yes | Neo4j warning for `l0.label` | Local guide fix, WP2 |
| F-011 | Open, low | Yes | Async client cleanup after loop close | Diagnose only, WP6 |
| F-012 | Open | Yes | Neo4j warning for `HAS_TECHNOLOGY` and `key` | Local guide fix, WP2 |
| F-014 | Open, security | Yes | Gateway key in an httpx INFO URL | Local redaction, WP3 |
| F-017 | Fixed | Resume | Consumed pod spec recovery | Out of scope |
| F-018 | Decided | Yes | `risk_total=44`, threshold 12 | Default becomes 250, WP7 |
| F-019 | Out of scope | No | 0 of 6 unit-level candidates; bare manager unit | Quality defect, not a runtime process failure |
| F-020 | Partially fixed | Yes | Terminal omission fixed; 16 drafts are a budget stop | Diagnosis complete, durability fix pending |
| F-021 | Fixed at class level | Yes | Retest has `/view` class-level specs; no pod proof | Trial proof only |
| F-022 | Open, in scope after diagnosis | Durability | 13 loops lost on provider pause; no at-least-once dispatch | Teardown decision pending |
| F-023 | Open | Resume | Quota-exhausted resume terminal | Out of scope |
| F-024 | Open | Cap | 3,355,148 spent against 3,000,000 | Out of scope |
| F-025 | Decided | Yes | Malformed multi-spec `hunts_store` JSON | One spec per write, WP4 |

## WP1 - F-009 Reasoning Replay Fallback

**Defect:** a checkpointed assistant message can reach the wire without `reasoning_content`, and the provider rejects the next turn with a 400.
**Live evidence:** the retest logged 28 `The reasoning_content in the thinking mode must be passed back` responses.
**Live probe:** the direct opencode-go provider accepted an assistant tool-call message with no reasoning and with `reasoning_content: ""`.
**Seam:** `ReasoningPreservingChatOpenAI._get_request_payload` in `src/polymerhus/app/llm/providers.py`.
**Test seam:** serialize an `AIMessage` with tool calls and no reasoning; assert the outbound message carries `reasoning_content: ""`; assert a message with real reasoning keeps its exact value.
**Files:**
- `src/polymerhus/app/llm/providers.py`
- `tests/test_llm_reasoning.py`
- `tests/test_llm_providers.py`
**Steps:**
1. Add a failing test that sends an `AIMessage` with a tool call and no reasoning through `_get_request_payload`.
2. Confirm the current payload omits the field and the test fails.
3. Add the narrow fallback for assistant messages that carry tool calls.
4. Keep the exact replay path unchanged when reasoning is present.
5. Run `pytest tests/test_llm_reasoning.py tests/test_llm_providers.py -q`.
6. Record the live probe result in the commit message.
**Risk:** the provider may require the exact prior reasoning in some deployments; the live probe accepts empty, so this is a fallback only for absent fields.

## WP2 - F-010 and F-012 Graph Schema Guide

**Defect:** the analysis graph guide does not teach the real L0 technology edge or the Observation identity.
**Evidence:** the canary model authored `HAS_TECHNOLOGY`, `key`, and `l0.label` queries against a schema that uses `USES_TECHNOLOGY`, `name`/`properties`, and labels.
**Seam:** `GRAPH_VIEW_CONTRACT`, `_SCHEMA`, and `_RETURN_SHAPE` in `src/polymerhus/analysis/graph_tools.py`.
**Test seam:** assert the contract names `USES_TECHNOLOGY`, states that `label` is not a node property, and states the Observation identity keys.
**Files:**
- `src/polymerhus/analysis/graph_tools.py`
- `tests/analysis/test_graph_tools.py`
**Steps:**
1. Add failing contract assertions for the missing schema facts.
2. Add `USES_TECHNOLOGY` to the L0-internal relationship list.
3. Add the Observation identity line.
4. Add the explicit rule: use `labels(node)`; do not read `node.label`.
5. Run `pytest tests/analysis/test_graph_tools.py -q`.
**Risk:** this is a guide fix, not a query validator; a later trial must measure whether the model stops inventing schema names.

## WP3 - F-014 Gateway Key Log Redaction

**Defect:** `GatewaySync.key_info` sends the key as a query parameter, and httpx logs the full URL at INFO.
**Evidence:** the agent startup log contains `GET /key/info?key=sk-ph-...`.
**Seam:** `src/polymerhus/app/llm/sync.py::key_info` and the app logging setup.
**Preferred fix:** redact `key=...` in the `httpx` logger record before it is emitted.
**Fallback:** use a POST body only if the gateway endpoint supports it; do not change the gateway contract without a live check.
**Test seam:** capture the `httpx` logger at INFO for a key-info request and assert the key is absent from the formatted record.
**Files:**
- `src/polymerhus/app/llm/sync.py`
- `src/polymerhus/app/logging.py` or the existing logging setup module
- `tests/test_llm_sync.py`
**Steps:**
1. Add a failing test that formats a key-info URL through the logging path.
2. Add a narrow `logging.Filter` that replaces `key=<value>` with `key=<REDACTED>`.
3. Install the filter on the `httpx` logger at app startup.
4. Keep the request URL unchanged so the gateway behavior is unchanged.
5. Run the targeted sync and logging tests.
**Risk:** a global httpx filter must not corrupt unrelated log records; the test covers a non-key URL unchanged.

## WP4 - F-025 One Spec per Write

**Status:** approved.
**Defect:** one `hunts_store` call with several specs contains a malformed nested object; the relay parser rejects the whole call before the typed contract runs.
**Evidence:** the captured payload is 13,338 characters and the first spec leaves a nested object open.
**Decision:** write one spec per call.
**Contract pattern:** mirror the threat modeller's typed write contract.
- One `spec` object, not a `specs` list.
- Each authored field is distinct and documented in the tool description.
- `status`, `fault_keyword`, `strategy_keyword`, `target_identity` are required.
- The remaining spec fields are optional and documented as optional.
- `extra="forbid"` remains the schema-based rejection.
- Add a `finalize` command with no spec payload.
- `finalize` checks the produced set and rejects any spec still in `hypothesised` with a coded error naming the identities.
- The existing whole-set `write_specs` guard remains for internal callers.
- The hunter tool calls a new single-spec store method for `write`.
**Prompt and description:**
- Update the `hunts_store` tool description to say one spec per call and finalize at the end.
- Update the hunter system prompt to use the same field names and required/optional language.
- Add a contract test that the prompt, tool description, and schema agree on the field names.
**Files:**
- `src/polymerhus/attack/hunting/hunter_tools.py`
- `src/polymerhus/attack/hunting/hunter_memory.py`
- `src/polymerhus/attack/hunting/llm.py` or the hunter system prompt module
- `tests/attack/test_hunter_tools.py`
- `tests/attack/test_hunter_memory.py`
- `tests/attack/test_hunting_prompt.py`
**Steps:**
1. Add a failing schema test that allows exactly one `spec` and rejects a `specs` list.
2. Add a failing store test for single-spec upsert and finalize with a remaining hypothesised spec.
3. Add the `write_spec` and `finalize_specs` store methods.
4. Switch the tool's write path to one spec.
5. Add the `finalize` command.
6. Update the tool description and the prompt.
7. Run the targeted suites.
**Risk:** one spec per call costs more turns.
The finalize check must not be skippable.
The store must preserve the whole-set completeness guard.

## WP5 - F-019 Unit Binding and Route Families

**Status:** out of scope.
**Reason:** the operator classified F-019 as a quality defect, not a runtime process failure that yields a degraded state.
**Action:** record the defect and its evidence in `FAILURES.md` and the quality notes.
**Action:** do not change the analysis or recon graph before white-jotter.

## WP6 - F-011 Async Cleanup Diagnosis

**Defect:** a LangChain or OpenAI async client schedules `aclose` after its event loop closes.
**Impact:** log noise only; no failed model call was observed.
**Action:** diagnose the owning client and the lifecycle.
**If the fix is one local close or one guard, implement it under TDD.**
**If the fix crosses the async bridge, record it as a deferred risk and do not block the trial.**

## WP7 - F-018 Risk Threshold

**Status:** approved.
**Decision:** increase `DEFAULT_RISK_THRESHOLD` from `12` to `250`.
**Reason:** the canary's first unit had `risk_total=44`; a threshold of 36 would still halt before the manager units.
**Action:** change the code default and use it in the next eval trial.
**Action:** remove the `HUNT_RISK_THRESHOLD=1000` override from the eval instance for the trial.
**Test seam:** the risk threshold default and the `threshold_basis` recorded on the run.
**Files:**
- `src/polymerhus/attack/hunting/run_lifecycle.py`
- the risk threshold tests
- `eval/setups/white-jotter-utm-retest.yaml` if it carries an override
**Steps:**
1. Add a failing test that expects the default `250`.
2. Change the default.
3. Run the risk and lifecycle tests.
4. Remove the eval instance override before the trial.

## WP8 - F-020 Abandoned Draft Processing

**Status:** diagnosis complete; durability fix pending.
**Finding:** the 16 retest drafts are a deliberate 3M budget-stop partial state, not a terminal-set omission.
**Finding:** the canary terminal write omitted the `/view` draft before the provider pause; the terminal guard fixes that case.
**Finding:** the actual lost-work defect is the destructive `produced/` to `consumed/` move on a run-wide provider stop.
**Action:** do not change the status model for this gate.
**Action:** fix the loop durability selected in WP9.

## WP9 - Teardown Durability Root Cause

**Status:** approved: fix both A and B.
**Evidence:** `HUNTER-TEARDOWN-DIAGNOSIS.md`.
**Confirmed events:**
- Three provider-failure interruptions: 2026-10-14, canary 4, retest first attempt.
- One deliberate 3M budget project stop.
- Two terminal pod failures, both F-009.
- One malformed hunter spec write, F-025.
- One terminal-set omission, F-020 canary.
**Operator choices:**
- **A:** at-least-once recovery for the four outlier surfaces only: consumed loops, their model dependency, hunter completion, and pod/spec completion.
- **Loop completion marker:** the terminal spec set. A zero-spec hunter must still write a terminal set, so finalize is a durable record even with zero specs.
- **Pod completion marker:** the pod export file is canonical. The hunter note is a derived live feed and never proves completion.
- **B:** a child provider failure no longer stops the whole run. A transient failure requeues the failed item with backoff and keeps sibling hunters and pods live. Quota exhaustion stops the run. Three consecutive transient child failures also stop the run.
**A design:**
- The hunter finalize command writes a terminal-set record under the hunt key, after checking that every produced spec is `ratified` or `dropped`.
- The record carries the run id, hunt key, the terminal spec identities, and zero specs is a valid terminal set.
- A consumed loop is recovered when its model belongs to this run and its hunt key has no terminal-set record.
- The model is read from `consumed/` as the loop payload dependency; it is not re-modelled.
- The recovered loop is a `ThreatLoopItem` with `recovered=True`; the move is already satisfied.
- The spec recovery keeps the F-017 read and the pod export file as the marker.
- `read_produced_inbox` includes recovered loops and recovered specs; `run_work_remaining` and the quiesce predicate therefore cannot pass while a recovered item is pending.
**B design:**
- The surfer records child provider failures per item, not as an immediate run-wide fatal error.
- A transient child failure stops only that child session and re-dispatches the recovered loop or spec after `retry_after_s` or the default backoff.
- Sibling hunters and pods continue.
- A quota-exhausted child failure is fatal for the run.
- Three consecutive transient child failures are fatal for the run.
- The #331 stop/flush/stamp handler remains for the fatal cases and the modeller pass abort.
**ADR action:** amend `docs/design/331-stop-only-resume-assessment-adr.md` to record the child-failure policy.
**Test seam:**
- A: a consumed loop with no terminal set is recovered and dispatched; the same loop with a terminal set is not.
- A: a zero-spec finalize writes a terminal set and stops recovery.
- A: a consumed spec with no pod export is recovered; with an export it is not.
- B: one transient child failure leaves a sibling hunter live and retries only the failed item.
- B: quota exhaustion stops the run; three consecutive transients stop the run.

## P2 - Verification and White-Jotter Trial

**Preconditions:**
- WP1, WP2, WP3, WP4, and WP7 are merged and their targeted tests pass.
- The WP9 teardown root cause is fixed or explicitly waived.
- F-019 is recorded as out of scope, with its evidence.
- The corrected retest evidence is committed in `FAILURES.md` and `EXPERIMENT-RESULTS.md`.
- The `HUNT_RISK_THRESHOLD` override is removed so the default 250 is used.
- The instance worktree is aligned to the fix commit.
- The agent container is recreated with the new code and health returns 200.

**Trial:**
1. Run `white-jotter-utm-retest.yaml` from scratch.
2. Use the `opencode-go:deepseek-v4.1-flash` model.
3. Keep threat modeller and hunter at max thinking; pod runner and triager at high.
4. Keep global compaction `0.4`; analysis assigner and mechanism typist at `0.2`.
5. Keep the native `7M` capped-token budget.
6. Keep the USD budget guard enabled.
7. Use one trial and zero mocks.
8. Preserve the failed artifacts if the trial fails.

**Measurement:**
- Use the standard trial runner and the official assessor; do not reconstruct an official trial record.
- Record the stage counts: loops, hunters, specs by status, consumed specs, pods, terminal pod exports, confirmed verdicts.
- Record unit-level and class-level candidates separately.
- Record the capped-token spend and any overshoot.
- Update `FAILURES.md`, `EXPERIMENT-RESULTS.md`, and `PLAN.md` with the result.

**Stop conditions:**
- A local fix fails its targeted suite: stop and diagnose; do not proceed to the trial.
- The WP9 teardown choice is unanswered: stop before the trial.
- The instance health is not 200: stop before the trial.
- The white-jotter trial produces no terminal export: preserve artifacts and diagnose before any new trial.
- The white-jotter trial exceeds the 7M cap by more than the accepted margin: record the overshoot and do not claim the cap held.

## Feedback Loop Protocol

- **Loop 1:** red test for one work package.
- **Loop 2:** minimal green fix.
- **Loop 3:** targeted suite for the touched domain.
- **Loop 4:** live or artifact evidence for the defect.
- **Loop 5:** commit with the test command and evidence.
- **Loop 6:** next work package.
- **No parallel code changes inside one work package.**
- **Independent diagnosis subagents may run in parallel; their outputs are evidence, not merges.**
- **Every commit names the failure ID and the test that proves the fix.**
- **No white-jotter launch from a dirty worktree.**

## Commit Sequence

1. `docs(eval): correct retest handoff evidence`
2. `docs(eval): record hunter teardown root causes`
3. `test(llm): cover missing reasoning replay`
4. `fix(llm): replay empty reasoning for tool calls`
5. `test(analysis): pin graph schema guide`
6. `fix(analysis): teach USES_TECHNOLOGY and Observation identity`
7. `test(logging): cover gateway key redaction`
8. `fix(logging): redact key info query values`
9. `test(hunting): pin the one-spec write contract`
10. `fix(hunting): write one spec per call and finalize the set`
11. `test(hunting): pin the 250 risk default`
12. `fix(hunting): raise the default risk threshold to 250`
13. `fix(hunting): the approved teardown durability package`
14. `docs(eval): record the canonical fix result`
15. The white-jotter trial commit or trial record.
