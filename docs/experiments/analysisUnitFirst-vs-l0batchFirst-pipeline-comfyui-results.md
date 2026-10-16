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
| **Status** | Completed - both analysis-unit-first formulations regress connectivity against the incumbent; the v2 enrichment fixes System attachment but not Service placement. The W-a..W-d fixes (arms D/E) recover most of the placement loss; the compaction tuning (arm E) then loses it again. The endpoint-first prefix + MCP seam fix (arm F) is the cheapest and best-cached run so far and ties the incumbent on ground-truth System exposure, but it regresses Service surface placement. Arm G (adjacent-surface assigner) recovers volume but collapses discrimination onto one non-GT owner |
| **Arms** | A = streamed L0-batch-first; B = batched analysis-unit-first (`service_sourced` v1); C = enriched analysis-unit-first (`service_sourced` v2, per-Service assign + System units + surface tools); D = surface-integrity fixes W-a..W-d (`dev` `c97750a`, current config); E = D with tuned per-proposer compaction thresholds; F = D-config + endpoint-first prefix (`aecac71a`) + http-history MCP seam fix (`6596a5f`) |
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

Reading rules (amended 2026-10-15):

- The cached axis is **sampled and gated**: a role entry whose `cache_detail_omitted` count equals its `calls` count reports SILENCE, and its cached share must be read as unknown, not as a measured miss.
- The streamed cache detail can regress to silence at the gateway hop (pinned litellm 1.96.0 dropped it whenever the provider attached `usage` to a choice-bearing finish chunk); the continuity patch now rides the gateway (`src/polymerhus/app/gateway_proxy_bootstrap.py`), and the trial's `token_spectrum` carries `cache_detail_omitted` so the condition is visible in the artifact.
- A trial whose `capped_tokens` include a fully-omitted role has an INFLATED budget axis; read its budget stop against the flag.

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

## Arm F - endpoint-first prefix + the http-history MCP seam fix

Arm F is the two-commit advance over arm D's `dev` base.
It carries the endpoint-first prefix (`aecac71a`), which feeds the Service surface into the FIRST human message of every proposer turn, and the http-history MCP seam fix (`6596a5f`), which rewrote the HTTP-history search filter from correlated `EXISTS`/`NOT EXISTS` subqueries to semi-joins.
The second change is the one under test by the run: the previous MCP filter was O(flows x attributes) and hung the analysis (measured 85s and 152s on the live store of 32,473 flows and 946,421 attributes, reduced to 0.03s and 0.006s).

| Attribute | Value |
|-----------|-------|
| Project | `6da91642-6298-4d73-8ec2-f16b740dd970` (`arm-f-rerun-2`) |
| Recon run | `1f4510ec-d1ae-4568-82ae-8e12e3d04b09` |
| Analysis run | `1f4510ec-d1ae-4568-82ae-8e12e3d04b09:e7ab848f` |
| `eval_sha` | `6596a5f4861feeb682e822de9f8f3056a529031b` (detached HEAD; `dev` `68d430af` + `aecac71a` + `6596a5f`) |
| `analysis_mode` | `service_sourced` (prompt variant `batched_l1unit_first`, the default) |
| Models | `opencode-go:deepseek-v4-flash` (every analysis role) |
| Compaction threshold | global `LLM_COMPACTION_THRESHOLD=0.2` (arm D's config) |
| Hunting | `hunt_after_analysis=false` (analysis-only) |
| Terminal | analysis `interrupted` (hard-stop; see Known Issues) |
| `stack_fingerprint` | not captured - the run was manual, with no orchestrator `trial.yaml` |

**F hypothesis:**

> We believed that feeding the surface into the first human message and fixing the HTTP-history MCP filter to be linear would keep arm D's placement while letting every unit run to completion (no MCP hang) at a lower cost.

### Comparison table (six arms)

| Criterion | Metric | A streamed | B batched | C enriched | D fixes | E tuned | F endpoint-first | Winner |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C1 | `service_aggregation_coverage` | 68.0% | 65.2% | 45.8% | 47.8% | 47.8% | 12/23 = 52.2% | A |
| C1 | `endpoint_placement` | 28.3% | 11.7% | 7.2% | 24.1% | 10.0% | 32/290 = 11.0% | A |
| C1 | `orphan_services` | 8 | 8 | 13 | 12 | 12 | 11 | A |
| C1 | `gt_service_aggregation` | 92.9% | 78.6% | 71.4% | 100% | 100% | 9/14 = 64.3% | D/E |
| C2 | `system_attachment_coverage` | 69.2% | 37.5% | 50.0% | 20.8% | 17.4% | 15/23 = 65.2% | A |
| C2 | `system_anchoring_coverage` | 50.0% | 37.5% | 46.4% | 20.8% | 17.4% | 7/23 = 30.4% | A |
| C2 | `orphan_systems` | 8 | 15 | 14 | 19 | 19 | 8 | A/F |
| C3 | `service_recall` | 100% | 100% | 100% | 100% | 100% | 14/14 = 100% | tie |
| C3 | `service_precision` | 56.0% | 60.9% | 58.3% | 60.9% | 60.9% | 14/23 = 60.9% | B/D/E/F |
| C3 | `dataitem_recall` | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | 0/8 | tie |
| C3 | `gt_service_system_exposure` | 100% | 57.1% | 71.4% | 28.6% | 57.1% | 14/14 = 100% | A/F |
| C4 | `cached_share_total` | 70.6% | 70.0% | 68.9% | 87.8% | 76.2% | 88.2% | F |
| C4 | `cached_share_worst_proposer` | 18.0% | 27.8% | 0.0% | 58.5% / 85.9% | 65.6% / 69.2% | 69.3% (`triager`) / 84.5% (proposers, `data_modeller`) | F |
| C4 | `input_uncached_tokens` | 4,492,641 | 4,495,625 | 15,881,382 | 3,749,265 | 3,903,682 | 2,071,438 | F |
| C4 | `generated_output_tokens` | 547,505 | 388,610 | 1,934,405 | 834,620 | 529,165 | 551,217 | B/E |
| C4 | `capped_tokens` | 5,036,246 | 4,884,235 | 17,815,787 | 4,583,885 | 4,432,847 | 2,622,655 | F |

C4 per-role (capped tokens / calls / cached share):

| Role | F capped | F calls | F cached |
|------|---------:|--------:|---------:|
| triager | 108,251 | 31 | 69.3% |
| assigner | 1,862,953 | 272 | 87.6% |
| mechanism_typist | 410,366 | 47 | 92.3% |
| data_modeller | 241,085 | 16 | 84.5% |
| **total** | **2,622,655** | **366** | **88.2%** |

Arm F is analysis-only (no hunting leg), so the whole-project total is the analysis total and is directly comparable to arms D and E.

### C1 - Service-to-surface aggregation

Arm F regresses placement against arm D, and the regression is in the ASSIGN pass, which completed in both arms (the per-Service loop that this stop interrupted writes no `AGGREGATES`).
The assign pass kept 33 edges across 12 Services against arm D's 70 across 11 Services, so `endpoint_placement` fell from 24.1% to 11.0% and `gt_service_aggregation` from 100% to 64.3%.

```
endpoint_placement   A [##########################.............] 28.3%
                     D [######################.................] 24.1%
                     F [##########.............................] 11.0%
```

The assigner logged `assign_services run=... units=23 kept=33 written=33 stale=6638`, with eight Manager Services reporting `no_surface` (bounded harvest found nothing; halted before `candidate_owners`).
The endpoint-first prefix is the change that separates arm F from arm D on this axis, and it is the likely cause: feeding the surface into the first human message can prime the harvest toward the pre-fed set and away from the tool-driven discovery that arm D's prompt relied on.
The model (`deepseek-v4-flash`) is a second, uncontrolled difference, so the two effects are not separated by this run.

### C2 - System anchoring

`system_attachment_coverage` is 65.2% (15 of 23) and `system_anchoring_coverage` is 30.4% (7 of 23), with 8 orphan Systems.
These are partial-loop numbers, as in arms D and E: the per-Service loop was stopped after a handful of units, so the System edges it writes are incomplete.
The attachment figure is nonetheless the second-best of any arm and nearly matches arm A, because the loop's mechanism-typist units wrote `EXPOSED_VIA` for 20 of 23 Services before the stop.

### C3 - Ground-truth breadth and depth

Breadth is a tie again (all 14 ground-truth Services captured, 100% recall; 60.9% precision).
Depth is unchanged: the spine carries `service_contract`, `exposure`, and `business_function_slug` on all 23 Services (`api_paradigm` and `auth_methods` absent), and the DataItem layer is empty (`0` `L1DataItem` nodes, `dataitem_recall` 0/8) even though the `data_modeller` ran (16 calls) - a partial, stopped run.
`gt_service_system_exposure` is 100%: every ground-truth Service carries a `ROUTED_BY`/`EXPOSED_VIA` System edge, tied with arm A.

### C4 - Cache spectrum

Arm F is the cheapest and best-cached run of the six, by a wide margin.
Its whole-project `capped_tokens` are 2,622,655 - 65.6% of the 4,000,000 budget and 57% of arm D's 4,583,885 - with `cached_share_total` 88.2% and uncached input 2,071,438 (46% of arm D's 3,749,265).
The cost falls for the same reason arm D's did: the endpoint-first prefix gives every proposer turn a byte-stable leading block, so the provider prefix cache matches and the assigner carries 87.6% of its input cached over 272 calls.

The worst proposer is the small `triager` at 69.3% (the only role under the 70% bar); across the three analysis proposers the floor is `data_modeller` at 84.5%.
Generation is 551,217 tokens, close to arm D's 834,620 and arm A's 547,505.

### C5 - L1 surface structure and L0 grounding

