# Plan: split the analysis trunk (L0-streamed) from the service-sourced experiment

Status: proposed (work session 2026-10-14).
Owner: operator + agent.

## 1. Goal

Separate the two analysis pipelines that now share one `dev` trunk:

- The L0-chunk-sourced pipeline (the `streamed` mode). This is the deliberate trunk.
- The service-sourced pipeline (the `service_sourced` mode). This is an experiment.

End state:

- `dev` carries ONLY the L0-chunk-sourced pipeline, plus every pipeline-agnostic fix.
- One experiment branch carries the whole service-sourced pipeline, plus every fix that targeted it.
- Every fix that targets a proposer agent or a shared component lives in BOTH branches.
- A report records where each changed component lands after the split.

## 2. Why the split is needed

The service-sourced pipeline (`docs/design/service-sourced-analysis-adr.md`) retired the L0-chunk stream as the analysis driver.
It landed on `dev` behind `settings.recon.analysis_mode`.
It then rewrote the shared proposer bodies (`assigner.py`, `mechanism_typist.py`, `data_modeller.py`) for the L1-unit-first discipline (`docs/design/batched-l1unit-first-adr.md`).
The rewrite changed the DEFAULT `streamed` path.
A later guard (T5, `af5fb84`) restored a slice-based assigner for `streamed`, but restored a WORKFLOW, not the original one-shot.
So the trunk now runs a service-sourced-shaped workflow on L0 chunks.
That mismatch is the regression this session observed.

## 3. The two pipelines, precisely

- L0-chunk-sourced (`streamed`): `chunking.chunks_for_job` makes a job-keyed chunk; the supervisor runs a chunk-major schedule of the three proposers; each proposer is a one-shot turn fed the chunk slice plus inventory.
- Service-sourced (`service_sourced`): the Bootstrapper makes L1 Services; a global assign pass writes `AGGREGATES`; a per-Service loop runs a decomposed `ReasoningWorkflow` per role, discovering the surface through `graph_view` and the HTTP-history tools; episodic memory binds the `notes` tool.

## 4. States

- `S0` = `93d213e` - the commit immediately before `3547a3d`; L0-chunk-sourced only. Also the "arm A" code of the experiment record.
- `S1` = `dev` `097211e` - both pipelines present; `streamed` guarded to a legacy WORKFLOW; `service_sourced` L1-unit-first.
- `Sdev` (target trunk) = `S0` + the SHARED churn.
- `Sexp` (target experiment) = `Sdev` + the service-sourced churn (equivalent tree to `S1`).

## 5. Transition gates

A commit lands in a branch only if it passes the gate for that branch.

- Gate D (dev): the change touches no service-sourced component, and it does not require the `service_sourced` mode, the Service slice, the reasoning workflow, the graph tools, the analysis memory, or the batched prompt variant.
- Gate E (experiment): the change adds or fixes a service-sourced component, or fixes a shared component in a way the service-sourced pipeline needs.
- Gate B (both): the change is pipeline-agnostic and improves a shared component (a proposer agent used by both modes, app, hunting, kali, llm/gateway, project-management, eval).

Grey cases (need an operator decision, listed in section 9).

## 6. Commit classification for `93d213e..dev`

Shared (`BOTH`):

- `99ba10a` refactor(memory): lift the shared notes/bounded-store primitives to `app`. Touches `app/memory/*` and `attack/hunting`; analysis does not import it in `Sdev`.
- `96f7787` refactor(analysis): yield `ToolStrategy` uniformly. Touches `proposer_turn.py` + `app/llm/session.py`; `streamed` uses `proposer_turn`.
- `55054aa` fix(pipeline): hunting launches at analysis finish. Touches `feed.py`, `lifecycle.py`, eval.
- `fe7593e` fix(project): stop every live run in one call. Touches `project_management/api.py`.
- `5e30332` fix(llm): disable the gateway cost guard by default.
- `15c2aed` feat(kali): gate scanner traffic out of the HTTP-history store.
- `5a5eb32` docs(recon): W-c finding.
- `8294c1f` docs(tickets): hunting cache-hit-ratio ticket.
- `63334d2` feat(analysis): carry the `operator_kb` Overview as a skeleton attribute. Shared per operator decision (item 3).
- `c97750a` refactor(eval): remove the daemon version-jumper.

Service-sourced (`EXPERIMENT`):

- `3547a3d` docs(design): service-sourced analysis.
- `ab99d30` feat(analysis): decompose the proposer turns into a reasoning workflow.
- `bbf8a80` feat(analysis): episodic memory via the shared notes tool.
- `45d4a37` feat(analysis): global assign pass over the settled surface.
- `60d45b8` feat(analysis): per-Service loop.
- `51d6042` feat(analysis): `service_sourced` mode, trigger and terminal.
- `0dd64f7` docs(analysis): model the service-sourced pipeline; eval mode field.
- `f23a3cb` fix(analysis): bind notes on the global assign pass.
- `88dc902` feat(analysis): enrich service-sourced proposers with graph tools.
- `dc994b0` feat(analysis): batched L1-unit-first prompt variant selector.
- `dd8d376` feat(analysis): rewrite the assigner L1-unit-first.
- `2ba9046` feat(analysis): rewrite the mechanism-typist L1-unit-first.
- `e8f3d6f` feat(analysis): rewrite the data-modeller L1-unit-first.
- `3ba4fb2` fix(analysis): batched L1-unit-first adversarial-review fixes.
- `b1381a1` fix(analysis): bound and de-anchor the L1-unit-first discovered index.
- `f4e9a43` feat(analysis): assigner degrades to `no_surface` (W-b). The diff changes only the unit-first `WORKFLOW` and the batched prompt.
- `af5fb84` fix(analysis): restore the legacy slice-based assigner for `streamed` (T5). The guard mechanism is `EXPERIMENT`; the one-shot behaviour is `Sdev`'s baseline.
- `aecac71` feat(analysis): endpoint-first prefix (experiment).
- `6596a5f` fix(analysis): bound the http-history MCP seam (experiment).

