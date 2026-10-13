---
artifact: experiment-results
version: "1.0"
created: 2026-10-11
status: draft
---

# Experiment Results: analysis-unit-first vs L0-batch-first pipeline - comfyui

## Summary

| Attribute | Value |
|-----------|-------|
| **Experiment ID** | `analysisUnitFirst-vs-l0batchFirst-comfyui` |
| **Experiment Name** | Analyser pipeline policy comparison, target comfyui |
| **Status** | Completed - both analysis-unit-first formulations regress connectivity against the incumbent; the v2 enrichment fixes System attachment but not Service placement. The W-a..W-d fixes (arms D/E) recover most of the placement loss; the compaction tuning (arm E) then loses it again |
| **Arms** | A = streamed L0-batch-first; B = batched analysis-unit-first (`service_sourced` v1); C = enriched analysis-unit-first (`service_sourced` v2, per-Service assign + System units + surface tools); D = surface-integrity fixes W-a..W-d (`dev` `c97750a`, current config); E = D with tuned per-proposer compaction thresholds |
| **Target** | WebExploitBench `comfyui` (ComfyUI core v0.3.76 + ComfyUI-Manager V3.37), 6 vulnerabilities |
| **Sample Size** | 1 trial per arm, single target |
| **Owner** | Operator + implementing agent |
| **Source reports** | `docs/experiments/streams-analysisL0batchFirst-pipeline-comfyui-results.md` (A); `docs/experiments/batched-analysisUnitFirst-pipeline-comfyui-results.md` (B, on branch `feat/hunting-at-analysis-finish`); `docs/experiments/unitv2-run-note.md` (C, on branch `feat/analysis-unit-enrichment`) |
| **Design docs** | `docs/design/proposer-per-batch-cache-adr.md` (A); `docs/design/service-sourced-analysis-adr.md`, `docs/design/service-sourced-analysis-spec.md`, `docs/design/hunting-at-analysis-finish-adr.md` (B); `docs/design/analysis-unit-enrichment-adr.md` (C) |

This document persists the **core quality assessment criteria** for the analyser pipeline and scores both arms against them.
It is the canonical comparison; the per-arm reports are its evidence.

Verification: the arm A graph was re-measured from `ph-dd131acc-neo4j-1` on 2026-10-11, so the A counts here supersede the mid-run snapshot in the arm A report.

---

## Core quality assessment criteria

These six criteria are the durable quality bar for any analyser pipeline.
Every future target run scores the same metrics, so runs are comparable across targets and across pipeline policies.
C1-C4 were the bar for arms A, B, and C; C5 and C6 are forward-only (see Statistical Methodology).

### C1 - Service-to-surface aggregation

A hunting agent reasons over L1 Services.
A Service with no aggregated endpoint is presented with no surface, so the agent is fully disoriented.
Therefore every Service must aggregate at least one L0 endpoint, and the placed endpoint set must be large enough to navigate.

Metrics:

- **`service_aggregation_coverage`** = Services with at least one inbound `AGGREGATES` / total Services.
- **`endpoint_placement`** = distinct `Endpoint` nodes with an inbound `AGGREGATES` / total `Endpoint` nodes.
- **`orphan_services`** = Services with zero inbound `AGGREGATES` (lower is better).
- **`gt_service_aggregation`** = ground-truth Services with at least one inbound `AGGREGATES` / total ground-truth Services.

### C2 - System anchoring

A System is a cross-cutting mechanism.
It is only reachable from the surface through a Service, so a System with no Service edge is dangling.
Therefore every System must connect to at least one Service, and that Service must itself aggregate surface.

Metrics:

- **`system_attachment_coverage`** = Systems with at least one edge to a Service / total Systems.
- **`system_anchoring_coverage`** = Systems whose adjacent Service has at least one inbound `AGGREGATES` / total Systems.
- **`orphan_systems`** = Systems with no edge to any Service (lower is better).

`system_anchoring_coverage` is the strict form: it requires the whole Service-to-surface chain, not just a Service hop.

### C3 - Ground-truth breadth and depth

Breadth is recall of the ground-truth units.
Depth is the shape completeness of each captured unit.

Metrics:

- **`service_recall`** = ground-truth Services present / total ground-truth Services.
- **`service_precision`** = ground-truth Services present / total captured Services.
- **`dataitem_recall`** = ground-truth DataItems present (by semantic match) / total ground-truth DataItems.
- **`spine_depth`** = ground-truth Service spine keys present / total ground-truth spine keys (`api_paradigm`, `auth_methods`, `exposure`, `business_function`, `service_contract`).
- **`gt_service_system_exposure`** = ground-truth Services reached by at least one System edge (`EXPOSED_VIA`/`ROUTED_BY`/`FRONTED_BY`) / total ground-truth Services.

### C4 - Cache spectrum

The input cache-hit rate bounds the cost of a run.
The bar is 70% mean cached-input share.
This criterion is a **hygiene** bar, not a quality bar: it is also driven by the compaction budget and by the target's own Service profile shape, so a sub-bar value is not by itself a pipeline defect.

Metrics:

- **`cached_share_total`** = cached input / (cached + uncached input), all roles.
- **`cached_share_worst_proposer`** = the lowest cached share across the proposer roles (a floor check).
- **`input_uncached_tokens`** = total uncached input tokens (the prefix the provider had to reprocess).
- **`generated_output_tokens`** = total generated output tokens (reasoning plus visible).
- **`capped_tokens`** = total capped tokens (budget guardrail, 4,000,000 per target).

### C5 - L1 surface structure and L0 grounding

Connectivity (C1/C2) says how much of L1 reaches the surface; it does not say what the L1 surface is made of or whether its elements are real.
A hunting agent navigates L1 nodes and L1-to-L1 edges, so an ungrounded L1 element is a fabricated mechanism, and a legible shape is as important as a large one.
This criterion opens the L1 surface into two readings:

- **Breakdown**: the L1 node inventory by kind (`L1Service`, `L1System`, `L1DataItem`) and the L1-to-L1 edge inventory by type (a Service `AGGREGATES` an `Endpoint`, a System reaches a Service by `EXPOSED_VIA`/`ROUTED_BY`/`FRONTED_BY`, a node carries `EVIDENCED_BY` surface, and any other L1-to-L1 edge).
  The breakdown shows the surface's shape, not only its connectivity.
- **L0 grounding**: the share of L1 elements concretely specified against an L0 element - a node that cites a specific `Endpoint`/`Parameter`/`Header`/`Secret`, or whose evidence names a concrete path, parameter, or header.
  A grounded element can be hunted; an ungrounded one cannot.