| Metric | F |
|--------|--:|
| `l1_nodes_by_kind` | L1Service 23, L1System 23, L1DataItem 0 |
| `l1_edges_by_type` | EXPOSED_VIA 20, ROUTED_BY 20 |
| `l1_l0_grounded_nodes` | 12/46 = 26.1% |
| `l0_unreferenced` (Endpoints) | 258 |

Arm F's L1 edge vocabulary is the narrowest yet: only the two presentation edges (`EXPOSED_VIA`, `ROUTED_BY`), no data-flow edges (`CONSUMES`/`PRODUCES`/`REFLECTED_IN`), no `AUTHENTICATED_BY` or `DEPENDS_ON`, and no DataItems.
Its grounding share (26.1%) is the highest of the three scored arms, but the edge vocabulary is thinner than arm D's.

### C6 - proposer trajectory fidelity

Read from the Langfuse trace (v2 observations, one session per unit) and the agent log.

| Axis | F | Evidence |
|------|--:|----------|
| `workflow_adherence` | pass (assigner) | The assigner ran `harvest_surface -> falsify_harvest -> prior_insights -> candidate_owners -> assign -> closure` in order per Service; the `no_surface` units halted cleanly after `falsify_harvest` |
| `tool_call_completeness` | pass | Every harvesting proposer bound and called the surface tools (`graph_view`, `search_http_history`, `get_http_artifact`, `notes`); the kept Service used all four |
| `interface_adherence` | pass (assigner) | No `ReadOnlyGraphViewError` or unknown-property-key warnings on the assign pass; the earlier arm D/E write-shaped cypher failures did not recur |
| `reasoning_coherence` | pass (assigner) | The harvest reasoning cites the contract nouns it discovered (`extensions`, `scripts`, `workflow_templates`, `i18n`) and the tool rows it read |
| `tool_output_fidelity` | pass | The empty-harvest path read `{"summaries": []}` correctly and halted, rather than inventing a mechanism |

The reading is complete for the assigner (its stage completed) and partial for the mechanism-typist and data-modeller (the loop was stopped).
The agent log carries one `ReadOnlyGraphViewError` and no `reasoning gap`, `hypotheses exhausted`, or `consecutive-pass cap` warnings, but this is a post-restart log (see Known Issues), so it undercounts the run.

### Produced artifacts and token distribution

Artifacts (all on the eval server):

| Artifact | Path | Note |
|----------|------|------|
| Graph | `ph-dd131acc-neo4j-1`, project `6da91642-6298-4d73-8ec2-f16b740dd970` | The re-measured C1/C2/C3/C5 source |
| Usage ledger | `GET /projects/6da91642-6298-4d73-8ec2-f16b740dd970/usage` | The C4 source (durable YAML, write-through per call) |
| Assigner log | `ph-dd131acc-agent-1` | `assigner chunk=<slug> ...`, `assign_services ... kept=33 written=33 stale=6638` |
| Langfuse | sessions `1f4510ec-..._e7ab848f:<slug>:assigner` | The C6 trajectory source |

No `trial.yaml`, `verdicts.yaml`, or `diagnoses.yaml` were produced: the run was manual and stopped by hand.

Token distribution by role (whole project, from the usage ledger):

| Role | cached input | uncached input | reasoning | visible | capped | calls |
|------|-------------:|---------------:|----------:|--------:|-------:|------:|
| triager | 191,360 | 84,788 | 16,798 | 6,665 | 108,251 | 31 |
| assigner | 10,616,960 | 1,499,543 | 143,447 | 219,963 | 1,862,953 | 272 |
| mechanism_typist | 3,600,512 | 299,797 | 57,017 | 53,552 | 410,366 | 47 |
| data_modeller | 1,023,616 | 187,310 | 30,028 | 23,747 | 241,085 | 16 |
| **total** | **15,432,448** | **2,071,438** | **247,290** | **303,927** | **2,622,655** | **366** |

### Verdict for arm F

- **The MCP hang is fixed.** The assign pass completed all 23 Services (`assign_services ... units=23 kept=33 written=33`) and the run never stalled on `HttpHistoryStore._filter_sql` - the defect that hung the previous run.
- **Placement regressed against arm D.** `endpoint_placement` fell from 24.1% to 11.0% and `gt_service_aggregation` from 100% to 64.3%, in the completed assign pass, so the endpoint-first prefix (or the model change) reduced assignment recall.
- **Cost and cache improved decisively.** `capped_tokens` 2,622,655 (65.6% of budget, 57% of arm D) and `cached_share_total` 88.2% - the cheapest, best-cached run of the six.
- **System/exposure metrics are strong but partial.** `system_attachment_coverage` 65.2% and `gt_service_system_exposure` 100%, both from a stopped loop.
- **The L1 edge vocabulary is the narrowest yet** (two presentation edges, no data edges, no DataItems).

The measured read is that the MCP seam fix should stay, while the endpoint-first prefix needs iteration: it bought cost but cost placement.

---

## Arm G - streamed L0 with the adjacent-surface assigner (collapse to one owner)

Arm G is the first trial of the L0 trunk after the pipeline split: the streamed chunk pipeline with the adjacent-surface assigner (D-A1..D-A4 - bounded BaseURL-neighbourhood discovery through the re-bound read-only `graph_view` + HTTP-history pair for disambiguation/confirmation only, the L1 dump as the deductive target, the out-of-chunk write gate dropped), the reset-per-chunk session lifecycle, and config 0.2.
It ran the same setup as the streamed fix trial (`eval/setups/webexploitbench-8-run2.yaml`, target `comfyui-1`, budget 7200s), analysis-only in effect (no hunting roles in the ledger), with the token budget lowered to 3M capped for this arm.

| Attribute | Value |
|-----------|-------|
| Trial | re-run `run-streamed-comfyui-arm-g2` (no `trial.yaml`: the orchestrator timed out at the token budget without writing one - the arm F precedent; graph + ledger + log are the sources) |
| Project | `90ededf2-9753-4362-83f9-6a98ee66f1b1` |
| Recon run | `2c319370-6dec-4dd5-a73d-17ccf1af70bc` (complete, phase 10) |
| `eval_sha` | `775505c36ad472f879122333fc7343bec99a773a` (`dev` merge of `rollback/l0-trunk`) |
| `stack_fingerprint` | `39a85f7d589fe32f22703ca77382a850269972435e1b2e18e031885b2b5444e1` |
| `analysis_mode` | `streamed` (the only mode; the `--analysis-mode` selector is removed) |
| Models | `opencode-go:deepseek-v4.1-flash` (every role - the new key is not entitled to `v4-flash`; v4.1 is the arms A-E lineage, F is the v4-flash outlier) |
| Token budget | 3,000,000 capped (arms A-F: 4,000,000) |
| Terminal | analysis ended at the token budget (3,235,875 capped / 198 calls, overshoot 235,875); hunting never launched |

**G hypothesis:**

> We believed that letting the streamed assigner judge each chunk against its adjacent settled surface (instead of refusing every out-of-chunk reference) would recover the correct edges the httpx:0 forensics showed the gate discarding, raising `endpoint_placement` toward arm A at a bounded per-chunk cost.

**What ran (~1h, 20:43Z-21:40Z):** recon completed and settled 290 Endpoints plus the KB skeleton (25 Services, 25 Systems).
Analysis ran 11 chunks to the budget cap.
The assigner census over the run: admitted 83, proposed 75, kept 75, `unresolvable` 0, `out_of_inventory` 0, `withheld` 0.
The gate drop works mechanically - nothing died as unresolvable - but the judgment collapsed: **74 of the 75 kept edges name `editor-shell`** (a non-ground-truth extra), 1 names `model-inventory`.
The withholding bar never fired once in 11 chunks.

### Comparison table (seven arms)

| Criterion | Metric | A streamed | F endpoint-first | G adjacent-surface |
|---|---|---:|---:|---:|
| C1 | `service_aggregation_coverage` | 68.0% | 52.2% | 2/25 = 8.0% |
| C1 | `endpoint_placement` | 28.3% | 11.0% | 75/290 = 25.9% |
| C1 | `orphan_services` | 8 | 11 | 23 |
| C1 | `gt_service_aggregation` | 92.9% | 64.3% | 1/14 = 7.1% |
| C2 | `system_attachment_coverage` | 69.2% | 65.2% | 5/25 = 20.0% |
| C2 | `system_anchoring_coverage` | 50.0% | 30.4% (partial) | 4/25 = 16.0% |
| C2 | `orphan_systems` | 8 | 8 | 20 |
| C3 | `service_recall` | 100% | 100% | 14/14 = 100% |
| C3 | `service_precision` | 56.0% | 60.9% | 14/25 = 56.0% |
| C3 | `dataitem_recall` | 0/8 | 0/8 | 0/8 |
| C3 | `spine_depth` | 60.0% | 60.0% | 60.0% (`api_paradigm`/`auth_methods` absent on all 25) |
| C3 | `gt_service_system_exposure` | 100% | 100% | 1/14 = 7.1% |
| C4 | `cached_share_total` | 70.6% | 88.2% | 30.2% (unaudited) |
| C4 | `input_uncached_tokens` | 4,492,641 | 2,071,438 | 2,972,981 (inflated) |
| C4 | `generated_output_tokens` | 547,505 | 551,217 | 262,894 |
| C4 | `capped_tokens` | 5,036,246 | 2,622,655 | 3,235,875 (3M budget, overshoot 235,875; inflated) |

