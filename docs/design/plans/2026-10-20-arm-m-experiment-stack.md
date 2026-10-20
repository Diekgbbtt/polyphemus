# Arm M experiment stack - runtime fixes and the approved analysis experiments

Status: active.
Date: 2026-10-20.
Owner: the arm M operator.
Base: `bace9e10` (the arm L overview and comparison docs on top of `origin/dev` `34f2be38`).
Eval target: `webexploitbench/white-jotter` only.
Thinking: held at the arm L high baseline (the assigner and mechanism_typist declare `medium`, negotiated to wire `high`).
Budget: 4,000,000 capped tokens per trial, 7,200 s trial budget.

## 1. Objective

Run one white-jotter trial for the runtime fixes and one trial for each approved analysis experiment.
Keep every other variable fixed.
Measure each batch against the arm L high baseline before advancing the stack.
Produce a written result for every batch, including negative and neutral outcomes.

## 2. Scope decisions

Approved and in scope:

- Recommendation 1: add the `_ObservationBatch` structured-delivery line to the triager prompt.
- Recommendation 2: normalize read timeouts in the tool layer and retry idempotent status polls with a bounded backoff.
- E1: services-to-systems linking guidance plus a more extensive Example 6.
- E3: authorization-system description primitives, with bounded probing.
- E4: union the extraction-call and linking-call `system_edges`, deduplicated.
- E6: state that `prefer PRIMARY` orders the links and does not restrict them.
- E7: require a per-endpoint `live route` / `mirror shell` evidence tag and a stated default.

Refused or deferred:

- E2 refused: the `keywords` Parameter is recoverable at hunting time.
  The domain model has `Parameter` and `HAS_PARAMETER` from `Endpoint`.
  The hunter's `graph_view` contract carries the exact `OPTIONAL MATCH (e)-[:HAS_PARAMETER]->(p:Parameter)` example.
  The hunter prompt already requires the parameter in the payload vector space.
  No hunt-orchestrator or hunter ticket is raised.
- E5 deferred: the `FRONTED_BY` versus `ROUTED_BY` contradiction stays as-is for this stack.
  Record the rel counts each trial, but do not treat the label as a gate.
- E8 stays instrument-owned and outside this stack.
- No merge to the canonical `dev` trunk.
  The trunk carries unrelated integration work.
- No `max` arm in this stack.
  A `max` run is the optional convergence check after the high stack settles.
- No deep authorization pyramid and no extensive probing.
  The typist may run a bounded probe to shape the trust boundary.

## 3. The read-timeout diagnosis and the freeze

The trial-2 abort was not an external dependency failure.

- The eval agent ran uvicorn with `--reload` from `docker-compose.dev.yml`.
- At 2026-10-19T11:54:22Z the instance source file `src/polymerhus/app/llm/providers.py` received a new mtime.
  Its content hash did not change.
- Uvicorn detected the change and restarted.
  The old server shut down at 11:54:22 and the new server was ready at 11:54:45.
- The harness status poll hit that window and read-timed-out at 30 s.
  The raw `TimeoutError` escaped the runner and the driver, so the trial aborted with no record.
- The status endpoints are not the cause.
  Both use `asyncio.to_thread(pg.get_*_run)` and the logs show 200 OK polls immediately before the reload.

The fix has two layers.

- Proactive: freeze the instance source before the trial and disable reload for the eval stack.
- Defensive: the tool-layer `HttpApiRunner` normalizes read timeouts and retries idempotent GET polls with a bounded backoff.
  The driver only records the terminal `ApiError`.

## 4. Worktree and trial stack

One worktree and branch per batch.
Each branch stacks on the previous branch head.
The first branch is based on `bace9e10`.

| Batch | Worktree | Branch | Trial id | Primary metric |
|---|---|---|---|---|
| Runtime | `arm-m-runtime` | `exp/arm-m-runtime-rec1-rec2` | `armm-wj-runtime` | Zero structured-channel warnings; no transport abort; GT no regression |
| E1 | `arm-m-e1-linking` | `exp/arm-m-e1-linking` | `armm-wj-e1` | 3 `AUTHORIZED_BY` M4 items; count 6-7 |
| E3 | `arm-m-e3-authz-description` | `exp/arm-m-e3-authz-description` | `armm-wj-e3` | `004` M3 5/5; S2/S4 stable |
| E4 | `arm-m-e4-edge-union` | `exp/arm-m-e4-edge-union` | `armm-wj-e4` | `navigation-menu` pair lands; zero dropped edges |
| E6 | `arm-m-e6-prefer-primary` | `exp/arm-m-e6-prefer-primary` | `armm-wj-e6` | `SHAPES_DATA_OF` coverage stays at 8 |
| E7 | `arm-m-e7-placement` | `exp/arm-m-e7-placement` | `armm-wj-e7` | Placement 71/114 plus a precision sample |

The worktrees live under `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/`.
The eval host keeps one harness worktree per batch under `/opt/polymerhus-dev/eval/experiments/`.
The instance worktree stays at `/opt/polymerhus-dev/eval/instances/eval-server-1`.

## 5. Eval alignment contract

Run these steps before every trial.
Do not skip a step because the previous trial passed.

### 5.1 Source freeze and hash

