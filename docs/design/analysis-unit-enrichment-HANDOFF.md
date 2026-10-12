# HANDOFF: analysis-unit enrichment pipeline (v2)

*Worktree: `/Users/diekgbbtt/polymerhus-unitv2`, branch `feat/analysis-unit-enrichment` (off `feat/hunting-at-analysis-finish`, `55054aa`). Working tree DIRTY and uncommitted.*

## Goal

Rework the v1 `service_sourced` pipeline so it stops being defective by design.
New principle: the bootstrapped L1 is already sufficient on Services; the pipeline ENRICHES each unit and expands with the Systems the bootstrap does not map.
Each proposer reasons FROM a unit, queries the mapped L0 surface broadly (no asset-name assumption), reads the notes store, and writes a modelling-closure note.
See `docs/design/analysis-unit-enrichment-adr.md` (the decision record) and `docs/design/analysis-unit-enrichment-plan.md`.

## Done and test-verified

1. **Plan + three role designs**: `docs/design/analysis-unit-enrichment-plan.md`, `...-{assigner,mechanism-typist,data-modeller}-subproblems.md`.
2. **Analysis graph tools** (`analysis/graph_tools.py`, NEW): read-only `graph_view` + lazy HTTP-history read pair + `build_surface_tools`; bound on every proposer turn in `proposer_turn.py` (`_surface_tools`), so the constant request shape is preserved.
3. **v2 workflow chains**: `assigner` 5 (`surface_scan -> prior_insights -> candidate_owners -> assign -> closure`); `mechanism_typist` 7 (`unit_surface_read -> prior_insights -> mechanism_hypotheses -> page_clusters -> systems_extract -> link -> closure`); `data_modeller` 8 (`surface_survey -> request_shapes -> insight_recall -> record_hypotheses -> data_extract -> flow_shape -> flow_extract -> closure_note`). Each seeds its `unit`/`service` + `endpoints` base artifacts and passes `note_kind` (`assignment`/`system`/`data`).
4. **Per-Service assign** (`assigner.py::assign_services`, ADR D46): one awaited pass per Service, judged with `existing_slugs={slug}`; wired as the stage-1 default in `service_sourced.py`. Tests: `tests/analysis/test_assign_services.py`.
5. **Docs pass**: `docs/design/analysis-unit-enrichment-adr.md`; `src/polymerhus/analysis/CONTEXT.md` updated.

Verification: `PYTHONPATH=$PWD/src /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/analysis tests/eval/test_orchestrator_trial.py -q` -> **461 passed**.

## Still open

1. **System units in the slice builder.** `build_service_slices` (or a sibling `build_system_slices`) must also emit ONE unit per L1 System, so the mechanism-typist's unit set is Service + System. The System unit's assets = the System's `EVIDENCED_BY` L0 nodes plus the aggregated endpoints of every Service that rides it. Then `run_service_loop` must dispatch roles PER UNIT KIND: `mechanism_typist` on a System unit, `("mechanism_typist", "data_modeller")` on a Service unit. A new read of `(:L1Service)-[r]->(:L1System)` plus `EVIDENCED_BY` is needed; keep it an injected seam so the builder stays pure.
2. **Deterministic `recon -> analysis -> hunting`.** The eval trial (`eval/orchestrator/trial.py`, commit `55054aa`) already sequences the three phases; the app-side `feed.resolve_hunt_after_analysis` remains default-OFF deliberately (an unconditional app-side launch would 409 against the trial's own hunting launch). Confirm the trial path is the intended control plane, else make the chain explicitly deterministic there.
3. **Role prompts.** Append a "WORK IN ORDER" section (the v2 phase list) to `prompts/{assigner.md,technical-system.md,data-plane.md}`; the full updated prose is in the three subproblem design docs.
4. **Langfuse keys** on the eval instance `.env`.
5. **Analysis-only eval trial**, monitored to stop once units are consumed, then measurement.

## Eval run procedure

1. Apply the Langfuse keys to `/opt/polymerhus-dev/eval/instances/eval-server-1/.env` (from the main-worktree `.env`; the export failure was a full log disk).
2. Transfer the branch to the eval server (push to origin, or `git bundle`/rsync over SSH; the `gh` token was invalid).
3. Run the trial for comfyui in **analysis-only** mode with `hunt_after_analysis: false`; `python -m eval.orchestrator.cli trial <setup> eval-server-1 comfyui-1 --analysis-mode service_sourced ...`.
4. Monitor and **stop once all units are consumed** (watch the `service_slice loop ... units=N wrote=... stopped=False` line).
5. Measure the criteria per `/measure-experiment-results` and append a v2 row to the registry in `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`.

## Metric queries (per project `$P`)

```cypher
MATCH (s:L1Service {project_id:$P}) RETURN count(s);
MATCH (s:L1Service {project_id:$P}) WHERE NOT (s)-[:AGGREGATES]->() RETURN count(s);
MATCH (e:Endpoint {project_id:$P})<-[:AGGREGATES]-() RETURN count(distinct e);
MATCH (y:L1System {project_id:$P}) WHERE NOT EXISTS { MATCH (y)-[]-(:L1Service) } RETURN count(y);
MATCH (y:L1System {project_id:$P}) WHERE EXISTS { MATCH (y)-[]-(s:L1Service)-[:AGGREGATES]->() } RETURN count(distinct y);
```
Token metrics: `GET /projects/{pid}/usage`.

## Test command

```bash
cd /Users/diekgbbtt/polymerhus-unitv2
PYTHONPATH=$PWD/src /Users/diekgbbtt/polymerhus/.venv/bin/python -m pytest tests/analysis -q
```

## Known risks

- `graph_tools.build_http_history_tools` lazily imports `attack.hunting.hunter_tools`, inverting the documented `analysis` -> not-`attack.hunting` dependency direction; a follow-up should move the HTTP tool classes to a shared `app` module.
- `assign_services` feeds each Service the WHOLE settled surface as its candidate set (O(Services x surface)). Deliberate: quality over cost; revisit only if the eval shows cost dominance.
- The Langfuse client warns "initialized without public_key" in tests (harmless).
