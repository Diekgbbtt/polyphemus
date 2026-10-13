---
artifact: experiment-results
version: "1.0"
created: 2026-10-11
status: draft
---

# Experiment Results: streams-analysis L0-batch-first pipeline - comfyui

## Summary

| Attribute | Value |
|-----------|-------|
| **Experiment ID** | `streams-analysisL0batchFirst` |
| **Experiment Name** | Constant-shape, per-batch proposer turns with per-agent compaction |
| **Target** | WebExploitBench `comfyui` (ComfyUI core v0.3.76 + ComfyUI-Manager V3.37), 6 vulnerabilities |
| **Status** | Completed - treatment shipped to `dev`, goal only partly met |
| **Duration** | Single trial, 2026-10-10 20:08Z to terminal |
| **Traffic Allocation** | Single-arm (no control); compared against the prior `#348` run (baseline) |
| **Sample Size** | 1 trial, 319 LLM calls, 6 analysis/hunting agents |
| **Owner** | Operator + implementing agent |
| **Design Doc** | `docs/design/proposer-per-batch-cache-adr.md`; plan `docs/design/plans/2026-10-10-proposer-cache-experiment.md` |
| **Code** | `dev` at `93d213e` (merge of `exp/proposer-cache`, commit `c42f3e9`) |

---

## Hypothesis Recap

**Original Hypothesis:**

> We believed that the analysis proposers' low prompt-cache hit rate was caused by an unstable provider request prefix, not by compaction or a shifting message anchor, because the per-chunk turn schedule toggles the bound tool: the reflection turn binds no tool while the extraction turn binds `L1DeltaBatch`.
> We further believed that reusing one run-long session let the re-injected surface and the accumulated trail grow the context without bound.
> We believed that binding a constant tool shape, resetting context per batch, and compacting per agent would raise the cached-input share and lower total uncached input.

**Success Criteria:**

- Primary metric: cache-hit rate (`cached / (cached + uncached)`) rises for **every** proposer.
- Hard bar: `data_modeller`, the worst offender at 0%, rises materially.
- Guardrail: total capped tokens stay within the per-target budget (`4,000,000`).
- Guardrail: no regression in the produced L1 surface well-formedness.

---

## Results

### Primary Metric: cache-hit rate per agent (treatment vs baseline)

Baseline is the prior `#348` comfyui run; treatment is this run at `93d213e`.

| Agent | Baseline hit | Treatment hit | Cached | Uncached | Capped | Calls |
|-------|-------------:|--------------:|-------:|---------:|-------:|------:|
| hunting_orchestrator | n/a | 73.3% | 6,217,088 | 2,265,896 | 2,336,449 | 81 |
| mechanism_typist | ~30% | 68.1% | 2,495,744 | 1,167,024 | 1,506,986 | 78 |
| hunting_hunter | n/a | 76.0% | 1,630,080 | 515,976 | 554,819 | 66 |
| **data_modeller** | **0%** | **18.0%** | 71,296 | 324,886 | 371,445 | 45 |
| triager | n/a | 4.8% | 9,600 | 189,060 | 197,065 | 28 |
| assigner | ~? | 75.2% | 90,368 | 29,799 | 69,482 | 21 |
| **Total** | - | - | 10,514,176 | 4,492,641 | **5,036,246** | 319 |

**Interpretation:**

The treatment is a clear net improvement: `mechanism_typist` more than doubled (about 30% to 68%), and the `assigner` reached 75%.
`data_modeller` moved off zero to 18%, but this misses the hard bar, so the primary success criterion is only partly met.
The residual defect is understood: the prose turn binds a hand-built `StructuredTool`, while the structured turn binds the actual `ToolStrategy` tool, so the two are not byte-identical and the request prefix still toggles.
`data_modeller` runs strictly `P,S` per chunk, so it never has two consecutive calls with the same tool set and therefore never matches a prefix.
`mechanism_typist` runs `P,S,S`, so its `S,S` pair matches and it caches despite the same P-to-S transition.

