# Plan: the streamed-pipeline failure-mode diagnoses after arm J

**Date:** 2026-10-16.
**Trigger:** operator feedback on the arm J trials, six items, "mostly bug diagnosing tasks, followed by fix proposals to the upstream root causes" (`diagnosing-bugs` discipline).
**Arm J build pin:** both arm J trials ran on `6d3897e1` (`eval_sha` in both `trial.yaml` files; the instance reflog shows the move at 21:57:12Z, the comfyui trial starting 21:59:57Z).
That build already contains every streamed-pipeline correction: T1 connectivity drop (`006ffd8`), T2 MCP session lifecycle (`2651e7d`), T3 noise-gate extension + stream dedup + topology-cohesive families (`778fd10`), E5 header canonicalization (`15888fa`).
The operator's guess that comfyui "ran before the recently added noise and chunk collapse gate" is DISPROVEN by the `eval_sha`; the 5-chunk typist economy IS the collapsed (family) chunking.
**Discipline:** each numbered task below follows the `diagnosing-bugs` loop (tight observable first, then hypotheses with verdicts). The plan is fixed; deviations get recorded here in the Progress log.

## Task order (strict)

### F1 - ComfyUI endpoint-crawl root cause (operator item 1, part 1)
- **Question:** why is comfyui's collected surface so thin when the target is a CSR SPA whose client JS should be rich in endpoint literals? Where does the loss happen: not discovered (katana/webpack/jsluice never saw it), discovered but dropped (curator/malformed-path gate), or curated but not streamed (noise gate / families)?
- **Sub-questions:** the fate of `.json`/other non-`.js` endpoint assets (e.g. `/api/*`, `/system_stats`, `/object_info`); whether relative literals exist in the graph at all; whether the discovered `.json` endpoints carry response content anywhere reachable by analysis (`http_history`).
- **Loop:** the L0 Endpoint inventory of project `2df3ad9d` (Neo4j, by `source` and `content_type`/`profile`) vs the endpoint set actually witnessed in the recon run's own tool traffic (kali `history.sqlite3` flows) vs what jsluice/webpack_chunks/katana job outputs hold.
- **Deliverable:** diagnosis section in `docs/experiments/streamed-endpoint-coverage-diagnosis.md`.

### F2 - Streamed-asset underspecification (operator item 1, part 2)
- **Question:** what exactly is saved in the graph and streamed to analysis for a node like `Header {name: 'content-type', baseurl: ...}` that carries no value? Which assets lose decisive props on the way from graph to feed (Header, Technology, Parameter, Endpoint)?
- **Loop:** for one comfyui chunk, compare the Neo4j node props against the exact `STREAMED SURFACE` paragraph rendered into the typist's first HumanMessage.
- **Deliverable:** diagnosis + fix direction in the same F1 doc.

### F3 - Streamed-chunk inventory and Langfuse report (operator item 1, part 3)
- **Question:** enumerate ALL chunks streamed in both arm J trials (comfyui `2df3ad9d`, white-jotter `bf0d9408`) with per-chunk asset-type counts, the observations carried, and a Langfuse URL to the trace whose first HumanMessage holds the chunk content.
- **Loop:** Langfuse API pull per project window; group by the first occurrence of each distinct `STREAMED SURFACE` block; link trace ids for analysis + mechanism-typist roles.
- **Deliverable:** `docs/experiments/streamed-chunks-inventory-arm-j.md` (tables per project, exact Langfuse URLs, asset-type breakdowns).

### F4 - baseURL x relative-path chaining (operator item 2)
- **Question:** is there a component that joins a discovered base URL (e.g. white-jotter's axios `defaults.baseURL="/api"`) with the relative endpoint literals collected from bundles/chunks? The operator notes a chaining step "should already be stacked after katana, jsluice and other phases producing endpoints".
- **Known starting point:** the #185 ADR (`docs/design/recon-webpack-chunk-map-185-adr.md` §"baseURL-awareness: deferred") recorded this as deferred; the recon CONTEXT.md carries the same deferral on "Webpack chunk map".
- **Loop:** take one real relative literal from a scanned chunk, run it through the jsluice parser path, and observe the minted URL versus the correct `baseURL + literal` form. Navigate the module in `src/polymerhus/recon/`.
- **Deliverable:** diagnosis + the chaining implementation with tests (new worktree if the change is substantial), recorded in the doc.

### F5 - Typist expression structural root cause (operator item 3)
- **Question:** why do the J trials' System specifications stay below arm H's despite (per-chunk) comparable quality? Operator hypotheses: more chunks/assets -> more turns -> more expressive power; and that longer reasoning chains are more prolific. Find the structural root cause.
- **Loop:** per-chunk typist economics and per-chunk System description volumes for H comfyui vs J comfyui vs J wj; the typist's turn structure per chunk (reflection -> extraction -> linking) and its input assets per chunk.
- **Deliverable:** `docs/experiments/typist-expression-diagnosis.md` with the fix direction (symbolic-layer reasoning prompts per System kind, e.g. per-service-type question sets).

### F6 - T5 D1-D3 re-surface (operator item 4)
- **Question:** surface the three pending decisions from `docs/design/plans/2026-10-15-T5-class-first-candidate-pull.md`.
- **Deliverable:** restated decisions in the final message (no code).

### F7 - Assigner concretisation quality, two-trial comparison (operator item 5)
- **Question:** from the two arm J trials, what do the assignment deltas (outcome) and the assigner's execution workflow (workflow) reveal about the current lack of concretisation quality? Is the root cause in a contained recon (thin/ambiguous slice) or in the analysis workflow, or both?
- **Loop:** per-chunk assigner generations for comfyui vs wj: counts of aggregates, null-owner decisions, `search_http_history` tool usage, drop counts; plus the L1 Service inventory each chunk was judged against.
- **Deliverable:** `docs/experiments/assigner-concretisation-diagnosis.md`.

### F8 - Steel crawl contribution (operator item 6)
- **Question:** record that the steel.dev cloud crawl cannot reach local-network-only target domains, so its crawling contribution is disregarded for now; moving it local is out of scope.
- **Deliverable:** recorded here and in the final report; the next arm's launcher/report must not count steel-crawl endpoints.

### F9 - Consolidation
- Consolidated diagnosis summary + the fix-proposal list (file-ready), delivered in chat and appended to the relevant docs.

## Progress log

- 2026-10-16: plan written; build pin confirmed (`eval_sha 6d3897e1` in both arm J trial records).