1. Commit and push the batch branch.
2. Fetch the branch on the eval host and create or refresh the batch harness worktree.
3. Run `eval/deploy/sync_instance.sh` from the batch worktree.
   The script rsyncs `src/` to the instance worktree with `--delete`, excluding `__pycache__`, `*.pyc`, and `.pytest_cache`.
   It also syncs `eval/docker-compose.eval.yml`.
   It writes the local and remote manifests and diffs them.
   It prints the source tree hash.
4. Treat any manifest difference as a hard stop.
5. Use the printed tree hash as `--stack-fingerprint`.

### 5.2 Credentials

Merge only these keys from `/Users/diekgbbtt/polymerhus/.env` into the instance `.env`:

- `API_KEY_OPENCODE_GO`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`

Preserve every other instance line, including the 36 lightrag and n8n keys.
Preserve the instance model roles `opencode-go:deepseek-v4.1-flash` and the instance capability overrides.
Do not copy the main worktree `LLM_*` values: they declare `deepseek-v4-flash` and would change the model variable.

Verify that the three values match the main worktree and that the Langfuse credentials resolve to the `polyphemus` project.
Do not print the secret values.

### 5.3 Reload disabled and the app re-created

`eval/docker-compose.eval.yml` must set `AGENT_UVICORN_ARGS: ""` for the `agent` service.
The dev overlay sets `--reload`; the eval overlay is applied last and must override it.

After the source sync and the `.env` merge, force-recreate the agent so the running process imports the frozen source:

```bash
cd /opt/polymerhus-dev/eval/instances/eval-server-1
INSTANCE_DATA_ROOT=/opt/polymerhus-dev/eval/instances/data/eval-server-1 \
  docker compose -p ph-dd131acc \
    -f docker-compose.yml -f docker-compose.dev.yml -f eval/docker-compose.eval.yml \
    up -d --force-recreate agent
```

Verify:

- `docker inspect ph-dd131acc-agent-1` shows no `--reload` in `AGENT_UVICORN_ARGS`.
- The agent log contains `Application startup complete` and no `StatReload` or `Reloading`.
- `curl -fsS http://localhost:8080/projects` returns 200.
- The Langfuse project is `polyphemus`.
- The source tree hash still matches the batch worktree.

### 5.4 Trial setup

Use one setup file per batch under `eval/setups/`.
Each file keeps the arm L high target, budget, data dependencies, and work items.
Only the `target_run_id` changes.

Run the trial from the batch harness worktree on the eval host:

```bash
cd /opt/polymerhus-dev/eval/experiments/<batch>
mkdir -p eval/runs-armm/<batch>
PYTHONPATH=eval python3 -m orchestrator trial \
  eval/setups/webexploitbench-arm-m-<batch>.yaml \
  eval-server-1 white-jotter-1 \
  --instances-root /opt/polymerhus-dev/eval/instances \
  --branch eval \
  --api http://localhost:8080 \
  --data-root /opt/polymerhus-dev/eval/instances/data/eval-server-1 \
  --runs-root eval/runs-armm/<batch> \
  --budget-s 7200 --poll-s 15 \
  --eval-sha "$(git rev-parse HEAD)" \
  --stack-fingerprint "<source tree hash>" \
  --trace-id armm-<batch>
```

Redirect the trial output to `eval/runs-armm/<batch>/trial.log`.

## 6. Monitoring contract

Poll at five-minute intervals while the trial runs.
Record every check in the execution log.

Check:

- The trial process is alive and the trial log advances.
- The app log has no `StatReload`, no `Reloading`, no `api transport failure`, and no new `structured-channel` warning.
- The phase transitions are recon, analysis, hunting.
- The token spend is below the 4,000,000 budget and the trial deadline is not exceeded silently.
- The source tree hash is unchanged.
- The target host and the front are reachable.

Stop and investigate on a reload, a source hash change, a raw transport abort, or an unexpected phase failure.
Do not advance the stack on a contaminated trial.

## 7. Measurement contract

Run these measurements after every trial and write the result in the execution log.

### 7.1 GT well-formedness

Open the Neo4j tunnel and run the structural scorer against the trial project:

```bash
ssh -f -N -L 17487:127.0.0.1:7687 eval-server-polyphemus
python3 tools/measure_gt_wellformedness.py \
  --target white-jotter \
  --project <project_id> \
  --label armm-wj-<batch> \
  --uri bolt://127.0.0.1:17487 \
  --user "$NUSER" --password "$NPASS" \
  --json --out /tmp/armm-wj-<batch>-gt.json
```

The 13-spec corpus stays local.
The white-jotter target has 7 specs.
The arm L high baseline is `/tmp/arml-wj-high-gt.json`.
The max baseline is `/tmp/arml-wj-max-gt.json`.

Track the five stable items by name:

- `white-jotter-002` M4 `AUTHORIZED_BY` (E1).
- `white-jotter-004` M4 `AUTHORIZED_BY` (E1).
- `white-jotter-007` M4 `AUTHORIZED_BY` (E1).
- `white-jotter-004` M3 `username` statement (E3).
- `white-jotter-005` M2 `keywords` Parameter (E2 refused; expected to remain missed; never a regression gate).