### Guardrail: token budget

| Metric | Value | Threshold | Status |
|--------|------:|-----------|--------|
| Total capped tokens | 5,036,246 | <= 4,000,000 | **FAIL** (125.9%) |
| Total LLM calls | 319 | not bounded | - |
| Cached input share (all) | 70.6% | no degradation | PASS |
| Generated output (all) | 547,505 | - | - |

The run overshot the per-target budget by about 1.04M tokens (25.9%).
The budget cannot shrink while `data_modeller` and the recon `triager` still re-inject large uncached prefixes.

### L0 batches streamed from recon that traversed the pipeline

Recon streams its L0 surface to analysis as per-job immutable batches of at most 100 assets (`analysis/chunking.py:CHUNK_MAX_ASSETS = 100`).
Each batch is expanded to one dispatch per chunk-fed role (`assigner`, `mechanism_typist`, `data_modeller`), so the batch count multiplies by three.

Source: the analysis supervisor's `analyser chunked` line and the per-role `chunk=` census lines in `ph-dd131acc-agent-1`.

| Metric | Value |
|--------|------:|
| Largest single supervisor pass (recon to analysis) | 13 batches / 1,240 L0 assets / 39 dispatched / 39 entered |
| Second large pass | 9 batches / 987 L0 assets / 27 dispatched / 27 entered |
| Small single-batch passes | 1 batch each (1, 13, 13, 22, 2 L0 assets) |
| Distinct chunk ids the `assigner` processed | 38 |
| of which recon batches | 37 (`katana` 24, `jsluice` 9, `arjun` 1, `ffuf` 1, `httpx` 1, `steel_crawl` 1) |
| of which non-recon (global aggregation pass) | 1 (`global:<run_id>`) |
| Distinct chunk ids the `data_modeller` processed | 33 (its admitted `Parameter`/`Header`/`Secret` subset, plus the `__residual__` unit) |
| Distinct chunk ids the `mechanism_typist` logged | 0 (the generalist holds the `ADMIT_ALL` sentinel and is not keyed by chunk in this log view) |

**Reading:** the recon L0 stream arrived as **37 recon batches** (plus one global aggregation pass), and every batch was fanned out to the three chunk-fed roles.
`katana` dominates the batch count (24 of 37), which is the crawl surface, while the vulnerability-relevant data assets (24 of them) were spread thin: the `data_modeller` admitted assets from only 32 recon batches and produced a single surviving `L1DataItem`.
The batch grain is the reason the fixed 100-asset ceiling matters: `data_modeller` sees a batch only when it carries `Parameter`/`Header`/`Secret`, so most of the 37 batches yield an empty `data_modeller` batch.

*Caveat: the analyser run window (`3ef8412d`, 2026-10-11 09:44 to 17:05) is the current re-run and its counts are read from the accumulated log; sibling analysis passes for other targets may share the container log, so treat 37 as the comfyui order of magnitude.*

---

## Well-formedness Analysis

Produced graph for project `e2b53777-828c-4799-82f2-a95484feb052` at snapshot (396 nodes, 430 edges).

### Node inventory

| Layer | Label | Count |
|-------|-------|------:|
| L0 | Endpoint | 290 |
| L0 | Header | 16 |
| L0 | Observation | 14 |
| L0 | Port | 6 |
| L0 | Service | 6 |
| L0 | Parameter | 4 |
| L0 | Secret | 4 |
| L0 | BaseURL | 2 |
| L0 | Domain | 1 |
| L0 | IP | 1 |
| L0 | Technology | 1 |
| L1 | L1Service | 25 |
| L1 | L1System | 26 |
| L1 | L1DataItem | 1 |

### Edge inventory

