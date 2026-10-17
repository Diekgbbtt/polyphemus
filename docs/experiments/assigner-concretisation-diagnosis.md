# Assigner concretisation diagnosis

## Operator ruling addendum (2026-10-16)

- The graph read step (graph_view) is REJECTED: a graph_view-capable assigner degraded quality in an earlier iteration, because it repeatedly queried the whole graph and its context grew vertically.
- Instead the L1 graph is posted in the assigner's human message: service contracts, system descriptions, other relevant attributes, and the typed edges among them.
- The posted graph updates progressively through the live inventory read on every dispatch, as the run concretises and specifies more linked systems.
- Null-owner paths (honest `unresolvable` / `out_of_inventory` outcomes) are NOT implemented now.
- They remain a future experiment direction only: an endpoint that is streamed but cannot be assigned is treated as an upstream filtering failure, not an assigner failure. - arm J comfyui vs white-jotter

Date: 2026-10-16.
Plan: `docs/design/plans/2026-10-16-failure-modes-diagnosis.md` (F7, operator item 5).
Scope: judge assigner concretisation quality by comparing the two arm J trials (outcome + execution workflow); locate the root cause in the contained recon, the analysis workflow, or both.

## Data sources

- Langfuse: `assigner-aggregates` structured generations for both J runs plus the aborted attempt; tool observations pulled per session `<recon_run>:assigner`; window 2026-10-15 21:55-23:50 UTC.
- Neo4j: final L1 service inventories for `2df3ad9d` (J comfyui), `bf0d9408` (J wj), `a9bb42f9` (H comfyui).
- The assigner's structured input is `{"chunk": "<job>:<i>"}` only; the service inventory it can reference is the live L1 set minted through the typist path.

## Outcome - per-chunk assignment deltas

The stats block of each turn: admitted / proposed / kept / unresolvable / out_of_inventory.

### comfyui (5 turns, one per streamed chunk)

| chunk | turn (UTC) | admitted | proposed | kept | unresolvable | out_of_inventory |
| --- | --- | --- | --- | --- | --- | --- |
| httpx:0 | 22:03:49 | 1 | 0 | 0 | 0 | 0 |
| katana:0 | 22:08:26 | 2 | 1 | 1 | 0 | 0 |
| ffuf:0 | 22:10:23 | 10 | 7 | 7 | 0 | 0 |
| steel_crawl:0 | 22:12:51 | 2 | 0 | 0 | 0 | 0 |
| jsluice:0 | 22:17:55 | 92 | 73 | 73 | 0 | 0 |
| totals | | 107 | 81 | 81 | 0 | 0 |

### white-jotter (3 turns)

| chunk | turn (UTC) | admitted | proposed | kept | unresolvable | out_of_inventory |
| --- | --- | --- | --- | --- | --- | --- |
| httpx:0 | 23:09:30 | 1 | 0 | 0 | 0 | 0 |
| katana:0 | 23:11:57 | 1 | 0 | 0 | 0 | 0 |
| jsluice:0 | 23:26:53 | 38 | 31 | 31 | 0 | 0 |
| totals | | 40 | 31 | 31 | 0 | 0 |

The aborted attempt shows the same shape (4 turns; the 38-admitted jsluice turn proposed 27).

Reading:

- Both trials: small early chunks propose nothing; the large jsluice turn proposes and keeps almost everything (comfyui 73/92, wj 31/38).
- Every proposal is kept (proposed = kept in all turns).
- The null-owner paths were never exercised: `unresolvable` = 0 and `out_of_inventory` = 0 in all 12 turns across the three runs. The gate never says "no".
- Grouping does happen: 92 admitted endpoints became 73 proposals (comfyui), 38 became 31 (wj).

## Concretisation quality - what the proposals say

### comfyui jsluice turn (73 proposals, 13 distinct slugs)

- Slugs: custom-node-catalog, custom-node-content, image-upload, image-viewing, model-inventory, node-registry, password-recovery, register, server-diagnostics, sign-in, system-status, user-profile, workflow-submission.
- Evidence refs per proposal: min 1, max 2, average 1.05; only 4 of 73 proposals carry two refs.
- Example refs: `path segment /extensions - the frontend extension scripts served by installed custom nodes (recorded 200, JSON list)`; `path segment /i18n - the i18n translations endpoint named in the contract (recorded 200)`.
- Concretisation here is effectively "slug from path segment": the grounding is one segment plus a one-line gloss.

### white-jotter jsluice turn (31 proposals, 18 distinct slugs)