Metrics:

- **`l1_nodes_by_kind`** = count of L1 nodes per kind.
- **`l1_edges_by_type`** = count of L1-to-L1 edges per type.
- **`l1_l0_grounded_nodes`** = L1 nodes with at least one concrete L0 reference / total L1 nodes.
- **`l1_l0_grounded_edges`** = L1-to-L1 edges whose announced surface is concretely cited on L0 / total L1-to-L1 edges.
- **`l0_unreferenced`** = L0 elements no L1 node references (lower is better) - the surface L1 never explained.

### C6 - Proposer trajectory fidelity

The graph metrics are structure; they do not show whether a proposer obeyed its own contract.
A run can place many endpoints while the agent ignored its workflow, mis-called a tool, or invented a mechanism from a tool response.
This criterion is a qualitative per-proposer assessment on five axes:

- **`workflow_adherence`** - did the proposer execute the workflow its prompt names, in order?
- **`tool_call_completeness`** - did it call every tool the workflow requires?
- **`interface_adherence`** - did each call respect the tool's interface agreement (arguments, result shape, read-only vs write)?
- **`reasoning_coherence`** - was the reasoning valid and free of contradictions?
- **`tool_output_fidelity`** - was the proposer deceived by tool-call response data (reading an error or an empty result as success, or inventing a mechanism the response does not support)?

Each analysis proposer role (`triager`, `assigner`, `mechanism_typist`, `data_modeller`) gets one verdict per axis, read from the Langfuse trace and the session transcript.
This is the only criterion that reads the trajectory rather than the graph or the ledger.

---

## Hypothesis Recap

**Original Hypothesis:**

> We believed that making the business Service the first-class analysis unit (the `service_sourced` batched pipeline: a global assign pass, then a per-Service loop) would produce a better-connected L1 surface than the streamed per-chunk pipeline, at no worse a cost.

**Success Criteria:**

- C1: `service_aggregation_coverage` and `endpoint_placement` at least match arm A.
- C2: `system_anchoring_coverage` at least matches arm A.
- C3: `service_recall` and `dataitem_recall` improve; spine depth does not regress.
- C4: `cached_share_total` stays at or above 70%; `capped_tokens` within budget.

---

## Results

### Comparison table

| Criterion | Metric | A streamed | B batched | Delta (B - A) | Winner |
|---|---|---:|---:|---:|---|
| C1 | `service_aggregation_coverage` | 17/25 = 68.0% | 15/23 = 65.2% | -2.8 pp | A |
| C1 | `endpoint_placement` | 82/290 = 28.3% | 34/290 = 11.7% | -16.6 pp | A |
| C1 | `orphan_services` | 8 | 8 | 0 | tie |
| C1 | `gt_service_aggregation` | 13/14 = 92.9% | 11/14 = 78.6% | -14.3 pp | A |
| C2 | `system_attachment_coverage` | 18/26 = 69.2% | 9/24 = 37.5% | -31.7 pp | A |
| C2 | `system_anchoring_coverage` | 13/26 = 50.0% | 9/24 = 37.5% | -12.5 pp | A |
| C2 | `orphan_systems` | 8 | 15 | +7 | A |
| C3 | `service_recall` | 14/14 = 100% | 14/14 = 100% | 0 | tie |
| C3 | `service_precision` | 14/25 = 56.0% | 14/23 = 60.9% | +4.9 pp | B |
| C3 | `dataitem_recall` | 0/8 = 0% | 0/8 = 0% | 0 | tie |
| C3 | `spine_depth` | 3/5 = 60.0% | 3/5 = 60.0% | 0 | tie |
| C3 | `gt_service_system_exposure` | 14/14 = 100% | 8/14 = 57.1% | -42.9 pp | A |
| C4 | `cached_share_total` | 70.6% | 70.0% | -0.6 pp | A (marginal) |
| C4 | `cached_share_worst_proposer` | 18.0% (`data_modeller`) | 27.8% (`assigner`) | +9.8 pp | B |
| C4 | `input_uncached_tokens` | 4,492,641 | 4,495,625 | +2,984 (+0.07%) | tie |
| C4 | `generated_output_tokens` | 547,505 | 388,610 | -158,895 (-29.0%) | B |
| C4 | `capped_tokens` | 5,036,246 | 4,884,235 | -152,011 (-3.0%) | B |

Total input tokens: A 15,006,817 (10,514,176 cached + 4,492,641 uncached); B 15,005,961 (10,510,336 cached + 4,495,625 uncached).
Total output tokens: A 547,505; B 388,610.

Score by criterion: C1 A (all four), C2 A (all three), C3 A (two of five, two ties, one to B), C4 B (two of four).

### C1 - Service-to-surface aggregation

Both arms orphan the same number of Services (8).
The batched pipeline places far fewer endpoints (34 against 82), so its aggregated Services carry a thinner slice, and it leaves the model-download Service with no surface at all.

```
endpoint_placement   A [##########################.............] 28.3%
                     B [###########............................] 11.7%
```

This is the load-bearing defect.
The batched pipeline's global assign pass is a single `assign_global` call whose workflow is two sub-problems (2 LLM calls).
The streamed pipeline's assigner is dispatched per chunk (21 calls).
The single global pass placed 34 endpoints against the per-chunk assigner's 82, so the Service-first reading did not improve assignment.

### C2 - System anchoring

The batched pipeline leaves 15 of 24 Systems with no Service edge, against 8 of 26 in the streamed arm.
It attaches only 9 Systems to a Service, against 18.

```
system_anchoring_coverage   A [########################.............] 50.0%
                            B [##################...................] 37.5%
```

The cause is the same one as C1: few Service-to-System edges are written because the per-Service typist runs over Service slices that contain few endpoints.
A System with no anchored Service is exactly the dangling mechanism a hunting agent cannot reach.

### C3 - Ground-truth breadth and depth

Service breadth is a tie: both arms capture all 14 ground-truth Services (100% recall).
The batched arm is marginally more precise (60.9% against 56.0%) because it minted two fewer presentation-as-Service extras (`editor-shell`, `workflow-editor`).

Depth fails on the same axis in both arms: the Service spine carries only 3 of the 5 ground-truth keys (`business_function_slug`, `exposure`, `service_contract`; `api_paradigm` and `auth_methods` are absent).
DataItem recall is 0 for both: the batched arm minted 3 DataItems (`gcp_service_key`, `firebase_client_credential`, `media_asset`) and the streamed arm minted 1 (`generated_media_artifact`), and none matches a ground-truth item.

The one depth metric that separates the arms is `gt_service_system_exposure`: the streamed arm reaches all 14 ground-truth Services with a System edge, the batched arm only 8.

