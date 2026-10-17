# Diagnosis: the katana chunks feed the typist a per-transaction repeat of ~10 facts

**Date:** 2026-10-15.
**Trigger:** operator correction 3 of `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md` (T3): the mechanism_typist feed is noise, and chunks are not cohesive.
**Evidence base:** arm H trial `comfyui-1-20261015T143534-1fc05262` (sha `a088730d`, project `a9bb42f9-6255-4f1e-87ee-fc09e2388024`), recon+analysis 12:28Z-14:31Z.
**Method:** the `diagnosing-bugs` procedure; the loop is at "Method" below and the repro command at its end.
**Status:** confirmed; the fix lands in the same branch (commits after this doc).

## 1. Symptom

The operator reports that katana attack-surface assets reach the mechanism_typist as an undifferentiated stream.
Headers are not collapsed per endpoint, chunks are not cohesive, and the typist spends turns on material that carries no new judgment.
Measured on arm H: the katana pass built 12 chunks over 1,240 assets, wrote 12 Systems and 1 aggregate, and fed the typist up to ~145,500 characters per chunk.

## 2. The tight loop

The narrowest observable of this defect is the typist's own rendered input.
Every typist turn renders its chunk as a `STREAMED SURFACE` block of asset paragraphs, and Langfuse stores that prompt verbatim.
I extracted the 13 LangGraph groups that cover the P3 (httpx) and P4 (katana) passes (12:44:01Z-13:00:06Z), then parsed each group's asset block per paragraph: type, identity, duplicates, and the structured outputs.
The script is `analyze_typist_feed.py` (local copy `/private/var/folders/gs/p9fl4f1s1yqfl8801x50nhjc0000gn/T/opencode/lf/analyze_typist_feed.py`, server copy `/root/analyze_typist_feed.py`):

```bash
ssh eval-server-polyphemus 'python3 /root/analyze_typist_feed.py /root/lf-typist-early.json'
```

The dump holds no secrets; no redaction was needed.
The L0-side counts come from `cypher-shell` queries against the arm H instance (`q1`-`q6` under `/root` on the eval server).
A live probe of the httpx binary settled E5 (`httpx -u http://t-1fc05262.target/ -irh -json -silent` against the still-running kali container).

## 3. Evidence

### E1 - the katana delta stream repeats one small basket per crawled request

`katana_parser.parse` decomposes each JSONL line (one crawled request) into: 1 `BaseURL`, 1 `Endpoint` (+`Parameter`s), 1 `Header` per response header, and 1 `Technology` per detected tech.
Nothing dedups at the source, and the parser says so: the per-line emission is the observation record.
The arm H crawl visited ~124 requests on one host, so P4's 1,240 assets are consistent with ~124 x 10 deltas.
After identity collapse the same stream holds ONE BaseURL, 11 Headers, 1 Technology and 2 admittable Endpoints (measured in Appendix A; the first estimate was ~16 headers / ~2 endpoints).

### E2 - the chunk builder slices the stream positionally at 100

`chunks_for_job` (`src/polymerhus/analysis/chunking.py`) walks the filtered stream in order and closes a chunk at `CHUNK_MAX_ASSETS` = 100.
The builder keeps no memory of identity and no topology; one crawled transaction contributes ~10 deltas, so each 100-asset chunk is ~10 transactions of the SAME basket.
The observed feed proves it, paragraph for paragraph:

| group | start (Z) | assets | chars | types | unique identities | redundant paragraphs |
|-------|-----------|-------:|------:|-------|------------------:|---------------------:|
| 4 (katana c1) | 12:48:15 | 100 | 145,529 | BaseURL 10, Endpoint 1, Header 80, Technology 9 | 14 | 86 |
| 7 (katana c2) | 12:50:57 | 100 | 144,002 | BaseURL 10, Header 80, Technology 10 | 10 | 90 |
| 10 (katana c3) | 12:54:48 | 100 | 144,009 | BaseURL 10, Header 80, Technology 10 | 10 | 90 |
| 13 (katana c4) | 13:00:06 | 100 | 144,010 | BaseURL 10, Header 80, Technology 10 | 10 | 90 |

