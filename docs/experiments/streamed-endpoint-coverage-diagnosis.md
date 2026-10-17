# Streamed endpoint coverage diagnosis - arm J comfyui and white-jotter

Date: 2026-10-16.
Plan: `docs/design/plans/2026-10-16-failure-modes-diagnosis.md` (F1, F2, F4).
Scope: why comfyui recon collected so few endpoints (not discovered vs dropped before stream/graph), the Header value question, and the baseURL x relative-path chaining fix.

## Trials under test

- comfyui: project `2df3ad9d-eb9c-4789-a118-44139a745ca2`, recon run `9ae295dc-d6fc-4180-a386-11598881a679`, 2026-10-15 21:59:57 - 22:44:09 UTC, spent 3,009,705 tokens, target `http://t-1fc05262.target`.
- white-jotter: project `bf0d9408-d403-457f-b769-076dd9cd9138`, recon run `131ba77d-6abc-44fd-83fb-329d4635f46c`, target `http://t-1618c524.target`.
- white-jotter aborted attempt: project `b0353d51`, recon run `96262aa1` (data-only repair, then re-run).

## F1 - Why comfyui recon collected so few endpoints

### Question

Was the surface not discovered, or discovered and dropped before it reached the graph/stream?

### Answer in one line

Both modes occurred with separate causes: the dedicated chunk scanner found nothing (Vite build, not webpack), and jsluice mis-resolved bundle-relative literals into root-level phantoms; the drop-before-stream filter removed only `.js/.mjs` bundle noise, never a useful non-JS endpoint.

### Job census (comfyui run 9ae295dc)

Columns: pods | consumed (gating items) | produced assets | produced observations.

| job | pods | consumed | produced assets | produced observations |
| --- | --- | --- | --- | --- |
| whois | 1 | 1 | 1 | 0 |
| subdomain_takeover | 1 | 1 | 0 | 0 |
| naabu | 1 | 1 | 13 | 1 |
| httpx | 1 | 1 | 13 | 3 |
| katana | 1 | 1 | 1240 | 3 |
| steel_crawl | 1 | 1 | 4 | 0 |
| ffuf | 1 | 1 | 22 | 3 |
| webpack_chunks | 5 | 105 | 0 | 0 |
| jsluice | 5 | 105 | 987 | 1 |
| httpx_reprofile | 1 | 290 | 1216 | 3 |
| kiterunner | 3 | 17 | 0 | 0 |
| arjun | 5 | 290 | 0 | 0 |
| graphql-cop | skipped | | | |

Collection meters are rich: katana produced 1240 assets, jsluice 987, httpx_reprofile 1216.
The bottleneck is downstream of collection: resolution and stream gating.

### Chunk-to-job map (comfyui)

| chunk | job |
| --- | --- |
| `04f33dcc941f` | httpx |
| `2494f99cee4f` | katana |
| `839f2a9eae5b` | ffuf |
| `406eb9631c54` | steel_crawl |
| `877ff08e6104` | jsluice |

### Stream vs graph

- Endpoint rows in the final comfyui graph: 289.
- Endpoint lines streamed to the analysis roles: 107 (98 unique paths; 9 cross-chunk duplicates).
- Withheld from the stream: 191 paths, all `.js`/`.mjs` (zero non-JS withheld).
- Status classes among the 289: HTTP 200 x124 (100 `/assets/*` Vite bundles, 17 JSON resources, the root document), HTTP 404 x162 (about 86-90 root-level `.js` literals, 40 `/locales/*.json`, foreign-host and misc paths), HTTP 403 x3, HTTP 307 x1.

### Root causes (code-level)