Note the denominator discipline: the two arm reports measured Service recall against different ground-truth slices (arm A against the 5 distinct per-vulnerability hinge Services, arm B against the 14 target-level Services).
This document re-measures both against the same 14-Service target slice, which removes the apparent precision gap.

### C4 - Cache spectrum

Both arms clear the 70% mean bar, and total cached input is effectively identical (A 10,514,176; B 10,510,336).
The uncached input is also effectively identical (A 4,492,641; B 4,495,625, a 0.07% difference).
The batched arm wins the floor metric and the output/cost metrics: its worst proposer is the 2-call `assigner` at 27.8%, against the streamed arm's 45-call `data_modeller` at 18.0%; it generates 29.0% less output and 3.0% fewer capped tokens.

The uncached-input tie is the honest reading of the cache axes: the batched pipeline did not reprocess less prefix than the streamed one.
Its win is on generation (29.0% less output), not on input.
This is the only criterion the batched pipeline wins, and it wins it on the cheap axes.

---

## Arm C - enriched analysis-unit-first (v2)

### What ran

Arm C is the v2 redesign of the analysis-unit-first pipeline.
It keeps the Service as the first unit and adds: a **per-Service assign pass** (each Service judged against the whole settled surface, `existing_slugs={slug}`), **System units** (one unit per L1 System, built from its `EVIDENCED_BY` surface and its rider Services), a **read-only `graph_view` surface tool** bound on every proposer turn, a **modelling-closure note** per unit, and **hunting-at-analysis-finish** as the default.

| Attribute | Value |
|-----------|-------|
| Trial | `comfyui-1-20261011T233832-1fc05262` |
| Project | `6c357d47-2b7e-401e-9521-d268f2902365` |
| `analysis_mode` | `service_sourced` |
| Branch | `feat/analysis-unit-enrichment` |
| `eval_sha` | `55054aae7feff362668da6af5a8774c4716080f9` |
| `stack_fingerprint` | `15069e14f527f78a013615730abf6ddb36ed61085562e82743b51b70aca75d0a` |
| Trial terminal | `stopped` (project budget overshoot 113,244 at the trial ledger) |
| Analysis terminal | `service_sourced pass ... units=24 wrote=True stopped=False (census_written=22 loop_aggregates=0)` |

**C hypothesis:**

> We believed that grounding each Service on the whole settled surface (per-Service assign), adding System units, and closing each unit with a modelling note would raise `endpoint_placement` and `system_anchoring_coverage` to at least arm A's level without worsening cost.

### Comparison table (three arms)

| Criterion | Metric | A streamed | B batched v1 | C enriched v2 | Delta (C - A) | Winner |
|---|---|---:|---:|---:|---:|---|
| C1 | `service_aggregation_coverage` | 17/25 = 68.0% | 15/23 = 65.2% | 11/24 = 45.8% | -22.2 pp | A |
| C1 | `endpoint_placement` | 82/290 = 28.3% | 34/290 = 11.7% | 21/290 = 7.2% | -21.1 pp | A |
| C1 | `orphan_services` | 8 | 8 | 13 | +5 | A |
| C1 | `gt_service_aggregation` | 13/14 = 92.9% | 11/14 = 78.6% | 10/14 = 71.4% | -21.5 pp | A |
| C2 | `system_attachment_coverage` | 18/26 = 69.2% | 9/24 = 37.5% | 14/28 = 50.0% | -19.2 pp | A |
| C2 | `system_anchoring_coverage` | 13/26 = 50.0% | 9/24 = 37.5% | 13/28 = 46.4% | -3.6 pp | A |
| C2 | `orphan_systems` | 8 | 15 | 14 | +6 | A |
| C3 | `service_recall` | 14/14 = 100% | 14/14 = 100% | 14/14 = 100% | 0 | tie |
| C3 | `service_precision` | 14/25 = 56.0% | 14/23 = 60.9% | 14/24 = 58.3% | +2.3 pp | B |
| C3 | `dataitem_recall` | 0/8 = 0% | 0/8 = 0% | 0/8 = 0% | 0 | tie |
| C3 | `spine_depth` | 3/5 = 60.0% | 3/5 = 60.0% | 3/5 = 60.0% | 0 | tie |
| C3 | `gt_service_system_exposure` | 14/14 = 100% | 8/14 = 57.1% | 10/14 = 71.4% | -28.6 pp | A |
| C4 | `cached_share_total` | 70.6% | 70.0% | 68.9% | -1.7 pp | A (marginal) |
| C4 | `cached_share_worst_proposer` | 18.0% (`data_modeller`) | 27.8% (`assigner`) | 0.0% (`triager`) | -18.0 pp | A |
| C4 | `input_uncached_tokens` | 4,492,641 | 4,495,625 | 15,881,382 | +11,388,741 (+253.5%) | A |
| C4 | `generated_output_tokens` | 547,505 | 388,610 | 1,934,405 | +1,386,900 (+253.3%) | A |
| C4 | `capped_tokens` | 5,036,246 | 4,884,235 | 17,815,787 | +12,779,541 (+253.7%) | A |

Arm C's C4 row is the analysis roles only (`triager`, `assigner`, `mechanism_typist`); arms A and B are whole-project totals.
The comparison is still decisive because arm C's analysis-only cost is 3.5x arm A's whole-project cost, and its whole-project C4 is far larger again (38.2% cached share, 160,727,360 capped).

Score by criterion: C1 A (all four); C2 A (all three, C second); C3 mixed (three ties, one to B, one to A); C4 A (all five).

### C1 - Service-to-surface aggregation

Arm C is the worst-connected of the three, and the regression is the same load-bearing axis as arm B, now deeper.
It aggregates only 21 endpoints against arm B's 34 and arm A's 82, and it orphans 13 of 24 Services against 8 in both other arms.

```
endpoint_placement   A [##########################.............] 28.3%
                     B [###########............................] 11.7%
                     C [######.................................] 7.2%
```

The cause is the new per-Service assign filter.
The pass feeds every Service the whole settled surface (the log shows `admitted=290`), but it validates each proposal against `existing_slugs={slug}` for that one Service.
Every proposal that names another Service is dropped as `out_of_inventory`.
The log shows the effect directly:

```
assigner chunk=comfyui-update admitted=290 proposed=25 -> kept=0 (out_of_inventory=25) backlog=10
assigner chunk=community-sharing admitted=290 proposed=0 -> kept=0
...
assign_services run=...:d8be3a2e units=23 kept=22 written=22 stale=6648
```

