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

## Amendment (2026-10-16): baseURL-awareness landed
- The deferral above is closed by the arm J diagnosis (`fix/baseurl-relative-chaining`).
  The "prefix must reach every pod" constraint is resolved by keeping the origin
  TOGETHER instead of persisting the prefix: `batching.build_batches` partitions
  bundles by origin, so the app bundle's config literal reaches the pod scanning
  that origin's chunks by construction (one origin = one pod; an origin beyond
  `_ORIGIN_GROUP_MAX` = 120 bundles degrades to the previous round-robin with
  chaining skipped, so no pod can outlive `EXEC_TIMEOUT_S`).
- `jsluice_scan.py` scans each batch's bundle/source bodies for two runtime
  prefix shapes (`baseURL: "/api"`, `+ "/internal" +`), then re-mints every
  buffered root-relative literal once per prefix as an ADDITIVE candidate
  (`chained_prefix`/`chained_from` props; the original literal is kept - a
  `/login` is a route as well as an API call). Candidates are probed and
  arbitrated by the reprofile pass like any other endpoint.
- The same change resolves literals against the scanned RESOURCE instead of the
  origin: `./commands-x.js` in `/assets/index-abc.js` means
  `/assets/commands-x.js`, closing the phantom class (the arm J comfyui index
  bundle's `./x-*.js` imports re-minted as 86 root-level `.js` 404s, of the
  graph's 162 404 endpoints).
- Live verification on the arm J targets: white-jotter's 14-bundle origin in
  one pod yields 37 chained candidates including `POST /api/login`,
  `/api/search`, `/api/admin/*` (200 live; the bare literals were 404); the
  full comfyui 105-bundle origin scans in 31s single-pod and yields the `/api/*`
  mirror (`/api/system_stats`, `/api/object_info`, `/api/queue`) and the
  `/internal/*` manager routes (`/internal/logs`, `/internal/folder_paths`).
- Known limits recorded: bundles served from the origin root have no directory
  discriminator (every root-relative literal is a candidate); bare-relative
  request literals under a runtime base (`axios.post("login")`) resolve
  bundle-relative and are not chained; absolute-URL bases
  (`baseURL: "https://api.comfy.org"`) are chained as the LATEST failover under
  the 2026-10-16 amendment below (never probed).
- Tests: `tests/recon/test_jsluice_scan.py` (resource-base resolution, prefix
  extraction forms, chaining guards), `test_batching.py` (origin grouping, cap
  degrade), `test_jsluice_parser.py` (provenance props), and the
  `test_consumption_set.py` independent oracle updated to the grouping rule.

## Amendment (2026-10-16): foreign-origin chaining, failover order, no-probe

The arm J diagnosis also found client-bundle URL literals assembled from a
runtime base the bundle declares as an ABSOLUTE URL
(`axios.create({baseURL:"https://api.comfy.org"})` + `/login`), which the first
chaining landing deliberately skipped. This amendment reverses that skip and
records the decisions and their rationale.

- **Decision (i): foreign origins are chained, and the full foreign URL is
  minted.** An absolute-URL `baseURL` config is captured (its own, separately
  capped list so it never evicts a target path prefix); a literal that produced
  no target-origin candidate is re-minted as the FULL foreign URL, and the
  chained record's `base_url` is the foreign ORIGIN. Rationale: a foreign origin
  reached from a first-party bundle is ADJACENTLY RELEVANT to the modelled
  service (an API host the client calls), so it belongs in the graph; minting
  the full URL lets the URL stream so the assigner can relate it through the
  application-overview domain. `chained_prefix` is the foreign base string and
  `chained_from` the original literal, so the provenance is intact.
- **Decision: failover order.** Target-origin resource-relative resolution and
  path-prefix chaining come FIRST; foreign-base chaining is the LATEST failover -
  attempted for a literal ONLY when it produced no target-origin candidate, and
  its candidates are emitted last. Path prefixes are extracted before absolute
  bases so the `_MAX_BASE_PREFIXES` cap always keeps the target ones. Rationale:
  a target-origin interpretation of a literal is almost always the right one;
  foreign chaining is the last resort that widens recall without displacing it.
- **Decision: no probing at all.** Every asset whose origin differs from the
  scanned origin, and every foreign-chained candidate, is marked
  `origin_scope: "external"` (absent means target). The consumption stage's new
  `skip_external` option drops external-marked assets (Endpoint AND BaseURL
  shapes) for every requesting job, so NO active phase sends traffic to a foreign
  origin. The marker propagates to the BaseURL delta via the shared
  `_urls.url_to_deltas` baseurl-extra-props seam.
- **Decision (ii): reachability-gated probing was CONSIDERED AND REJECTED.**
  Rationale: (a) `baseURL` parsing is heuristic, so wrong foreign chaining is
  common - including taking the branch when the origin is not actually foreign -
  and probing every such guess multiplies off-target requests; (b) a foreign
  origin typically answers 401/403 without the correct auth material, so a
  reachability gate would learn nothing and still fire the request. The
  mechanism typist (NOT the harness) may obtain auth context through the project
  auth_store or `graph_view` WHEN REASONING, and the assigner needs no
  interaction - so no automated gate is required. A mitigation that iterates the
  baseurl over the resource's baseurl/origin domain until a 200 was also
  rejected: it still fails on auth-gated origins and adds request volume for no
  verdict. Final ruling: no probing at all; foreign chaining is the latest
  failover.
- **Decision (iii): directory-like / trailing-slash literals are KEPT.** The
  previous guard rejected a literal ending `/` (a directory reference). Rationale:
  the base path stays systematically identifiable, so a `/dist/` under `/api` is a
  legitimate candidate the reprofile pass can arbitrate; the static-asset-extension,
  already-prefixed, and resource-directory guards remain, and the root-path `/`
  rejection remains.
- **Note (auth-store access of the mechanism typist).** Checked per this
  amendment: the mechanism typist currently has NO auth-store access. Grepping
  `auth_store`/`auth_feed`/`auth_capable` under `src/polymerhus/analysis` finds
  only `anatomy.py` projecting `recon.control.auth_feed.select_account_role` for
  its interface executor (a separate concern); `auth_capable_binding` and
  `build_auth_store_tool` are bound only by the recon orchestrator, the recon pod
  triager, and the attack hunting roles. The typist turn binds the read-only
  `graph_view`, the HTTP-history pair, and a bounded `exec` (`graph_tools.py`).
  No new tool was implemented.

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