With E2 refused the analysis-owned stable ceiling is four items plus the high arm's two run-specific S2/S4 items.
The adjusted high ceiling is about 0.789, not 0.813.
The E2 item stays visible but outside the target.

### 7.2 Edge parity

Pull the `typist-systems-and-edges` generation output for the run from Langfuse.
Extract every emitted `system_edges` entry.
Compare it with the committed `L1Service -> L1System` edges in Neo4j.
Report every emitted edge that did not commit.
The E4 acceptance is that the `navigation-menu` `AUTHENTICATED_BY` and `IDENTIFIED_BY` pair commits and the dropped set is empty.

### 7.3 Rel agreement

Count the committed `FRONTED_BY` and `ROUTED_BY` edges per run.
Record which perimeter system carries which rel.
Do not gate on the label while E5 is deferred.

### 7.4 SHAPES coverage

Count the distinct services with a committed `SHAPES_DATA_OF` edge.
The high baseline is 8.
E6 must not reduce it.

### 7.5 Placement

Count the endpoints placed in the graph and the number of aggregates.
The high baseline is 71 of 114 endpoints and 72 aggregates.
E7 must keep completeness at the high level and pass a sampled precision audit of ten placed mirror paths.
The sample must show a stated `live route` or `mirror shell` tag for each path and a defensible owner.

## 8. Batch tasks

Each batch follows the same loop:

1. Create the stacked worktree.
2. Write the failing tests first.
3. Implement.
4. Run the targeted tests and the baseline regression set.
5. Commit.
6. Push.
7. Align the eval instance.
8. Run the trial.
9. Monitor.
10. Measure.
11. Write the result and decide.

Do not start the next batch until the current batch's measurement and decision are written.

### Batch 1 - runtime fixes (recommendation 1 and recommendation 2)

Files:

- `src/polymerhus/recon/domain/prompts/writing-observations.md`
- `tests/recon/test_skills.py`
- `eval/orchestrator/api.py`
- `tests/eval/test_orchestrator_api.py`
- `eval/docker-compose.eval.yml`
- `tests/eval/test_eval_overlay.py`
- `eval/deploy/sync_instance.sh` (new)
- `eval/setups/webexploitbench-arm-m-runtime.yaml` (new)

Recommendation 1:

- Test: `tests/recon/test_skills.py::test_triager_prompt_names_the_structured_delivery_tool`.
  The test asserts that the loaded triager prompt contains `_ObservationBatch`, `tool call`, and `message text`.
- Implementation: add a short `## Deliver the batch as a tool call` section after the Overview.
  The section says the answer is the `_ObservationBatch` tool call, the JSON payload goes in the tool arguments, and message text is not read.
- Acceptance: the next trial has zero `stateful_turn triager structured-channel` warnings.
  The triager traces show the tool call as the delivery channel.

Recommendation 2:

- Tests:
  - `test_http_runner_retries_a_get_read_timeout_then_succeeds`.
  - `test_http_runner_normalizes_an_exhausted_get_read_timeout`.
  - `test_http_runner_does_not_retry_a_post_read_timeout`.
  - `test_http_runner_retries_a_transient_url_error_on_get`.
- Implementation: add `retries=2`, `backoff_s=1.0`, and an injectable `sleep` to `HttpApiRunner`.
  Retry only `GET` and `HEAD`.
  Retry only `TimeoutError` and `URLError`.
  Never retry `HTTPError`.
  Normalize an exhausted or non-retryable transport failure to `ApiError(call, 0, detail)`.
  Keep the retry logic in the runner, not in the trial driver.
- Acceptance: the trial never aborts on a raw `TimeoutError`.
  The existing `ExplodingApi` driver test still records an `ApiError` failure.
  The runner tests prove the bounded attempt count.

Reload guard:

- Test: `tests/eval/test_eval_overlay.py::test_eval_overlay_disables_agent_reload`.
  The test parses `eval/docker-compose.eval.yml` and asserts `services.agent.environment.AGENT_UVICORN_ARGS == ""`.
- Implementation: add `AGENT_UVICORN_ARGS: ""` to the eval overlay's agent environment.
- Implementation: add `eval/deploy/sync_instance.sh` with the source sync, manifest diff, and tree hash.
- Acceptance: the source manifest diff is empty.
  The agent container has no `--reload`.
  The app log has no `StatReload` during the trial.

Trial and gate:

- Trial `armm-wj-runtime`.
- Gate: zero structured-channel warnings, no transport abort, no reload, source hash unchanged.
- GT gate: no regression larger than 0.02 against the 0.697 high baseline.
  The five stable items keep their baseline outcomes, except that the E2 item stays missed.
- If the rec1 fix changes the analysis input enough to move the GT, diagnose before advancing.

### Batch 2 - E1 services-to-systems linking

Files:

- `src/polymerhus/analysis/prompts/technical-system.md`
- `tests/analysis/test_technical_system_prompt.py` (new or the nearest prompt-test module)
- `eval/setups/webexploitbench-arm-m-e1.yaml` (new)

Implementation:

