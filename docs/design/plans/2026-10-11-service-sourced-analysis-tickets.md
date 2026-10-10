# Tickets: service-sourced analysis

Status: active.
Branch: `feat/service-sourced-analysis`.
Plan: `docs/design/plans/2026-10-11-service-sourced-analysis.md`.
Spec: `docs/design/service-sourced-analysis-spec.md`.
Decision record: `docs/design/service-sourced-analysis-adr.md`.

Coarse tickets, addressed sequentially.
Each ticket lands with green unit + integration tests before the next begins.
`blocked_by` is the hard edge: a ticket never starts before its blockers are green.

## T1 - Lift the shared memory primitives to an app module

Goal: the notes-tool base, the coded-teaching rejection, the bounded-retention primitive, and a minimal store base live in a shared helper module under `src/polymerhus/app/`; hunting re-imports them; behaviour is unchanged.
blocked_by: none.
Acceptance: hunting's stores and tools import from the shared module; the existing hunting memory tests stay green; `retain_bounded_records` has a single definition.
Files: `src/polymerhus/app/memory/*` (new), `src/polymerhus/attack/hunting/tool_contract.py`, `hunt_store.py`, `hunter_memory.py`, `pod/pod_memory.py` (imports).

## T2 - The reasoning workflow core

Goal: the `AnalysisTurn` and `Claim` value objects; the `ReasoningWorkflow` value object with `SubProblem` (id, name, prompt, inject, emit, depends_on) and its validation; the three roles' sub-problem chains per the spec; the verbatim-injection rendering; the constant tool set `{analysis_turn, notes}`; the `AnalysisTurn` -> `L1DeltaBatch` mapper.
blocked_by: none.
Acceptance: a workflow is valid only if every `depends_on` names an earlier sub-problem and every sub-problem emits a declared artifact; each role's chain matches the spec tables; every turn binds a byte-identical tool set; the mapper drops `claims`.
Files: `src/polymerhus/analysis/reasoning_workflow.py` (new), `analyser_types.py`, `proposer_turn.py`, `assigner.py`, `mechanism_typist.py`, `data_modeller.py`.

## T3 - Analysis episodic memory

Goal: the analysis memory store (`data/<project>/analysis/memory.yaml`, keyed by Service slug, bounded); the `notes` args schema and field map; binding `notes` on every proposer turn; the per-unit backstop that writes one note when the proposer wrote none; within-run and cross-run read-back.
blocked_by: T1, T2.
Acceptance: the store is bounded by `retain_bounded_records`; the backstop guarantees one note per unit; the constant tool-set assertion still holds with `notes` bound; note kinds are the closed L1-modelling enum.
Files: `src/polymerhus/analysis/memory.py` (new), `proposer_turn.py`, `session.py` (tools seam), `app/data_root.py` (the `analysis/` bucket), `app/llm/providers.py` (role tool binding).

## T4 - The global assign pass

Goal: a plain awaited `assign_global(project_id, ...)` that re-reads the settled L0 and the Service inventory, runs the Assigner's two sub-problems over the whole surface, writes `AGGREGATES` via `write_aggregates`, and returns the census (withheld, out-of-inventory, unresolvable, stale).
blocked_by: T2.
Acceptance: the five shaping gates are reused unchanged; the pass no-mints; the census is returned and persisted to `analysis_runs.stats`.
Files: `src/polymerhus/analysis/assigner.py`, `supervisor.py`, `l1_read.py`, `l0_stream.py`.

## T5 - The per-Service loop

Goal: the pure Service-slice builder (Services from the live L1 inventory, each with its aggregated L0 surface, plus the residual unaggregated unit); the unit ordering; the per-unit role order; the per-unit session discriminator (sanitised slug); fail-open with a bounded per-unit retry; the per-unit receipts; the `ReasoningWorkflow` execution per unit.
blocked_by: T2, T4.
Acceptance: units are deterministic; a degraded unit is recorded; a unit with no surface yields an explicit outcome; the residual unit carries unaggregated surface; receipts are per unit.
Files: `src/polymerhus/analysis/service_slice.py` (new), `chunking.py`, `supervisor.py`, `feed.py`.

## T6 - Mode flag, trigger, terminal, stop

Goal: `settings.recon.analysis_mode`; the recon push skip in service-sourced mode; the complete-only and once-per-run gating; the terminal `PassResult` with a write-based drained signal; the census persistence; the graceful stop at a unit boundary and the terminal-branch stop classification.
blocked_by: T5.
Acceptance: `streamed` is byte-unbroken; `service_sourced` requires no `streaming_analysis`; the pass runs only on recon `complete` and once; a stop is reported `stopped`; zero units yields `withheld`.
Files: `src/polymerhus/analysis/feed.py`, `lifecycle.py`, `supervisor.py`, `src/polymerhus/recon/control/pipeline.py`, `src/polymerhus/project_management/api.py`.

## T7 - Eval mode field, docs pass, verification

Goal: the `TrialConfig` field and the settings PUT for the new mode; the docs pass (CONTEXT glossaries, `domain-model.md`, the amended ADRs); the no-mock pipeline walkthrough; the comparative eval arm.
blocked_by: T6.
Acceptance: an eval trial can select the mode; the docs pass is complete; the walkthrough runs green; the comparative arm is defined.
Files: `eval/**`, `docs/design/**`, `src/polymerhus/analysis/CONTEXT.md`, `docs/design/domain-model.md`, `tests/**`.
