# Assessment: `/experiment/models` - the right owner reached by the wrong path

**Date:** 2026-10-15.
**Trigger:** T4 of `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md` ("Differentiation assessment, report only").
**Question:** could `/experiment/models` have been correctly assigned to `model-inventory`; if yes, name the reasoning quirk and report a throughput relaxation with its wrong-allocation risk.
**Evidence base:** arm H trial `comfyui-1-20261015T143534-1fc05262` (sha `a088730d`, project `a9bb42f9-6255-4f1e-87ee-fc09e2388024`); the assigner session dump (`/root/lf-h-assigner-final.txt` and its digest); the L1 graph over `ph-dd131acc-neo4j-1`; a live re-fetch of the payload through `ph-dd131acc-kali-1`.
**Status:** report only. No code or prompt change lands in this iteration.

## 1. Verdict

The claim is TRUE, but the run did not earn it.

- `model-inventory` is a correct owner: the payload is a model-scoped folder map, and that contract's boundary explicitly covers "the model folders" (section 3).
- The run's differential never tested the rival whose contract names the payload class: `server-diagnostics` ("the folder-path map") never entered (sections 4 and 5).
- In the same turn, the model routed the sibling route `/folder_paths` to `server-diagnostics` on that exact clause. The clause was in the turn's working set and was applied to one route, not the other.
- The keep is therefore a noun-coincidence with the right boundary, not a contract discrimination.

## 2. The live payload

`GET http://t-1fc05262.target/experiment/models` returns 1589 bytes of JSON, the same size and shape the run recorded (`http_01M4ZRRAB5QN9340AFPJ9CJ4V3`, re-fetched 2026-10-15):

```json
[{"name": "checkpoints", "folders": ["/workspace/models/checkpoints", "/workspace/output/checkpoints"]},
 {"name": "loras", "folders": ["/workspace/models/loras", "/workspace/output/loras"]},
 {"name": "vae", "folders": ["/workspace/models/vae", "/workspace/output/vae"]},
 {"name": "text_encoders", "folders": ["/workspace/models/text_encoders", "/workspace/models/clip", "/workspace/output/clip"]},
 {"name": "diffusion_models", "folders": ["/workspace/models/unet", "/workspace/models/diffusion_models", "/workspace/output/diffusion_models"]},
 {"name": "clip_vision", "folders": ["/workspace/models/clip_vision"]},
 ...]
```

The shape is a list of `{name, folders}` pairs: a model category and the directories that hold its files.
The payload carries no file names, no file metadata and no catalog entries.
Both facts matter: they bound the correct owners, and they name the payload CLASS the differential ignored.

## 3. The competing contracts (quoted from the live L1)

```
model-inventory    - Lists the model files and embeddings available in the model folders, exposing the full recursive model inventory with file metadata, plus a safetensors-metadata reader for a chosen model file.
model-download     - Lists the downloadable external model catalog and triggers model file downloads into the model directories, honoring the model catalog membership checks before a download is queued.
server-diagnostics - Exposes the internal diagnostics surface used by the frontend: application log retrieval and subscription, the folder-path map and directory file listings.
```

- `model-download` does not reach the payload: no catalog, no membership check and no download appears anywhere. The run got this half right.
- `model-inventory` reaches it through "the model folders". The "file metadata" half of its contract is not exercised by this payload.
- `server-diagnostics` reaches it literally: the payload IS "the folder-path map", scoped to the model directories.

## 4. What the run did (assigner turn 7, 13:45:20Z)

The turn's own summary table carries both rows side by side:

| Endpoint | Surface nouns/actions | Candidates run | Discrimination | Result |
|---|---|---|---|---|
| `GET /experiment/models` | noun *models* | `model-inventory`, `model-download` | model-inventory "lists the model files ... in the model folders" (local folder listing); model-download claims the *downloadable external* catalog, which this path does not name | `model-inventory` |
| `GET /folder_paths` | noun *folder_paths* | `server-diagnostics` | "the folder-path map" | `server-diagnostics` |

(The `/folder_paths` row was judged from the route name and the contract clause; the recorded probe of that path was a 404, so no payload backed it. The clause was still the decisive evidence in that row.)

The aggregate the run emitted for `/experiment/models`:

```json
{"service_slug": "model-inventory",
 "l0": {"label": "Endpoint",
        "identity": {"path": "/experiment/models", "method": "GET", "baseurl": "http://t-1fc05262.target"}},
 "evidence_refs": ["path segment /experiment/models",
   "GET returning a JSON collection of model entries (200, application/json, 1589 bytes) - a listing of the models available in the model folders",
   "no download/catalog path segment, so model-download's external-catalog contract is not reached"]}
```

Two details matter:

- the model read the artifact and quoted its size and shape ("1589 bytes"), yet described it as "a JSON collection of model entries";
- the runner-up it named and dropped was `model-download`, the noun-adjacent candidate. `server-diagnostics` never entered the differential.

The graph confirms both placements as `AGGREGATES` edges: `(/experiment/models) -> model-inventory` and `(/folder_paths) -> server-diagnostics`.

## 5. The reasoning quirk

Candidate generation is path-noun-driven, and the differential inherits that blindness.

