# Spec: service-sourced analysis (the L1-first per-Service pipeline)

Status: ready-for-agent.
Branch: `feat/service-sourced-analysis` (off `dev` `93d213e`).
Umbrella plan: `docs/design/plans/2026-10-11-service-sourced-analysis.md`.
Decision record: `docs/design/service-sourced-analysis-adr.md` (this spec elaborates it; the ADR governs on conflict).
Ubiquitous language: `src/polymerhus/analysis/CONTEXT.md` (the new terms land there in the same change).

## 1. Problem statement

Analysis today is driven by the recon job's surface, not by the business Service.
`analysis/feed.py` consumes a per-job `L0Chunk` FIFO and `analyse_chunked` runs a chunk-major schedule of three proposers over each chunk.
Two harms follow.
The reasoning unit is a technical slice, so the model reasons about "this recon job's assets" rather than "this business Service's surface".
And each proposer's reasoning is a coarse one-to-three-turn chain whose intermediate conclusions ride the session trail, so a later turn's input is neither checkable nor compaction-safe.
The Service, meanwhile, already exists as the first-class business target; it is only the pipeline that ignores it.

## 2. Solution

Add a `service_sourced` analysis mode.
It runs when recon drains, as the analysis module on the module runtime.
It first runs a global assign pass over the settled L0, attaching Endpoints to Services via `AGGREGATES`.
It then iterates the bootstrapped Services (plus one residual unit for unaggregated surface) and runs, per Service, a decomposed reasoning workflow: each proposer role is a chain of distinct sub-problems, one LLM turn each, every sub-problem carrying its declared inputs verbatim and emitting a typed artifact.
Each proposer gains the hunting-style `notes` tool.
The existing streamed path is untouched and stays the default.

## 3. The reasoning workflow

### 3.1 The contract

A role's workflow is a `ReasoningWorkflow`: an ordered list of `SubProblem`s.
Each `SubProblem` declares:

- `id` and `name`.
- `prompt`: the task text (the volatile part of the human message).
- `inject`: the list of artifacts injected verbatim (the Service slice; the `depends_on` artifacts).
- `emit`: the typed artifact it produces.
- `depends_on`: the sub-problem ids whose artifacts it injects.

Execution: for each sub-problem in order, one `stateful_turn`; the human message is the sub-problem prompt plus its injected artifacts rendered verbatim; the output is parsed into the sub-problem's artifact and recorded for its dependents.
The session is stateful per `(run, service_slug, role)` so the run archive and the cache prefix persist.
No dependency relies on the trail: a dependency is always re-injected (ADR D24).

### 3.2 The turn contract

- Every turn binds the SAME tool set, byte-identical across a role's calls: `{analysis_turn, notes}` (ADR D26, D34).
- `analysis_turn` is the single structured schema `AnalysisTurn`: it is a superset of `L1DeltaBatch` plus a `claims: list[Claim]` list (ADR D23).
  A `Claim` is `{subject, assertion, evidence, verdict}`.
- A reasoning sub-problem populates `claims`; an extraction sub-problem populates the `L1DeltaBatch` delta lists.
- The pipeline maps the delta lists of an `AnalysisTurn` to an `L1DeltaBatch` for the sole-writer and drops `claims` after the memory backstop reads them.
- `L1DeltaBatch` stays the pure curator input; `AnalysisTurn` is the LLM-facing envelope.

### 3.3 The sub-problems, per role

Each sub-problem maps onto the stages the role's `_REFLECTION_STEPS` already enumerate (ADR D22); the mapping is explicit so no boundary is invented.

**Assigner (global pass), `_REFLECT_STEPS` stages RESTATE / COMPETING OWNER / CALIBRATE / RESIDUE:**

| id | covers stages | emits |
|---|---|---|
| `candidate_owners` | RESTATE, COMPETING OWNER, CALIBRATE | `claims` (per Endpoint: matched evidence, competing owner, chosen owner, confidence) |
| `assign` | RESIDUE | `L1DeltaBatch.aggregates` (shaped by the five gates) |

`assign.depends_on = [candidate_owners]`.

**mechanism_typist (per Service), stages ORIENT / HYPOTHESISE / CLUSTER PAGES / VERIFY-FALSIFY / INTEGRATE / EMIT:**

| id | covers stages | emits |
|---|---|---|
| `mechanism_hypotheses` | ORIENT, HYPOTHESISE | `claims` (per asset+observation: candidate System kind, new-vs-extend) |
| `page_clusters` | CLUSTER PAGES | `claims` (per (service, cluster): member pages) |
| `systems_extract` | VERIFY-FALSIFY, INTEGRATE | `L1DeltaBatch.systems` |
| `link` | EMIT | `L1DeltaBatch.system_edges` |

`systems_extract.depends_on = [mechanism_hypotheses, page_clusters]`; `link.depends_on = [systems_extract]`.

**data_modeller (per Service), stages ORIENT / HYPOTHESISE / VERIFY-FALSIFY / INTEGRATE / SHAPE / EMIT-WITHHOLD:**

| id | covers stages | emits |
|---|---|---|
| `record_hypotheses` | ORIENT, HYPOTHESISE, VERIFY-FALSIFY | `claims` (per admitted name: candidate record, reuse-vs-coin, verdict) |
| `data_extract` | INTEGRATE | `L1DeltaBatch.data_items`, `L1DeltaBatch.surfaces_at` |
| `flow_shape` | SHAPE (Ground, Trust, Relate) | `claims` (surface sites, producer/consumer, assumption predicate, record-to-record relation) |
| `flow_extract` | EMIT-WITHHOLD | `L1DeltaBatch.data_flows`, `L1DeltaBatch.data_relationships` |