Top repeats in group 4: `BaseURL {'url': 'http://t-1fc05262.target'}` x10, `Header {'name': 'accept-ranges', 'baseurl': ...}` x10, `Header {'name': 'connection', ...}` x10, `Header {'name': 'content-length', ...}` x10, `Header {'name': 'content-type', ...}` x10, `Header {'name': 'date', ...}` x10.
Groups 7, 10 and 13 (the later katana chunks) carry a smaller variant of the same pattern.

### E3 - the noise gate drops the .js endpoints but not their satellites

The `is_noise_endpoint` gate withholds script/style/map bundles and whole-segment `assets/`/`static/` paths.
Katana's crawl visited almost only ComfyUI frontend bundles (`application/javascript`), so the gate withheld nearly every `Endpoint` delta of P4.
`Header`, `Technology` and `BaseURL` deltas hang off the BaseURL, not off the endpoint, so the gate cannot reach them.
Result: 10 of the 12 katana chunks reached the typist with NO Endpoint paragraph at all, and the assigner (Endpoint-only admission) had nothing to judge.

### E4 - the typist output carries the contamination

Group 5 (katana chunk 1 extraction) wrote `systems(3)`: `['__singleton__', 'core-rest', '__singleton__']`.
Group 9 and 12 wrote edges that all point at `__singleton__` (10 and 13 edges).
The pass table (`docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`) records P4 as 12 chunks, 1,240 assets, 12 Systems, 1 aggregate: one `__singleton__`-flavoured System per chunk, minted from header slurry.

### E5 - response headers fragment across tools (an amplifier, recon side)

The httpx binary's `-irh` JSON emits header keys with UNDERSCORES (`accept_ranges`, `content_type`), and katana's JSONL emits dashes (`accept-ranges`, `content-type`).
Both parsers identity the header with `name.lower()` and nothing else, so one real header becomes two L0 Header nodes.
The graph shows it: 10 underscore headers first seen by the httpx pass (12:31:44Z) and 6 dash headers first seen by the katana pass (12:32:33Z), overlapping on 5 names (`accept-ranges`, `cache-control`, `content-length`, `content-type`, `last-modified`; the other underscore names - `date`, `etag`, `expires`, `pragma`, `server` - have no dash twin in the run).
Any feed dedup on identity would still render both rows.

## 4. Hypotheses, with verdicts

| # | Hypothesis | Verdict |
|---|------------|---------|
| H1 | The chunk builder is order-positional with no identity or topology awareness; chunk composition is an artifact of array position. | CONFIRMED (E2, code + measured feeds) |
| H2 | No layer dedups identical deltas; the renderer renders whatever the stream repeats. | CONFIRMED (E2, E3) |
| H3 | The noise gate drops gated endpoints but their host-level satellites still stream, so a gated family is not fully withheld. | CONFIRMED (E3) |
| H4 | The katana parser is the root cause. | REJECTED as root cause; CONFIRMED as amplifier (E1). The per-transaction emission is recon's correct observation record. The stream layer must collapse it, not recon. |
| H5 | Header identity fragmentation across tools amplifies the noise and defeats dedup on the key. | CONFIRMED (E5) |

## 5. Root cause

The chunk builder treats the delta stream as a flat sequence of positions.
Katana's stream is a per-transaction repetition of one small identity set, so positional chunking produces 100-paragraph repeats with no topology cohesion.
Every downstream consumer then pays for repetition that carries zero information, and the assigner receives the chunks that carry no Endpoint at all.

## 6. Fix direction (the T3 change)

The fix moves into the stream layer; the parsers keep emitting observations and the chunk builder stops treating them as positions.