The G cache cells are UNAUDITED (corrected 2026-10-15): every one of the typist's 58 streamed calls reached the ledger with no cache detail at all, because the pinned gateway (litellm 1.96.0) drops `prompt_tokens_details` from streamed usage when the provider attaches `usage` to a choice-bearing finish chunk.
The provider did cache the requests: replays of the captured typist bytes hit `cached=4480/4673` (95.9%) and `4672/4673`.
The recorded 0.0% is silence read as a miss, and the recorded `input_uncached` / `capped` are correspondingly inflated (`typist-cache-collapse-diagnosis.md`, verdict falsified; `cache-spectrum-measurement-research.md`).

C4 per-role (capped tokens / calls / cached share):

| Role | G capped | G calls | G cached |
|------|---------:|--------:|---------:|
| triager | 112,722 | 30 | 66.8% |
| assigner | 309,878 | 73 | 76.7% |
| mechanism_typist | 2,670,245 | 58 | 0.0% (unaudited) |
| data_modeller | 143,030 | 37 | 77.9% |
| **total** | **3,235,875** | **198** | **30.2%** (unaudited) |

The typist row is the unaudited one: the ledger recorded `input_cache_read=0` because the streamed usage carried NO detail (`cache_detail_omitted` 58/58), not because the provider measured a miss.

Two cost readings: the assigner did NOT explode (309,878 capped over 73 calls at 76.7% cached - the adjacent phase costs ~28k capped per chunk); the run stopped on the **mechanism-typist's 2.67M recorded uncached at 0.0% cached** (58 calls, ~46k each).
That typist figure is a measurement artifact, not a cache failure: the calls carried no cache detail through the gateway, and replays of the same bytes hit the provider cache at 95.9-100%.
The typist's true uncached input is therefore expected an order of magnitude smaller (~10% of the recorded figure at the sampled hit rates), and the 3M budget stop fired early on an inflated axis.
The 70% hygiene bar reads 30.2% under the artifact; the per-role floor that flagged the typist flagged a gateway defect, not a prompt defect.

### C5 - L1 surface structure and L0 grounding

| Metric | G |
|--------|--:|
| `l1_nodes_by_kind` | L1Service 25, L1System 25, L1DataItem 0 |
| `l1_edges_by_type` | EXPOSED_VIA 12, FRONTED_BY 7, ROUTED_BY 1 |
| `l1_l0_grounded_nodes` | 2/50 = 4.0% |
| `l0_unreferenced` (Endpoints) | 215 |

The edge vocabulary is presentation-only (as in arm F); grounding collapses with the ownership collapse (only the 2 aggregating Services touch L0).

### C6 - proposer trajectory fidelity (arm G, structural - no IO persisted)

Langfuse carries no message IO for this run (generations and tool calls persist without input/output, as in arm F), so the C6 reading is structural, from the 772-observation assigner session (`2c319370-...:assigner`, the one `run:role` thread - the Task-2 reset visible in observability):

| Axis | G (assigner) | Evidence |
|------|--:|----------|
| `workflow_adherence` | partial | 73 generations over 11 chunks (~7 turns/chunk); the adjacent phase executed every chunk (100 `graph_view`, 11 `search_http_history`, 6 `get_http_artifact`); extractions shaped cleanly into kept batches |
| `tool_call_completeness` | pass | The bound set (`graph_view` + HTTP pair) was called on every chunk; the HTTP pair stayed disambiguation-scale as specified |
| `interface_adherence` | pass | 771 DEFAULT / 1 ERROR (a single `search_http_history` fail-open); no write-shaped cypher, no property warnings |
| `reasoning_coherence` | fail | 74/75 edges to one non-GT owner with 0 withholds in 11 chunks - the differential/calibration discipline did not operate at the outcome level |
| `tool_output_fidelity` | unreadable | No IO persisted; no verdict possible |

The per-chunk reset lifecycle is verified live in the same session: one `run:assigner` thread across all chunks with reset markers at each boundary.
Per-proposal confidences are unrecoverable (`assigner-aggregates` traces persist with empty outputs) - all that is known is every kept edge cleared 0.75.

### Verdict for arm G