- Add a `## Link each System to its Services` section after `## Name the witness (evidence)`.
  The section mirrors the evidence section's style.
  It states that an unlinked System is unusable, names the exact `service_slug`, the exact `rel`, the one-edge-per-pair rule, and the no-duplicate rule.
  It states that the gate filters every route its chain covers, including anonymous-allowed routes.
  It states that `prefer PRIMARY` orders the links and does not restrict them only where needed; the dedicated E6 wording lands in Batch 5.
- Expand Example 6 into the authorization-linking worked example.
  Show the role-gated response, the full route chain, the service selection, the exact `AUTHORIZED_BY` edge, the evidence, and the stop-at-existence boundary.
  Show the emission as a concrete `system_edges` entry.
- Test: the prompt test asserts the new section heading, the `system_edges` example, the anonymous-allowed route sentence, and the expanded Example 6 terms.

Trial and gate:

- Trial `armm-wj-e1`.
- Gate: the `white-jotter-002`, `004`, and `007` M4 `AUTHORIZED_BY` items land.
- `AUTHORIZED_BY` count stays at 6-7, not 12.
- No public service gains a gate edge without evidence.
- Expected cumulative GT: about 0.760.

### Batch 3 - E3 authorization description primitives

Files:

- `src/polymerhus/analysis/prompts/technical-system.md`
- `tests/analysis/test_technical_system_prompt.py`
- `eval/setups/webexploitbench-arm-m-e3.yaml` (new)

Implementation:

- Extend `## Writing a System description` with the description-primitive rule.
  The rule requires the observed mechanism primitives that make the System adversarially usable.
  The full primitive coverage is a later threat-modelling phase.
- For `AuthorizationSystem`, require:
  - the request object carrying the identification material, such as the Authorization header or JWT, a specific cookie, or a request payload parameter;
  - any privilege level observed;
  - the breadth of the protected surface;
  - the observed trust-agreement semantics on the authorization axis, applied to the services the evidence supports;
  - a bounded probe is allowed to shape the trust boundary, never extensive probing.
- Extend Example 6 with those primitives without turning it into a role-hierarchy dump.
- Test: the prompt test asserts each required authorization primitive and the bounded-probe sentence.

Trial and gate:

- Trial `armm-wj-e3`.
- Gate: `white-jotter-004` M3 is 5/5.
- The high run-specific S2/S4 statements on `002` stay satisfied.
- No boilerplate description inflation.
- Expected cumulative GT: about 0.789.

### Batch 4 - E4 edge union

Files:

- `src/polymerhus/analysis/mechanism_typist.py`
- `tests/analysis/test_mechanism_typist.py` or the nearest writer test
- `eval/setups/webexploitbench-arm-m-e4.yaml` (new)

Implementation:

- Union `systems_batch.system_edges` and `link_batch.system_edges` before `_reconcile_webpresentation`.
- Deduplicate by `(service_slug, kind, discriminator, rel)`.
- Update the `trace_generation` output to include the union, so the emitted inventory and the committed inventory use the same set.
- Test: a fake two-call typist where the extraction call emits an edge and the linking call emits none.
  Assert the combined batch contains the edge.
  Add a duplicate case and assert one edge survives.

Trial and gate:

- Trial `armm-wj-e4`.
- Gate: the `navigation-menu` `AUTHENTICATED_BY` and `IDENTIFIED_BY` pair commits.
- The emitted-versus-committed dropped set is empty.
- The GT does not regress.

### Batch 5 - E6 prefer PRIMARY

Files:

- `src/polymerhus/analysis/prompts/technical-system.md`
- `tests/analysis/test_technical_system_prompt.py`
- `eval/setups/webexploitbench-arm-m-e6.yaml` (new)

Implementation:

- Replace the ambiguous `prefer the PRIMARY services` sentence with an explicit ordering rule.
  `prefer` orders the links; it does not restrict them.
  Emit a link for every service the evidence supports.
- Keep the change to the one sentence and one test assertion.

Trial and gate:

- Trial `armm-wj-e6`.
- Gate: `SHAPES_DATA_OF` coverage stays at 8 services.
- No service loses a supported link.
- The GT does not regress.

### Batch 6 - E7 placement discipline

Files:

- `src/polymerhus/analysis/prompts/assigner.md`
- `tests/analysis/test_assigner_prompt.py` or the nearest prompt-test module
- `eval/setups/webexploitbench-arm-m-e7.yaml` (new)

Implementation:

- Add a short placement-discipline section to the assigner prompt.
- Require a per-endpoint evidence tag in `evidence_refs`: `live route` or `mirror shell`.
- State the default: a live route is placed when the evidence supports an owner; a mirror shell that repeats the same SPA shell across paths stays unowned unless the evidence shows a distinct business surface.
- Keep the existing null-hypothesis and shared-ownership rules unchanged.
- Test: the prompt test asserts the two tags and the default sentence.

Trial and gate:

- Trial `armm-wj-e7`.
- Gate: placement completeness stays at 71 of 114 endpoints.
- A ten-path precision sample shows a tag and a defensible owner for every sampled placement.
- No hunting-anchor starvation: the aggregate count stays near the high baseline.
- The GT does not regress.

## 9. Decision gates

After each trial:

- Advance only when the batch gate passes and the GT regression is within 0.02.
- Fix and re-run the same batch when the gate fails because of a defect in the batch.
- Stop the stack and diagnose when a regression exceeds 0.02 or a stable item flips from hit to miss without an explanation.
- Treat a contaminated trial as no trial.
  A reload, a source hash change, or a raw transport abort is contamination.
