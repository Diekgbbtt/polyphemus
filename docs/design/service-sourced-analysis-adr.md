# ADR: service-sourced analysis - the L1-first per-Service pipeline

Status: ACCEPTED (design; implementation follows).
Date: 2026-10-11.
Branch: `feat/service-sourced-analysis` (off `dev` `93d213e`).
Umbrella plan: `docs/design/plans/2026-10-11-service-sourced-analysis.md`.
Amends: `docs/design/converged-agent-turn-adr.md` (the no-expansion clause), `docs/design/proposer-per-batch-cache-adr.md` (the batch unit), `docs/design/control-plane-decoupling-decisions.md` (the trigger flag), `docs/design/assigner-A1-decisions.md` (the reflection mode), `docs/design/eval-streamed-analysis-default-adr.md` (the mode selector).
Related: `docs/design/domain-model.md` (the hinge and the up/down classing), `docs/design/hunting-memory-system-spec.md` (the memory pattern this reuses), `docs/design/service-decomposition-A2.md` (the deferred unpack this makes more load-bearing).

## 1. The decision in one line

Retire the L0-chunk stream as the analysis driver.
Make the bootstrapped L1 Service the first-class pipeline unit.
Post-recon, assign the settled L0 globally, then iterate the bootstrapped Services one at a time and run, per Service, a decomposed reasoning workflow in which each distinct sub-problem is one LLM turn carrying its declared inputs verbatim.
Give each proposer the hunting-style `notes` tool.
Land the whole thing behind an `analysis_mode` setting; the streamed path stays the default.

## 2. Context

Today `analysis/feed.py` consumes a per-job `L0Chunk` FIFO and runs `analyse_chunked`, a chunk-major schedule of the three proposers.
The unit of reasoning is the recon job's surface, not the business Service.
The Service already exists as an L1 node (the pre-analysis Bootstrapper projects `operator_kb` into Services); the Assigner attaches L0 to it via `AGGREGATES`.
The change promotes the Service to the pipeline unit and demotes the L0 surface to lower-class evidence carried only by the hinge edges.
This is a deliberate reversal of the chunk-fed default; the streamed path remains the default until the new mode proves out on a full eval.

## 3. Decisions

### 3.1 Pipeline shape and trigger

- **D1.** Reuse the feed's terminal marker as the trigger.
  The new mode is a new `pass_fn` selected by mode.
  Recon's per-job chunk push stays unchanged in the streamed mode; in the service-sourced mode recon pushes NO per-job chunk and still calls `signal_end`, so the terminal marker is the only push.
  (Skipping the push is justified: the new pass re-reads the graph, so a pushed payload would be pure overhead.)
- **D2.** Add `settings.recon.analysis_mode` with values `streamed` (default) and `service_sourced`, read at one seam alongside `resolve_feed_mode`.
  `service_sourced` creates the queued feed and fires the trigger on its own; it does NOT require `streaming_analysis` (the incident in `eval-streamed-analysis-default-adr.md` must not recur as a silent no-op).
- **D3.** At the terminal pass the new mode re-reads the settled L0 and the bootstrapped L1 from the graph (operator-ratified), not the pushed chunks.
- **D4.** The pass runs only when recon reached `complete`.
  A recon `stopped` (or `failed`) run enqueues the same terminal marker today; the new pass must gate on the recon status so the most expensive pass never runs on the least complete surface.
- **D5.** A second `signal_end` (double terminal marker) must not re-run the full pipeline; the pass is guarded once per run.
- **D6.** The pass has two sequential stages: the global assign stage, then the per-Service loop.
  The stage boundary is the barrier.

### 3.2 The global assign pass