| Layer | Relationship | Count |
|-------|--------------|------:|
| L0 | HAS_ENDPOINT | 290 |
| L0 | HAS_HEADER | 16 |
| L0 | HAS_OBSERVATION | 14 |
| L0 | HAS_PORT | 6 |
| L0 | RUNS_SERVICE | 6 |
| L0 | HAS_SECRET | 4 |
| L0 | HAS_PARAMETER | 4 |
| L0 | USES_TECHNOLOGY | 1 |
| L0 | BELONGS_TO | 1 |
| L0 | DEPENDS_ON | 1 |
| L1 | AGGREGATES | 41 |
| L1 | EXPOSED_VIA | 28 |
| L1 | FRONTED_BY | 14 |
| L1 | ROUTED_BY | 1 |
| L1 to L0 | SURFACES_AT | 2 |
| L1 | CONSUMES | 1 |

### Well-formedness verdict

**Vocabulary conformance: good.**
Every label and relationship is drawn from the fixed L0 and L1 vocabularies (`HAS_ENDPOINT`, `AGGREGATES`, `EXPOSED_VIA`, `SURFACES_AT`, `CONSUMES`).
No out-of-vocabulary or malformed edge appears.

**Structural integrity: partly good.**
The L1 spine is present: services are aggregated and joined to systems over `EXPOSED_VIA`, and systems are fronted over `FRONTED_BY`.
Ratio checks: `AGGREGATES` 41 over 290 Endpoints is only 14% coverage, so about 249 Endpoints sit in an unplaced pool with no owning service.

**Data plane: near-empty.**
One `L1DataItem` (`generated_media_artifact`) with 2 `SURFACES_AT` and 1 `CONSUMES`, against 24 surfaced data assets on L0 (16 Header, 4 Parameter, 4 Secret).
The data plane is a structural singleton and does not support record-to-service navigation.

**System layer: over-fragmented.**
26 L1Systems include singleton auth systems (`IdentificationSystem`, `AuthenticationMechanism`, `AuthorizationSystem`, `ReverseProxy`) plus per-service `WebPresentation` and `RESTApi` discriminators.
Two near-duplicate presentation systems appear (`WebPresentation:workflow-editor::editor-shell` and `WebPresentation:editor-shell::workflow-editor`), which indicates a discriminator-ordering defect in authoring.

---

## Ground-Truth Comparison

Ground truth is the `comfyui` corpus at `~/.local/share/polymerhus/vuln-groundtruth/comfyui/` (6 vuln bundles + `_target.md`).

### Expected L1 services and data items (from the six `l1-profile.md` bundles)

| vuln | Service unit | CONSUMES | PRODUCES |
|------|--------------|----------|----------|
| comfyui-001 | `user-data-file` | `manager_configuration` | `user_data_file` |
| comfyui-002 | `user-data-file` | `user_data_file` | `stored_markup` |
| comfyui-003 | `image-upload` | - | `uploaded_image` |
| comfyui-004 | `image-viewing` | `viewed_file` | - |
| comfyui-005 | `manager-preferences` | `custom_node_catalog` | `channel_selection` |
| comfyui-006 | `model-download` | `model_download_request` | `remote_model_file` |

Distinct expected Service units: **5** (`user-data-file`, `image-upload`, `image-viewing`, `manager-preferences`, `model-download`).
Distinct expected DataItems: **9** (`manager_configuration`, `user_data_file`, `stored_markup`, `uploaded_image`, `viewed_file`, `custom_node_catalog`, `channel_selection`, `model_download_request`, `remote_model_file`).
Expected Systems: one `RESTApi` and one `WebPresentation` per service, discriminated (`<slug>::rest` / `<slug>::<shell>`), so about 10 to 12.

### Produced vs expected

| Dimension | Expected | Produced | Coverage | Verdict |
|-----------|---------:|---------:|---------:|---------|
| Service units (distinct) | 5 | 25 | 5/5 found, 20 extra | Over-produced |
| DataItems (distinct) | 9 | 1 | 1/9 (11%) | **Severely under-produced** |
| Systems | ~10-12 | 26 | over | Over-produced |
| Endpoints placed (`AGGREGATES` / routes) | 11 routes | 41 placed of 290 | - | Coverage thin |
| Data-plane edges (`SURFACES_AT`, `CONSUMES`) | per banking chain | 3 | - | Near-absent |

