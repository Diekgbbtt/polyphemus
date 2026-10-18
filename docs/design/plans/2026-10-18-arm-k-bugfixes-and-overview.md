# Arm K: bug fixes + the Overview-integrated iteration - execution plan

Status: active (2026-10-18).
Owner: the coordinator agent (this session); fix agents dispatched per Appendix A.
Contract: the operator's directive of 2026-10-18 and the five ratified answers in section 0.
Companion docs: `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md` (the registry this iteration extends); `docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md` (the criterion this iteration centers on).

---

## 0. Ratified decisions (operator, 2026-10-18)

1. **Overview delivery: keep the delivered Q4 model.**
   The assigner and the mechanism-typist each send the dedicated Overview-only `HumanMessage` at the head of their turn, coupled by the chaining verbatims (`_ASSIGN_CHAIN`, `_TYPIST_CHAIN`).
   Arm K carries this as-is; no prompt-architecture change.
2. **C5 precision policy: include the optional assigner decision node.**
   On a failed or dropped verification tool call, the assigner fails open: it keeps loose control, writes the aggregation edge, and names the wrong-unit-concretisation risk in its evidence.
   #369 remains the upstream fix; the node is the defence-in-depth.
3. **Trial slice: comfyui + white-jotter**, same budgets as arm J formal (3M / 4M capped) and the same model (`opencode-go:deepseek-v4.1-flash`).
4. **Stacking: merge the four fixes AND the TA1/TA2 tooling branch into `dev`; push; align the eval instance.**
   Operator caveat: the containerised stack runs the DEV compose, which live-mounts `./src` with `uvicorn --reload` and `compose watch` restart (`docker-compose.dev.yml`); no image rebuild is needed, and the instance container refreshes once the worktree source is aligned.
5. **Criterion corrections before the measurement.**
   M3 Service spine = `business_function` (the managed `business_function_slug`), `exposure`, `service_contract`.
   `api_paradigm` and `auth_methods` leave the Service requirements: the domain model places them System-side (`docs/design/l1-domain-model-catalogue.md` section 3), reached by edges - already measured as `EXPOSED_VIA -> RESTApi/GraphQLApi` and `AUTHENTICATED_BY -> AuthenticationMechanism`.
   Capability-gap statements count as satisfied-by-declaration.
   Re-baseline arm J formal under the corrected criterion before arm K.

Explicitly NOT in arm K: no harness changes beyond the new setup file; no budget or model change; no change to the Q4 Overview delivery; no targets beyond the two; no work on tickets #359-#363, #366, #367 (operator: false failures or out of scope).

## 1. Termination conditions

Execute end to end until one of:

