# ADR: analysis-unit enrichment pipeline (v2)

*Status: accepted, not yet released (branch `feat/analysis-unit-enrichment`).*
*Supersedes the v1 formulations noted below; extends ADR D1-D45 of the service-sourced pipeline.*

## Context

The v1 `service_sourced` pipeline was DEFECTIVE BY DESIGN, measured on the comfyui eval run `79f96b81`:

- The Assigner admitted only `Endpoint`; `Parameter` / `Header` / `Secret` never entered a Service slice.
- The data-modeller's admission set is exactly `Parameter` + `Header` + `Secret`, so it ran ONCE, on the `__residual__` chunk (`chunk=__residual__ admitted=24 ...`), and nowhere else.
- 8 of 24 units were `no_surface` (no aggregated surface), so 16 of 24 were dispatched.
- On a second run the System layer was largely uncaptured (15 orphan Systems vs 8 in v1), and the DataItem layer captured 0 of 8 ground-truth items.

The root cause is structural: the pipeline reasoned from a pre-filtered asset slice, so a role could only see the asset types its admission set named, and a unit with no matching assets was a silent no-op.

## Decision

The pipeline's reasoning unit is a UNIT (a Service or a System) and the pipeline ENRICHES the unit. It does not filter the surface down to the role's asset types.

1. **Broad L0 query first.** Each proposer begins its workflow with a broad, read-only `graph_view` query over the mapped L0 surface, with NO asset-name assumption. A new analysis-side tool bundle (`analysis/graph_tools.py`) provides `graph_view` and, for the data-modeller, the HTTP-history read pair. The tools are bound on EVERY proposer turn (alongside `notes` and the structured tool last), preserving the constant request shape (ADR D26).
2. **Consumption filter.** `assigner` <- each Service; `mechanism_typist` <- all units aggregated to L0 endpoints (Service and System); `data_modeller` <- each Service.
3. **Episodic modelling-closure memory.** Each proposer has a dedicated `prior_insights` phase that reads the shared `notes` store, and a `closure` phase that WRITES one modelling-closure note per unit (kind `assignment` / `system` / `data` respectively). The per-unit backstop (`ensure_unit_note`) remains the coverage guarantee.
4. **Per-Service assign.** Stage 1 is `assign_services`: one awaited pass per Service, each judged with `existing_slugs={slug}` so a Service writes only its own `AGGREGATES`. The v1 `assign_global` is retained but no longer the service-sourced default.
5. **Deterministic chaining.** `recon -> analysis -> hunting` is sequenced by the execution control plane (the eval trial), and the app-side `settings.recon.hunt_after_analysis` default is flipped from OFF to ON for this experiment (ADR D46). An absent value now returns True; an explicit `false` opts out. The app-side launch reuses the same operator-intent seam as `POST /projects/{id}/hunting`, so a chain the trial also launches is refused (409) rather than double-run - the ordering is deterministic and idempotent.

### Superseded by point 5

- The v1 `resolve_hunt_after_analysis` default-OFF rationale ("the eval trial sequences the chain itself, so an app-side launch would collide") is superseded: the chain is now default-ON, and the 409 guard makes the collision a safe no-op rather than a reason to disable.

### Workflow chains (v2)

- `assigner` (5): `surface_scan -> prior_insights -> candidate_owners -> assign -> closure`.
- `mechanism_typist` (7): `unit_surface_read -> prior_insights -> mechanism_hypotheses -> page_clusters -> systems_extract -> link -> closure`.
- `data_modeller` (8): `surface_survey -> request_shapes -> insight_recall -> record_hypotheses -> data_extract -> flow_shape -> flow_extract -> closure_note`.

Each sub-problem speaks the one `AnalysisTurn` envelope; `emit` is a declared artifact (`claims` for a reasoning turn, a delta list for an extraction turn). Dependencies are injected VERBATIM (ADR D24).

## Consequences

- The v1 defect (data-modeller only on the residual) is removed: the data-modeller now runs on every Service and can reach `Parameter` / `Header` / `Secret` through `graph_view` rather than a pre-filtered slice.
- The mechanism-typist can now reason over the System cross-cutting layer as well as per-Service.
- Cost rises: the per-Service assign is O(Services x surface) rather than one global pass, and each chain is longer. This is accepted - the v1 formulation failed on coverage, not on cost.
- Open: the System-unit expansion in `build_service_slices` (so the typlist's unit set is Services + Systems) is specified but not yet built; see `analysis-unit-enrichment-HANDOFF.md`.

## Superseded

- The v1 `assign_global` as the stage-1 default for `service_sourced` (superseded by `assign_services`).
- The v1 four-sub-problem typist and four-sub-problem data-modeller chains (superseded by the seven- and eight-sub-problem chains).
- The v1 claim that a per-unit asset slice is the reasoning input (superseded by the broad `graph_view` query).