1. **Identity dedup in the stream.** Keep the first occurrence of each `(type, identity)`; drop later repeats. The counts stay observable in L0 and in the recon log, not in the prompt.
2. **Families over topology.** Group the deduped stream into families: a `host-meta` family per BaseURL (`BaseURL` + `Header` + `Technology` + `Certificate`), and one `endpoints` family per `(baseurl, bucket)` (`Endpoint` + its `Parameter`/`Secret` children).
3. **Endpoint sub-buckets.** Classify each Endpoint by its `content_type` into `html`, `code`, `visual`, `data`, `other`; Parameters/Secrets follow the bucket of their `endpoint_path`.
4. **Soft target, family-complete chunks.** Add whole families until the chunk count reaches ~100, then close the chunk after the family that crossed it. A large family goes whole; cohesion wins over a hard cap.
5. **Headers keep their owner.** The feed row already carries the owning `baseurl` from the header's identity. The graph links a Header to its BaseURL, never to a single endpoint, so endpoint-level attribution is NOT invented; this is a deliberate deviation from a literal reading of the operator note (see section 7).
6. **Header name canonicalization (recon, small).** Normalize response header names to lowercase-with-dashes in both parsers, so httpx and katana observations merge on one node (E5).

## 7. Deliberate deviations and open items

- **REVERSED 2026-10-16 (operator ruling).** The entry below held the Header identity at `{name, baseurl}` with baseurl-only ownership. The operator overruled it: the Header identity is now `{name, endpoint, baseurl}` (the `endpoint` being the path that returned the header, the value a prop). The `(BaseURL)-[:HAS_HEADER]->(Header)` edge is unchanged - the binding stays the source BaseURL, and no header-to-endpoint edge is invented - but two endpoints under one origin carrying a same-named header no longer merge, while a re-crawled endpoint's headers still collapse. The `date` response header is dropped entirely. The measurement in Appendix A predates this change.
- **"Headers report the owning endpoint" (the superseded position, kept as record):** the Header identity is `{name, baseurl}` and its only minted edge is `(BaseURL)-[:HAS_HEADER]->(Header)`. Endpoint-level ownership would need a parser change that invents a link recon does not observe. The fix keeps the baseurl owner visible and collapses the per-transaction repeats.
- **The exec-seam double sessions** (`recon.domain.pod.default_exec_fn`) remain a separate follow-up from T2; they show up in the same kali access log and are measured in the next trial.
- **Group sizes for the typist:** after the fix the katana pass collapses to one small cohesive chunk (15 unique assets, measured; Appendix A). If a single family ever exceeds a prompt budget, a future iteration can split a family by parent endpoint.

## Appendix A - the collapse in numbers (measured 2026-10-15)

Source: the full arm H window (12:28Z-14:32Z) pulled per trace from Langfuse (`/root/lf-blocks.json`: 5,233 observations, 444 generations, 26 distinct `STREAMED SURFACE` blocks = the run's 26 chunks).
The 12 katana blocks (first seen 12:48:26Z through 13:26:28Z) were parsed paragraph by paragraph.

PRE - what the typist actually received (P4's chunks):

| type | paragraphs streamed | distinct identities | repeats |
|------|--------------------:|--------------------:|--------:|
| BaseURL | 114 | 1 | 113 |
| Header | 905 | 11 | 894 |
| Technology | 114 | 1 | 113 |
| Endpoint | 2 | 2 | 0 |
| **total** | **1,135** | **15** | **1,120** |

- 12 chunks: 11 x 100 assets + one 35-asset tail, cut positionally at 100.
- P4 produced 1,240 deltas (the results doc); 1,135 reached the typist; the 105-delta difference is the Endpoint deltas the pre-existing noise gate withheld (the script/style bundles, E3).
- The two streamed Endpoints are `GET /` and `GET /experiment/models`; the old builder put them in the FIRST and LAST chunks.
- Repeat share: 1,120 of 1,135 paragraphs (98.7%) repeated an identity already in the stream.

POST - the same stream through the T3 builder (filter -> collapse -> families):

| type | identities | family |
|------|-----------:|--------|
| BaseURL | 1 | host-meta, 13 assets |
| Header | 11 | host-meta |
| Technology | 1 | host-meta |
| Endpoint | 2 | endpoints: `GET /` and `GET /experiment/models` |
| **total** | **15** | 3 families -> ONE chunk |

- Typist turns for this pass fall 12 -> 1 (15 assets never reach the soft target of 100).
- The assigner-visible surface stays 2 Endpoints and now arrives in ONE turn instead of two.
- Corrections to earlier estimates in this doc: E1's "~16 Headers" matched the graph's total Header node count across both tools (16 nodes); the katana stream's own identity set is 11. Section 7's "~20 unique assets" is superseded: measured 15.