- Record every negative and neutral result.
  Do not hide a failed experiment.

## 10. Risks and mitigations

- Rec1 can change the analysis input, not only the delivery channel.
  Mitigation: the runtime trial is a measured baseline, not an assumed no-op; compare the recon and analysis inventories.
- Prompt edits are wording-sensitive and can over-link or inflate descriptions.
  Mitigation: count guardrails (`AUTHORIZED_BY` 6-7, `SHAPES_DATA_OF` 8) and the per-spec GT.
- The trial budget can stop hunting before the assessment.
  Mitigation: the GT and the L1 structural metrics come from the drained analysis phase, which completes before hunting.
- The eval host source copy can be overwritten by another process.
  Mitigation: the manifest diff before the trial and the hash recheck after it.
- The dev overlay can reintroduce reload.
  Mitigation: the eval overlay asserts `AGENT_UVICORN_ARGS: ""`, the config test guards it, and the app log is checked.
- The `.env` merge can drop instance-only keys.
  Mitigation: the allowlist merge, a backup, and a value-pair verification.
- The Langfuse keys can point at the wrong organization.
  Mitigation: verify the `polyphemus` project before the trial.
- The n=1 trials are directional.
  Mitigation: report points, not significance; use the stable-item inventory and the fixed corpus.

## 11. Rollback

- Keep a backup of the instance `.env` at `/tmp/armm-instance.env.bak` before the merge.
- Keep a backup of the instance `eval/docker-compose.eval.yml` before the overlay sync.
- To roll back a batch, sync the previous branch's `src/` and overlay to the instance, force-recreate the agent, and re-run the previous trial's setup.
- Remove an abandoned worktree with `git worktree remove <path>`.
- Do not delete the instance data root.
  It carries the trial evidence.

## 12. Execution log

Fill this section after every step.

### 2026-10-20 - plan and baseline

- Worktree `arm-m-runtime` created at `bace9e10` on branch `exp/arm-m-runtime-rec1-rec2`.
- Baseline targeted tests: 139 passed.
- Read-timeout diagnosis recorded in section 3.
- E2 refusal verified against the domain model, `graph_tools.py`, `graph_view_tool.py`, and `hunting-agent.md`.
- Plan written.

### Batch 1 - red and green

- Red: five new checks failed.
  The prompt test lacked `_ObservationBatch`, the four runner tests failed on the missing `retries`/`sleep` seam, and the overlay test raised `KeyError: AGENT_UVICORN_ARGS`.
- Green: 198 targeted tests passed, including the eight overlay/compose tests.
- The setup file `eval/setups/webexploitbench-arm-m-runtime.yaml` parses as `armm-wj-runtime` with the 4,000,000 budget.
- The sync script passes `bash -n`.
- The overlay test replaced the old `--reload` assertion in `test_eval_overlay_renders_with_complete_env`.

### Batch 1 - attempt 1 (aborted before recon)

- The launch omitted `--data-root`, so the trial checked the authn skill under the harness worktree's `data/` directory.
  The app wrote the skill to the instance data root, so the check failed with "the authn skill did not land".
- The project `f85db8a6-0c9c-461f-8347-37446f6a6c0f` is orphaned: the auth files and skill landed, and no recon ran.
- The failed log is kept at `eval/runs-armm/runtime/trial-attempt1.log`.
- The re-run passes `--data-root /opt/polymerhus-dev/eval/instances/data/eval-server-1`.
- This is a launch-argument error, not an app failure.

### Batch 1 - runtime result (pass)

- Trial `white-jotter-1-20261020T103730-1618c524`, project `f6fc851b-d2f4-43fe-a123-e193d3898c86`, `target_run_id: armm-wj-runtime`.
- Recon: 13 jobs, 12 success, 1 skipped (`graphql-cop`); complete at 09:53.
- Analysis: drained at 10:05.
  `passes` 9, `advanced` 8, `dispatches_entered` 12, `l0_assets_read` 681, `pass_seconds_total` 1353.
- Hunting: started at 10:05, stopped at 10:37 on the token budget.
- Spend: 4,012,199 capped tokens, overshoot 41,625.
- GT final: **0.711111** against the **0.696825** high baseline.
  The delta is **+0.014286**, inside the 0.02 regression gate.
- Per-spec (runtime against high):
  - `white-jotter-001` sign-in: 0.800 against 0.800.
  - `white-jotter-002` AuthorizationSystem: 0.522 against 0.589.
    M3 fell from 0.6 to 0.4, so the runtime lost one run-specific description statement (S1, S2, and S4 are absent; S3 is present).
  - `white-jotter-003` article-publishing: 1.000 against 1.000.
  - `white-jotter-004` AuthorizationSystem: 0.767 against 0.767.
    M3 is 0.8 and the `username` statement (S2) is still missing.
  - `white-jotter-005` book-search: 0.833 against 0.833.
    The `keywords` M2 item is still missing.
  - `white-jotter-006` book-cover-serving: 0.500 against 0.333.
    M4 rose from 0.0 to 0.5, so one presentation link now commits.
  - `white-jotter-007` account-registration: 0.556 against 0.556.
    The `AUTHORIZED_BY` M4 item is still missing.