A single Service's assigner read the whole surface, proposed 25 candidates, and kept none, because each candidate named a different owner.
The design intended per-Service grounding; the strict write filter turned it into a starvation filter.

### C2 - System anchoring

Arm C is the only arm that improved on arm B, and the improvement is real but partial.
It attaches 14 of 28 Systems to a Service against arm B's 9 of 24, and anchors 13 of 28 (46.4%) against arm B's 37.5%.
It still trails arm A's 50.0%.

```
system_anchoring_coverage   A [##########################...........] 50.0%
                            B [##################...................] 37.5%
                            C [#######################..............] 46.4%
```

This is the expected effect of the new System units: the mechanism-typist now runs on a System's own `EVIDENCED_BY` surface, so more Systems acquire a Service edge.
The gain is capped because a System's anchoring still depends on a Service that itself aggregates surface, and C1 starved those Services.

### C3 - Ground-truth breadth and depth

Breadth is again a tie: all three arms capture all 14 ground-truth Services.
Precision is between the arms (58.3%).
Depth is unchanged: the spine still carries only 3 of the 5 keys (`business_function_slug` 24/24, `exposure` 23/24, `service_contract` 23/24 present; `api_paradigm` 0 and `auth_methods` 0 absent), and the DataItem layer is still empty (0 `L1DataItem` nodes), so `dataitem_recall` is 0/8.

The separating depth metric is `gt_service_system_exposure`: arm C reaches 10 of 14 ground-truth Services with a System edge (71.4%), ahead of arm B's 57.1% and behind arm A's 100.0%.
The System-unit change moved this metric in the intended direction, and the assign starvation held it back from arm A.

### C4 - Cache spectrum

Arm C fails the C4 hygiene bar on every axis and is the most expensive arm by far.
Its analysis roles show `cached_share_total` 68.9%, just under the 70% bar, and a worst proposer of 0.0% (`triager`, 142,995 uncached input with no cache hits).
Its analysis-only capped tokens are 17.8M against arm A's whole-project 5.0M, a 3.5x increase, and its whole-project capped total is 160.7M.

The cost has two causes:

1. **Call volume.** The per-Service pass makes more calls: the assigner ran 231 calls and the mechanism-typist 204, against arm A's 21-call assigner and 45-call data-modeller. The per-Service grounded assigner reads the whole surface once per Service, so it pays the full-surface prompt 23 times.
2. **Compaction churn.** The assigner thread repeatedly crossed the 200,000-token budget and applied compacted trails (for example `workflow-submission:assigner` reclaimed 102,156 and 115,404 tokens in single passes), which reprocesses prefix.

The `data_modeller` never ran in arm C: no `data_modeller` entry appears in the usage ledger and no per-Service data dispatch occurred, so the DataItem layer stayed empty exactly as in arm B.

### Produced artifacts and token distribution

Artifacts (all under the eval workspace):

| Artifact | Path | Note |
|----------|------|------|
| Trial record | `eval/runs-unitv2/comfyui-1/comfyui-1-20261011T233832-1fc05262/trial.yaml` | Only artifact written; terminal `stopped`, `spent_tokens` 4,113,244 |
| Agent log | `ph-dd131acc-agent-1` container log | Role and pass evidence |
| Graph | `ph-dd131acc-neo4j-1`, project `6c357d47-2b7e-401e-9521-d268f2902365` | The re-measured C1/C2/C3 source |
| Usage ledger | `GET /projects/{pid}/usage` | The C4 source |

No `verdicts.yaml` or `diagnoses.yaml` were produced: the trial terminal is `stopped` (not a successful run), so the post-execution monitor deferred it.

Token distribution by role (whole project, from the usage ledger):

| Role | cached input | uncached input | reasoning | visible | capped | calls |
|------|-------------:|---------------:|----------:|--------:|-------:|------:|
| triager | 0 | 142,995 | 4,287 | 1,770 | 149,052 | 28 |
| assigner | 17,983,104 | 12,467,518 | 291,837 | 1,151,699 | 13,911,054 | 231 |
| mechanism_typist | 17,238,144 | 3,270,869 | 195,292 | 289,520 | 3,755,681 | 204 |
| hunting_orchestrator | 11,618,816 | 122,539,534 | 175,970 | 456,957 | 123,172,461 | 1,107 |
| hunting_hunter | 50,057,088 | 18,708,237 | 721,040 | 253,196 | 19,682,473 | 698 |
| pod_runner | 164,992 | 45,672 | 4,864 | 6,103 | 56,639 | 22 |
| **total** | **97,062,144** | **157,174,825** | **1,393,290** | **2,159,245** | **160,727,360** | **2,290** |

The analysis roles (triager + assigner + mechanism_typist) are 35,221,248 cached + 15,881,382 uncached input and 1,934,405 generated output.
The hunting roles are 143,412,340 of the 160,727,360 capped tokens (89.2%), so the arm C whole-project figure is dominated by hunting and is not an analyser cost.
Arm C's hunting arm is far longer than arm B's (which was uninformative), so the projects are not cost-comparable at the whole-project level.

### Verdict for arm C

Arm C did not meet its success criteria.
It regressed C1 (`endpoint_placement` 7.2%, worst of three) and C4 (3.5x the analysis cost, sub-bar cache), and it tied C3 breadth and depth.
It improved only C2 and `gt_service_system_exposure`, and only relative to arm B.
The enrichment mechanisms work, but they are fed by a starved assignment: the per-Service `existing_slugs` write filter drops most proposals, so the Services that would anchor the improvements carry almost no surface.

---

## The batched L1-unit-first pipeline is defective by design

This version of the analysis-unit-first pipeline is defective by construction, not merely under-tuned.
Six design defects explain every metric above.

1. **The global assign pass is a single call and under-assigns.**
   `assign_global` runs once over the whole settled surface (2 LLM calls), and placed only 34 endpoints.
   The per-chunk assigner placed 82.
   A single call over a large surface loses recall.

2. **The data-modeller admission set never intersects a Service slice.**
   `data_modeller` admits only `Parameter`/`Header`/`Secret`, but the assigner aggregates only `Endpoint`, so no Service slice ever contains a data asset.
   Every per-Service `data_modeller` dispatch therefore returns with no LLM call.
   The log shows exactly one `data_modeller chunk=` line for the whole run, and it is `__residual__` (`admitted=24(p=4 h=16 s=4)`).
   The Service-first data modelling the design intends never happens, which is why the DataItem layer is empty.

3. **The residual unit is a monolith.**
   Because data assets are never aggregated, the single `__residual__` unit carries the entire unaggregated surface (about 256 endpoints plus 24 data assets).
   One giant unit contradicts the Service-first intent and concentrates all data reasoning in one context.