- **The hypothesis is disproven in this form.** Dropping the out-of-chunk gate recovered volume (`endpoint_placement` 25.9%, near arm A's 28.3%, with zero unresolvable) but destroyed discrimination: coverage 8.0%, GT aggregation 7.1%, grounding 4.0%. The gate was load-bearing friction, not just a scope bug - removing it without a counterweight turns the assigner into a single-owner dustbin.
- **The failure is calibration, not discovery.** The adjacent phase found real surface (100 bounded graph queries, HTTP pair used as specified); the bar never fired because every judgment cleared it. Candidates for the next experiment, in order: (a) the `editor-shell` contract is over-broad (a skeleton property - the model may be right that the shell "owns" the UI surface, in which case the defect is the skeleton's, not the judgment's); (b) the L1-dump-as-deductive-target primes deduction-to-one when the gate no longer localises; (c) confidence calibration collapsed under the wider view.
- **Do not re-run this configuration.** The next experiment is NOT more of arm G: raise the bar (`ASSIGN_CONFIDENCE_BAR` 0.85/0.9) to test the calibration hypothesis, or cap per-owner volume, or narrow the adjacent phase to the chunk's own BaseURLs - one change at a time.
- **Cost verdict REVISED (2026-10-15).** The typist's 0%-cached 2.67M was a gateway measurement artifact: the same request bytes replayed hit the provider cache at 95.9-100% (`typist-cache-collapse-diagnosis.md`, verdict falsified), so the per-chunk typist prompt was cache-friendly and the 3M stop fired early on an inflated axis. The true cost axis needs a clean re-run (arm H) before any budget conclusion, and the endpoint-first-prefix treatment is unproven as a cache need.
- **Model/budget provenance for comparability:** arm G ran `v4.1-flash` (arms A-E lineage) under a 3M cap; arm F ran `v4-flash` under 4M. The F-vs-G delta bundles model + budget + pipeline - read it as directional, never as isolated.

---

## Arm H - streamed L0 with the noise gate, the HTTP-history assigner and the measured cache

Arm H re-runs arm G2's variables with the three fixes the G forensics named: the L0 noise gate (`3162d3f`, `353f003`), the streamed-usage continuity fix at the gateway (`bd341fd`) with the N5 omission count in the token spectrum (`913552d`), and the assigner rollback to the HTTP-history disambiguation surface (`99b400e`, R-A1..R-A3 of the assigner-surface ADR).
It also carries the four-track analysis integration (aggregate-confidence drop, `data_modeller` drop, typist tool-surface trim) and the A6 runtime relax-and-replay (`8a8907b`).
Same setup as G2 (`eval/setups/webexploitbench-8-run2.yaml`, target `comfyui-1`, `--budget-s 7200`), same environment, config 0.2, 3M token cap, `v4.1-flash` in every role.

| Attribute | Value |
|-----------|-------|
| Trial | `comfyui-1-20261015T143534-1fc05262` (`trial.yaml` written; the dir name carries the finish time - started `12:28:03Z`, finished `14:35:34Z`, terminal `stopped`) |
| Project | `a9bb42f9-6255-4f1e-87ee-fc09e2388024` |
| Recon run | `d09748ab-92ef-4046-89c4-517f813d24e9` (complete) |
| `eval_sha` | `a088730dd0bd5d5f42075eaf0ef7d312e8c859fd` (`dev` merge of the streamed-usage and N5 landings) |
| `stack_fingerprint` | `613d2f7cc8490deac7cf7b7a5d6fdce6cea623379e3aeb5942e8948b650ff9de` |
| `analysis_mode` | `streamed` |
| Models | `opencode-go:deepseek-v4.1-flash` (every role) |
| Token budget | 3,000,000 capped |
| Terminal | phases `recon: complete`, `analysis: drained`, `hunting: stopped`; spend 3,017,307 at the stop (+17,307 over); the hunting run started and was stopped by the spend guard as the 7200s wall budget expired |

**H hypothesis:**

> We believed that gating L0 noise before queueing, restoring the HTTP-history surface to the assigner and fixing the streamed-usage accounting would keep the placement volume the G forensics pointed to without G's single-owner collapse - and would finally yield a cost reading without the gateway artifact.

**What ran (~2h03m, 12:28Z-14:31Z):** recon settled 290 Endpoints (httpx 183, katana 105, jsluice 1, steel 1) and the KB skeleton (23 Services, 15 scaffold Systems).
The L0 stream arrived in 7 passes: 26 chunks, 52 role dispatches, 2,280 L0 assets.

| Pass | Source | Chunks | L0 assets | Aggregates | Systems |
|------|--------|-------:|----------:|-----------:|--------:|
| P1 | Domain | 1 | 1 | 0 | 4 |
| P2 | IP/Port/Service | 1 | 13 | 0 | 3 |
| P3 | httpx | 1 | 13 | 0 | 3 |
| P4 | katana | 12 | 1,240 | 1 | 12 |
| P5 | ffuf | 1 | 22 | 7 | 2 |
| P6 | steel_crawl | 1 | 4 | 0 | 1 |
| P7 | jsluice | 9 | 987 | 97 | 22 |

The assigner census over the run: **admitted 298, proposed 105, kept 105, `unresolvable` 0, `out_of_inventory` 0** over 14 turns.
193 admitted endpoints were declined into the stale pool, so the discrimination G lost operated again at the admitted-to-proposed step (35.2% proposal rate).
The ffuf and jsluice passes carry the volume (104 of the 105 kept aggregates, from endpoint-rich wordlist and JS findings).
The katana pass is the mechanical counter-example: only 2 of its Endpoint deltas are admissible after the noise gate (the gate drops the static-bundle `*.js` paths), the pass's other ~1.2k assets are metadata deltas (header/technology/BaseURL baskets for already-known endpoints) that the assigner cannot use, and 10 of its 12 chunks spend a typist turn with no admissible Endpoint for the assigner.

### Comparison table (A, F, G, H)

| Criterion | Metric | A streamed | F endpoint-first | G adjacent-surface | H gate + HTTP-surface |
|---|---|---:|---:|---:|---:|
| C1 | `service_aggregation_coverage` | 68.0% | 52.2% | 2/25 = 8.0% | 14/23 = 60.9% |
| C1 | `endpoint_placement` | 28.3% | 11.0% | 75/290 = 25.9% | 78/290 = 26.9% |
| C1 | `orphan_services` | 8 | 11 | 23 | 9 |
| C1 | `gt_service_aggregation` | 92.9% | 64.3% | 1/14 = 7.1% | 10/14 = 71.4% |
| C2 | `system_attachment_coverage` | 69.2% | 65.2% | 5/25 = 20.0% | 18/27 = 66.7% |
| C2 | `system_anchoring_coverage` | 50.0% | 30.4% (partial) | 4/25 = 16.0% | 11/27 = 40.7% |
| C2 | `orphan_systems` | 8 | 8 | 20 | 9 |
| C3 | `service_recall` | 100% | 100% | 14/14 = 100% | 14/14 = 100% |
| C3 | `service_precision` | 56.0% | 60.9% | 14/25 = 56.0% | 14/23 = 60.9% |
| C3 | `dataitem_recall` | 0/8 | 0/8 | 0/8 | 0/8 |
| C3 | `spine_depth` | 60.0% | 60.0% | 60.0% | 60.0% (`api_paradigm`/`auth_methods` absent on all 23) |
| C3 | `gt_service_system_exposure` | 100% | 100% | 1/14 = 7.1% | 14/14 = 100% |
| C4 | `cached_share_total` | 70.6% | 88.2% | 30.2% (unaudited) | 90.0% (measured) |
| C4 | `input_uncached_tokens` | 4,492,641 | 2,071,438 | 2,972,981 (inflated) | 2,151,348 |
| C4 | `generated_output_tokens` | 547,505 | 551,217 | 262,894 | 867,442 |
| C4 | `capped_tokens` | 5,036,246 | 2,622,655 | 3,235,875 (3M, +235,875; inflated) | 3,018,790 (3M, +18,790; measured) |

H's `gt_service_system_exposure` uses the same source-side reading as arm F ("every ground-truth Service carries a `ROUTED_BY`/`EXPOSED_VIA` System edge"); the staged measure script's target-side variant of this one query reads 0 on this schema and is an inverted-direction artifact.

C4 per-role (capped tokens / calls / cached share):

| Role | H capped | H calls | H cached |
|------|---------:|--------:|---------:|
| triager | 117,977 | 30 | 69.1% |
| assigner | 324,340 | 59 | 74.3% |
| mechanism_typist | 2,362,165 | 304 | 91.0% |
| hunting_orchestrator | 115,911 | 19 | 93.4% |
| hunting_hunter | 98,397 | 8 | 75.2% |
| **total** | **3,018,790** | **420** | **90.0%** |

No row is unaudited: `cache_detail_omitted` is 0 for all 420 calls, the first arm where the streamed-usage path carried cache detail end to end.
Three readings:

- The typist's real cost shape is now measured: 304 calls at 91.0% cached (2,362,165 capped, ~7.8k per call) - a cache-friendly per-chunk prompt, not G's recorded 0%-cached 58-call artifact. The four-track integration turned the typist into many small turns, and the recorded axis is trustworthy.
- The worst proposer is the assigner at 74.3%, above the 70% bar; the total is 90.0% - the first clean crossing of the C4 hygiene bar in the streamed line.
- The budget stop is readable: the analysis roles total 2,804,482 (93.5% of the cap) and hunting adds 214,308; the stop was the spend guard, not an inflated axis. (The usage pull taken after the stop reads +1,483 over the `trial.yaml` figure from two late orchestrator calls.)

### C5 - L1 surface structure and L0 grounding

| Metric | H |
|--------|--:|
| `l1_nodes_by_kind` | L1Service 23, L1System 27, L1DataItem 0 |
| `l1_edges_by_type` | AUTHENTICATED_BY 12, DEPENDS_ON 1, EXPOSED_VIA 24, IDENTIFIED_BY 9, ROUTED_BY 20 |
| `l1_l0_grounded_nodes` | 14/50 = 28.0% |
| `l0_unreferenced` (Endpoints) | 212 |

The vocabulary is the widest of any arm (six edge types; `AUTHENTICATED_BY`/`IDENTIFIED_BY` arrive with the four-track integration) and is entirely analyser-written: 66 L1-to-L1 edges, with the scaffold contributing nodes only.
Grounding is the best measured so far (28.0% against F's 26.1%, E's 23.9%, D's 22.4% and G's 4.0%): exactly the 14 aggregating Services are grounded, and no System carries L0 evidence.
The 212 unreferenced endpoints are the reconnaissance bulk no pass reaches, dominated by the httpx fuzz/probe deltas and the katana feed's bundle and metadata endpoints.

### C6 - proposer trajectory fidelity (arm H)

The assigner session persisted full message IO (803 observations, 59 generations, 14 turns - one per chunk that admitted surface).
The typist session was read as a census of its last 1,000 observations (the 13:56-14:31 tail, six full turns).

| Axis | H (assigner) | Evidence |
|------|--:|----------|
| `workflow_adherence` | pass | 14/14 turns ran the prompt's sequence - surface-first reading, history widening, differential, `L1DeltaBatch` commit; the "history unreachable -> retry once -> judge on the slice" degradation plan appears on the degraded turns |
| `tool_call_completeness` | pass | the bound set was called on every turn (`search_http_history` always, `get_http_artifact` where a candidate artifact existed); widening stayed bounded (limits 5-60) |
| `interface_adherence` | agent pass / seam fail | the agent's calls are read-only and correctly shaped (filter and text forms, limits); the seam returned 39 error-level tool results across 14/14 turns (4 `TimeoutError` at the 150s client bound; `ClosedResourceError` on freshly opened sessions; ~10 `invalid_request`/validation results including two `HttpArtifact` validation errors) |
| `reasoning_coherence` | partial | explicit candidate -> discrimination -> commit/drop on every turn, and the discipline operated (193/298 admitted endpoints declined); one quirk: the `/experiment/models` keep ran its differential only against noun-adjacent candidates (`model-download`) and never against the rival whose contract names the observed payload class (`server-diagnostics`, "the folder-path map") - candidate generation is path-noun-driven |
| `tool_output_fidelity` | pass | every `http_history_failed` result was read as "missing evidence, not an empty surface" (verbatim in six turns); 404-with-empty-body artifacts were read correctly; no mechanism was invented from a tool response |

Typist: the sampled tail shows six turns at 9-14 generations each running the complete tool set (`graph_view`, the HTTP pair, `exec`) and closing with `L1DeltaBatch`, with zero errors or warnings; combined with the live pass-table reading (P1-P4) and the per-chunk reset markers in the agent log (one `run:mechanism_typist` thread, reset at every chunk boundary), the typist trajectory reads as the cleanest of the line.
`data_modeller`: dropped from the pipeline by the four-track integration, so no verdict.

### Verdict for arm H

- **The hypothesis holds in the form tested.** The streamed trunk with the noise gate and the HTTP-history assigner pairs volume with discrimination for the first time since the split: `endpoint_placement` 26.9% (at arm A's level), 14 of 23 Services aggregating, `gt_service_aggregation` 71.4% against G's 7.1%, 193 of 298 admitted endpoints declined rather than pinned, `unresolvable` 0 throughout. G's collapse does not reproduce.
- **The cost reading is finally clean.** 90.0% cached across 420 calls with zero omissions, worst proposer the assigner at 74.3%; the budget stop is legible without an inflation footnote. The typist's G-era 0% is confirmed dead as a measurement artifact; its true shape is many small cache-friendly calls.
- **The next feed defect is named and mechanical.** The noise gate gates Endpoints only; the katana metadata deltas (~1.2k header/technology/BaseURL baskets) still stream and still buy typist turns, while the assigner starves on the same chunks. The next iteration gates the remaining feed forms (Domain/IP/Port/Service) at queue time and rebuilds chunks as endpoint-anchored cohesive families.
- **The next reliability defect is the MCP session lifecycle.** Fresh sessions die for most of the run (`ClosedResourceError` in 14/14 assigner turns; the kali server log shows `DELETE /mcp` followed by `POST /mcp` 404); the fix direction is a deterministic close when a unit's processing completes and a fresh session per streamed chunk, replacing the reuse of failed sessions.
- **One differentiation quirk stays open.** `/experiment/models` is the folder-path map (live probe, 15 Oct 2026); its judgment ran noun-to-noun and never reconciled the payload's other route identity (`/folder_paths`, kept under `server-diagnostics`). The relaxation analysis is scoped to the next iteration, not decided here.

---

## Arm J - the corrected streamed pipeline and the WS1-WS4 formal re-run

Arm J is the streamed pipeline with the operator-ruled corrections of 2026-10-16 landed.
Its first trials ran on 2026-10-15 (`6d3897e1`) with the T1-T3 stream corrections and the E5 header canonicalization; this document calls those runs **arm J baseline**.
The failure-mode diagnoses F1-F9 (`docs/design/plans/2026-10-16-failure-modes-diagnosis.md`) drove four workstreams WS1-WS4, and the plan with its rollout is `docs/design/plans/2026-10-16-arm-j-formal-corrections.md`.
The workstreams landed on `dev` through `eee6740` (the header hotfix `1163f33` followed it), and the formal re-runs ran `1163f330` with stack fingerprint `542674ea...` on both targets on 2026-10-16.
Evidence for this section: the Langfuse window pulls (6 distinct streamed blocks per formal run), the observation censuses, the hunter-store counts, the graph queries of the Appendix, and the durable usage pull.

### What changed (WS1-WS4) and what the formal data shows

| Workstream | Change (merged) | Formal verification (both runs unless noted) |
|------------|-----------------|----------------------------------------------|
| WS1 - runtime baseURL chaining (`85f9938`, `3c12a6f`) | JS literals resolve against their resource and chain runtime baseURL prefixes; foreign-origin chaining stays the latest failover; the external gate never probes foreign origins | the `/api` namespace enters the graph: 52 `/api/*` paths on comfyui against 4 at baseline, 38 on white-jotter against 2, including `/api/admin/**`, `/api/authentication` and `/api/books`; 0 foreign `BaseURL`s and 0 `ExternalDomain`s; the mis-resolved json-literal artifacts are gone (44 `.json` paths in the baseline comfyui graph, all streamed, against 0 now) and the comfyui extensionless class grows 54 -> 145 |
| WS2 - endpoint-scoped headers (`2fcc1dd`, `2f1f984`) | header identity is `{name, endpoint, baseurl}`; `value`/`direction` stay attributes; `date` is never minted; headers stay bound to their source BaseURL | comfyui carries 1,743 headers over 339 distinct endpoints (baseline 11 project-global, one named `date`), white-jotter 329 over 68 (baseline 9); 0 `date`-named headers, 0 identity duplicates, every header `response` with a value and a `HAS_HEADER` BaseURL membership |
| WS3 - recall-biased stream gate + description overwrite (`ea9b092`, `97dd9c8`) | hard-drop the static families (css/scss/less/fonts/map, js/mjs, wasm); images/media/archives only under `assets`/`static`; `.json` and extensionless stay; System descriptions overwrite instead of accumulate | the comfyui graph holds 189 `.js`/`.mjs` endpoints (191 at baseline: 100 `.mjs` + 91 `.js`) and the stream carries none (its 153 endpoint deltas are 152 extensionless + 1 `.html`); white-jotter holds 16 `.js` and streams none; the described Systems read as single coherent narratives (12/24 comfyui, 7/29 white-jotter) |
| WS4 - assigner L1 graph block (`2ad4575`, `011848c`) | the L1 graph (contracts, System descriptions, attributes, edges) is posted in the assigner's human message and updates live per dispatch; no `graph_view` step and no null-owner drop path | all 17 (comfyui) and 15 (white-jotter) assigner generations carry the block and grow with it live (25,757 -> 130,734 chars / 24,984 -> 112,020); 0 `graph_view` calls by the assigner; `unresolvable` 0 and `out_of_inventory` 0 on every chunk; `proposed` equals `kept` throughout |

### Trials

| Attribute | J baseline comfyui | J formal comfyui | J baseline white-jotter | J formal white-jotter |
|-----------|--------------------|------------------|-------------------------|-----------------------|
| Trial | `comfyui-1-20261015T224409-1fc05262` | `comfyui-1-20261016T203228-1fc05262` | `white-jotter-1-20261015T235448-1618c524` | `white-jotter-1-20261016T212305-1618c524` |
| Project | `2df3ad9d-eb9c-4789-a118-44139a745ca2` | `d04b947f-d6c3-48be-9b18-1c4eef851241` | `bf0d9408-d403-457f-b769-076dd9cd9138` | `f16de150-b032-4566-871b-2df6fa4d48a9` |
| `eval_sha` | `6d3897e1` | `1163f330` | `6d3897e1` | `1163f330` |
| `stack_fingerprint` | `5d3a954b...` | `542674ea...` | `5d5e9d21...` | `542674ea...` |
| Token budget / spend at stop | 3,000,000 / 3,009,705 | 3,000,000 / 3,042,118 | 4,000,000 / 4,029,445 | 4,000,000 / 4,003,908 |
| Wall (UTC) | 21:59:57-22:44:09 (44 min) | 19:37:30-20:32:28 (55 min) | 23:02:11-23:54:48 (53 min) | 20:32:29-21:23:05 (51 min) |
| Terminal | `stopped` | `stopped` | `stopped` | `stopped` |

The spend column is the `trial.yaml` agent sum at the stop; the usage pull (the C4 source, see the list footnotes) reads 3,010,284 / 3,044,033 / 4,033,225 / 4,031,857 capped because late calls land after the record is written.
Both formal runs close clean: zero `merge failed` and zero `ParsingRecovery` lines in either agent log.

### C1-C3 criteria (comfyui)

| Criterion | Metric | A streamed | H | J (15 Oct) | J formal |
|-----------|--------|-----------:|------------:|------------:|-----------:|
| C1 | `service_aggregation_coverage` | 68.0% | 14/23 = 60.9% | 14/23 = 60.9% | 14/23 = 60.9% |
| C1 | `endpoint_placement` | 28.3% | 78/290 = 26.9% | 76/290 = 26.2% | 67/335 = 20.0% |
| C1 | `orphan_services` | 8 | 9 | 9 | 9 |
| C1 | `gt_service_aggregation` | 92.9% | 10/14 = 71.4% | 10/14 = 71.4% | 10/14 = 71.4% |
| C2 | `system_attachment_coverage` | 69.2% | 18/27 = 66.7% | 10/24 = 41.7% | 12/24 = 50.0% |
| C2 | `system_anchoring_coverage` | 50.0% | 11/27 = 40.7% | 10/24 = 41.7% | 12/24 = 50.0% |
| C2 | `orphan_systems` | 8 | 9 | 14 | 12 |
| C3 | `service_recall` | 100% | 14/14 = 100% | 14/14 = 100% | 14/14 = 100% |
| C3 | `service_precision` | 56.0% | 14/23 = 60.9% | 14/23 = 60.9% | 14/23 = 60.9% |
| C3 | `dataitem_recall` | 0/8 | 0/8 | 0/8 | 0/8 |
| C3 | `spine_depth` | 60.0% | 60.0% | 60.0% | 60.0% |
| C3 | `gt_service_system_exposure` | 100% | 100% | 10/14 = 71.4% | 11/14 = 78.6% |
| C4 | `cached_share_total` | 70.6% | 90.0% | 92.5% | 93.0% |
| C4 | `input_uncached_tokens` | 4,492,641 | 2,151,348 | 2,187,976 | 2,090,533 |
| C4 | `generated_output_tokens` | 547,505 | 867,442 | 822,308 | 953,500 |
| C4 | `capped_tokens` | 5,036,246 | 3,018,790 (+18,790) | 3,010,284 (+10,284) | 3,044,033 (+44,033) |

`gt_service_system_exposure` uses the source-side reading (the ground-truth Service carries the `ROUTED_BY`/`EXPOSED_VIA`/`FRONTED_BY` System edge); the staged script's target-side variant reads 0 and is an inverted-direction artifact.

### C1-C3 criteria (white-jotter)

| Criterion | Metric | J (15 Oct) | J formal |
|-----------|--------|-----------:|---------:|
| C1 | `service_aggregation_coverage` | 18/24 = 75.0% | 17/24 = 70.8% |
| C1 | `endpoint_placement` | 29/57 = 50.9% | 51/93 = 54.8% |
| C1 | `orphan_services` | 6 | 7 |
| C1 | `gt_service_aggregation` | 18/21 = 85.7% | 17/21 = 81.0% |
| C2 | `system_attachment_coverage` | 27/28 = 96.4% | 24/29 = 82.8% |
| C2 | `system_anchoring_coverage` | 24/28 = 85.7% | 24/29 = 82.8% |
| C2 | `orphan_systems` | 1 | 5 |
| C3 | `service_recall` | 21/21 = 100% | 21/21 = 100% |
| C3 | `service_precision` | 21/24 = 87.5% | 21/24 = 87.5% |
| C3 | `dataitem_recall` | 0/13 | 0/13 |
| C3 | `spine_depth` | 60.0% | 60.0% |
| C3 | `gt_service_system_exposure` | 21/21 = 100% | 21/21 = 100% |
| C4 | `cached_share_total` | 92.8% | 93.0% |
| C4 | `input_uncached_tokens` | 2,937,955 | 2,941,414 |
| C4 | `generated_output_tokens` | 1,095,270 | 1,090,443 |
| C4 | `capped_tokens` | 4,033,225 (+33,225) | 4,031,857 (+31,857) |

The white-jotter ground truth is 21 Services and 13 DataItems (`~/.local/share/polymerhus/vuln-groundtruth/white-jotter/_target.md` section 8); the produced 24 slugs add `register`, `sign-in` and `password-recovery` from the KB skeleton, so `service_precision` reads 21/24 = 87.5%.

### Typist economics (extended from the arm J baseline report)

| Metric | H comfyui | J comfyui | J white-jotter | J formal comfyui | J formal white-jotter |
|--------|----------:|-----------:|----------------:|------------------:|-----------------------:|
| Analysis typing window | 116 min | 13 min | 17 min | 22 min | 19.5 min |
| Typist feed chunks | 26 | 5 | 6 | 6 | 6 |
| Streamed feed paragraphs (distinct blocks) | - | 144 (5) | 30 (6) | 977 (6) | 123 (6) |
| Typist calls / capped | 304 / 2,362,165 | 59 / 533,222 | 65 / 596,663 | 70 / 522,634 | 73 / 490,094 |
| Capped per call | ~7,770 | 9,037 | 9,179 | 7,466 | 6,713 |
| Typist share of spend | 78.2% | 17.7% | 14.8% | 17.2% | 12.2% |
| Hunting window | 4 min | 23 min | 26 min | 29 min | 24 min |
| Hunting spend | 214,308 | 2,241,355 | 3,136,008 | 2,290,371 | 3,330,040 |
| Findings produced / consumed | 0 / 0 | 7 / 22 | 10 / 21 | 7 / 22 | 9 / 20 |

Windows read from per-session observation timestamps (typist first-to-last; hunting from the analysis drain to the terminal); hunting spend is the hunting orchestrator + hunter + pods from the usage pull; findings are YAML counts in the hunter store (`test-specs/<fault_key>/produced|consumed`) and reproduce the baseline exactly at 7/22.
The formal feed grows to 977 paragraphs on comfyui (144 at baseline) and 123 on white-jotter (30).
One comfyui chunk carries the katana metadata stream alone: 795 paragraphs (793 Header deltas), 140,577 characters and 300 near-duplicate paragraphs, the WS2 per-endpoint identity multiplier (11 project-global headers at baseline to 1,743).
The typist absorbs it: capped per call falls from 9,037/9,179 to 7,466/6,713 and turns per chunk stay at 11-12 across every streamed run.

### Final spec surface

| Metric | H comfyui | J comfyui | J white-jotter | J formal comfyui | J formal white-jotter |
|--------|----------:|-----------:|----------------:|------------------:|-----------------------:|
| L1 Systems | 27 | 24 | 28 | 24 | 29 |
| Systems with a description | 12 | 5 | 8 | 12 | 7 |
| Description text total (chars) | 34,960 | 10,782 | 18,042 | 16,739 | 15,809 |
| Average per described System | 2,913 | 2,156 | 2,255 | 1,395 | 2,258 |
| Systems attached to a Service | 18 | 10 | 27 | 12 | 24 |
| L1-to-L1 edges | 66 | 29 | 75 | 43 | 87 |
| Typist trailing commits (events / Systems / edges) | - | - | - | 11 / 22 / 71 | 9 / 17 / 87 |

The overwrite contract turns description breadth around on comfyui: 5 of 24 Systems described at baseline, 12 of 24 now, total text 10,782 -> 16,739 characters, longest single description 3,003 characters.
The descriptions read as verbatim evidence narratives; samples: comfyui `ReverseProxy`: "nginx/1.31.6 is the single front tier for http://t-1fc05262.target, and http:// is the ONLY scheme that answers: the slice's second BaseURL https://t-1fc05262.target is defined but does not serve - a live read of port 443 is refused immediately while the same host answers on 80 - so the origin has no TLS listener, no HTTP-to-HTTPS upgrade"; white-jotter `ReverseProxy`: "nginx/1.31.6 is the sole public HTTP server and reverse proxy in front of the Spring Boot (Java) origin, reached in cleartext on :80 (recorded transactions show connection.protocol http, tls:false to 172.17.0.1:80; re-verified live as `HTTP/1.1 200`, Content-Type text/html;charset=UTF-8, Content-Length 662 ...)".
White-jotter holds the same edge count as its commits (87) on a slightly larger L1 (29 Systems, 93 endpoints) with AUTHORIZED_BY 12, IDENTIFIED_BY 17 and FRONTED_BY 21 entering the vocabulary.

### C4 per-role (capped tokens / calls / cached share, usage pull)

| Role | J comfyui | J formal comfyui | J white-jotter | J formal white-jotter |
|------|-----------|------------------|----------------|-----------------------|
| job_orchestrator | - | - | 34,731 / 9 / 79.1% | 27,120 / 10 / 89.2% |
| triager | 115,195 / 32 / 68.5% | 108,684 / 22 / 63.7% | 135,936 / 25 / 65.0% | 87,050 / 18 / 60.9% |
| assigner | 120,512 / 18 / 71.2% | 122,344 / 17 / 69.9% | 129,887 / 20 / 71.8% | 97,553 / 15 / 66.8% |
| mechanism_typist | 533,222 / 59 / 88.9% | 522,634 / 70 / 91.3% | 596,663 / 65 / 90.2% | 490,094 / 73 / 91.3% |
| hunting_orchestrator | 496,610 / 76 / 94.9% | 275,526 / 74 / 97.4% | 542,966 / 73 / 93.9% | 675,630 / 104 / 95.0% |
| hunting_hunter | 1,023,946 / 192 / 94.2% | 1,078,356 / 216 / 93.6% | 1,749,821 / 311 / 94.5% | 1,861,289 / 364 / 93.9% |
| pod_runner | 557,093 / 229 / 90.8% | 663,859 / 282 / 91.9% | 634,255 / 250 / 92.0% | 569,405 / 229 / 91.0% |
| pod_triager | 163,706 / 14 / 67.5% | 272,630 / 18 / 44.8% | 208,966 / 16 / 58.4% | 223,716 / 24 / 51.2% |
| **Total** | **3,010,284 / 620 / 92.5%** | **3,044,033 / 699 / 93.0%** | **4,033,225 / 769 / 92.8%** | **4,031,857 / 837 / 93.0%** |

Every pull reports `cache_detail_omitted` 0, so no row is unaudited.
Three readings: the typist stays many small cache-friendly calls (88.9-91.3% cached across the four runs); the hunt dominates the spend (74.5% / 77.8% baseline and 75.2% / 82.6% formal); the 70% proposer floor is breached by the triager on all four runs (68.5% / 63.7% comfyui, 65.0% / 60.9% white-jotter) and by the formal assigners (69.9% / 66.8%), while every total clears the overall bar at 92.5-93.0%.

### C5 - L1 structure and L0 grounding

| Metric | J comfyui | J formal comfyui | J white-jotter | J formal white-jotter |
|--------|-----------|------------------|----------------|-----------------------|
| `l1_nodes_by_kind` | L1Service 23, L1System 24 | L1Service 23, L1System 24 | L1Service 24, L1System 28 | L1Service 24, L1System 29 |
| `l1_edges_by_type` | AUTHORIZED_BY 1, DEPENDS_ON 1, EXPOSED_VIA 16, FRONTED_BY 11 | AUTHENTICATED_BY 2, AUTHORIZED_BY 3, DEPENDS_ON 3, EXPOSED_VIA 18, FRONTED_BY 16, IDENTIFIED_BY 1 | AUTHENTICATED_BY 2, DEPENDS_ON 3, EXPOSED_VIA 41, IDENTIFIED_BY 6, ROUTED_BY 21, SHAPES_DATA_OF 2 | AUTHENTICATED_BY 2, AUTHORIZED_BY 12, DEPENDS_ON 3, EXPOSED_VIA 32, FRONTED_BY 21, IDENTIFIED_BY 17 |
| `l1_l0_grounded` | 14/47 = 29.8% | 14/47 = 29.8% | 18/52 = 34.6% | 17/53 = 32.1% |
| `l0_unreferenced` (Endpoints) | 214 | 268 | 28 | 42 |

The grounded node count equals the aggregating Services on every run, so the C5 cost of placement volume is direct: comfyui unreferenced endpoints rise 214 -> 268 as the chained surface enters.
comfyui widens its edge vocabulary (six types against four) and white-jotter swaps its ROUTED_BY/SHAPES_DATA_OF reads for AUTHORIZED_BY 12, FRONTED_BY 21 and a wider IDENTIFIED_BY (6 -> 17).

### C6 - proposer trajectory fidelity (arm J formal)

The assigner sessions persisted their full message IO (17 generations on comfyui, 15 on white-jotter) and the typist trajectory is read from the censuses (84 and 86 `graph_view` reads) and the per-chunk commit outputs.

| Axis | J formal (both targets) | Evidence |
|------|-------------------------|----------|
| `workflow_adherence` | pass | chunk-by-chunk dispatch after each typist pass; every session opens on the L1 block and re-reads it live (the block grows 25,757 -> 130,734 chars on comfyui and 24,984 -> 112,020 on white-jotter) |
| `tool_call_completeness` | pass | `search_http_history` on every candidate turn and `get_http_artifact` per named artifact (42 + 6 on comfyui, 14 + 8 on white-jotter); zero `graph_view` calls, per the WS4 ruling |
| `interface_adherence` | pass with recoverables | assigner calls are read-only and correctly shaped; the recoverables sit with the hunting orchestrator (4 `notes` argument validations on comfyui, 1 on white-jotter, and 1 `query_lightrag` validation; 2 white-jotter write-shaped `graph_view` refusals self-corrected); one assigner chain error per run (19:59:06, 20:53:53) recovered inside its chunk |
| `reasoning_coherence` | pass | every chunk reports `admitted -> proposed -> kept` with a reason set; `proposed` equals `kept` and `unresolvable`/`out_of_inventory` stay 0; the proposal rate falls (comfyui 72/153 = 47.1% against 81/107 = 75.7%; white-jotter 51/77 = 66.2% against 31/40 = 77.5%) |
| `tool_output_fidelity` | pass | the sampled turns read error and empty results as evidence gaps, with no mechanism invented from a tool response; the comfyui baseline's four tool-argument parse incidents have no counterpart |

The typist closes every turn with `L1DeltaBatch` commits (11 events / 22 Systems / 71 edges on comfyui, 9 / 17 / 87 on white-jotter), and the error census tags no typist session; the flagged rows are the provider 404s and the recoverables above.

### Verdict for arm J

- **Every workstream verifies in the formal data.** WS1 chains `/api` into the graph (52/38 paths against 4/2) with zero foreign origins; WS2 replaces 11/9 project-global headers with 1,743/329 endpoint-scoped ones (`date` gone, zero duplicates); WS3 streams the extensionless routes and withholds every `.js`/`.mjs` delta (none streamed against 189/16 in the graph); WS4 posts the L1 block live in all 32 assigner dispatches with zero `graph_view` calls and zero drops.
- **The surface and the spec deepen while the cost holds.** comfyui endpoints 290 -> 335 and white-jotter 57 -> 93; comfyui descriptions 5 -> 12; C4 reads 93.0% cached on both formal runs with `cache_detail_omitted` 0; the typist stays a small-call shape (70/73 calls at 7,466/6,713 capped per call) on a feed ~7x / ~4x the baseline paragraphs.
- **comfyui placement regresses; white-jotter holds it above the line.** comfyui `endpoint_placement` 26.2% -> 20.0% (67 aggregates against 76 over 335 endpoints) with GT aggregation flat at 71.4%; white-jotter 50.9% -> 54.8% (29 -> 51) with GT aggregation 85.7% -> 81.0%. The C1 bar (28.3%) reads unmet on both targets.
- **The hunting outputs hold.** comfyui produced/consumed 7/22 with the baseline's exact status split (1 dropped / 6 hypothesised / 22 specified); white-jotter 9/20 against 10/21 (6 dropped / 3 hypothesised / 20 specified).
- **The run's reliability story is external and recoverable.** The hunts absorbed 77 provider 404s on `chat/completions` through retries; 5 (comfyui) and 3 (white-jotter) tool-argument recoverables self-corrected; zero `merge failed` and zero parse incidents in either window.

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
| comfyui | F | endpoint-first prefix + MCP seam fix, config 0.2 | 11.0% | 11 | 30.4% (partial loop) | 14/14 | 0/8 | 88.2% | 2,071,438 | 551,217 | 2,622,655 | 12/46 = 26.1% | partial (assigner pass) | 2026-10-13 |
| comfyui | G | streamed + adjacent-surface assigner, no out-of-chunk gate, config 0.2, 3M cap, v4.1-flash | 25.9% | 23 | 16.0% (budget stop) | 14/14 | 0/8 | 30.2% (unaudited) | 2,972,981 | 262,894 | 3,235,875 | 2/50 = 4.0% | structural (coherence fail) | 2026-10-14 |
| comfyui | H | streamed + L0 noise gate + HTTP-history assigner + streamed-usage fix, config 0.2, 3M cap, v4.1-flash | 26.9% | 9 | 40.7% (analysis drained; hunting stopped on spend) | 14/14 | 0/8 | 90.0% (measured, 0 omissions) | 2,151,348 | 867,442 | 3,018,790 (+18,790) | 14/50 = 28.0% | partial (assigner pass; seam errors; one quirk) | 2026-10-15 |
| comfyui | J | streamed corrected (T1-T3, E5 header canonicalization), config 0.2, 3M cap, v4.1-flash | 26.2% | 9 | 41.7% (analysis drained; hunting stopped on spend) | 14/14 | 0/8 | 92.5% (measured, 0 omissions) | 2,187,976 | 822,308 | 3,010,284 (+10,284) | 14/47 = 29.8% | partial (4 tool-arg parse incidents) | 2026-10-15 |
| comfyui | J formal | J + WS1-WS4 (baseurl chaining, endpoint-scoped headers, recall-biased gate, assigner L1 block), 3M cap, v4.1-flash | 20.0% | 9 | 50.0% (analysis drained; hunting stopped on spend) | 14/14 | 0/8 | 93.0% (measured, 0 omissions) | 2,090,533 | 953,500 | 3,044,033 (+44,033) | 14/47 = 29.8% | pass (assigner + typist; 5 recoverable tool-arg validations) | 2026-10-16 |
| white-jotter | J | streamed corrected (T1-T3, E5 header canonicalization), config 0.2, 4M cap, v4.1-flash | 50.9% | 6 | 85.7% (analysis drained; hunting stopped on spend) | 21/21 | 0/13 | 92.8% (measured, 0 omissions) | 2,937,955 | 1,095,270 | 4,033,225 (+33,225) | 18/52 = 34.6% | pass (zero flagged incidents) | 2026-10-15 |
| white-jotter | J formal | J + WS1-WS4 (baseurl chaining, endpoint-scoped headers, recall-biased gate, assigner L1 block), 4M cap, v4.1-flash | 54.8% | 7 | 82.8% (analysis drained; hunting stopped on spend) | 21/21 | 0/13 | 93.0% (measured, 0 omissions) | 2,941,414 | 1,090,443 | 4,031,857 (+31,857) | 17/53 = 32.1% | pass (1 validation + 2 read-only refusals, recovered) | 2026-10-16 |

The C5 and C6 columns are `-` for arms A, B, and C: the criteria were defined after those runs, and the caveat is that they are forward-only (see Statistical Methodology).

Arm C's C4 columns are the analysis roles only (`triager` + `assigner` + `mechanism_typist`); arms A and B reported whole-project totals.
The arm C whole-project totals, including its long hunting arm, are `cached_share_total` 38.2%, 157,174,825 uncached input, 3,552,535 generated output, 160,727,360 capped.
The arms are therefore not cache-comparable without this note; see the C4 section.
Arm G's C4 cells are unaudited for the same reason: its 0% typist reading is a gateway artifact, not a provider miss (corrected 2026-10-15).
The four arm J rows' C4 cells come from the durable usage pull (`GET /projects/{pid}/usage`); the `trial.yaml` agent sums at the stop read 3,009,705 (J comfyui), 3,042,118 (J formal comfyui), 4,029,445 (J white-jotter) and 4,003,908 (J formal white-jotter), and late calls add +579 / +1,915 / +3,780 / +27,949 capped; `cache_detail_omitted` is 0 on every pull.

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

9. **The endpoint-first prefix trades placement for cost.**
   Arm F places 11.0% of endpoints against arm D's 24.1% and covers 9 of 14 ground-truth Services against arm D's 14, in the completed assign pass, while its capped tokens fall to 57% of arm D's. Feeding the surface into the first human message buys a stable cache prefix but appears to prime the harvest away from tool-driven discovery.

10. **The http-history MCP fix holds under a full assign pass.**
   All 23 Services were judged and the loop ran without the O(flows x attributes) stall, so the semi-join rewrite (85s and 152s reduced to 0.03s and 0.006s on the live store) removed the hang that blocked the previous run.

11. **A graceful `POST /execution/stop` does not settle a mid-pass analysis.**
   The project-execution stop blocked for over 15 minutes while the per-Service loop sat inside one unit, and never returned; the run only stopped on a container restart (`interrupted`). This is a stop-path defect worth a ticket.

12. **Removing a gate removes friction, not just scope.**
    Arm G dropped the out-of-chunk write gate and recovered volume (placement 25.9%, zero unresolvable) but collapsed discrimination (74/75 edges to one non-GT owner, bar never fired in 11 chunks). A gate that looks like a scope bug may be load-bearing friction; its removal needs a counterweight (calibration, competition, per-owner caps), tested one change at a time.
13. **Cost has a per-role shape, and the mean hides it.**
    Arm G's 30.2% cache share is the typist's recorded 0%-cached 2.67M alone (unaudited - a gateway artifact, corrected 2026-10-15); the assigner ran at 76.7% cached. A hygiene bar on the mean misdirects the fix - the per-role floor names the anomaly, and here it named one whose number was wrong.
14. **A gate must gate the feed's noise forms, not one asset type.**
    Arm H's L0 gate removed the katana static-bundle Endpoints but left the metadata deltas (headers, technologies, per-transaction BaseURL baskets) streaming; 10 of its 12 chunks bought a typist turn while the assigner starved, and the pass wrote 1 aggregate. Noise gated for one role is still noise for the other.
15. **A measured axis changes the verdict.**
    With the gateway continuity fix, arm H reads 90.0% cached over 420 calls with zero omissions and a legible budget stop - the first readable C4 in the streamed line. Arm G's 30.2% had been silence read as a miss, and its budget stop fired early on that inflation.
16. **Candidate generation is path-noun-driven, and payload-class rivals escape the differential.**
    Arm H's assigner declined 193 of 298 admitted endpoints, yet one payload's route identities split across two Services (`/experiment/models` -> `model-inventory`; `/folder_paths` -> `server-diagnostics`) because no path noun pulled the rival whose contract names the payload class. Relaxing this is a separate, risk-accounted change (next iteration).

### Surprising Findings

- The streamed (older) pipeline is the better-connected one; both analysis-unit-first redesigns (B and C) regressed connectivity.
- The v2 enrichment fixed the System axis but starved the Service axis, so it lost C1 while winning C2 against arm B.
- Both arms orphan the same 8 Services, so the orphan rate is a bootstrap property, not a pipeline property; arm C raises it to 13. DataItem recall is 0 in all three arms: the data plane failure is shared, not a differentiator.

### What We Still Don't Know

- Whether a per-Service assign pass without the strict `existing_slugs` write filter closes the connectivity gap.
- Whether a Service slice that unions data assets with endpoints grounds the DataItem layer (the data-modeller never ran in either arm B or arm C).
- Whether the connectivity regression holds on other targets, or whether comfyui is an outlier.
- Whether arm F's placement regression is caused by the endpoint-first prefix or by the `deepseek-v4-flash` model change (the run bundles both).
- Whether a full arm F loop (unstopped) would ground the DataItem layer and lift `system_anchoring_coverage` to arm D's completed-loop level.
- Whether arm G's adjacent-surface phase recovers the httpx:0-style correct edges (the D-A hypothesis) - answered: it recovers volume but collapses discrimination (74/75 to `editor-shell`, GT 1/14).
- Whether the collapse is calibration (uniformly high confidences), an over-broad `editor-shell` contract (skeleton property), or deduction-to-one primed by the L1-dump target - per-proposal confidences are unrecoverable (empty trace outputs), so the mechanism is open; the bar-raise experiment separates calibration from the rest.

---

## Recommendation

### Decision: Keep the incumbent streamed pipeline (arm A); iterate the analysis-unit-first design before any further target

**Rationale:**

Arm A (streamed L0-batch-first) remains the best-connected and cheapest arm and is the best latest version: it wins C1 (all four), C2 (all three) and C4 (all five), and ties C3 breadth and depth.
Arm B (batched v1) loses C1 and C2 and wins only C4.
Arm C (enriched v2) also loses C1 and C4 and wins only C2 against arm B.
Arm D (the W-a..W-d surface-integrity fixes) recovers most of the placement (`endpoint_placement` 24.1%, `gt_service_aggregation` 100%) and arm E's compaction tuning regresses it again.
Arm F (endpoint-first prefix + MCP seam fix) is the cheapest and best-cached run of the six and fixes the MCP hang, but its `endpoint_placement` (11.0%) and `gt_service_aggregation` (64.3%) regress against arm D in the completed assign pass.
Arm G (adjacent-surface assigner, no out-of-chunk gate) recovers placement volume (25.9%) but collapses discrimination (74/75 edges to non-GT `editor-shell`, GT aggregation 7.1%); its apparent cache-bar break (typist 0%, 30.2% total) is a gateway measurement artifact, not a cache failure (corrected 2026-10-15).
Arm H (streamed + L0 noise gate + HTTP-history assigner + streamed-usage fix) is the first post-split arm to pair volume with discrimination (`endpoint_placement` 26.9%, `gt_service_aggregation` 71.4%, 193/298 admitted endpoints declined, zero `unresolvable`) and clears the C4 bar on a correct measurement (90.0%, zero omissions); its open defects are feed cohesion, the MCP session lifecycle and one differential quirk, all scoped to the next iteration rather than a redesign.
Neither analysis-unit-first formulation beats the incumbent on the criteria that orient a hunting agent, so neither should proceed to further targets as-is.

### If Iterating (precondition for re-testing)

- **What to change:**
  - Do not adopt the endpoint-first prefix as-is: it bought cost and cache but cost `endpoint_placement` (24.1% -> 11.0%) and `gt_service_aggregation` (100% -> 64.3%) against arm D. Re-test it in isolation against arm D's config to separate the prefix from the model change (`deepseek-v4-flash`).
  - Keep the http-history MCP seam fix (`6596a5f`): with it the assign pass completes all 23 Services and the loop never stalls.
  - Keep arm D's global `0.2` compaction config and arm D's assignment shaping; both are the placement-best settings measured so far.
  - Fix the graceful-stop path: `POST /execution/stop` blocks past its bound when the per-Service loop is inside a unit.
- **Next experiment:** re-run comfyui on arm D's config with ONLY the MCP seam fix (no endpoint-first prefix), and require `endpoint_placement` at or above 24.1% with capped tokens at or below arm D's 4,583,885.
- **Timeline:** one worktree, TDD, then re-run on the eval server.

---

## Next Steps

| Action | Owner | Due |
|--------|-------|-----|
| Write the connectivity fix as a design change (assign pass and slice builder) | implementing agent | next change |
| Land the `hunting-at-analysis-finish` ordering fix | implementing agent | next change |
| Gate the non-Endpoint feed forms (Domain/IP/Port/Service) at queue time and rebuild chunks as endpoint-anchored families | implementing agent | next change |
| Move the MCP session lifecycle to unit completion (close on unit done, fresh session per chunk) | implementing agent | next change |
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
- Arm F's terminal is `interrupted`, not `stopped`: the graceful `POST /projects/{id}/execution/stop` blocked for over 15 minutes while the per-Service loop sat inside a unit and never returned, so the run was stopped by restarting the agent container and the startup reconcile wrote `interrupted`.
- Arm F is a partial run: the assign pass completed all 23 Services, but the per-Service loop was stopped after a few units, so the C2 and C5 System metrics are partial (as in arms D and E).
- Arm F's `stack_fingerprint` was not captured (no orchestrator `trial.yaml`); only the `eval_sha` is recorded.
- Arm F bundles two changes (the endpoint-first prefix and the MCP seam fix) with a model change (`deepseek-v4-flash`); the run does not separate the prefix effect from the model effect.
- Arm F's agent log is post-restart, so its C6 warning counts undercount the run; the C6 reading is taken from the Langfuse trace instead.
- Arm F's `data_modeller` ran (16 calls) but the loop was stopped before the DataItem layer could be written, so `dataitem_recall` is 0/8 as in every other arm.
- Arm G ended at its 3M token budget (3,235,875 capped / 198 calls, overshoot 235,875) with no `trial.yaml` (the orchestrator timed out without writing one - the arm F precedent); graph + ledger + log are the sources. Its first attempt the same day ended early on provider quota exhaustion (`quota_exhausted=true`, 0 calls) and was superseded by the re-run; the attempt's record (`...-185850-1fc05262`) stays on disk for provenance.
- Arm H wrote `trial.yaml` again (first completed record since arm C): `recon: complete`, `analysis: drained`, `hunting: stopped`, spend 3,017,307 (+17,307) at the wall-budget stop. Its `usage` field is null, so C4 is read from the usage pull (3,018,790; two late orchestrator calls add 1,483 over the stop figure).
- Arm H's `gt_service_system_exposure` follows arm F's source-side reading (the ground-truth Service carries the System edge); the staged measure script's target-side query reads 0 on this schema and is an inverted-direction artifact.
- Arm H's katana pass streamed ~1.2k metadata deltas against 2 admissible Endpoints; 10 of its 12 chunks spent a typist turn with nothing for the assigner, and the pass wrote 1 aggregate in total.
- Arm H's kali MCP sessions failed on freshly opened sessions for most of the run (`ClosedResourceError` in 14/14 assigner turns; the kali server log shows `DELETE /mcp` then `POST /mcp` 404).
- `/experiment/models` (arm H) returns the folder-path map (live probe, 15 Oct 2026); `model-inventory` and `server-diagnostics` both carry contract text that can claim it, and the nouns-only differential never reconciled the payload's other route identity (`/folder_paths`). Scoped for the next iteration.
- Arm J's C4 cells for all four rows come from the durable usage pull (`cache_detail_omitted` 0 on every pull); the `trial.yaml` agent sums at the stop differ by +579 (J comfyui), +1,915 (J formal comfyui), +3,780 (J white-jotter) and +27,949 (J formal white-jotter) capped.
- The formal hunts absorbed 77 provider `404` responses on `chat/completions` (36 comfyui, 41 white-jotter), spread 1-6 per minute through each hunting phase; every call was retried, and both runs closed with zero `merge failed` and zero parse incidents. Provider flakiness, flagged for a provider-side note.
- The hunting orchestrators emitted 4 (comfyui) + 1 (white-jotter) `notes` calls missing the `cmd` argument and 1 `query_lightrag` call missing `scenario_id`; each was refused by argument validation and retried. The `notes` tool's argument contract is the weak spot to tighten.
- White-jotter's hunting orchestrator twice ran write-shaped `graph_view` cypher and the read-only guard refused both calls (21:01:00 and 21:01:04); it self-corrected.
- comfyui `endpoint_placement` fell 26.2% -> 20.0% while `endpoints_total` rose 290 -> 335: the WS1 chaining brings 52 `/api/*` paths into the graph (baseline 4) and the assigner keeps 67 aggregates against the baseline's 76. No target meets the C1 bar (28.3%).
- `steel_crawl` streams 2 admitted endpoints with 0 kept on each formal target; its cloud-crawl contribution stays disregarded (the F8 diagnosis), and the pass is a candidate for the next gate ruling.
- The triager's cached share (68.5% / 63.7% comfyui, 65.0% / 60.9% white-jotter) and the formal assigners' (69.9% / 66.8%) sit under the 70% proposer floor while every C4 total clears the bar at 92.5-93.0%; the figures are measured with zero omissions, so this is a small-prefix shape, not the arm G silence artifact.
- Pre-existing (found during the arm G merge verification, unrelated to any arm): `tests/test_llm_checkpoints_module.py::test_the_module_scoped_saver_carries_the_serde_allowlist` fails on the installed langgraph (`JsonPlusSerializer(allowed_msgpack_modules=())` yields `serde._allowed_msgpack_modules is None`). It fails identically on the pre-merge trunk, so it is environment/version drift, not a regression; recorded here so a future red suite is not misread.

---

*Results documented on 2026-10-11. Decision to kill the current batched formulation recorded with the document.*
*Arm F appended on 2026-10-13: the MCP seam fix holds, the endpoint-first prefix trades placement for cost, and the graceful project-execution stop does not settle a mid-pass analysis.*
*Arm G appended on 2026-10-14: the adjacent-surface assigner recovers placement volume (25.9%, zero unresolvable) but collapses discrimination (74/75 edges to non-GT `editor-shell`, GT 1/14) - the dropped gate was load-bearing friction; the typist's recorded 0%-cached 2.67M appeared to break the cache bar on its own - CORRECTED 2026-10-15: that reading is a gateway artifact (the same bytes replay at 95.9-100% cached), so the break is unaudited. First G attempt (quota exhaustion) superseded by the re-run.*
*Arm H appended on 2026-10-15: the L0 noise gate + HTTP-history assigner + streamed-usage fix pair volume with discrimination (placement 26.9%, GT aggregation 71.4%, 193/298 declined, zero unresolvable) and C4 reads 90.0% with zero omissions - the first clean crossing. Open defects: feed cohesion on the katana metadata deltas, the kali MCP session lifecycle, and the path-noun-driven candidate generation at `/experiment/models`.*
*Arm J appended on 2026-10-16: the WS1-WS4 corrections land and verify (52/38 `/api` chained paths against 4/2, 1,743/329 endpoint-scoped headers against 11/9 with `date` dropped, every `.js`/`.mjs` feed delta withheld, the assigner reading the L1 block live with zero `graph_view` calls) and the cost holds (93.0% cached on both, typist 7,466/6,713 capped per call); comfyui placement regresses 26.2% -> 20.0% as the `/api` namespace enters the graph while white-jotter holds 54.8%; both hunts absorbed provider 404s with zero pipeline impact. Open defects: the triager/assigner cache-prefix shape, the `steel_crawl` 0-kept pass, and the `notes` argument contract.*