- The five stable items keep their baseline outcomes:
  - `002`, `004`, and `007` still miss `account-registration` / `AUTHORIZED_BY` from `account-registration`;
  - `005` still misses the `keywords` M2 item;
  - `004` still misses the `username` M3 statement.
- The committed `AUTHORIZED_BY` count is 6, already inside the 6-7 E1 gate range.
  The missing edge is `account-registration -> AuthorizationSystem`, so E1 adds at most one edge.
- Rec 1: zero `triager structured-channel` recoveries over the whole trial.
- Rec 2: no transport abort; no `TimeoutError`, `URLError`, or `Traceback` in the app log.
  The recon, analysis, and hunting status polls all completed.
- Reload: `AGENT_UVICORN_ARGS` is empty and the log has zero `StatReload` entries.
- Source hash: the `src` manifest stayed at `d38753c139b6dfef7dc970acf9e510c9d71019b28a7667eeb101d75fd11101d2`, and the local and instance manifests are identical.
- Diagnosis of the GT movement:
  the rec 1 recovery count is zero, so the triager delivery channel did not change the graph input.
  The movement is run-to-run model variation: `002` lost one run-specific statement while `006` gained a presentation link.
  The five stable items are unchanged, so the batch gate holds.
- Decision: **pass**; advance to E1.
- Expected E1: `0.711111 + 0.0635 = 0.7746` if the three M4 items land.
- Expected E3: `0.711111 + 0.0635 + 0.0381 - 0.0238 = 0.7889` if E1 and E3 land and E2 stays refused.

### Batch 2 - E1 attempt 1 (gate failed)

- Trial `white-jotter-1-20261020T115419-1618c524`, project `8b21bc29-f641-411d-b2c0-30c8bbbf2e40`, `target_run_id: armm-wj-e1`.
- Recon: complete with the same 13-job shape as the runtime trial.
- Analysis: drained at 11:43.
- Hunting: started at 11:44 and stopped deliberately at 11:53 once the gate failed; the hunt cannot change the L1 graph.
- Spend: 1,754,397 tokens.
- GT provisional: **0.706349** against the 0.696825 high and the 0.711111 runtime.
- The three E1 M4 items did not land:
  - `002` M4 is 0.5; the `account-registration` edge is missing.
  - `004` M4 is 0.5; the `account-registration` edge is missing.
  - `007` M4 is 0.667; the `AUTHORIZED_BY` edge is missing.
- The committed `AUTHORIZED_BY` edges are 5, from the same five admin services in all three arms:
  `navigation-menu`, `user-administration`, `role-permission-administration`, `book-management`, `article-management`.
- `register` (the GT alias `account-registration`) has no `AUTHORIZED_BY` edge in any arm: high 0, runtime 0, E1 0.
  The high's committed count is also 5, so the earlier "12" figure was wrong or measured a different relation; this entry corrects it.
- Other movement is run variance:
  - `002` M3 rose 0.4 -> 0.6;
  - `004` M3 rose 0.8 -> 1.0 (the `username` statement landed);
  - `006` M4 fell 0.5 -> 0.0.
- Diagnosis:
  the role-prompt section asks for every evidenced Service, but the linking call's last message says "prefer PRIMARY services".
  The typist links the admin surfaces that plainly sit behind the path filter and never treats the self-service registration Service as part of the authorization chain.
  The worked example's anonymous route is the same Service (the admin shell), so it does not teach the cross-Service account-creation link.
- Fix:
  make the account-creation Service explicit in the section and in Example 6.
  The registration Service mints the accounts the gate authorizes, so it gains `AUTHORIZED_BY` even though its own route is anonymous and it may be listed as SECONDARY.
  Example 6 emits two edges: the admin Service and the account-registration Service.
  The prompt test asserts both edges and the account-creation rule.
- The fix is committed and the same batch is re-run as attempt 2.

### Batch 2 - E1 attempt 2 (pass)

- Trial `white-jotter-1-20261020T125212-1618c524`, project `53dc6c5b-592a-49c4-9c33-0f984d0cb9c4`, `target_run_id: armm-wj-e1`.
- Recon: complete; analysis: drained; hunting: stopped at the 4M token budget.
- Spend: 4,082,214 tokens, overshoot 82,214.
- GT: **0.760317** against the 0.696825 high.
  The delta is **+0.063492**.
- The runtime's 0.711111 included a run-variance `006` M4 gain (0.5) that did not repeat.
  Against the high every non-E1 item returned to its high value, so the delta is exactly the three M4 gains:
  `002` +0.1667, `004` +0.1667, `007` +0.1111, divided by 7 = +0.0635.
- The three E1 M4 items land:
  - `002` M4 rises 0.5 -> 1.0; `article-publishing` and `account-registration` both match.
  - `004` M4 rises 0.5 -> 1.0; both match.
  - `007` M4 rises 0.667 -> 1.0; the `AUTHORIZED_BY` item matches.
- Per-spec (high -> E1):
  - `001` 0.800 -> 0.800;
  - `002` 0.589 -> 0.756;
  - `003` 1.000 -> 1.000;
  - `004` 0.767 -> 0.933;
  - `005` 0.833 -> 0.833;
  - `006` 0.333 -> 0.333;
  - `007` 0.556 -> 0.667.