1. jsluice relative-literal mis-resolution (`src/polymerhus/recon/scripts/jsluice_scan.py`, `-R <origin>`).
   The index bundle contains literals like `./main-17LNOc6i.js` (124 such `./x-hash.js` asset literals).
   Resolving against the origin root minted `<origin>/main-17LNOc6i.js` -> 404, while `<origin>/assets/main-17LNOc6i.js` -> 200.
   Live proof: the root-level path returns 404, the `/assets/` path returns 200.
   These phantoms are a large share of the 404 mass and were invisible to the typist (all `.js`).
2. Vite, not webpack: `webpack_chunks` ran 5 pods over 105 bundles and resolved 0 chunks on every run.
   The chunk scanner looks for a webpack runtime chunk map; comfyui ships a Vite build.
3. Foreign-origin client base: bundle config includes `axios.create({baseURL: "https://api.comfy.org"})`.
   Literals of that client (`/cloud/*`, `/customers/*`, `/register`, `/sign-in`, `/password-recovery`) were minted against the target origin.
   These became streamed endpoints, and the assigner concretised them into services (see the assigner diagnosis doc).
4. `/locales/*.json` literals were genuine 404s on the target (served under a different prefix), not mis-resolution.
5. Bundle-relative API literals with no leading slash and no runtime base prefix (`login`, `api/...`) never resolved at all pre-F4.

### Drop-before-stream assessment

The anti-noise gate withholds `.js`/`.mjs` only, and all 191 withheld paths are bundle or module URLs.
No useful non-JS endpoint was dropped at the gate.
The real loss is at discovery: mis-resolved literals became `.js` phantoms (then withheld), and unresolved bare literals never became endpoints.

### Usability of `.json`/HTML assets and response content (assigner/typist)

- The trial recorded 33,148 HTTP flows, 212 response bodies, and 16,416 captured-response artifacts.
- Both analysis roles worked from that channel: the comfyui typist session used `search_http_history` 32 times and `get_http_artifact` 16 times; the assigner session used `search_http_history` 48 times and `get_http_artifact` 16 times.
- Concrete uses include the typist fetching the `/experiment/models` artifact and searching `/docs` with bundle JS text.
- One important endpoint (`/internal/logs`, HTTP 200) was found by the hunting phase only, not by the recon stream.
- Read: the http-history channel is usable and used; its usefulness is bounded by what recon streamed into it.

### F1 verdict

- Not discovered: the app's own bundle-relative surface. The Vite chunk scanner is a no-op, and mis-resolution turned the asset/API literals into unresolvable or phantom rows.
- Dropped before stream: 191 rows, but only `.js`/`.mjs` noise; the gate behaved as designed.
- A separate fidelity defect fed phantom material (root `.js` phantoms, foreign SaaS routes) into the analysers; F4 removes its sources.

## F2 - Header value and direction in the streamed surface

### Question

The operator quoted `Header {name: 'content-type', baseurl: 'http://t-1fc05262.target'}:` and noted there is no value field.
Check the exact STREAMED SURFACE paragraph of one comfyui chunk against the Neo4j node props.

### Findings

- The graph carries the fields: 11/11 Header nodes in the comfyui chunks have `name`, `value`, and `direction`.
- The streamed text carries them too: every streamed Header line renders `[direction=response, value=<...>]`.
- The typist itself queried `MATCH (b:BaseURL)-[:HAS_HEADER]->(h) RETURN b.url, h.name, h.value, h.direction` at 22:08:32 UTC and received the values.
- Source of the operator's quote: the identity-only table at `docs/experiments/typist-feed-quality-diagnosis.md:52`, which renders `(name, baseurl)` without the value; the value was present in the serialized block all along.

### Real nuance found

- Header nodes merge per `(name, baseurl)` identity with last-write-wins.
- Example: chunk 1 streamed `content-type: text/html`; the final graph node for the same identity holds `application/json` from a later probe.
- Per-endpoint header scoping is therefore lost; `(name, baseurl)` cannot express "this endpoint returns HTML and that one JSON".

### Fix direction (small)

- Include `value` in identity-only renderings used in feed-quality tables.
- Consider keying header identity per endpoint (or per `(endpoint, name)`) so that value mutations do not collapse into one node.