- **Goal reached**: the four fixes are merged and reviewed; `dev` is pushed; the eval instance is aligned and refreshed; the arm K trials (comfyui + white-jotter) complete; the measurement is extended (well-formedness primary + C1-C6 registry rows + the arm K section + recommendation); the report is delivered.
- A **fundamentally blocking technical condition** (degraded stack, a provider/target failure that survives the documented remediation).
- A **global design decision is required** (then deliver the spec/tickets/assertions instead of a fix, per the operator's decision tree).
- **Missing data or a missing technology dependency** (report precisely what is missing).

## 2. Baseline state (verified 2026-10-18)

- Canonical repo: `/Users/diekgbbtt/polymerhus`, branch `dev` at `c3e487bb` (28 commits ahead of `origin/dev` `6c25613`; carries the parallel workstream: structured Overview entity, external bootstrap, regenerated data dependencies).
- This session's branch: `feat/recon-coverage-and-eval-wellformedness` at `c1e3d5e8` (TA1 report, 13 GT unit specs in the local corpus, the criterion tool + tests, the D5 assessment, the optimal-paths/deltas/clusters doc).
- Tickets in scope: **#369** (proposer final tool round), **#354** (System EVIDENCED_BY writer), **#364** (analysis auth_store binding), **#365** (recon method coverage).
- Eval server: `/opt/polymerhus-dev` (canonical clone, `dev` at `6c25613`); instance worktree `/opt/polymerhus-dev/eval/instances/eval-server-1` (detached HEAD at `1163f330`); containers `ph-dd131acc-*`; instance compose = `docker-compose.yml` + `docker-compose.dev.yml` + `eval/docker-compose.eval.yml` (`eval/orchestrator/instances.py: COMPOSE_FILES`).
- Stack semantics: the agent service bind-mounts `./src:/srv/src` and runs `uvicorn --reload --reload-dir /srv/src`; `develop.watch` restarts the agent on any `./src` change (the eval server runs watch mode); the gateway proxy never reloads.
- Stack fingerprint: sha256 over the advance manifest (`eval/advance/manifest.py` path-group SHAs + `eval/advance/images.py` running image digests; commit excluded as provenance); `EVAL_SHA` = the instance worktree HEAD; both ride `trial.yaml`.
- Launch template: `/root/drive-run2.sh` (eval-orchestrator `next_target` + `eval_monitor`, then `orchestrator trial` per target with `--eval-sha` and a computed `--stack-fingerprint`, then monitor to convergence, `close-verify`, `store materialize`).
- Data dependencies: `/root/eval-dd/data/<target>/` (regenerated `operator_kb.md` with the structured Overview, `auth/`, `skills/`, plus the `l1-surface.yaml` validation mirror); the harness places `operator_kb.md` + the auth artifacts per trial (`eval/orchestrator/trial.py::_place_data_dependencies` / `_place_l1`).

## 3. W0 - Foundations (this session, no subagents)

### W0.1 Criterion corrections + arm J re-baseline

Files:

- `tools/measure_gt_wellformedness.py` + `tests/tools/test_measure_gt_wellformedness.py` (this branch).
- The 13 corpus specs `~/.local/share/polymerhus/vuln-groundtruth/<target>/<bundle>/unit-spec.yaml` (local-only corpus; the operator kept the locus).
- `docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md`.

Changes:

1. Service spine: the field `business_function` resolves the Service prop `business_function_slug`; remove `api_paradigm` and `auth_methods` from the Service spine of every spec.
   The paradigm/auth coverage stays in M4, which already requires `EXPOSED_VIA -> RESTApi` and `AUTHENTICATED_BY` where the GT expects them.
2. Statement-level `satisfied_by: capability_gap` support in the tool; mark the statements the spec itself declares capability gaps (wj-004 S1 and S4); audit the other 12 specs for the same condition and mark only declared gaps.
3. Re-run the criterion over the four arm J projects (comfyui base `2df3ad9d`, comfyui formal `d04b947f`, wj base `bf0d9408`, wj formal `f16de150`); update the assessment doc with a "corrected baseline (2026-10-18)" section that keeps the original numbers visible.

Verification: `--lint` clean on 13 specs; the tool's unit tests pass (extend them for both changes); the four re-runs reproduce from the documented commands; the doc's corrected numbers match the tool output.

### W0.2 Arm K setup file

`eval/setups/webexploitbench-arm-k.yaml`: one instance (`eval-server-1`), two targets (`webexploitbench/comfyui` with `target_run_id: armk-comfyui`, budget 3,000,000; `webexploitbench/white-jotter` with `target_run_id: armk-white-jotter`, budget 4,000,000), `target_config.operator_kb` and `data_dir` pointing at `/root/eval-dd/data/<target>/`.
Model unchanged (the setup carries no model knob; the instance env does).

### W0.3 C5 assigner fail-open node

Edit `src/polymerhus/analysis/prompts/assigner.md`: add the optional decision node.

Verbatim requirements: when a verification tool call (`search_http_history`, `get_http_artifact`) fails, times out, or returns nothing, the assigner does NOT drop the route: it fails open with loose control, writes the aggregation edge for the best-supported owner, and names the wrong-unit-concretisation risk in its evidence.
A route is dropped only when its owner is genuinely ambiguous, never because verification was unavailable.

Pin with a focused test (the rendered prompt carries the node; mirror the existing prompt-test pattern in `tests/analysis/`).

### W0.4 Plan commit + merge into dev

Commit the plan, the criterion corrections, the setup file, and the C5 node on this branch; then the coordinator merges this branch into `dev` (single dev writer).
No push yet (the push happens once, after the review round and the full sweep).

## 4. W1 - the four fixes (subagent-driven, waves)

Rules for every fix workstream:

- The coordinator creates the worktree off the current `dev` before dispatch: `git -C /Users/diekgbbtt/polymerhus worktree add /Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/<slug> -b <branch> dev`.
- The fix agent works only in its worktree; it does NOT merge into `dev` (the coordinator is the single dev writer) and does NOT touch the eval server or the corpus.
- Workflow per the operator's classification (encoded in the Appendix A prompt per ticket).
- TDD for the fix itself (`/Users/diekgbbtt/.claude/skills/tdd/SKILL.md`, read directly).
- The agent's report must carry: branch + commits, files, test commands + results, diagnosis summary, grill decisions, docs updated, residual risks, merge-readiness statement.

Waves:

- **Wave 1 (parallel, disjoint):** W1.1 #369 (app/llm turn engine) + W1.4 #365 (recon discovery).
- **Wave 2 (parallel; overlaps resolved by the coordinator at merge):** W1.2 #354 (typist proposal + curator write path) + W1.3 #364 (analysis tool binding).

### W1.1 #369 - the dropped final tool round

- Classification: root cause NOT established -> `diagnosing-bugs` FIRST; the diagnosis decides the shape (narrow fix vs design).
- Branch: `fix/369-proposer-final-tool-round`; worktree `.../worktree/7b3bba/fix-369-final-tool-round`.
- Lead evidence in the prompt: the two arm J generations (`5f437dad0095952b` 19:59:06 comfyui, `f2106593` 20:53:53 wj), and the census finding that each assigner session carries exactly ONE ERROR observation at that same timestamp (the arm J results doc: "one assigner chain error per run (19:59:06, 20:53:53) recovered inside its chunk").
- Merge gate: a regression test that fails on `dev` and passes on the branch; every emitted tool call receives its ToolMessage before the next model step (or the turn fails loudly); diagnosis evidence recorded on the ticket.

### W1.2 #354 - the EVIDENCED_BY writer

- Classification: known cause, local -> `grill-with-docs` -> design-doc adjustments -> TDD.
- Branch: `fix/354-system-evidenced-by`; worktree `.../worktree/7b3bba/fix-354-evidenced-by`.
- Merge gate: the proposal -> curation path writes `EVIDENCED_BY` for each witness (Header / Technology / Certificate / recorded transaction); a no-witness claim stays edgeless; the relabel remap still works; the read side (graph_view neighbours, index-card edge degree) surfaces the edge; suites green.

### W1.3 #364 - the analysis auth_store binding

- Classification: local enhancement with grey points -> `grill-with-docs` -> TDD.
- Branch: `fix/364-analysis-auth-store`; worktree `.../worktree/7b3bba/fix-364-auth-store`.
- Merge gate: the read-only binding is present for the typist and the assigner; no write or authenticate capability; the redaction decision recorded; the analysis `CONTEXT.md` updated; tests green.
  The ticket's "a trial shows the typist referencing its session material" is satisfied by arm K.

### W1.4 #365 - recon method coverage

- Classification: cause known, blast radius unknown -> `diagnosing-bugs` FIRST; if the fix needs a new discovery -> probe contract, then `to-spec` -> `to-tickets` -> `to-assertions`; else `grill-with-docs` -> TDD.
- Branch: `fix/365-recon-method-coverage`; worktree `.../worktree/7b3bba/fix-365-method-coverage`.
- Scope guard (operator: light recon change): no job-graph rewrite; the acceptance is that a write route discovered with a method hint is probed (and at minimum minted) with that method.

### W1.5 Fix merges (coordinator)

As each fix reports green: the coordinator merges the branch into `dev` (one at a time), re-runs the touched suites plus the neighbouring suites on `dev`, records the merge commit, and comments the ticket with the merge + evidence.

## 5. W2 - one critical adversarial review round

Scope: the whole `dev` delta since `c3e487bb` (this branch's merge + the four fix merges).

1. Dispatch the `code-reviewer` subagent with the diff range, the four tickets, and the two-axis rubric (Standards + Spec).
2. Triage findings by severity; fix the accepted findings (dispatch a focused fix agent per finding group, or the coordinator for trivial ones); re-run the affected suites.
3. Record the review outcome in the plan's status log and on the tickets.

## 6. W3 - stacking, push, eval alignment

1. Full local sweep on `dev`: the unit tier + the affected integration tiers, run per the repo's convention; record the pre-existing failures (known: `tests/test_llm_checkpoints_module.py::test_the_module_scoped_saver_carries_the_serde_allowlist` on the installed langgraph; `tests/test_llm_sync_key_rotation.py::test_budget_windows_are_provisioned_and_converge` flaky; the live tiers that need infrastructure) so nothing new is misattributed.
2. `git push origin dev` (this also publishes the parallel workstream's commits).
3. Align the eval instance:
   - `git -C /opt/polymerhus-dev fetch origin && git -C /opt/polymerhus-dev merge --ff-only origin/dev`.
   - Fast-forward the instance worktree: `git -C /opt/polymerhus-dev/eval/instances/eval-server-1 merge --ff-only <new-dev-sha>` (detached HEAD; the new sha is a descendant of `1163f330`).
   - Confirm the refresh: `docker inspect ph-dd131acc-agent-1 --format '{{.State.StartedAt}}'` moves (compose watch restart) or `docker compose ... up -d --force-recreate agent`; then probe the new code inside the container (`/srv/src` carries the new commit's content).
   - Recompute the stack fingerprint with the `drive-run2.sh` snippet; check `eval/state/alignment.yaml` and resolve any hold per `orchestrator alignment`.
   - Record: instance HEAD sha, fingerprint, agent restart evidence.

## 7. W4 - arm K: delta model, trials, measurement

### W4.1 The implementation delta from arm J (write first)

A "What changed" section listing, with commits: #369, #354, #364, #365, the C5 node, the regenerated bootstrapped-L1 data dependencies (data-side), and the criterion corrections (measurement-side).
This is the model the measurement is read against; it lands in the plan's status log and later in the results doc.

### W4.2 Trials

On the eval server, mirroring `/root/drive-run2.sh` with:

- `EVAL_SETUP=eval/setups/webexploitbench-arm-k.yaml`, `EVAL_RUN_TARGETS="comfyui-1 white-jotter-1"`, `EVAL_RUNS_ROOT=eval/runs-armk`.
- Chain state: back up `eval/instances/eval-server-1/chain-state.yaml`, then reset it for the fresh arm K cycle (per the run2 convention).
- Per target: eval-orchestrator `next_target` + `eval_monitor`; `orchestrator trial` with the recorded `--eval-sha` and `--stack-fingerprint`; then monitor to convergence; `close-verify`; `store materialize`.

### W4.3 Measurement (primary: the well-formedness criterion)

1. GT well-formedness: run `tools/measure_gt_wellformedness.py` against the arm K projects (both targets), per-unit M1-M4 + unit scores + `--lint`; compare against the corrected arm J formal baseline.
2. Goal 2: analysis-role cached share (triager, assigner, mechanism_typist) from the durable usage API (`GET /projects/{pid}/usage`), versus the 70% bar.
3. The existing framework: C1-C3 + C5 from the graph queries (results doc appendix), C4 from the usage ledger, C6 from the Langfuse trajectory (the W2.4-style pulls).
4. Outcome-quality defect classes for arm K (which assessment-doc classes closed, which remain), per the D5 shape.
5. Registry: append the arm K rows to the cumulative per-target registry; write the arm K section (hypothesis, what ran, comparison tables, C5/C6 readings, learnings, verdict, next steps) per `/Users/diekgbbtt/.claude/skills/measure-experiment-results/SKILL.md`.

### W4.4 Docs + push

Commit the results-doc extension and the assessment-doc updates; push (docs-only).

## 8. W5 - report (green-light gate)

Report to the operator: fixes + review outcome + push + alignment evidence; arm K trial records (projects, shas, fingerprints, terminals); the measurement (primary + guardrails); the verdict and the recommended next iteration; any escalated decision.

## 9. Stop rules and feedback loops

- After each fix merge: targeted suites on `dev` (gate G1).
- After the review: accepted findings fixed + re-tested (gate G2).
- Before the push: the full sweep with a documented pre-existing-failure list (gate G3).
- Before the trials: alignment evidence (instance sha, fingerprint, agent restart) (gate G4).
- After each trial: terminal + evidence bundle + monitor convergence before the next target (gate G5).
- Stop immediately and report on any section-1 termination condition; never heal a stack by hand without recording it (the run2 `remediation` convention).

---

## Appendix A - fix-agent prompts (dispatch verbatim, with the branch/worktree specifics filled)

Every prompt requires the agent to READ the referenced files directly from the filesystem, to work only in its worktree, and to stop rather than merge.

### A1 - #369 (the dropped final tool round)

```
You are the fix agent for polymerhus ticket #369: "Analysis (proposer turn): the final tool round of a batch turn is dropped before the commit". You are an expert in the LangGraph-based agent runtime of this repository.

MISSION: pin the mechanism that drops the final tool round of an analysis proposer turn (evidence first, no fix before the diagnosis), then fix it if the fix is narrow; otherwise deliver the design.

READ DIRECTLY FROM THE FILESYSTEM (do not guess; open every file):
- The ticket: run `gh issue view 369 --repo Diekgbbtt/polyphemus`.
- Evidence docs (this branch is not yet on dev; read from the branch: `git -C /Users/diekgbbtt/polymerhus show c1e3d5e8:<path>`):
  - docs/experiments/2026-10-17-typist-assigner-optimal-paths.md (section 3.1; cluster C3)
  - docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md
  - docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md (the arm J C6 row: "one assigner chain error per run (19:59:06, 20:53:53) recovered inside its chunk")
- Code seams: src/polymerhus/app/llm/session.py (`arun_session_turn`), src/polymerhus/app/llm/parsing_recovery.py (its docstrings document the ToolNode-pairing invariants), src/polymerhus/app/llm/actor.py, src/polymerhus/analysis/proposer_turn.py, and the middleware modules they import.
- Conventions: CODING_STANDARD.md (repo root), src/polymerhus/app/CONTEXT.md.
- Skills (read the files directly):
  - /Users/diekgbbtt/.claude/skills/diagnosing-bugs/SKILL.md   (your FIRST workflow)
  - /Users/diekgbbtt/.claude/skills/debug-hypothesis/SKILL.md
  - /Users/diekgbbtt/.claude/skills/critical-thinking-logical-reasoning/SKILL.md
  - /Users/diekgbbtt/.claude/skills/langgraph-docs/SKILL.md    (the turn engine is LangGraph; verify tool-routing/step semantics from the docs)
  - /Users/diekgbbtt/.claude/skills/tdd/SKILL.md               (the fix follows TDD)
  - /Users/diekgbbtt/.claude/skills/langfuse/SKILL.md          (raw observations when needed)

ESTABLISHED EVIDENCE (verify, do not assume):
- comfyui formal (project d04b947f-d6c3-48be-9b18-1c4eef851241): generation 5f437dad0095952b at 19:59:06 emits four search_http_history calls; no TOOL observation follows; the next generation 6b9866064a5b6372 at 20:00:03 commits 64 aggregates.
- white-jotter formal (project f16de150-b032-4566-871b-2df6fa4d48a9): generation f2106593 at 20:53:53 emits three search_http_history calls; no TOOL observation follows; the next generation b4ff9a0b at 20:56:01 commits 51 aggregates.
- The census carries exactly ONE ERROR observation per assigner session, at those same timestamps (19:59:06 / 20:53:53). Pull those ERROR observations from Langfuse first: they are the strongest lead.

WORKTREE (create if absent; work only there):
  git -C /Users/diekgbbtt/polymerhus worktree add /Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/fix-369-final-tool-round -b fix/369-proposer-final-tool-round dev

WORKFLOW, in order:
1. DIAGNOSE per diagnosing-bugs: reproduce the failure in a test; state the mechanism with evidence (observation ids, code lines); name the seam.
2. Decide the shape honestly. Narrow and local -> grill the grey points via /Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md (which runs grilling + domain-modeling), adjust the design decisions the fix invalidates, then TDD the fix. Global/structural -> produce the spec via /Users/diekgbbtt/.claude/skills/to-spec/SKILL.md, then /Users/diekgbbtt/.claude/skills/to-tickets/SKILL.md, then /Users/diekgbbtt/.claude/skills/to-assertions/SKILL.md; STOP there and report.
3. The regression test must reproduce the dropped round on dev (red-capable) and prove the fix: every tool call the model emits receives its ToolMessage before the next model step on the same thread, or the turn fails loudly.
4. Report per the output contract below.

DISCIPLINE: fix the invariant where it lives (the session/turn engine or the middleware that owns it), never a shallow patch that hides the error path; keep parsing_recovery's documented pairing invariants true; update docstrings/CONTEXT.md your change invalidates; follow CODING_STANDARD.md; no new dependencies without need.

OUTPUT CONTRACT (report exactly this):
- Status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
- Diagnosis: the mechanism, observation ids, code lines, the repro command
- Branch + commits; files touched
- Test commands + results (the new test red on dev, green on the branch; the touched suites)
- Decisions taken (grill outcomes) and docs updated
- Residual risks; merge-readiness statement

Do NOT merge into dev (the coordinator is the single dev writer). Do NOT touch the eval server, the ground-truth corpus, or other worktrees.
```

### A2 - #354 (the EVIDENCED_BY writer)

```
You are the fix agent for polymerhus ticket #354: "mechanism_typist grounds its Systems in evidence but never writes the EVIDENCED_BY edge".

MISSION: give the mechanism-typist path a real EVIDENCED_BY writer: every System it types carries EVIDENCED_BY edges to the L0 nodes whose observation witnesses it; a witness-less claim stays edgeless; the read side surfaces the edge.

READ DIRECTLY FROM THE FILESYSTEM:
- The ticket: `gh issue view 354 --repo Diekgbbtt/polyphemus` (acceptance criteria included).
- Source: src/polymerhus/analysis/mechanism_typist.py (the 3-call proposer), src/polymerhus/analysis/analyser_types.py (the L1DeltaBatch / system proposal schema), src/polymerhus/analysis/l1_curator.py (`_EVIDENCED_BY`, the relabel remap, the write seam), src/polymerhus/analysis/l1_types.py (the typed edges), src/polymerhus/analysis/graph_tools.py + src/polymerhus/attack/hunting/graph_view_tool.py (the read side), src/polymerhus/analysis/index_card.py (edge degree).
- Domain: src/polymerhus/analysis/CONTEXT.md; docs/design/l1-domain-model-catalogue.md (section 3 and the EVIDENCED_BY classification); docs/design/domain-model.md.
- Prior art and evidence: docs/experiments/2026-10-17-typist-assigner-optimal-paths.md (section 3.2 typist executed paths; the compounds), docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md (M4/C6 readings), docs/design/unit-threat-model-workbench.md (provenance).
- Conventions: CODING_STANDARD.md; skills/analysis/... if the typist has a skills-side prompt.
- Skills (read the files directly):
  - /Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md  (FIRST: resolve the grey points, record the decisions)
  - /Users/diekgbbtt/.claude/skills/grilling/SKILL.md
  - /Users/diekgbbtt/.claude/skills/domain-modeling/SKILL.md
  - /Users/diekgbbtt/.claude/skills/critical-thinking-logical-reasoning/SKILL.md
  - /Users/diekgbbtt/.claude/skills/tdd/SKILL.md

GREY POINTS TO SETTLE IN THE GRILL (and record): which L0 node kinds count as witnesses (Header, Technology, Certificate, Endpoint, a recorded HTTP transaction); how the typist expresses the witness in its proposal (a typed evidence field on the System delta - prefer the domain's L0Ref/identity keys over free text); the curator write semantics (MATCH only against existing L0 nodes; unmatched witness degrades without an edge; idempotent MERGE; `__singleton__` Systems included); how the read side renders the edge (graph_view neighbours + index-card edge degree); the withhold-the-unproven-claim rule stays unchanged; the relabel remap keeps working.

WORKTREE:
  git -C /Users/diekgbbtt/polymerhus worktree add /Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/fix-354-evidenced-by -b fix/354-system-evidenced-by dev

WORKFLOW: grill-with-docs (decisions + any design-doc adjustments the fix invalidates: the technical-system skill text, analysis CONTEXT.md glossary, the catalogue section if the witness semantics change) -> TDD the fix -> suites -> report.
Tests must cover: a proposal with witnesses writes one EVIDENCED_BY per witness; a witness that does not exist in L0 produces no edge and no crash; a no-witness proposal stays edgeless; the remap path is unchanged; the read side surfaces the edge.

OUTPUT CONTRACT: Status | branch+commits | files | test commands+results | grill decisions | docs updated | residual risks | merge-readiness.
Do NOT merge; do NOT touch the eval server or the corpus.
```

### A3 - #364 (the analysis auth_store binding)

```
You are the fix agent for polymerhus ticket #364: "Analysis: bind the read-only auth_store to mechanism_typist and assigner (auth context for request shapes)".

MISSION: give the mechanism-typist and the assigner a read-only view of the project's auth store (accounts, cookie names, token status), with no write or authenticate capability, so they can type request shapes against the recorded session material.

READ DIRECTLY FROM THE FILESYSTEM:
- The ticket: `gh issue view 364 --repo Diekgbbtt/polyphemus` (acceptance criteria included).
- Source: src/polymerhus/analysis/proposer_turn.py (`_surface_tools`, the tool-binding seam), src/polymerhus/analysis/pod.py + src/polymerhus/analysis/supervisor.py (the proposer wiring/collaborators), src/polymerhus/app/auth/seams.py (`auth_capable_binding`, D223-5), src/polymerhus/recon/control/orchestrator_agent.py (the recon binding precedent, lines ~333-368), the auth store module (`AuthStore`) and its read form.
- Domain: src/polymerhus/analysis/CONTEXT.md, src/polymerhus/recon/CONTEXT.md (the auth_store contract; "analysis-domain agents never bind it" is the line you are changing), docs/design/recon-auth-gateway-223-spec.md (D223-5), docs/design/auth-store decisions if present.
- Conventions: CODING_STANDARD.md.
- Skills (read the files directly):
  - /Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md  (FIRST: grey points + decisions)
  - /Users/diekgbbtt/.claude/skills/grilling/SKILL.md
  - /Users/diekgbbtt/.claude/skills/domain-modeling/SKILL.md
  - /Users/diekgbbtt/.claude/skills/critical-thinking-logical-reasoning/SKILL.md
  - /Users/diekgbbtt/.claude/skills/tdd/SKILL.md

GREY POINTS TO SETTLE (record them): the tool's name/form and schema (what the read view exposes: overview, accounts, cookie names, token status); the redaction level for cookie values in the read view (the ticket requires a recorded decision); the exact binding site for both roles (reuse `_surface_tools` / `auth_capable_binding`; keep the write/authenticate capability OUT); how the analysis process obtains the store (which container/mount/interface - check how recon gets it and how the analysis pod gets its collaborators); the tests, including that no write path is reachable.

WORKTREE:
  git -C /Users/diekgbbtt/polymerhus worktree add /Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/fix-364-auth-store -b fix/364-analysis-auth-store dev

WORKFLOW: grill-with-docs -> adjust the design notes the change invalidates (analysis CONTEXT.md; any D223-5 note) -> TDD -> suites -> report.
The ticket's trial-level acceptance ("the typist references its session material") is carried by the arm K iteration; state that in your report instead of running a trial.

OUTPUT CONTRACT: Status | branch+commits | files | test commands+results | grill decisions (incl. the redaction level) | docs updated | residual risks | merge-readiness.
Do NOT merge; do NOT touch the eval server or the corpus.
```

### A4 - #365 (recon method coverage)

```
You are the fix agent for polymerhus ticket #365: "Recon: write routes (POST/PUT/DELETE) are never probed or minted - method coverage".

MISSION: make recon carry method evidence from discovery into minting and probing, so a route the JS uses with a write method (fetch/axios method, form post) is minted - and at minimum probed - with that method. Light recon change: no job-graph rewrite.

READ DIRECTLY FROM THE FILESYSTEM:
- The ticket: `gh issue view 365 --repo Diekgbbtt/polyphemus`.
- Evidence docs (this branch is not yet on dev; `git -C /Users/diekgbbtt/polymerhus show c1e3d5e8:<path>`): docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md (D-2, the method-blind rows), docs/experiments/recon-auth-coverage-verification.md, docs/experiments/2026-10-17-typist-assigner-optimal-paths.md (clusters C2/C3).
- Recon source: src/polymerhus/recon/domain/parsers/ (jsluice_parser.py, webpack_chunks_parser.py, katana_parser.py, httpx_parser.py, passive_url_parser.py, _urls.py), the Endpoint asset model (src/polymerhus/recon/domain/types.py), the probe/profiling job path, the curator/mint path (src/polymerhus/recon/domain/curator.py), and the job definitions that decide probing (src/polymerhus/recon/...).
- Related open tickets for context only: #363 (chained-twin validation), #353 (XHR routes), #366 (EXPR placeholders).
- Domain: src/polymerhus/recon/CONTEXT.md; CODING_STANDARD.md.
- Skills (read the files directly):
  - /Users/diekgbbtt/.claude/skills/diagnosing-bugs/SKILL.md   (FIRST: map the data flow with evidence before touching code)
  - /Users/diekgbbtt/.claude/skills/debug-hypothesis/SKILL.md
  - /Users/diekgbbtt/.claude/skills/critical-thinking-logical-reasoning/SKILL.md
  - /Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md   (if the fix is narrow: grey points first)
  - /Users/diekgbbtt/.claude/skills/to-spec/SKILL.md, /Users/diekgbbtt/.claude/skills/to-tickets/SKILL.md, /Users/diekgbbtt/.claude/skills/to-assertions/SKILL.md  (if the fix needs a new contract)
  - /Users/diekgbbtt/.claude/skills/tdd/SKILL.md

WORKFLOW, in order:
1. DIAGNOSE: produce the exact data flow a method hint can travel today, with the insertion points (which parser sees the JS call site; where the Endpoint's method is set; which job decides GET-only probing; what the capture/history path holds and why it does not reach L0).
2. Decide the shape: a contained carry-the-hint fix -> grill the grey points -> TDD. A new discovery->probe contract (method hints + a small method matrix) -> to-spec -> to-tickets -> to-assertions; STOP there and report.
3. TDD acceptance: a write route carrying a method hint is minted with that method (and probed with it where the small matrix applies); the GET-only default remains for unhinted routes.

WORKTREE:
  git -C /Users/diekgbbtt/polymerhus worktree add /Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/fix-365-method-coverage -b fix/365-recon-method-coverage dev

OUTPUT CONTRACT: Status | diagnosis (data flow + insertion points + evidence) | branch+commits | files | test commands+results | decisions | docs updated | residual risks | merge-readiness.
Do NOT merge; do NOT touch the eval server, the corpus, or the running stack.
```

### A5 - C5 assigner fail-open node (coordinator, small)

Not dispatched; executed by the coordinator as W0.3 (prompt edit + focused test), per section 3.

---

## Appendix B - eval commands (W3/W4)

Instance alignment (W3):

```bash
ssh eval-server-polyphemus
git -C /opt/polymerhus-dev fetch origin
git -C /opt/polymerhus-dev merge --ff-only origin/dev
git -C /opt/polymerhus-dev/eval/instances/eval-server-1 merge --ff-only "$(git -C /opt/polymerhus-dev rev-parse dev)"
docker inspect ph-dd131acc-agent-1 --format '{{.State.StartedAt}}'
# fingerprint (drive-run2.sh snippet)
cd /opt/polymerhus-dev && EVAL_SHA="$(git -C eval/instances/eval-server-1 rev-parse HEAD)" PYTHONPATH=eval python3 -c "
from pathlib import Path
from advance import fingerprint, images, manifest
m = manifest.build_manifest(Path('/opt/polymerhus-dev'), '$EVAL_SHA', images.collect_image_digests(images.default_containers('ph-dd131acc')))
print(fingerprint.fingerprint(m))"
```

Arm K trials (W4):

```bash
# mirror /root/drive-run2.sh with:
#   EVAL_SETUP=eval/setups/webexploitbench-arm-k.yaml
#   EVAL_RUN_TARGETS="comfyui-1 white-jotter-1"
#   EVAL_RUNS_ROOT=eval/runs-armk
#   chain-state backed up and reset for the fresh cycle
python3 -m orchestrator up eval/setups/webexploitbench-arm-k.yaml    # stack gate (or rely on next_target)
python3 -m orchestrator next-target eval/setups/webexploitbench-arm-k.yaml --instance eval-server-1 --target comfyui-1
python3 -m orchestrator trial eval/setups/webexploitbench-arm-k.yaml eval-server-1 comfyui-1 \
  --eval-sha "$EVAL_SHA" --stack-fingerprint "$EVAL_STACK_FINGERPRINT" --budget-s 7200 --data-root "$EVAL_DATA_ROOT"
# then white-jotter-1; then monitor to convergence; close-verify; store materialize
```

Measurement (W4):

```bash
python3 tools/measure_gt_wellformedness.py --project <pid> --target <target>   # flags verified at execution
curl -s http://127.0.0.1:8080/projects/<pid>/usage                            # Goal 2 + C4
# graph queries per the results-doc appendix; Langfuse pulls per the W2.4 scripts
```

---

## Status log

- 2026-10-18: plan authored (this doc committed first on `feat/recon-coverage-and-eval-wellformedness`).
- 2026-10-18: **W0 landed and merged to dev** (`68acd614`): corrected criterion (Service spine via `business_function_slug`; mechanism slots System-side; capability-gap statements satisfied-by-declaration; 15 tool tests + lint clean), arm J re-baseline (comfyui 0.45/0.48, white-jotter 0.49/0.66), `eval/setups/webexploitbench-arm-k.yaml`, and the C5 fail-open assigner node with its workflow test.
- 2026-10-18: **W1.4 #365 merged** (`38300b01`; branch commit `30c64604`): method hints from discovery into minting and probing; `tests/recon` 1063 passed / 18 skipped; the DELETE mint-only decision is recorded on the ticket as the one flagged scope call.
- 2026-10-18: **W1.1 #369 dispatched** (background diagnosis first); **W1.2 #354 dispatched** (grill-first). W1.3 #364 staged (worktree `fix-364-auth-store` ready).
- 2026-10-18: an earlier dispatch wave died on a provider rate limit; the operator updated the subagent model lanes and all three fixes were re-dispatched fresh (worktrees verified clean at `68acd614`).
- 2026-10-18: **W1.2 #354 merged** (`bdfa73f9`; branch commit `f7dee94b`): typed L0Ref witnesses on System proposals; the curator writes idempotent EVIDENCED_BY edges (MATCH-only, unmatched = no-op); read side contract + index-card pin. `tests/analysis tests/attack tests/tools` 1171 passed on the merge. Live emission confirmation rides arm K (an EVIDENCED_BY count).
- 2026-10-18: **W1.3 #364 merged** (`16673b20`; branch commit `ed70387a`): the read-only `auth_store` view bound to both proposer roles on every turn (no write/authenticate; values redacted before projection; fail-open threading through the analysis seams). `tests/analysis tests/app tests/attack tests/tools` 1452 passed on the merge. Two accepted vocabulary additions (review round may challenge): `with_readonly_auth_store` on the shared auth seam and the `auth_readonly` envelope. AC3 rides arm K.
- 2026-10-18: **W1.1 #369 merged** (`c676ef87`; branch commit `af38eb39`): root cause = the blackloop stream cut aborting the live LangGraph run on tool-bound turns (the emitted tool round was discarded, the recovery then committed blind). The cut now applies to no-tool roles only - #206 Decision 8's own scope - and both outcomes are logged; 4 new regression tests, red on the base. Accepted trade: a genuine tool-bound blackloop burns its completion ceiling. `tests/test_llm_*.py tests/analysis tests/attack` 1882 passed on the merge. All four fix branches are merged; W2 review next.
- 2026-10-18: **W2 adversarial review round complete** (code-reviewer over `c3e487bb..104a7c1f`: PASS_WITH_CONCERNS, no blockers; 2766 tests run by the reviewer). Findings applied: S1/S2 (#369 recovery + budget docstrings), S3 (the auth-view fail-open direction asserted), P1 (the tautological `business_function` spine item dropped; baseline re-verified IDENTICAL 0.45/0.48/0.49/0.66), P2 (the `satisfied_by: capability_gap` marker now requires a `gap_reason` naming a declared `edges_to_l0.capability_gaps` entry; lint + scoring guards, 2 new tool tests, 17 total), P3 (the local-only corpus change set reproduced in assessment section 2.4.1). Accepted without change: S4 (parity-pinned schema string), P4 (the harness census assertion stays a future enhancement), P5 (noted on #365), P6 (the C5 precision risk is watched in the arm K C5 reading).
- 2026-10-18: **W3 stacked and aligned.** Full local sweep on `dev`: 5357 passed / 46 skipped / 1 xfailed / 10 failed - all ten environmental (docker daemon down: test_agent_health, test_kali_mcp, test_neo4j_schema, test_steel_exec_live x6), plus `test_stack_smoke` and `test_postgres_schema` excluded for the same reason. `dev` pushed (`6c256130..8bcbd1e3`). Eval host: canonical checkout + instance worktree fast-forwarded to `8bcbd1e3`; agent container force-recreated (StartedAt 16:12:14Z); in-container code probes pass (the #369 and #364 markers present); health `http 200`; stack fingerprint `58383452e7ce562150bd81c79390d74a3dad2ee03530224d28d76b055cf67957`. Boot note: the gateway model-sync hit a SOFT 401 (the opencode-go model list) and failed toward staleness per D9 - the agent starts on last-known-good records; recorded, not blocking.
- 2026-10-18: **W4 trials launched** via `/root/drive-armk.sh` (comfyui-1 then white-jotter-1; comfyui formal comparability; log `/root/armk-driver.log`).
- 2026-10-18: **Key rotation (recorded remediation).** The first launch (16:13:55Z) died on an expired eval-host `opencode-go` key ("This API key has expired"; every analysis call 401s, the OC CLI agents refused to start). Remediated by refreshing the host's `~/.local/share/opencode/auth.json` (`opencode-go` + `opencode`) and the instance `.env` `API_KEY_OPENCODE_GO` from the operator's local auth; backups `auth.json.bak-armk-20261018T162712Z` and `.env.bak-armk-20261018T162712Z`. Verification: the gateway sync now reconciles 77 records, `opencode models` lists the Go models, health 200. The doomed 16:15 trial (project `4eba8f70`, zero usage) was stopped; the driver was relaunched at 16:29:11Z on the same sha/fingerprint.
- 2026-10-18: **W4 complete.** Trials: comfyui `comfyui-1-20261018T173450-1fc05262` (project `471401f8-d0ed-435e-bc8b-43de2095b0e7`, 16:32:06-17:34:50Z, stopped at 3,006,684) and white-jotter `white-jotter-1-20261018T183651-1618c524` (project `35189233-ca25-4fc9-8c09-33f7c913c6ca`, 17:54:39-18:36:51Z, stopped at 4,006,400); the driver closed with verdicts/diagnoses present and the store materialized.
  Primary measurement: GT well-formedness comfyui **0.42** (arm J formal 0.48) and white-jotter **0.38** (0.66); the deficits are M2 (GT surfaces undiscovered) and M4 (typed edges), the M3 spine is 2/2 on every Service unit. Goal 2 passes: analysis-only cached shares 88.1% / 85.4% against the 70% bar.
  Fix verification: **0 dropped rounds on both targets** (#369), `EVIDENCED_BY` 74 / 22 edges (#354), the read-only `auth_store` exercised (2 / 3 calls; #364), method hints minted 21 non-GET endpoints on white-jotter against 0 in arm J (#365; comfyui carried no JS hint and produced none).
  New dominant findings: the white-jotter recon orchestrator absorbed 2,553,915 capped (64% of the 4M budget; arm J formal 27,120) and the service-to-System linking collapsed to 4 edges / 4 anchored Systems (arm J formal: 87 / 24).
  Docs: the results doc carries the arm K section + two registry rows (new `evidenced_by_edges` column at the end); the assessment doc records the corrected and bridged baseline. Verdict and recommendation are in the results doc; no global design decision was required.
- 2026-10-18: **Closed.** #369, #354, #364 and #365 are closed with the arm K live-verification evidence. Final stack: `origin/dev` carries the arm K code (`8bcbd1e3`) plus the post-run docs; the eval instance is fast-forwarded to the pushed tip (the docs-only delta does not touch `src/`, so the running stack is code-identical to the trials).
- 2026-10-18: **Post-run diagnosis (#384, #385) and the Overview workflow evaluation** landed in `docs/experiments/2026-10-18-arm-k-384-385-diagnosis-and-overview-workflow.md`: #384 root cause = the regenerated white-jotter auth bundle records the bootstrap deployment's address (`46.224.225.245:35493`) instead of the run-stable alias (`t-1618c524.target`), the uncapped gateway loop thrashed, a 4 MB tool result took the thread to ~852k tokens (compaction reclaimed 4,212), 2.55M capped burned, and the terminal gateway 400 produced no verdict -> the recon ran unauthenticated; #385 root cause = the final 591-asset pass returned the typist's `L1DeltaBatch` as text instead of a tool call (4 of 4 structured calls), the seam reads only `structured_response`, the retry repeated it, and `or L1DeltaBatch()` silently dropped 6 Systems + 44 edges.