- Slugs: all target-real services (book-*, article-*, role-*, user-*, account-*, menu-provisioning).
- Evidence refs per proposal: exactly 2 for 31 of 31 proposals - a path segment plus a contract quote.
- Example refs: `path segment /books` + `contract: 'Lists the book catalog either in full or filtered to the books of a chosen category, newest records first'`; `query parameter 'keywords' matches contract: 'Finds books whose title or author matches a submitted keyword'`.
- The wj assigner's grounding is materially stronger per proposal (path + contract pairing, including a query-parameter match).

### Cross-trial note on the auth trio

`sign-in`, `register`, and `password-recovery` appear in all three final inventories (H comfyui, J comfyui, J wj).
They are class/lens-driven services, not artifacts of any single target's traffic.
The foreign-client literals of comfyui (`api.comfy.org`) polluted the endpoint stream, but no cloud/customer service appears in any final inventory: the contamination did not reach the service layer in this trial.

## Execution workflow

| trial | assigner tool calls | search_http_history | get_http_artifact | graph_view | execute_command |
| --- | --- | --- | --- | --- | --- |
| comfyui | 64 | 48 | 16 | 0 | 0 |
| wj | 42 | 30 | 12 | 0 | 0 |

- The assigner never reads the graph (`graph_view` = 0 in both trials), while the typist uses graph_view heavily (93 calls comfyui, 69 wj).
- Its channels are HTTP-history search and artifact fetch; concretisation is done over raw captured traffic.
- Query style is structured filter usage, not just free text. comfyui examples: text queries `/experiment/models`, `/settings`, `user-select`, `index.json`, `/i18n`, plus filter queries (path contains, method equals, URL equals). wj examples: filter queries over request method/URL and response `location` header absence, plus the target host name.
- The probes cluster around each chunk's decision: the comfyui jsluice turn's probes (including `/experiment/models`, `index.json`, `/i18n`) run at 22:15:25-22:16:25, just before its 22:17:55 structured output.
- Workflow reading: the assigner spends real effort (48 searches in comfyui), but the effort goes to raw-traffic evidence hunting, not structural reconciliation against the service inventory. With `graph_view` = 0 it cannot answer "which existing service already owns this endpoint?" from the graph; missing a structural check, bad proposals have nothing to fail against, and no drop path exists (`unresolvable`/`out_of_inventory` stay 0).

## Root cause location: recon or workflow?

Both layers contribute, with distinct signatures:

1. Contained recon sets the ceiling.
   - comfyui received volume: 107 admitted endpoints, and the assigner proposed 81. But the failed discovery of the app's own surface (Vite chunk scanner no-op, mis-resolution; see the coverage doc) means the admitted set mixes phantoms (`/locales/*.json` 404s, foreign-client literals) with real endpoints. The comfyui assigner's thin refs (avg 1.05) partly reflect that noisy, weakly linked input.
   - wj received thinness: 40 admitted endpoints across the whole trial. Bundle-relative `/api/*` paths were unresolvable pre-F4, so the assigner could only attach 31 aggregates; its final service set carries 31 aggregate edges vs 76/80 on comfyui. The wj proposals themselves are well grounded (2.0 refs) - the ceiling is the input volume.
2. The analysis workflow caps grounding quality in both trials.
   - No graph reconciliation step (graph_view 0), no drop paths exercised (all 12 turns clean), proposed = kept everywhere, and comfyui's largest turn grounds 69 of 73 proposals in a single path segment.
   - The wj trial shows the workflow can do better (2 refs/proposal with contract pairing), so the workflow is not intrinsically incapable; the comfyui shortfall tracks the weaker link between endpoints and existing contracts.

## L1 inventory each chunk was judged against

- Final inventories: comfyui 23 services / 4,084 contract chars / 76 aggregate edges; wj 24 / 2,820 / 31.
- J comfyui and H comfyui have byte-identical slug lists (all 23 services). Trial-to-trial, the inventory is stable; what varies is evidence attachment.
- Ordering dependency: proposals attach to service slugs, so a turn can only reference services the typist has already minted. In wj the final assigner turn (23:26:53) lands after the typist's last big turn (23:23:00), which is the correct order; keep it.

## Fix proposals (for F9 - consolidated list)

Recon side:

- F4 chaining (done) raises the admitted volume for `/api/*`/`/internal/*` surfaces and removes the mis-resolved/foreign contamination at its source.

Workflow side:

- Give the assigner a graph read step: query existing services and their contracts before proposing, so proposals can reference or extend a service instead of re-deriving it from a path segment.
- Exercise the null-owner paths: enable honest `unresolvable` / `out_of_inventory` outcomes so weakly grounded candidates can be dropped rather than kept. Today the gate never drops.
- Require at least two independent evidence refs for a kept proposal (path + observed artifact/schema/contract), as the wj assigner effectively did for 31 of 31 proposals.
- Keep the typist-before-assigner ordering per chunk.