- The governing rule is noun/action-anchored: "Hold every candidate Service whose contract touches those nouns or actions" (`prompts/assigner.md`, differential step 2).
- The evidence doctrine is noun/action-anchored as well: "A path noun that names a record or an action the contract explicitly says that Service owns is strong evidence". The response payload is not part of the evidence model.
- So candidates come from the route's own words. The noun `models` pulls the `model-*` family; nothing pulls the contract whose text names the payload CLASS ("the folder-path map").
- The knowledge was present in the turn. The model cited "the folder-path map" for `/folder_paths` two rows away. It never applied the clause to `/experiment/models`, whose payload is exactly that class scoped to models.
- Consequence: two sibling routes split across two Services on route noun alone. The split may be defensible (section 6), but the run cannot show that, because the choice was never weighed.

The prompt already demands rigour: name a runner-up "even when you are sure".
That demand operates inside the noun-generated candidate set, so it cannot repair a missing candidate.

## 6. Why the answer is still defensible

- The payload is scoped to model categories, and each entry names directories that hold model files. `model-inventory` genuinely owns that view.
- The sibling split has a real boundary: `/folder_paths` returns the full folder map (input, output, temp, models), while `/experiment/models` returns the model subset.
- Shared ownership would also have been defensible: with `server-diagnostics` in the differential, the honest outcomes were `model-inventory` alone (model-scope discriminator) or BOTH (shared ownership). The run cannot distinguish those two.

So the verdict is TRUE with a caveat: the owner is right, the reasoning path is not reproducible.

## 7. Relaxation proposal (report only)

Today every judgment pays the full differential: a runner-up search, widening calls, and prose, even when one contract is the only reachable owner.

Three moves, each with its cost model:

**Move A - class-first candidate pull (closes the quirk).**
Add one step before the differential: name the payload CLASS from the artifact (folder map, log stream, file listing, external catalog, membership check) and pull every contract that names that class, even when no path noun does.
Cost: it ADDS candidates, so it raises differential work. It saves nothing by itself.

**Move B - single-candidate direct admit (the throughput move).**
When exactly ONE contract matches both the nouns/actions AND the payload class, admit it without the runner-up requirement and without further widening. Roughly two in five arm H judgments were single-candidate cases. In turn 7, 5 of 12 rows (`system_stats`, `global_subgraphs`, `logs`, `folder_paths`, `i18n`) named one candidate, so their runner-up step bought nothing.

**Move C - one ownership question per payload class across route identities (deferred).**
When several routes deliver the same payload class and shape, decide the class once and let each route inherit the verdict, unless its own payload differs. `folder_paths` and `experiment/models` are the motivating pair. The collapse needs payload-shape evidence, never path prefixes.

**Throughput envelope (arm H, measured).**
14 assigner turns; 803 observations; 122 widening calls (117 `search_http_history` + 5 `get_http_artifact`) for 298 admitted endpoints, roughly 0.4 widening calls per admitted endpoint.
Move B removes the runner-up step for single-candidate classes; Move C removes repeated class questions across routes.
A rough bound: with about 42% of turn 7's judgments single-candidate and the class questions collapsing, the differential work drops materially. This doc does not claim a number without a trial that measures it.

**Wrong-allocation risk.**
- Move B's shortcut locks in a wrong candidate while candidate generation stays noun-only. The quirk in this doc is exactly that failure mode.
- Move A adds candidates, so it can add shared-ownership writes. Each extra aggregate is a possible false positive.
- Move C can import a verdict into a route whose payload differs.

**Guard set (bounds the risk).**
1. The single-candidate shortcut requires TWO independent matches: nouns/actions AND payload class. Nouns alone never qualify.
2. A class matched by two or more contracts keeps the full differential and its named runner-up.
3. Move C only groups routes with observed payload evidence (artifact body shape), never by path prefix.
4. The no-owner option stays: a class that matches no contract is still left unowned.
5. Shared ownership stays legal and explicit.
6. Acceptance signals for the next trial: `endpoint_placement` at or above arm H's 26.9%, `gt_service_aggregation` at or above 71.4%, and zero new `out_of_inventory` drops. The stale-pool decline rate (193/298 in arm H, 64.8%) is EXPECTED to fall; it is a volume signal, not the precision signal.

**Recommendation (one).**
Adopt Move A now, and Move B behind guards 1 and 2. Keep Move C out until a trial measures the first two.
This buys throughput where the differential is provably idle. It closes the class-blindness that produced this assessment's quirk, at the cost of a bounded rise in proposals that the placement and aggregation metrics must hold.

Specified in `docs/design/plans/2026-10-15-T5-class-first-candidate-pull.md`: the exact prompt edits, the formal two-signal guard (uniqueness, two independent matches, no class competition, artifact held, signal independence), the motivating-case walkthrough, and the measurement plan.

## 8. Arm H keep/drop rows (the precision baseline)

| Metric | Value |
|---|---|
| Admitted endpoints | 298 |
| Proposed aggregates | 105 (35.2%) |
| Kept (written) | 105 |
| Declined (stale pool) | 193 (64.8%) |
| `unresolvable` | 0 |
| `out_of_inventory` | 0 |
| Assigner turns | 14 |
| Kept carried by the ffuf and jsluice passes | 104 of 105 |
| `endpoint_placement` (eval) | 26.9% |
| `gt_service_aggregation` (eval) | 71.4% |

Sources: the assigner census rows in `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`, and the turn dump quoted above.

## 9. What does not change in this iteration

- This doc only. No prompt change, no candidate-generation code and no `ROLE_ADMITS` change.
- The next trial keeps the current differential, so it measures the T1-T3 corrections on a stable judge.
- The T4 change rides the trial after it, with the guard set above as its acceptance.