**Service recall: complete.** All 5 ground-truth services are present, including the shared `user-data-file` and the `image-upload`, `image-viewing`, `manager-preferences`, `model-download` units.
Their `WebPresentation` discriminators also match the ground-truth form (`user-data-file::userdata-shell`, `image-upload::editor-shell`, `model-download::manager-shell`), which is strong evidence the operator knowledge base is being applied.

**Service precision: poor.** 20 of 25 services are not in the ground truth for this target's vulnerability chains.
They are plausible target services (`workflow-submission`, `node-registry`, `system-status`, ...) but they are not grounded in any of the six bundles, so they add navigation noise.

**Data plane recall: the failure.** One DataItem against nine expected is an 11% recall.
The single item (`generated_media_artifact`) does not map to any expected item.
Every vulnerability chain depends on a data item (the config read, the persisted markup, the uploaded image, the viewed file), so the empty data plane means the chains are not navigable from the graph.

### Ground-truth endpoints vs produced aggregation

| vuln | Expected routes | Aggregated in graph |
|------|-----------------|---------------------|
| comfyui-001 | `GET /userdata`, `GET /userdata/comfy.settings.json` | yes (`user-data-file`) |
| comfyui-002 | `GET`, `POST /userdata/comfy.settings.json` | yes |
| comfyui-003 | `POST /upload/image`, `POST /upload/mask` | partly |
| comfyui-004 | `GET /view`, `GET /view_metadata/checkpoints` | partly |
| comfyui-005 | `GET /manager/channel_url_list`, `GET /manager/version` | partly |
| comfyui-006 | `GET /manager/queue/start`, `GET /manager/queue/status`, `POST /manager/queue/install_model` | partly |

---

## Segment Analysis

### By agent role

| Segment | Cached share | Capped tokens | Note |
|---------|-------------:|--------------:|------|
| Hunting orchestrator + hunter | 73-76% | 2.89M | Cache well; hunting is the cost centre |
| mechanism_typist | 68.1% | 1.51M | Improved from baseline; steady `P,S,S` matches |
| assigner | 75.2% | 0.07M | Small, structured-only, caches |
| **data_modeller** | **18.0%** | 0.37M | The residual defect; `P,S` only |
| triager (recon) | 4.8% | 0.20M | Not a proposer; separate recon matter |

### Segment insight

Proposer cache-hit is explained entirely by turn-shape pattern: agents with a repeated same-shape pair (`S,S` or structured-only) cache at 68-76%, and the only proposer without such a pair (`data_modeller`, strict `P,S`) stays low at 18%.
The recon `triager` is a distinct case outside this experiment's scope.

---

## Learnings

### What We Learned

1. **The prefix stability diagnosis was correct, and the fix works for agents that already had a matching pair.**
   `mechanism_typist` went from about 30% to 68% and the `assigner` to 75%, which confirms the tool-set stability matters.

2. **A hand-built placeholder tool is not enough; the tool object must be the same object the structured turn carries.**
   The prose turn's `StructuredTool` and the structured turn's `ToolStrategy` tool differ, so the prefix still toggles; `data_modeller` moved only to 18%.

3. **Turn-shape parity, not compaction, is the dominant lever.**
   `data_modeller`'s schedule is strictly `P,S` per chunk, so it never has two same-shape calls; no compaction threshold can repair a prefix that changes on every call.

4. **The generated L1 surface is structurally valid but semantically thin in exactly the data plane.**
   Services are over-produced and well-formed, but the data plane holds one item against nine expected.

5. **Cached input dominates spend, so the remaining cost is a prefix problem, not an output problem.**
   Across the run cached input was 10.51M tokens against 547K generated output.