4. **An orphan Service is never dispatched.**
   `build_service_slices` gives a Service with no aggregated surface an empty unit, and the loop marks it `no_surface` without dispatch (`service_slice.py:330-336`).
   The 8 orphan Services are therefore never reasoned about at all, so the pipeline cannot repair its own cold start.

5. **Hunting launched at recon drain, not at analysis finish.**
   The run started hunting at 16:08, before the analysis finished, so the hunting arm reasoned over the bootstrap L1.
   Its 175 calls and 3.85M capped tokens measured nothing about the analysis; this is the defect the `hunting-at-analysis-finish` change fixes.

6. **Its observability export failed silently.**
   Every span batch was rejected `403 Forbidden` (`exporter-failed`), so the run delivered zero observations to Langfuse.
   The run's evidence survives only in the container log and the graph, which is why this comparison was re-measured from the graph.

Defects 1 to 4 are structural and would each require a design change, not a parameter change.

---

## Arms D and E - the surface-integrity fixes and the compaction tuning

Arms D and E are the two trials run after the surface-integrity work (W-a HTTP-history capture integrity, W-b assigner absent-surface degradation, W-c surface-gap finding, W-d operator-KB Overview attribute) landed on `dev` `c97750a`.
Both are `service_sourced`, `batched_l1unit_first`, analysis-only (no hunting), on the comfyui target, one trial each.
The two arms differ in exactly one configuration knob: the per-proposer compaction threshold.

| Attribute | D (current config) | E (tuned config) |
|-----------|--------------------|------------------|
| Project | `98fb2d02-3e42-49ab-9e88-b8cdbbd02157` | `d4a13619-ab48-4721-a742-69848361337f` |
| Recon run | `417599b4-7db9-4661-9fb6-899fc9f71e50` | `3651b043-1a08-4198-8d8b-79ea3b4df6b5` |
| Analysis run | `...:c6b4e5cc` | `...:b0cb712a` |
| `eval_sha` | `c97750a` | `c97750a` |
| `analysis_mode` | `service_sourced` | `service_sourced` |
| Compaction threshold | global `LLM_COMPACTION_THRESHOLD=0.2` (all roles) | `MECHANISM_TYPIST=0.08`, `DATA_MODELLER=0.016`, `ASSIGNER=0.05` |
| Per-unit statefulness | `AnalysisSession(run, role, batch=<service-slug>)` | same |
| Terminal | analysis `stopped` (graceful, at the 4M budget) | analysis `stopped` (graceful, at the 4M budget) |
| `assign_services` census | `units=23 kept=70 written=70 stale=6600` | `units=23 kept=29 written=29 stale=6641` |

Both trials capped at the 4,000,000 capped-token budget and were stopped gracefully (R5).
The assign pass completed in both arms; the per-Service loop did not (it ran ~4 units of 23 before the cap in each), so the C2 System metrics are partial in both.

### Comparison table (five arms)

| Criterion | Metric | A streamed | B batched | C enriched | D fixes | E tuned | Winner |
|---|---|---:|---:|---:|---:|---:|---|
| C1 | `service_aggregation_coverage` | 68.0% | 65.2% | 45.8% | 11/23 = 47.8% | 11/23 = 47.8% | A |
| C1 | `endpoint_placement` | 28.3% | 11.7% | 7.2% | 70/290 = 24.1% | 29/290 = 10.0% | A |
| C1 | `orphan_services` | 8 | 8 | 13 | 12 | 12 | A |
| C1 | `gt_service_aggregation` | 92.9% | 78.6% | 71.4% | 14/14 = 100% | 14/14 = 100% | D/E |
| C2 | `system_attachment_coverage` | 69.2% | 37.5% | 50.0% | 5/24 = 20.8% | 4/23 = 17.4% | A |
| C2 | `system_anchoring_coverage` | 50.0% | 37.5% | 46.4% | 5/24 = 20.8% | 4/23 = 17.4% | A |
| C2 | `orphan_systems` | 8 | 15 | 14 | 19 | 19 | A |
| C3 | `service_recall` | 100% | 100% | 100% | 14/14 = 100% | 14/14 = 100% | tie |
| C3 | `service_precision` | 56.0% | 60.9% | 58.3% | 14/23 = 60.9% | 14/23 = 60.9% | B/D/E |
| C3 | `dataitem_recall` | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | tie |
| C3 | `gt_service_system_exposure` | 100% | 57.1% | 71.4% | 4/14 = 28.6% | 8/14 = 57.1% | A |
| C4 | `cached_share_total` | 70.6% | 70.0% | 68.9% | 87.8% | 76.2% | D |
| C4 | `cached_share_worst_proposer` | 18.0% | 27.8% | 0.0% | 58.5% (`triager`) / 85.9% (proposers) | 65.6% (`triager`) / 69.2% (proposers) | D |
| C4 | `input_uncached_tokens` | 4,492,641 | 4,495,625 | 15,881,382 | 3,749,265 | 3,903,682 | D |
| C4 | `generated_output_tokens` | 547,505 | 388,610 | 1,934,405 | 834,620 | 529,165 | E |
| C4 | `capped_tokens` | 5,036,246 | 4,884,235 | 17,815,787 | 4,583,885 | 4,432,847 | E (marginal) |

C4 per-role (capped tokens / calls / cached share):

| Role | D capped | D calls | D cached | E capped | E calls | E cached |
|------|---------:|--------:|---------:|---------:|--------:|---------:|
| triager | 107,319 | 26 | 58.5% | 130,237 | 31 | 65.6% |
| assigner | 1,610,110 | 310 | 87.0% | 2,472,239 | 295 | 76.9% |
| mechanism_typist | 1,479,592 | 116 | 85.9% | 1,056,334 | 58 | 69.2% |
| data_modeller | 1,386,864 | 153 | 90.3% | 774,037 | 69 | 81.3% |
| **total** | **4,583,885** | **605** | **87.8%** | **4,432,847** | **453** | **76.2%** |

Score by criterion: C1 D/E (placement), A (coverage); C2 A; C3 tie; C4 D (hygiene) / E (cost).

### C5 - L1 surface structure and L0 grounding

| Metric | D | E |
|--------|--:|--:|
| `l1_nodes_by_kind` | L1Service 23, L1System 24, L1DataItem 2 | L1Service 23, L1System 23, L1DataItem 0 |
| `l1_edges_by_type` | EXPOSED_VIA 6, ROUTED_BY 5, AUTHENTICATED_BY 1, CONSUMES 2, PRODUCES 2, DEPENDS_ON 1, REFLECTED_IN 1 | EXPOSED_VIA 11, FRONTED_BY 11 |
| `l1_l0_grounded_nodes` | 11/49 = 22.4% | 11/46 = 23.9% |
| `l0_unreferenced` (Endpoints) | 220 | 261 |

