# Development plan: analysis-unit enrichment pipeline (v2)

*Status: in progress, 2026-10-11. Branch `feat/analysis-unit-enrichment` off `feat/hunting-at-analysis-finish`.*

## Why

The v1 `service_sourced` (analysis-unit-first) pipeline is defective by design (see `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`).
Its failure modes are structural:
the single global assign pass under-assigns;
the data-modeller admission set never intersects an aggregation-only Service slice;
the residual unit is a monolith;
an orphan Service is never dispatched;
hunting races the analysis.

## The new design principle

The bootstrapped L1 is already sufficient on the **Services**.
The pipeline's job is to **enrich each Service unit** and **expand with the Systems** the bootstrapped L1 does not map.
Each proposer reasons **from a unit** (a Service, or a System for the mechanism-typist), queries the mapped L0 surface broadly and aggressively (no assumption on asset names), and inductively enriches the unit's features and relationships.

## Design changes

### 1. Consumption filters (the entity-hierarchy fit)

Obsolete per-chunk admission sets are replaced by the new unit hierarchy.

- **assigner** is fed **each Service** (no Systems).
- **mechanism_typist** is fed **every unit already aggregated to L0 endpoints** (Service and System).
- **data_modeller** is fed **each Service**.

### 2. Per-proposer reasoning workflow (aggressive L0 grounding first)

Every proposer workflow starts with a **broad L0 query phase** (no asset-name assumption), then a **memory-insight phase** (read the notes store), then unit-specific enrichment, then closure.

- **assigner**: for one Service, query the L0 endpoints broadly, judge which belong to the Service, emit `AGGREGATES`; close with a note.
- **mechanism_typist**: for one unit, query the aggregated endpoints, query triager Observations for adversarial signal, define/extend the Systems the unit rides, link them; close with a note.
- **data_modeller**: for one Service, query the endpoints, query the HTTP-history store for the request shapes to those endpoints, lift/compound DataItems, bind `SURFACES_AT`, map flows; close with a note.

### 3. Tool surface

Every analysis proposer binds the same constant tool set (the cache-shape rule):

- `graph_view` - the read-only L0/L1 Cypher view (broad L0 query).
- `search_http_history` - the recorded transaction search.
- `get_http_artifact` - fetch one recorded transaction.
- `notes` - the episodic memory read/write.
- the role's structured tool (`AnalysisTurn`).

### 4. Episodic memory

Each proposer writes a **modelling-closure note** per unit it finishes, and each workflow has a phase that **reads prior modelling insights** from the notes store before enriching.

### 5. Control plane

`recon -> analysis -> hunting` is **sequential and deterministic**, encoded in the execution control plane (the analysis-drain chain is on by default).

## Metrics (the acceptance bar)

From the analysis-unit-first v1 comparison document:
`endpoint_placement`, `orphan_services`, `system_anchoring_coverage`, `service_recall`, `dataitem_recall`, `cached_share_total`.
The v2 target is to beat v1 on `endpoint_placement` (>= 28.3%) and `system_anchoring_coverage` (>= 50.0%) while keeping `cached_share_total` >= 70%.

## Steps (strict, TDD, tight loops)

1. Analysis read-only graph tool + http-history tools (`analysis/tools.py`).
2. Bind them into the proposer tool surface (`proposer_turn.py`).
3. Consumption filters (`service_slice.py`, `service_sourced.py`, `assigner.py`).
4. Per-role workflows + prompts.
5. Deterministic chaining.
6. Tests per step; run the targeted suites.
7. Analysis-only eval trial; measure; update the comparison document.
