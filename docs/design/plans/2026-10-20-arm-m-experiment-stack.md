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

### Batch 2 - pending

### Batch 3 - pending

### Batch 4 - pending

### Batch 5 - pending

### Batch 6 - pending