Arm D carries a richer L1 edge vocabulary (data-flow edges `CONSUMES`/`PRODUCES`/`REFLECTED_IN`, an `AUTHENTICATED_BY`, a `DEPENDS_ON`) and two DataItems; arm E carries only presentation edges and no DataItems.
Neither arm is scored against C5 by an earlier arm - both are the first runs to record it.

### C6 - proposer trajectory fidelity

Read from the agent transcript (`ph-dd131acc-agent-1` container log); the Langfuse export for the analysis sessions was not reliably retrievable this run (the legacy sessions API is gone and the v2 observations returned no analysis-proposer session ids), so the trajectory reading is transcript-based.

| Axis | D | E | Evidence |
|------|--:|--:|----------|
| `workflow_adherence` | fail | fail | The per-Service loop did not complete (the assign pass did); the capped run never reached the closure turns for most units |
| `tool_call_completeness` | partial | partial | Every proposer bound and called the surface tools; the read-only `graph_view` was called with write-shaped cypher |
| `interface_adherence` | fail | fail | 8 (D) / 9 (E) `ReadOnlyGraphViewError` fail-opens on write-shaped cypher; 51 (D) / 13 (E) unknown-property-key warnings (`o.triager`, `s.on_endpoints`) from guessed property names |
| `reasoning_coherence` | fail | fail | 288 (D) / 183 (E) `reasoning gap` warnings (the deepseek profile expects `reasoning_content` and the response omits it) |
| `tool_output_fidelity` | partial | pass | 5 (D) / 0 (E) `hypotheses exhausted; fail-closed` degradations; both read empty harvests correctly (the W-b `no_surface` path fires cleanly) |

The dominant C6 defect in both arms is interface adherence: the proposers emit write-shaped cypher and guess L0 property names.
The read-only guard and the empty-result handling both fail open, so the run is not corrupted, but the turns are wasted and the L0 queries return nothing.

### Verdict for arms D and E

- **The W-a..W-d fixes recovered most of the endpoint placement** lost by arms B and C: arm D places 70 endpoints (24.1%) against arm C's 21 (7.2%) and arm B's 34 (11.7%), close to the incumbent arm A (82, 28.3%). The per-Service assign no longer starves: `custom-node-content` alone kept 48 endpoints where arm C kept 0.
- **The W-b absent-surface degradation fires cleanly**: nine Manager Services report `no_surface` (bounded harvest found nothing; halted before `candidate_owners`) instead of escalating to the HTTP firehose.
- **`gt_service_aggregation` is now 100%** (all 14 ground-truth Services aggregate surface), the best of any arm.
- **C2 System metrics regressed further** (20.8% / 17.4%), but this is a partial-run artifact: the per-Service loop that writes System edges ran only ~4 of 23 units before the budget cap. Arm C's 46.4% came from a completed loop.
- **The compaction tuning (arm E) is a clear regression.** Lowering the thresholds to the mined per-role values cost quality (29 aggregates against 70; 10.0% placement against 24.1%; 0 DataItems against 2) and cache hygiene (76.2% against 87.8%), for a marginal cost saving (4,432,847 against 4,583,885). The lower thresholds triggered compaction churn: 8 `consecutive-pass cap` warnings against 0 in arm D, and the assigner grew to 2,472,239 capped tokens against arm D's 1,610,110.
- **Arm E is cheaper only on generation and the total budget**, and it is worse on every quality axis that orients a hunting agent.

The measured recommendation is to keep arm D's configuration (the global `0.2` threshold) and not adopt the per-role tuned thresholds.

---

## Cumulative per-target registry

This table is the extension point.
Every future target run appends one row, so the criteria accumulate evidence across targets and pipeline policies.

| Target | Arm | Policy | C1 `endpoint_placement` | C1 `orphan_services` | C2 `system_anchoring` | C3 `service_recall` | C3 `dataitem_recall` | C4 `cached_share_total` | C4 `input_uncached` | C4 `output_tokens` | C4 `capped_tokens` | C5 `l1_l0_grounded` | C6 `proposer_fidelity` | Date |
|--------|-----|--------|------------------------:|---------------------:|----------------------:|--------------------:|---------------------:|------------------------:|-------------------:|------------------:|-------------------:|--------------------:|----------------------:|------|
| comfyui | A | streamed L0-batch-first | 28.3% | 8 | 50.0% | 14/14 | 0/8 | 70.6% | 4,492,641 | 547,505 | 5,036,246 | - | - | 2026-10-10 |
| comfyui | B | batched analysis-unit-first | 11.7% | 8 | 37.5% | 14/14 | 0/8 | 70.0% | 4,495,625 | 388,610 | 4,884,235 | - | - | 2026-10-11 |
| comfyui | C | enriched analysis-unit-first (v2) | 7.2% | 13 | 46.4% | 14/14 | 0/8 | 68.9% (analysis roles) | 15,881,382 | 1,934,405 | 17,815,787 | - | - | 2026-10-12 |
| comfyui | D | surface-integrity fixes (W-a..W-d), config 0.2 | 24.1% | 12 | 20.8% (partial loop) | 14/14 | 0/8 | 87.8% | 3,749,265 | 834,620 | 4,583,885 | 11/49 = 22.4% | fail (interface, reasoning) | 2026-10-13 |
| comfyui | E | D + tuned per-proposer compaction | 10.0% | 12 | 17.4% (partial loop) | 14/14 | 0/8 | 76.2% | 3,903,682 | 529,165 | 4,432,847 | 11/46 = 23.9% | fail (interface, reasoning) | 2026-10-13 |
| `<target>` | | | | | | | | | | | | | | |
| `<target>` | | | | | | | | | | | | | | |

The C5 and C6 columns are `-` for arms A, B, and C: the criteria were defined after those runs, and the caveat is that they are forward-only (see Statistical Methodology).

Arm C's C4 columns are the analysis roles only (`triager` + `assigner` + `mechanism_typist`); arms A and B reported whole-project totals.
The arm C whole-project totals, including its long hunting arm, are `cached_share_total` 38.2%, 157,174,825 uncached input, 3,552,535 generated output, 160,727,360 capped.
The arms are therefore not cache-comparable without this note; see the C4 section.

## Segment Analysis - by ground-truth Service

Placed endpoints per ground-truth Service (arm A vs arm B):