`data_extract.depends_on = [record_hypotheses]`; `flow_shape.depends_on = [data_extract]`; `flow_extract.depends_on = [flow_shape, data_extract]`.

The existing shaping gates are unchanged and run after each extraction sub-problem.

## 4. The pipeline

### 4.1 Trigger and gating

- `settings.recon.analysis_mode in {streamed, service_sourced}`, default `streamed`.
- In `service_sourced` mode recon pushes no per-job chunk and calls `signal_end`; the terminal marker triggers the service-sourced `pass_fn`.
- The pass runs only when recon reached `complete`, and only once per run (ADR D4, D5).

### 4.2 Stage 1 - the global assign pass

A plain awaited call (not a supervisor dispatch).
It re-reads the settled L0 and the Service inventory, runs the Assigner's two sub-problems over the whole surface, and writes `AGGREGATES` via `write_aggregates`.
It reports a census (withheld, out-of-inventory, unresolvable, stale) persisted to `analysis_runs.stats`.

### 4.3 Stage 2 - the per-Service loop

- Units: the bootstrapped Services sorted by `business_function_slug`, plus one residual unit for unaggregated surface (ADR D14, D20).
- Per unit: `mechanism_typist` then `data_modeller`, each running its `ReasoningWorkflow` scoped to the unit's aggregated slice.
- Session discriminator: the unit slug (sanitised, ADR D18), giving `run:<slug>:<role>`.
- Fail-open per unit, with a bounded per-unit retry (ADR D15, D16).
- Graceful stop at a unit boundary.

### 4.4 Write path

Unchanged routing: the global pass writes `AGGREGATES`; the typist and data-modeller route through `default_curate_with_enrichment_fn` (`enrich` / `l1_curate`).
The global pass no-mints; the Bootstrapper remains the sole Service source.

### 4.5 Terminal

Returns a `PassResult` with `terminal=True`, `unprocessed_after=0`, and a write-based drained signal (ADR D41).
Zero units yields `withheld`.

## 5. Episodic memory

- Shared primitives lifted to a shared app module as a prerequisite change (ADR D27, D28).
- Analysis store: `data/<project>/analysis/memory.yaml`, keyed by Service slug, bounded by `retain_bounded_records` with analysis `MEMORY_NOTES_MAX_RECORDS` / `_MAX_BYTES`.
- Note kinds (closed, L1-modelling only): `assignment`, `system`, `data`, `refusal`, `open_question`.
- Each proposer binds `notes` on every turn and writes during its turns; a per-unit backstop writes one note if the proposer wrote none.
- Read-back: within-run (later units read earlier notes) and cross-run.

## 6. User stories

1. As the analyser, I want the pipeline unit to be the business Service, so that reasoning is about a business target, not a recon job.
2. As the analyser, I want each proposer to break its problem into named sub-problems, so that each turn is focused and its inputs are explicit.
3. As the analyser, I want each sub-problem's dependencies injected verbatim, so that a conclusion is never silently lost to compaction.
4. As a maintainer, I want every turn to bind the same tool set, so that the provider prompt cache is never invalidated by a shape toggle.
5. As the analyser, I want episodic notes per Service, so that a later Service reuses an earlier Service's findings.
6. As the operator, I want the new mode behind a flag, so that the streamed default is never disturbed.
7. As the operator, I want the streamed default byte-unbroken under the flag.
8. As the operator, I want a census of the assignment, so that coverage and withholding are measurable.
9. As the operator, I want a graceful stop at a Service boundary, so that a long pass is interruptible.
10. As a verifier, I want a comparative eval arm, so that the new mode is judged against the streamed one without a target count.

## 7. Acceptance criteria

- `analysis_mode=service_sourced` runs the global assign pass then the per-Service loop and writes L1 only through the sole-writer.
- `analysis_mode=streamed` (or unset) is byte-unbroken.
- Each role runs its declared sub-problem chain; each turn injects its declared `depends_on` artifacts verbatim.
- The tool set is byte-identical across a role's calls.
- The notes store is bounded and one note per unit exists after the run.
- The census is persisted on `analysis_runs.stats`.
- The pass gates on recon `complete` and is guarded once per run.
- A stop is honoured at a unit boundary and reported `stopped`.

## 8. Testing decisions

- Unit (fake collaborators, no DB): the pure Service-slice builder; the `ReasoningWorkflow` validation (every `depends_on` names a prior sub-problem; every sub-problem emits a declared artifact); the verbatim-injection rendering; the constant tool-set assertion; the `AnalysisTurn` -> `L1DeltaBatch` mapper; the bounded notes store; the `notes` args schema.
- Integration (injected `invoke_fn`/`write_fn`, fake graph): the global assign pass shaping; the per-Service loop fail-open and bounded retry; the residual unit; the census.
- No-mock pipeline walkthrough (mirrors the bootstrap e2e): a small Service set runs end to end and the observable `AGGREGATES`/System/DataItem counts are asserted.
- E2E: the phase-6 eval; comparative arm versus the streamed default.
- Per the repo's tier discipline, walkthrough and contract predicates gate the verifier, not the red-green loop.

## 9. Out of scope

- The A.2 SPLIT op and service decomposition, except where the residual unit needs a stale pool.
- The anti-cluttering A.2 pass.
- The recon L0 pipeline itself.
- The hunting and exploit modules, beyond the shared memory-primitive lift.
- Recursive/multi-level decomposition.