6. **The stream is batch-shaped, so a per-call defect is multiplied across batches.**
   Recon delivered 37 L0 batches (24 of them crawl batches), and each batch is fanned out to three roles.
   A prefix that toggles inside one batch therefore repeats 37 times per role, which is why the `data_modeller` defect cost 324,886 uncached tokens.

### Surprising Findings

- The `data_modeller` fix raised the number to 18% rather than the expected large jump, revealing that the placeholder and the real tool are distinct objects.
- Service recall is complete (5/5) even though the data plane is nearly empty, so the two layers degrade independently.
- The per-target budget overshot by 25.9% because the uncached prefix reprocessing in `data_modeller` and `triager` cannot be trimmed by compaction alone.

### What We Still Don't Know

- The exact token cost of the 20 extra services (grounding and navigation noise) versus their analytical value.
- Whether the recon `triager` low hit rate shares the same prefix-instability root cause.
- Whether a per-agent `ToolStrategy`-object binding closes `data_modeller` to parity (68-76%).

---

## Recommendation

### Decision: Iterate

**Rationale:**

The experiment proved the root cause and shipped a real improvement, but it did not meet the primary success criterion for `data_modeller` (18% against a parity target of about 70%).
The remaining defect is precise and small: bind the exact `ToolStrategy` tool object on the prose turn, uniformly across every proposer.
A full run is not justified until that change lands, because the budget guardrail already failed at 125.9%.

### If Iterating

- **What to change:** in `proposer_turn._prose_tools`, extract the tool from the `ToolStrategy` produced by `structured_response_format(...)` and bind that same object; apply it to `assigner`, `mechanism_typist`, and `data_modeller` without exception.
- **Next experiment:** re-run the single `comfyui` trial and require `data_modeller` cache-hit >= 60% and total capped tokens <= 4,000,000.
- **Timeline:** one worktree, TDD, then re-run on the eval server.

---

## Next Steps

| Action | Owner | Due |
|--------|-------|-----|
| Bind the shared `ToolStrategy` tool object on all prose turns | implementing agent | next change |
| Add a regression test asserting the prose and structured turns expose an identical tool set | implementing agent | with the fix |
| Re-run the `comfyui` trial and measure hit rate + spend | operator | after the fix |
| Raise data-plane recall (9 expected items) as a tracked work item | operator | new ticket |
| Investigate the recon `triager` low cache-hit (separate root cause) | operator | new ticket |
| Tighten `WebPresentation` discriminator ordering (near-duplicate systems) | implementing agent | new ticket |
| Relocate run-2 artifacts out of peer `runs-run2/` into the canonical `runs/` layout | operator | queued |

---

## Appendix

### Raw Data

- Usage: `GET http://localhost:8080/projects/e2b53777-828c-4799-82f2-a95484feb052/usage`.
- Graph: `GET http://localhost:8080/projects/e2b53777-828c-4799-82f2-a95484feb052/graph`.
- Ground truth: `~/.local/share/polymerhus/vuln-groundtruth/comfyui/` (6 bundles, `_target.md`).

### Statistical Methodology

- Test type: single-arm descriptive comparison against the prior run's baseline (no randomisation, no p-value).
- Cache-hit rate = `cached / (cached + uncached)` per agent, from the provider usage ledger.
- Sample sizes are LLM-call counts, reported per agent in the primary table.
- No confidence intervals are claimed: the sample is one trial per arm.

### Known Issues

- The run overshot the per-target budget (125.9%), so it is not a clean budget comparison.
- The graph snapshot is mid-run; node and edge counts may still move.
- Ground-truth expected-service count is 5 distinct units but 6 bundles (001 and 002 share `user-data-file`).
- The `L1System` count read 25 via Cypher and 26 via the API in the same window, so treat it as about 25-26.

---

*Results documented on 2026-10-11. Decision to iterate recorded with the document.*