## F4 - baseURL x relative-path chaining (implemented)

### Question

Is there a component that joins a discovered base URL (for example white-jotter's axios `defaults.baseURL`) with relative endpoint paths after katana/jsluice/etc.?
If it does not exist, implement it and chain it systematically whenever relative endpoints are collected.

### Finding: absent pre-fix

No component chained a discovered base prefix with relative literals.
Relative literals were resolved only against the scanned resource origin root (the jsluice `-R` behavior), which is the F1 defect.

### Implementation

Branch `fix/baseurl-relative-chaining`, commit `9931ea9`, base dev `fbb3ae8`.

- Part A: literals now resolve against the scanned RESOURCE URL (the bundle), not the origin root.
- Part B: runtime base-prefix extraction in-pod (`baseURL` config literals and joined-concat helpers), then re-minting of chained candidate URLs as ADDITIVE records.
  Provenance is carried in `chained_prefix` and `chained_from`; the original literal is kept, and the reprofile probe arbitrates which candidate is real.
- Determinism: `build_batches` groups by origin with `_ORIGIN_GROUP_MAX = 120`; an origin beyond the cap degrades to per-item units (no chaining) to bound `EXEC_TIMEOUT_S`.
- Guards on proposed records: skip foreign-origin, root path, trailing-slash or directory-like path, static-asset extensions (js/mjs/css/map/wasm/images/fonts/media; not `.json`), already-prefixed paths, and literals that resolved under the resource's own directory (asset/module references; disabled for root-served bundles).
- Prefix extraction is capped: `_MAX_BASE_PREFIXES = 4`.

### Live evidence

- comfyui 12-bundle sample: 91 chained records recovered the full `/api/*` mirror plus the manager routes (`/api/system_stats`, `/api/object_info`, `/internal/logs`, `/internal/folder_paths`), all confirmed 200 live.
- white-jotter 14-bundle sample: 37 chained records including `/api/login`, `/api/search`, `/api/admin/*`; the bare literals 404 live, the chained candidates 200.
- Full-scale run: all 105 comfyui bundles in a single pod = 31 s, rc=0 (12-bundle sample 20-21 s); no timeout risk at the cap.
- Junk classes observed and filtered: the asset-relative `.json` family and js/css hash files.

### Tests and docs

- `tests/recon`: 1024 passed, 18 skipped.
- Full non-e2e suite: 1337 passed, 34 skipped, 1 pre-existing environmental error (`tests/e2e/test_blackloop_live_walkthrough.py` requires the sibling agent container; unrelated).
- ADR: `docs/design/recon-webpack-chunk-map-185-adr.md` - deferral closed with an amendment.

### Known limits (documented in the amendment)

- Root-served bundles have no directory discriminator, so all literals are candidates there.
- Bare-relative request literals (`axios.post("login")`) have no textual anchor; they resolve bundle-relative and are not chained.
- Absolute-URL bases are not chained (by design).
- Rejected alternative: persisting prefix facts in the graph (BaseURL prop or Observation) and chaining in a later phase; kept documented as an alternative.

### Effect on the F1 defects

With chaining, the comfyui manager/API surface (`/api/*`, `/internal/*`) becomes discoverable, and the white-jotter `/api/*` family (the login/search/admin endpoints the authn story needs) is recoverable.
This addresses the thin assignment evidence of the white-jotter trial at its root (see the assigner and typist diagnosis docs).

## Files

- `src/polymerhus/recon/scripts/jsluice_scan.py` (F4 implementation).
- `src/polymerhus/recon/control/batching.py` (origin grouping).
- `src/polymerhus/recon/domain/parsers/jsluice_parser.py` (provenance passthrough).
- `docs/design/recon-webpack-chunk-map-185-adr.md` (amendment).
- Commit: `9931ea9` on `fix/baseurl-relative-chaining`.
