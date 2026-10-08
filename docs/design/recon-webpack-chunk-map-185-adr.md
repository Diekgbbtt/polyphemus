# ADR: a webpack chunk-map resolver job mints lazy-loaded SPA chunks (#185)

## Status
Accepted (2026-10-08).

## Context
- Against a client-side-rendered SPA with webpack code-splitting (observed live:
  white-jotter), the recon surface stopped at the shell. katana crawled
  `index.html` and the shell bundles (`manifest.<hash>.js`, `vendor.<hash>.js`,
  `app.<hash>.js`), jsluice scanned those bundles, but the real API surface
  (`POST /api/login`, `/api/search`, `/api/file/`, `/api/register`,
  `/api/admin/*`) never landed.
- The page components - and their `this.$axios.post("/login", ...)` literals -
  are LAZY-LOADED CHUNKS (`8.<hash>.js` ..), fetched only at route navigation.
- The chunk-id to filename-hash map is STATIC JSON inside the crawled
  `manifest.<hash>.js` runtime: `{"0": "e97b6a900e6dba290e55c", ...}`. No stage
  resolved it, so the chunk URLs never became Endpoints and jsluice never
  scanned their bodies.
- Eval evidence: `tools/eval/runs/white-jotter/attempt-front/` on branch
  `eval-harness-light` (22 Endpoints, none from the `/api/*` family); the
  manifest and the shell bundles are the only JS Endpoints in the graph.
- The root cause is pinned (Profile A): the ticket diagnoses it from the live
  target, and the miss is fully explained by "the chunk map is static and
  nothing reads it". The blast radius is one job/phase insertion plus a parser.

## Decision
1. Add a dedicated recon Job `webpack_chunks` (`JOBS["webpack_chunks"]`): it
   consumes the crawled `.js`/`.mjs` Endpoints (the same `AssetSelector` path
   selector jsluice uses), rides the existing endpoint-batch seam
   (`ConsumptionOptions(pack="batches")`), and mints the resolved lazy chunk
   URLs as Endpoints with `source="webpack"`.
2. The pod command is built by `batching.build_webpack_chunks_command`, which
   base64-embeds `scripts/webpack_chunks.py` and runs it over the batch's bundle
   URLs (mirroring `build_jsluice_command`). The script fetches each bundle,
   extracts the first webpack chunk map (`{chunk_id: "<hex content hash>"}`, two
   or more all-hash entries), and emits one JSONL record per resolved chunk URL
   `{"webpack_chunk_url": "<url>"}`. A chunk URL is the bundle's own directory
   plus `<chunk_id>.<hash>.js` (webpack's default `[id].[contenthash].js` under
   the runtime's output directory - the observed white-jotter layout).
3. `parsers/webpack_chunks_parser.py` turns each record into a `BaseURL` +
   `Endpoint` pair through the shared `url_to_deltas`, so a chunk URL MERGEs
   onto the identical node a crawler would have minted.
4. It is placed in its OWN phase, after the crawl phase (its bundle producer)
   and BEFORE jsluice. The phase barrier resolves jsluice's input set after the
   chunk Endpoints exist, so jsluice now scans the chunk bodies (and their
   relative API literals) it would otherwise never see. This is the same
   phase-barrier mechanism that fixed D17.
5. `JobSpec.skill` (used only as an Observation `source_job`) is `js_secret_scan`
   - the resolver's product is JS-bundle surface, and no new triager skill is
   introduced.

## baseURL-awareness: deferred
- The ticket also notes the shell's `defaults.baseURL="/api"` is invisible, so a
  chunk's `/login` literal is really `/api/login`. It marks that as OPTIONAL.
- It is deferred here, with a follow-up work item, because it is a distinct
  concern from chunk-map resolution: the config literal lives in the APP bundle
  while the relative literals live in the CHUNKS, and the jsluice batch
  round-robin can place them in different pods, so a per-bundle prefix is not
  deterministic. A correct fix needs the origin-scoped prefix to reach every pod
  that scans that origin's chunks - either by persisting the prefix as a
  `BaseURL` fact and enriching jsluice's batch inputs, or by making the resolver
  scan chunks itself with the prefix applied. Both are a separate design.
- Consequence: after this change the lazy chunks and their scanned endpoints
  enter the surface; the API endpoints recovered from chunks carry the origin
  root rather than the `/api` prefix until the follow-up lands.

## Consequences
- The lazy-loaded chunk files become Endpoints (`source="webpack"`) and are
  reprofiled and parameter-probed like any other endpoint.
- jsluice scans the chunk bodies, so their URL and secret extraction runs; the
  API endpoint family that only ever existed inside chunks enters the graph
  (subject to the baseURL deferral above).
- Cost is browser-free and bounded: one extra job over the crawled `.js`
  endpoints (batched, so O(1) triager turns per job), and the chunk Endpoints
  it mints. The bundle fetch duplicates jsluice's fetch, but the batch seam
  bounds both.
- The heuristic misses a build whose `publicPath` differs from the runtime
  bundle's directory, or whose runtime is inlined into a non-manifest bundle
  with a map the regex does not match. Both degrade to "no chunk deltas", never
  a crash, and are recorded here as known limits.

## Alternatives considered
- **Extend `jsluice_scan.py` to resolve chunk maps and scan chunks in the same
  pod.** Rejected as the primary seam: it conflates the scanner's
  URL/secret-extraction responsibility with chunk-graph resolution, and the
  baseURL prefix (the reason to scan in the same pod) is deferred anyway. A
  separate Job gives honest `source="webpack"` provenance and keeps each tool's
  JobSpec parser-testable in isolation.
- **Teach katana's JS parsing to extract chunk maps.** Rejected: katana does not
  execute JS, and the map is static JSON in a crawled bundle - a deterministic
  fetch-and-parse job is cheaper and testable without the Go tool.
- **A browser crawl of the SPA.** Rejected: strictly more expensive, and the
  chunk map needs no execution.
- **Include baseURL-awareness now.** Deferred (see above) rather than smuggling
  a cross-pod prefix resolver into the chunk job; recorded as a follow-up.

## References
- #185 (this defect). Related: D17 (jsluice input/output contract),
  `docs/design/recon-pipeline-forward-decisions.md`,
  `docs/design/recon-pipeline-design.md` §4.2.