## 7. Component map after the split

| Component | Introduced by | Pipeline | Lands in |
|---|---|---|---|
| `analysis/service_sourced.py` | `51d6042` | service-sourced | exp |
| `analysis/service_slice.py` | `60d45b8` | service-sourced | exp |
| `analysis/graph_tools.py` | `88dc902` | service-sourced | exp |
| `analysis/memory.py` | `bbf8a80` | service-sourced | exp |
| `analysis/reasoning_workflow.py` | `ab99d30` | service-sourced | exp |
| `analysis/prompt_variant.py` | `dc994b0` | service-sourced | exp |
| `prompts/*-batched-l1unit-first.md` | `dc994b0`+ | service-sourced | exp |
| `app/memory/*` | `99ba10a` | shared | both |
| `analysis/proposer_turn.py` | shared seam; `96f7787` | shared | both |
| `analysis/assigner.py` | shared file | split: one-shot (dev) vs workflow (exp) | both |
| `analysis/mechanism_typist.py` | shared file | split | both |
| `analysis/data_modeller.py` | shared file | split | both |
| `analysis/feed.py`, `lifecycle.py`, `supervisor.py` | shared file | split: streamed schedule (dev) vs `service_sourced` mode (exp) | both |
| `recon/control/pipeline.py` | `51d6042` | split | both |
| `kali/http_history/*` | `15c2aed` | shared | both |
| `app/llm/checkpoints.py` | `3f2041f` | shared (allow-list) | both (grey) |
| `app/llm/sync.py`, `gateway/*` | `5e30332` | shared | both |
| `project_management/api.py` | `fe7593e` | shared | both |
| `l1_inventory.py`, `scaffold.py`, `prompts/bootstrapper.md` | `63334d2` | shared | both |
| Overview prepend in the L0 proposers | new (W-d re-apply) | shared | both |
| `eval/*` | many | shared | both |
| service-sourced design docs | `3547a3d`+ | experiment | exp |

## 8. Execution workflow (states and gates)

Each step leaves the tree in a valid state (tests green, gate held).

1. **Freeze `Sexp`.** Tag the current `dev` as the experiment tree: `exp/service-sourced` at `097211e`. No force-push.
2. **Create the `Sdev` candidate.** A worktree on a new branch `rollback/l0-only-trunk` from `S0` (`93d213e`).
3. **Re-apply the SHARED churn** onto `Sdev`, in order, one commit at a time. Cherry-pick each shared commit; resolve conflicts toward the L0 pipeline. Gate D applies.
4. **Re-apply the Overview prepend** (item 3) to the L0 proposers' human message. Gate B.
5. **Verify `Sdev`.** Run `tests/analysis`, `tests/kali`, `tests/recon`, `tests/integration`; assert no `service_sourced` import survives; assert the assigner is the one-shot.
6. **Reconcile `Sexp`.** Reset the experiment branch to `Sdev` and cherry-pick the EXPERIMENT commits. Gate E.
7. **Verify `Sexp`.** The tree must equal `S1`'s analysis tree (or differ only by the intended shared re-application).
8. **Design diagnoses** (section 10) and the report (section 11). File the ADRs before any commit.
9. **Report.** Present the branch plan and the component table to the operator. Do not force-push or overwrite `dev` without an explicit go-ahead.

## 9. Grey decisions (need the operator)

- G1. Does `73334d2`'s assigner edit apply to `Sdev`? Its `_unit_context_block` prefix is service-sourced. Proposal: in `Sdev`, prepend the Overview to the L0 proposers' one-shot human message instead.
- G2. `3f2041f` (checkpoint allow-list) names a service-sourced type by dotted string. Proposal: keep it in both (harmless, future-proof).
- G3. `Sdev`'s assigner: restore `93d213e`'s one-shot, or keep a slice-based WORKFLOW? Proposal: the one-shot (it is the arm A baseline).
- G4. Branch naming: reuse `feat/service-sourced-analysis`, or create `exp/service-sourced`. Proposal: create `exp/service-sourced` at `097211e`.
- G5. Is `dev` rewritten in place (history rewrite), or advanced by a revert commit? Proposal: rewrite to the new base, because the operator asked to roll back to a state precedent to the service-sourced pipeline.

## 10. Design diagnoses to produce

- **D-1 Tool surface.** The assigner receives the L0 and L1 surface in its first human message, so it does not need `graph_view`. Evaluate from the last trial whether `graph_view` enabled more correct `AGGREGATES`, counting the edges the endpoint-scoping gate refused (`unresolvable`). Quantitative analysis, filed in the report.
- **D-2 CoT drift.** The verbatims that drive the chain of thought are shared across pipelines. Split them by pipeline kind.
- **D-3 L1 domain prose.** The `operator_kb` Overview is a shared skeleton attribute. Prepend it to each proposer's human message in both pipelines.

## 11. Report deliverable

A table of every component that changed across the recent experiments, traversed backward through `dev` and the feature branches, stating where each lands: experiment, dev, or both.
