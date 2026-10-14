# ADR: split the L0-chunk-sourced analysis trunk from the service-sourced experiment

Status: accepted (2026-10-14).
Branch: `rollback/l0-trunk` (the L0-only trunk candidate); the service-sourced pipeline stays on `exp/service-sourced` at `097211e`.
Plan: `docs/design/l0-l1-pipeline-split-plan.md`.
Supersedes: the T5 streamed guard in `batched-l1unit-first-adr.md` (decision 27), on this trunk only.
Related: `service-sourced-analysis-adr.md`, `analysis-unit-enrichment-adr.md`, `batched-l1unit-first-adr.md`.

## Context

Two analysis pipelines landed on one `dev` trunk.

- The L0-chunk-sourced pipeline (`streamed`): recon pushes a job-keyed chunk; a chunk-major schedule of the three proposers; each proposer is a one-shot turn over the chunk slice plus the inventory.
- The service-sourced pipeline (`service_sourced`): the Bootstrapper makes L1 Services; a global assign pass writes `AGGREGATES`; a per-Service loop runs a decomposed `ReasoningWorkflow` per role, discovering the surface through `graph_view` and the HTTP-history tools, with episodic memory.

The service-sourced era (`3547a3d..88dc902`) then rewrote the SHARED proposer bodies (`assigner.py`, `mechanism_typist.py`, `data_modeller.py`) for the L1-unit-first discipline (`dc994b0..b1381a1`).
The rewrite changed the DEFAULT `streamed` path: `ab99d30` turned the shared `assign` from arm A's one-shot into the five-step `surface_scan -> candidate_owners -> assign -> closure` workflow.
A later guard (T5, `af5fb84`) restored a slice-based WORKFLOW for `streamed`, but restored a WORKFLOW, not the one-shot.
So the trunk ran a service-sourced-shaped workflow on L0 chunks; that mismatch is the regression observed live (the assigner proposed project-wide references that the chunk-scoped `resolve_l0_refs` gate dropped).

## Decision

1. **The trunk is the L0-chunk-sourced pipeline only.** `dev` carries the L0 pipeline and every pipeline-agnostic fix.
2. **The service-sourced pipeline is an experiment.** It lives on `exp/service-sourced` (at `097211e`), which stacks all its progressive fixes.
3. **A fix that targets a proposer agent or a shared component lands in BOTH branches.** A change lands on the trunk only if it passes gate D; on the experiment only if it passes gate E; on both if it passes gate B (see the plan, section 5).
4. **The trunk is built by a SPLICE at the analysis package**, not by a history rewrite. The trunk starts from `dev` and replaces `src/polymerhus/analysis/` plus `recon/control/pipeline.py` with the pre-service-sourced (`93d213e`) code, then deletes the service-sourced modules and re-applies the shared analysis churn. The non-analysis subsystems (eval, app, attack, kali, gateway, project-management) stay at their current `dev` state, so the newest shared work is kept.
5. **The ten service-sourced modules are removed from the trunk:** `analysis/service_sourced.py`, `analysis/service_slice.py`, `analysis/graph_tools.py`, `analysis/memory.py`, `analysis/reasoning_workflow.py`, `analysis/prompt_variant.py`, and the three `*-batched-l1unit-first.md` prompts. The `service_sourced` mode (and its `analysis_mode` eval selector) is removed everywhere.
6. **The shared analysis churn is re-applied to the trunk:** the `operator_kb` Overview as a skeleton attribute (`scaffold.parse_overview`, `settings.application_overview`, `read_l1_inventory.application_overview`, `bootstrapper.md`), and the hunting-at-analysis-finish chain (`feed.resolve_hunt_after_analysis`, `lifecycle._chain_hunting_on_drained`, default OFF).
7. **The Overview is prepended to each L0 proposer's human message.** `pod.overview_block` renders `APPLICATION OVERVIEW: ...`; the assigner's `_user_prompt`, the typist's `_reflection_prompt`, and the data-modeller's `_reflection_prompt` prepend it.
8. **The stale integration contract tests are repaired on the trunk.** `test_assigner_contracts.py` and `test_mechanism_typist_contracts.py` predated the `invoke_fn(messages, *, schema, system_prompt)` seam and the retired reflect mode; their stubs and prompt reads are updated to the L0 seam.

## Consequences

- The trunk's `streamed` assigner is arm A's one-shot again, so its references are the chunk's own endpoints and the chunk-scoped gate resolves them.
- The `WORKFLOW`, `WORKFLOW_LEGACY`, `_unit_context_block`, `_service_block`, `surface_block`, `graph_tools`, `memory`, `prompt_variant`, and the batched prompts no longer exist on the trunk.
- The T5 guard is unnecessary on the trunk (there is no second flavour to guard); it remains meaningful only on the experiment branch.
- The `ANALYSIS_PROMPT_VARIANT`, `structured_tools_bound`, `AnalysisTurn` checkpoint allow-list entry, and the eval `--analysis-mode` selector are experiment-only.
- The experiment branch is the full current tree; a future service-sourced feature rebases onto `exp/service-sourced`, and any proposer/shared fix is cherry-picked to both.

## Known drift (reported, not fixed here)

- The e2e compaction walkthrough (`test_mechanism_typist_chained_lane_compacts_e2e`) assumes one session across chunks; the proposer-cache experiment (`93d213e`) scopes each chunk to its own batch session. This drift pre-dates the split.
- The 5 `test_arjun_consumption_contracts` failures and the live `test_assigner_eval_live` / `test_llm_sync_key_rotation` failures are unchanged from `dev` and are env- or drift-bound.