- The committed `AUTHORIZED_BY` count is 7:
  the five admin services (`article-management`, `book-management`, `navigation-menu`, `role-permission-administration`, `user-administration`) plus `register` (alias `account-registration`) and `sign-in`.
  The 7 is inside the 6-7 gate; the two edges beyond the high's 5 are exactly the account-creation and sign-in links.
- The remaining stable gaps are unchanged:
  - `004` M3 `username` is missing (0.8);
  - `005` M2 `keywords` is missing;
  - `006` M4 is missing again, so the runtime's 0.5 was run variance.
- Rec 1: zero `triager structured-channel` recoveries.
- Rec 2: no transport error, no `Traceback` in the app log.
- Reload: `AGENT_UVICORN_ARGS` is empty and the log has zero `StatReload` entries.
- Source hash: `5651d301ae457ffb0193c6a028aa85423206724f03ecc2c25397e734d48b154d` on both sides; the local and instance manifests are identical.
- The plan's earlier E1 expected 0.7746 assumed the runtime's `006` M4 gain persisted.
  The clean high-relative result is 0.7603.
- Decision: **pass**; advance to E3.

### Batch 3 - E3 attempt 1 (gate failed)

- Trial `white-jotter-1-20261020T134507-1618c524`, project `2fedc478-1bfc-4fc7-971b-9eaef4bb340d`, `target_run_id: armm-wj-e3`.
- Recon: complete (13 jobs); analysis: drained at 13:38; hunting: stopped deliberately at 13:45 once the gate failed.
- Spend: 1,896,680 tokens.
- GT provisional: **0.769841**, up from the E1 0.760317.
- The primary gate fails: `white-jotter-004` M3 is **4/5**, not 5/5.
  - S2 (`username`) is missing.
- `white-jotter-002` M3 is 4/5:
  - the E3 primitives landed S2 (`principal`, `cookie`) and S4 (`filter`, `reachable`);
  - the high's S1 was lost: the description says "302 with Location" but never the word "redirect", and the GT matches the literal `302` and `redirect` pair.
- The committed AuthorizationSystem description names the authenticated session principal, the cookie, the per-route filter and the directly reachable route, and the role vocabulary.
  It never names the `username` request parameter, and it states the refusal as "302 with `Location: ...`".
- Diagnosis:
  the rule lists the carriers as alternatives ("an `Authorization` header or JWT, a specific cookie, or a request-payload parameter"), so the model named the cookie and dropped the parameter carrier.
  The refusal bullet does not exist, so the model paraphrased the 302 and lost the `redirect` vocabulary.
  The example's `username` and `302 redirect` words did not transfer to the evidence-driven text.
- Fix:
  require EVERY observed carrier, literally naming each request-payload parameter (for example `username`);
  require the refusal shape with the literal status vocabulary ("302 redirect", not just "302");
  name the request parameter on the deny path inside the trust-agreement bullet;
  bound the description to at most three sentences and the protected route families, never every route.
- The fix is committed and the same batch is re-run as attempt 2.

### Batch 3 - E3 attempt 2 (gate failed)

- Trial `white-jotter-1-20261020T141549-1618c524`, project `3a98b8fb-22dd-4e50-be78-cd1cbc0de952`, `target_run_id: armm-wj-e3`.
- Recon: complete; analysis: drained at 14:11; hunting: stopped deliberately at 14:16 once the gate failed.
- Spend: 1,365,521 tokens.
- GT: **0.793651**.
  The +0.0238 against attempt 1 is entirely the `006` M4 run-variance flip (0.0 -> 0.5); the `002` and `004` M3 shares are unchanged at 0.8.
- The primary gate still fails: `white-jotter-004` M3 is **4/5**.
  - S2 (`username`) is still missing.
- `white-jotter-002` M3 is 4/5:
  - S1 (`302 redirect`) is regained;
  - S3 and S4 stay;
  - S2 (`principal` + `cookie`) is lost: the description says "JSESSIONID session" and "rememberMe token" and never the word "cookie".
- The committed description is an exhaustive route enumeration.
  It names the session/token principal, the role vocabulary, the coverage and the registration route, but not the generic carrier classes (`cookie`, `username`).
- Diagnosis:
  the model writes the specific carrier names and route functions, not the carrier class;
  the GT sufficiency statements read the class words.
  The length bound was also not followed.
- Fix:
  require the carrier class alongside the specific name: a `JSESSIONID` or `rememberMe` value is a cookie, so write "the JSESSIONID cookie"; a form field is a request parameter, so write "the `username` request parameter";
  name the account-creation route's `username` parameter as the principal carrier the account store receives.
- The fix is committed and the same batch is re-run as attempt 3.

### Batch 3 - E3 attempt 3 (gate failed)

- Trial `white-jotter-1-20261020T144917-1618c524`, project `f735e35f-c7b6-413e-8c6e-2874ee195f92`, `target_run_id: armm-wj-e3`.
- Recon: complete; analysis: drained at 14:47; hunting: stopped deliberately at 14:49 once the gate failed.
- Spend: 998,159 tokens.
- GT: **0.779365**.
  The `002` M3 gain is offset by the `005` M4 run-variance loss (1.0 -> 0.5).