| Ground-truth Service | A placed | B placed |
|---|---:|---:|
| server-diagnostics | 6 | 5 |
| system-status | 4 | 3 |
| workflow-submission | 3 | 3 |
| custom-node-catalog | 3 | 2 |
| image-upload | 2 | 2 |
| image-viewing | 3 | 2 |
| model-inventory | 3 | 2 |
| node-registry | 3 | 1 |
| user-profile | 3 | 2 |
| workflow-history | 2 | 1 |
| user-data-file | 1 | 1 |
| custom-node-lifecycle | 1 | 0 |
| manager-preferences | 1 | 0 |
| model-download | 0 | 0 |

Segment insight: the batched arm places fewer endpoints on 8 of the 14 ground-truth Services, ties on 3, and drops two Services to zero (`custom-node-lifecycle`, `manager-preferences`).
The regression is uniform, not concentrated.

---

## Learnings

### What We Learned

1. **The Service-first reading did not improve connectivity in this version.**
   `endpoint_placement` fell from 28.3% to 11.7% and `system_anchoring_coverage` from 50.0% to 37.5%.

2. **The single global assign pass is the primary cause.**
   Two calls placed 34 endpoints against the per-chunk assigner's 82 over 21 calls.

3. **The admission-set and slice-builder interaction is a latent design bug.**
   Because the assigner aggregates only endpoints, the data-modeller never runs per Service; the DataItem layer cannot be Service-scoped.

4. **Cache hygiene improved but is secondary.**
   The worst proposer rose from 18.0% to 27.8% and generated output fell 29.0%, but these do not offset the connectivity regression.

5. **Observability delivery is a run-blocking dependency.**
   A `403` silently dropped every span, so the run's evidence was nearly lost.

6. **Per-Service grounding alone does not raise placement, and a strict write filter lowers it.**
   Arm C rode `admitted=290` per Service yet placed fewer endpoints than arm B (21 against 34), because the `existing_slugs={slug}` filter dropped every candidate that named another owner (one Service proposed 25 and kept 0).

7. **System units improve System attachment.**
   Arm C is the only arm to beat arm B on C2, moving `system_anchoring_coverage` from 37.5% to 46.4% by giving the mechanism-typist a System's own surface.

8. **Reading the whole surface once per Service multiplies cost.**
   Arm C's analysis cost 3.5x arm A's whole-project cost, driven by 23 whole-surface prompts and repeated compaction passes.

### Surprising Findings

- The streamed (older) pipeline is the better-connected one; both analysis-unit-first redesigns (B and C) regressed connectivity.
- The v2 enrichment fixed the System axis but starved the Service axis, so it lost C1 while winning C2 against arm B.
- Both arms orphan the same 8 Services, so the orphan rate is a bootstrap property, not a pipeline property; arm C raises it to 13. DataItem recall is 0 in all three arms: the data plane failure is shared, not a differentiator.

### What We Still Don't Know

- Whether a per-Service assign pass without the strict `existing_slugs` write filter closes the connectivity gap.
- Whether a Service slice that unions data assets with endpoints grounds the DataItem layer (the data-modeller never ran in either arm B or arm C).
- Whether the connectivity regression holds on other targets, or whether comfyui is an outlier.

---

## Recommendation

### Decision: Keep the incumbent streamed pipeline (arm A); iterate the analysis-unit-first design before any further target

**Rationale:**

Arm A (streamed L0-batch-first) remains the best-connected and cheapest arm and is the best latest version: it wins C1 (all four), C2 (all three) and C4 (all five), and ties C3 breadth and depth.
Arm B (batched v1) loses C1 and C2 and wins only C4.
Arm C (enriched v2) also loses C1 and C4 and wins only C2 against arm B.
Neither analysis-unit-first formulation beats the incumbent on the criteria that orient a hunting agent, so neither should proceed to further targets as-is.

### If Reverting

- Keep the streamed `L0-batch-first` pipeline as the default (`analysis_mode: streamed`).
- Keep the `service_sourced` mode behind its flag until the assignment starvation is fixed.

### If Iterating (precondition for re-testing)

- **What to change:**
  - Remove or widen the per-Service assign write filter. The per-Service pass should ground on one Service but write a proposal onto whichever Service the surface evidence names, or reconcile owners, so it stops dropping `out_of_inventory` candidates.
  - Cut analysis cost: stop reading the whole settled surface once per Service; window the candidate set per Service.
  - Fix the data plane: the `data_modeller` never ran in arms B or C, so the DataItem layer stays empty.
  - Keep the System-unit change: it is the one measured improvement.
- **Next experiment:** re-run comfyui and require `endpoint_placement` at or above 28.3%, `system_anchoring_coverage` at or above 50.0%, and analysis capped tokens at or below arm A's whole-project 5,036,246.
- **Timeline:** one worktree, TDD, then re-run on the eval server.

---

## Next Steps

| Action | Owner | Due |
|--------|-------|-----|
| Write the connectivity fix as a design change (assign pass and slice builder) | implementing agent | next change |
| Land the `hunting-at-analysis-finish` ordering fix | implementing agent | next change |
| Fix the Langfuse `403` export auth on the eval instance | operator | next change |
| Run the connectivity fix on comfyui and re-score the four criteria | operator | after the fix |
| Extend the registry with a second target to test generality | operator | after comfyui passes |
| Add the criteria and metrics to the eval harness as first-class assertions | implementing agent | with the fix |

---

## How to extend this document with further targets

1. Reproduce one trial per arm on the new target, one arm at a time.
2. Re-measure every graph metric from the graph (never from a mid-run snapshot), using the queries in the Appendix, including the C5 L1-structure and L0-grounding queries; read the C4 token metrics from the durable usage ledger (`GET /projects/{pid}/usage`); read the C6 proposer trajectory from the Langfuse trace and the session transcript.
3. Ground-truth the new target under `~/.local/share/polymerhus/vuln-groundtruth/<target>/` in the same shape (`_target.md` section 8 plus per-unit `l1-profile.md`).
4. Append one row per arm to the cumulative per-target registry.
5. Keep the criteria and the metric definitions constant; add new columns only at the end.
6. Record the run SHA, the stack fingerprint, and the `analysis_mode` with every row.

---

## Appendix

### Raw Data