- **D7.** Reuse the Assigner prompt and its FIVE shaping gates (`narrow_to_assignment`, `resolve_l0_refs`, `drop_out_of_inventory`, `normalise_confidence`, `withhold_below_bar`); change only the input assembly and the session scope.
  (Note: five, not six; six is the data-modeller's count.)
- **D8.** The global pass writes `AGGREGATES` through `write_aggregates`; the per-Service loop reads them via `read_aggregated_l0` / `read_service_aggregations`.
- **D9.** The global pass runs as a plain awaited call, NOT a supervisor dispatch.
  `AgentDispatch` rejects a slice-less non-slice-less role, so a dispatch would force a `messages.py` change; a plain call needs none, and the pass is a whole-graph single step anyway.
- **D10.** Keep the 0.75 withholding bar and the stale pool.
  The pass reports a census: withheld, out-of-inventory, unresolvable, and the residual stale count.
- **D11.** The census has a persistence home: new `PassCensus` fields plus `analysis_runs.stats` via `set_analysis_run_status(..., stats=...)`.
  (`AssignmentStats` is persisted nowhere today; without a home the coverage signal stays unanswerable.)

### 3.3 The per-Service loop

- **D12.** Iteration axis: `for service: for role in (mechanism_typist, data_modeller)`.
  The Assigner is global only.
- **D13.** Per Service the roles run in the order mechanism_typist then data_modeller.
- **D14.** Services run sorted by `business_function_slug` (deterministic and replayable).
- **D15.** Fail-open per Service: a degraded step still counts the Service done, mirroring `supervisor._make_proposer`.
  A Service with no aggregated surface yields an explicit "no surface" outcome, never a silent skip.
- **D16.** Bounded per-Service retry for the degraded case.
  One attempt per Service with no recovery pass would lose that Service's Systems and DataItems for the whole run.
- **D17.** Session address reuses the existing discriminator: `proposer_batch(service_slug)` gives `run:<slug>:<role>`.
  No new address type.
- **D18.** `business_function_slug` is LLM-authored and unvalidated beyond non-empty; before it becomes a `thread_id` segment, a `dispatch_id` segment, and a provider session header, sanitise or hash it.
- **D19.** The typist compounds a System `description` on extension.
  Over N Services this compounds N times.
  Rule: only the Service that FIRST defines a System compounds its description; later Services never re-compound it (they may only enrich a System they own).
- **D20.** Coverage risk: an Endpoint with no `AGGREGATES` edge has no Service to iterate, so it is never seen by the typist or the data-modeller on any iteration, whereas today every pushed asset reaches all roles.
  Decision: the unaggregated surface is carried by a residual unit the loop also visits (the stale/unaggregated bucket), so coverage is not silently lost.
  The phase-6 eval measures it.

### 3.4 The reasoning workflow (the sub-problems)

- **D21.** Each role's workflow is a declared DAG of distinct sub-problems, one LLM turn each.
  The workflow is a value object (`ReasoningWorkflow`) whose sub-problems each declare: an id and name, the human-message prompt, the injected inputs, which typed artifact they emit, and their `depends_on`.
- **D22.** The sub-problems map onto the reasoning stages each role's `_REFLECTION_STEPS` already enumerates; no stages are invented.
  The spec enumerates them per role from the scaffolds.
  This is a bounded expansion of the chain, which the converged-turn ADR refused without measurement; the operator directs the expansion, and the phase-6 eval is the measurement.
- **D23.** Every sub-problem emits a TYPED artifact.
  A reasoning sub-problem emits a compact structured judgment (claims with evidence and a verdict), not free prose.
  This is what makes a dependency a checkable, injectable datum.
- **D24.** Dependencies are injected VERBATIM.
  Each turn's human message carries its `depends_on` artifacts rendered verbatim, plus the Service slice.
  The session trail still accumulates (stateful per Service and role) for the run archive and the cache prefix, but NO dependency relies on the trail.
  This resolves the tension the adversarial pass found: a trail-carried prose dependency is compaction-evictable and unverifiable; an injected typed artifact is neither.
- **D25.** Reviving the Assigner's reflection mode (`assigner._REFLECT_STEPS`) reverses the 2026-07-28 ratification that recorded it as deliberately unreached.
  This is a deliberate reversal, recorded here so it is not mistaken for an accident.
- **D26.** Keep the constant request shape per role: the tool set is byte-identical across a role's calls (`L1DeltaBatch` plus `notes`).
  The sub-problems differ only in their prompt and injected inputs.

### 3.5 Episodic memory

- **D27.** Reuse the hunting memory pattern, not a copy.
  Lift to a shared app module: `retain_bounded_records`, a minimal shared store base, the coded-teaching rejection, and the notes-tool base.
  Hunting re-imports from the shared module; analysis never imports `attack.hunting`.
  **Landed (T1)** in `src/polymerhus/app/memory/`: `bounds.py` (`retain_bounded_records`, `rendered_len`, `notes_body_len`), `store.py` (`BoundedRecordStore` + `project_lock`), and `tool_contract.py` (`StoreToolBase`, `coded_teaching_rejection`, `build_notes_tool` / `StoreNotesTool`).
  Hunting's `HuntStore` / `HunterMemoryStore` build on `BoundedRecordStore` and import the primitives; the historical `attack/hunting/tool_contract.py` path is now a thin re-export so existing hunting imports (and tests) keep resolving.
- **D28.** The lift lands as its own prerequisite change, green, before the pipeline is built, so a pipeline bug and a refactor bug are never indistinguishable.
  Lift a minimal set.
  The seam-specific args schemas and field maps stay with their seams (the orchestrator's and hunter's live in `actors.py` / `hunter_tools.py`); only the GENERIC base and the generic builder move.
  `StoreNotesTool` / `build_notes_tool` are already generic over `NotesFieldMap`, so they moved as-is; analysis defines its own args schema and field map on the shared base.
- **D29.** Analysis store: `data/<project>/analysis/memory.yaml`, keyed by Service slug.
  The app scaffold (`ensure_project`) must create the `analysis/` bucket, or the first write fails.
- **D30.** A new closed note-kind enum, fenced to L1-modelling kinds (no fault-hypothesis, payload, technique, or vector language; the phase-3 vocabulary stays unratified).
- **D31.** Each proposer binds `notes` and writes during its turns; a pipeline backstop records one Service note if the agent wrote none, so "one note per Service" is an auditable coverage guarantee, not just a prompt instruction.
  The backstop runs in a `finally`, so a unit whose turns RAISE still leaves its note; the global assign pass is a proposer too (its turns bind the same notes-bound seam) and its backstop writes an `assignment` note, making that kind reachable in `service_sourced`.
- **D32.** Memory reads back both within-run (a later Service reads earlier Services' notes) and cross-run.
- **D33.** `notes` binds through the session `tools=` seam, NOT the skill seam (`skill_agent_binding` would raise for an undeclared role).
- **D34.** Binding a second tool changes the structured-output negotiation; verify the negotiation still lands on the same structured method, or the cache fix regresses.
  The constant-shape tests pin `convert_to_openai_tool` equality and must be extended.
- **D35.** Re-mine the per-role compaction thresholds for the new per-Service unit; the current `0.016` and `0.08` were mined on per-chunk occupancy and are stale.
  **Reconciled (T7): deferred to the phase-6 eval, and recorded as such.** The service-sourced unit's occupancy differs by construction (a per-Service slice is at most one Service's aggregated surface; the global assign pass groups the whole settled surface into one unit), so the per-chunk values are not the new optimum.
  The mined values are left in place because they remain defensible in the safe direction: a fraction-of-window threshold generous for the larger per-chunk unit fires LESS often on the smaller per-Service unit, and the mode is behind a flag.
  The re-mine is owned by the phase-6 comparative eval (D48), and the reasoning is recorded in `proposer-per-batch-cache-adr.md` section 8, so the stale value is never mistaken for a measured one.
  **Landed (T3, the memory items D29-D34, recorded here for locality):** `analysis/memory.py` (the store, the closed note-kind enum, the args schema + field map, `notes_tool_for`) and `proposer_turn.py` (the notes tool bound on every turn).
  The negotiation is pinned to its pre-notes no-tools axis (`stateful_turn(structured_tools_bound=False)`), so the second tool never flips the negotiated method (D34).
  The `analysis/` bucket is in `PROJECT_SCAFFOLD` (D29).
  The per-unit backstop is `run_workflow(..., unit_slug=, memory=, project_id=)` -> `ensure_unit_note` (D31).

### 3.6 L1 write path

- **D36.** Reuse the existing routing unchanged: `write_aggregates` for the global pass, `default_curate_with_enrichment_fn` (`enrich`/`l1_curate`) for the typist and data-modeller.
  No new writer.
- **D37.** The global pass no-mints; the Bootstrapper remains the sole Service source.

### 3.7 Control plane and chunking

- **D38.** Reuse `build_supervisor_graph` for the per-Service loop with a Service-major schedule of `(service-slice, role)` dispatches.
  The global pass (D9) is outside it.
- **D39.** Keep `chunking.py`, `Chunk`, `L0Chunk`, and `chunks_for_job` intact for the streamed default.
  The new mode adds a pure Service-grouping slice builder; a Service slice is represented as a `Chunk` whose `chunk_id` is the Service slug (no `AgentDispatch` change).
- **D40.** Reuse `_chunked_write_fn` / `_make_proposer` fail-open / `merge_receipts` unchanged, with per-Service receipts.

### 3.8 Lifecycle, runtime, settings

- **D41.** The pass returns a `PassResult` with `terminal=True` and `unprocessed_after=0`.
  The drained signal is write-based (at least one written receipt or `aggregates_written`), NOT dispatch count, so a run where every Service degraded is not falsely reported `drained`.
  Zero Services yields `withheld`.
- **D42.** Graceful stop at a Service boundary: a stop predicate is checked between Services.
  The terminal-branch classification in `_consume` must also honour a mid-pass stop (today it would label a stopped run `drained`).
- **D43.** The pass holds the analysis gate for the whole run (intended); this serialises concurrent runs behind one long pass and is recorded as accepted.
- **D44.** Observability: new Langfuse tags for the service-sourced pass and a per-Service trace join; the run stays one session (`session_id=run_id`).

### 3.9 Eval and testing

- **D45.** Add the mode to `TrialConfig` and the settings PUT, or no eval can exercise the new mode.
- **D46.** Testing tiers: unit for the pure Service-slice builder, the `ReasoningWorkflow` dependency validation, and the notes-args schema; integration for the global pass and the per-Service loop with injected `invoke_fn`/`write_fn` and a fake graph; a no-mock pipeline walkthrough; e2e via the phase-6 eval.
- **D47.** Add a test that the streamed default is byte-unbroken under the new mode flag.
- **D48.** The regression oracle is comparative: reuse `evaluate_assigner`/the bootstrapper harness on a service-sourced arm against the streamed arm; assert no regression on the integrity columns (stale pool, withheld rate, out-of-inventory rate); do not encode a target count.
  **The arms, defined (not yet run).** Arm A is the streamed default (`analysis_mode: streamed`, `streaming_analysis: true`); arm B is the service-sourced pipeline (`analysis_mode: service_sourced`).
  The two arms run the SAME targets and the SAME `operator_kb`, selected per trial through `TrialConfig.analysis_mode` (the settings PUT; the `run` verb's `--analysis-mode`).
  Per target, read the graph back with `evaluation.read_assignment` and derive `assignment_metrics`, then `evaluation.evaluate_assigner` / `compare` with `primary_key="n_aggregates"` and `ASSIGNMENT_INTEGRITY_KEYS`.
  The verdict is read off the INTEGRITY columns, not the primary axis: arm B must not regress the `stale_pool` (a LARGER stale pool is the positive signal here), the `withheld_rate`, or the `out_of_inventory_rate`.
  Assignment VOLUME is never a score, and no target count or threshold is encoded anywhere.
  This is the measurement D22 rests on.

## 4. Riskiest decision and its mitigation

The riskiest decision was the dependency-delivery mechanism (an earlier draft kept dependencies on the session trail).
It failed silently: model-authored prose can be summarised away by compaction before a later sub-problem reads it, and the per-role thresholds were mined for a different unit.
The mitigation is D23 and D24: dependencies are typed artifacts injected verbatim, and D35 re-mines the thresholds.

## 5. What this does not decide

The exact sub-problem list per role (enumerated in the spec from the scaffolds).
The exact note-kind enum values.
The residual-unit shape (D20).
The precise `PassCensus` field names.
These are pinned in the phase-2 spec.

## 6. Reversals and amendments to record in the same change

- `converged-agent-turn-adr.md`: the "do not expand the chain without measurement" clause is superseded for the proposers; the eval is the measurement.
- `proposer-per-batch-cache-adr.md`: the batch unit changes from recon chunk to Service; the mined thresholds are re-derived.
- `control-plane-decoupling-decisions.md` and `eval-streamed-analysis-default-adr.md`: the mode selector becomes `analysis_mode`.
- `assigner-A1-decisions.md`: the reflection mode is revived (D25).
- `analysis/CONTEXT.md` and `domain-model.md`: the Service as the pipeline unit, the reasoning workflow, the sub-problem, the Service slice, and the analysis episodic memory; the up/down classing as a reading discipline (no new node class).
- `hunting` docs, if the memory primitive moves to `app/`.