- `white-jotter-002` M3 is now **5/5**:
  the carrier-class fix landed S2 (`principal` + `cookie`), and S1 (`302 redirect`), S3 and S4 stay.
  The spec score is 0.8889.
- The primary gate still fails: `white-jotter-004` M3 is **4/5**.
  - S2 (`username`) is still missing after three attempts.
- The description (1,711 characters) carries the cookie class, the 302 redirect, the principal, the role vocabulary, the per-route filter and the registration trust boundary.
  It says "the anonymous /api/register resource whose registrants land in the back office" but never names the `username` request parameter.
- Diagnosis:
  the descriptive bullets do not force the account-creation parameter;
  the model paraphrases the register route and never reads the field name.
- Fix:
  add a pre-emit checklist that names each observed item, including the `username` request parameter, and read the register form or recorded request when the map omits the field name.
- The fix is committed and the same batch is re-run as attempt 4.

### Batch 3 - E3 attempt 4 (pass)

- Project `5f75d8e9-60b2-499e-bb73-9027a8c2ed8f`, `target_run_id: armm-wj-e3`.
- Trial `white-jotter-1-20261020T155658-1618c524`; stopped at the 4M budget with **4,026,424** tokens (overshoot 26,424).
- Recon: complete; analysis: drained at 15:19; hunting: stopped at the budget.
- GT: **0.765079** against the 0.696825 high; delta **+0.068254**.
  The GT is below attempt 3 because of run variance in `005` M2 (0.5 -> 0.0) and `006` M4 (0.5 -> 0.0), not the E3 change.
- The primary gate passes: `white-jotter-004` M3 is **5/5**.
  - S2 (`username`) lands: the description says the accounts are "minted anonymously by POST /api/register from its `username` request parameter".
- `white-jotter-002` M3 is **5/5**:
  - S1 (`302 redirect`), S2 (`principal` + `cookie`), S3 (`role`) and S4 (`filter` + `reachable`) all present.
- Per-spec (high -> E3):
  - `001` 0.800 -> 0.800;
  - `002` 0.589 -> 0.889;
  - `003` 1.000 -> 1.000;
  - `004` 0.767 -> 1.000;
  - `005` 0.833 -> 0.667 (run variance: M2 0.5 -> 0.0, M4 0.5 -> 1.0);
  - `006` 0.333 -> 0.333 (M4 0.0; run variance);
  - `007` 0.556 -> 0.667.
- The description is 2,239 characters and 3 sentences; it carries the cookie class, the 302 redirect, the `username` parameter, the principal, the observed roles, the per-route enforcement, the two refusal shapes and the registration trust boundary.
  It is not boilerplate; every clause is an observed fact.
- The checklist fix is the causal change: the pre-emit checklist forced the account-creation parameter that three descriptive-only attempts missed.
- Rec 1: zero `triager structured-channel` recoveries.
  Rec 2: no transport error.
  Reload: zero `StatReload` entries.
  Source hash: `ee6be96e6cc5a1fd073d05b0790cfc67350ace7af434b8bf06213bb8811e6eae` on both sides; the local and instance manifests are identical.
- Decision: **pass**; advance to E4.

### Batch 4 - E4 (pass)

- Project `402fa3de-bced-482a-99d3-73109d93923b`, `target_run_id: armm-wj-e4`.
- Trial `white-jotter-1-20261020T170107-1618c524`; stopped at the 4M budget with **4,008,655** tokens (overshoot 8,655).
- Recon: complete; analysis: drained at 16:31; hunting: stopped at the budget.
- GT: **0.793651** against the 0.696825 high; delta **+0.096825**.
  Against the E3 attempt 4 it is **+0.028572**.
- The primary gate passes: the `navigation-menu` `AUTHENTICATED_BY` (AuthenticationMechanism) and `IDENTIFIED_BY` (IdentificationSystem) pair commits.
- The emitted-versus-committed dropped set is empty:
  the six `typist-systems-and-edges` generations emit **62** edge identities and the committed graph holds the same **62**; `dropped=0`, `committed-but-not-emitted=0`.
- Per-spec (high -> E4):
  - `001` 0.800 -> 0.800;
  - `002` 0.589 -> 0.756;
  - `003` 1.000 -> 1.000;
  - `004` 0.767 -> 1.000;
  - `005` 0.833 -> 0.833;
  - `006` 0.333 -> 0.500;
  - `007` 0.556 -> 0.667.
- The E3 gains hold where they are causal: `004` M3 stays 5/5.
  `002` M3 reads 0.6 on this run (E3 attempt 4: 1.0); the edge union does not touch the description, so this is the known description-run variance.
  The `005` M2 recovery and the `006` M4 flip are likewise run variance.
- Rec 1: zero `triager structured-channel` recoveries.
  Rec 2: no transport error.
  Reload: zero `StatReload` entries.
  Source hash: `3519cb97a9cdc20728a1fe6753273c71ecc5c11caba545e69ac8b7587643d0a6` on both sides; the local and instance manifests are identical.
- Decision: **pass**; advance to E6.

### Batch 5 - E6 pending

### Batch 5 - pending

### Batch 6 - pending