- Arm A graph: `ph-dd131acc-neo4j-1`, project `e2b53777-828c-4799-82f2-a95484feb052`.
- Arm B graph: `ph-dd131acc-neo4j-1`, project `79f96b81-3d27-4e8b-886d-948627609e64`.
- Arm C graph: `ph-dd131acc-neo4j-1`, project `6c357d47-2b7e-401e-9521-d268f2902365`; trial record `eval/runs-unitv2/comfyui-1/comfyui-1-20261011T233832-1fc05262/trial.yaml`; branch `feat/analysis-unit-enrichment`, `eval_sha` `55054aae`.
- Arm C evidence: `docker logs ph-dd131acc-agent-1` lines `assigner chunk=<slug> admitted=290 ... out_of_inventory=N`, `assign_services run=... units=23 kept=22 written=22`, and `service_sourced pass run=... units=24 wrote=True stopped=False`; C4 from `GET /projects/6c357d47-2b7e-401e-9521-d268f2902365/usage`.
- Arm B evidence: `docker logs ph-dd131acc-agent-1` lines `service_slice loop ... units=24 ... receipts=32` and `data_modeller chunk=__residual__ ...`.
- Ground truth: `~/.local/share/polymerhus/vuln-groundtruth/comfyui/` (`_target.md` section 8, `<vuln>/l1-profile.md`).
- Token spend: app `GET /projects/{pid}/usage`.

### Metric queries (Cypher, per project `$P`)

```cypher
-- C1
MATCH (s:L1Service {project_id:$P})                                   RETURN count(s);            -- services_total
MATCH (s:L1Service {project_id:$P}) WHERE NOT (s)-[:AGGREGATES]->()   RETURN count(s);            -- orphan_services
MATCH (e:Endpoint  {project_id:$P})                                   RETURN count(e);            -- endpoints_total
MATCH (e:Endpoint  {project_id:$P})<-[:AGGREGATES]-()                 RETURN count(distinct e);   -- endpoints_aggregated
-- C2
MATCH (y:L1System {project_id:$P}) WHERE NOT EXISTS { MATCH (y)-[]-(:L1Service) } RETURN count(y);
MATCH (y:L1System {project_id:$P}) WHERE EXISTS { MATCH (y)-[]-(s:L1Service)-[:AGGREGATES]->() } RETURN count(distinct y);
-- C3
MATCH (d:L1DataItem {project_id:$P})                                  RETURN count(d);            -- dataitems_total
MATCH (y:L1System {project_id:$P})-[:EVIDENCED_BY]->()                RETURN count(y);            -- evidenced_by
-- C5 (L1 structure + L0 grounding)
MATCH (n {project_id:$P}) WHERE n:L1Service OR n:L1System OR n:L1DataItem
  RETURN labels(n)[0] AS kind, count(n);                              -- l1_nodes_by_kind
MATCH (n {project_id:$P}) WHERE n:L1Service OR n:L1System OR n:L1DataItem
  RETURN count(n);                                                    -- l1_nodes_total
MATCH (a {project_id:$P})-[r]->(b {project_id:$P})
  WHERE (a:L1Service OR a:L1System OR a:L1DataItem)
    AND (b:L1Service OR b:L1System OR b:L1DataItem)
  RETURN type(r), count(r);                                           -- l1_edges_by_type (L1-to-L1 only)
MATCH (n {project_id:$P}) WHERE n:L1Service OR n:L1System OR n:L1DataItem
  WITH n WHERE EXISTS { MATCH (n)-[:EVIDENCED_BY|AGGREGATES]->(:Endpoint) }
  RETURN count(distinct n);                                           -- l1_l0_grounded_nodes
```

The C5 grounding reading follows the L0-L1 edge the proposer writes: a node is grounded when it holds at least one `EVIDENCED_BY`/`AGGREGATES` edge onto a concrete `Endpoint`, and an L1-to-L1 edge is grounded when its announced surface resolves to such an endpoint.
An ungrounded node is a mechanism with no L0 anchor and is counted, never dropped.

### C6 rubric (proposer trajectory fidelity)

For each proposer role, read the Langfuse trace and the session transcript and record one verdict per axis.

| Axis | Question | Reading |
|------|----------|---------|
| `workflow_adherence` | Did the proposer run the prompt's workflow, in order? | The turn sequence against the prompt's workflow steps |
| `tool_call_completeness` | Did it call every tool the workflow requires? | Every named tool present in the trace |
| `interface_adherence` | Did each call respect the interface agreement? | Tool arguments, result shape, read-only vs write |
| `reasoning_coherence` | Was the reasoning valid and contradiction-free? | The reasoning text against the evidence it cites |
| `tool_output_fidelity` | Was it deceived by tool-call response data? | Every error/empty result read correctly, no invented mechanism |

A verdict is an axis-by-axis pass or fail with the trace evidence that shows it; the criterion is not a single score.

### Statistical Methodology

- Test type: single-arm descriptive comparison, two pipeline policies, one trial per arm, one target.
- No randomisation, no p-value, no confidence interval: the sample is one trial per arm.
- Cross-arm comparability caveat: arm A ran `dev` `93d213e`; arm B ran `dev` `96f7787`.
  The comparison therefore bundles the pipeline change with a code change.
- Ground-truth denominator: both arms re-measured against the same 14-Service target slice.
- C5 and C6 are **forward-only**: arms A, B, and C were scored on C1-C4 only and did not record the L1 breakdown, L0 grounding, or a proposer trajectory reading.
  Their C5/C6 cells stay blank in the registry, and the first run that measures them is the current `dev` run (W-a..W-d).
  This is a recorded caveat, not a silent omission: the two criteria apply from that run onward and never retro-fit an earlier arm.

### Known Issues

- Arm B's hunting arm is uninformative (it launched at recon drain against the bootstrap L1).
- Arm B's capped-token figure is the final project total; its terminal figure was lower.
- Arm A's counts were re-measured from the graph and supersede the mid-run snapshot in the arm A report.
- Neither arm meets the 4,000,000 capped-token budget (A 125.9%, B 122.1%).
- Arm B delivered no Langfuse observations (export `403`).
- Arm C's trial terminal is `stopped` with a trial-ledger overshoot of 113,244, but the analysis pass completed (`stopped=False`); the trial ledger captured an early terminal while the app kept running, so the graph and the usage ledger are the authoritative arm C sources.
- Arm C's C4 columns are analysis-role-only; arms A and B are whole-project totals, so the C4 rows are not directly comparable without the note in the comparison table.
- Arm C's hunting arm ran far longer than arm B's, so the whole-project cost is not a clean pipeline comparison.
- Arm C's `data_modeller` never ran (no usage-ledger entry), so its DataItem layer is empty for the same reason as arm B's.
- The arm C comparison bundles the pipeline change with a code change (branch `feat/analysis-unit-enrichment` against arm A's `dev` `93d213e`).

---

*Results documented on 2026-10-11. Decision to kill the current batched formulation recorded with the document.*
