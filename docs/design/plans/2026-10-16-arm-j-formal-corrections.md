# Arm J formal: correction workstreams (2026-10-16)

Purpose: land the operator-ruled corrections from the arm J streamed-pipeline diagnosis, advance dev, and run the formal arm J eval trials on the same two targets (comfyui, white-jotter).

## Operator rulings (2026-10-16)

- Foreign-origin chaining exists, but it is the LATEST FAILOVER mechanism; target-origin (path-prefix) and resource-relative chaining are prioritised.
- No probing of foreign origins, at all. A reachability-gated probing design was considered and rejected: baseURL parsing is heuristic, and foreign origins answer 401/403 without the correct authentication material.
  The mechanism typist (not the harness) may obtain auth context via the project auth_store or graph_view when reasoning; the assigner needs no interaction.
  The rationale is recorded in the chaining ADR (`docs/design/recon-webpack-chunk-map-185-adr.md`).
- Typist stream gate: recall-biased variant. Hard-drop static families (css/scss/less/fonts/map, js/mjs, wasm); images/media/archives drop only under `assets`/`static` path segments; `.json` and extensionless paths stay.
- Header assets: identity per endpoint (`name`, `endpoint`, `baseurl`); `value`/`direction` stay attributes; the `date` header is removed entirely; headers remain bound to the source BaseURL (no Header->Endpoint edge).
- Assigner: no graph_view step, no null-owner drop paths. Post the L1 graph (contracts, system descriptions, attributes, edges) in the assigner human message; it updates progressively (live read per dispatch).
- Null-owner drop paths are recorded as a future experiment direction only; an endpoint that streams but cannot be assigned is treated as an upstream filtering failure.

## Workstreams

| WS | Branch | Worktree | Scope |
|----|--------|----------|-------|
| W1 | fix/baseurl-relative-chaining | baseurl-relative-chaining | foreign-origin failover + no-probe exclusion + directory literals + CONTEXT.md entry + ADR rationale + provenance pinning tests |
| W2 | fix/header-endpoint-scoping | header-endpoint-scoping | header identity per endpoint + value attribute + date removal + typed surface update |
| W3 | fix/typist-systems-extension | typist-systems-extension | recall-biased gate + System description verbatims + overwrite contract |
| W4 | fix/assigner-l1-graph-block | assigner-l1-graph-block | L1 graph posted in the assigner human message (contracts/descriptions/attributes/edges), live per dispatch |

Docs branch: `fix/streamed-pipeline-corrections` (diagnosis docs + this plan).

## Rollout

1. Merge W1-W4 and the docs branch into dev (fast-forward dev to origin/dev first), push.
2. Advance the eval instance worktree to the new dev sha; force-recreate the agent container (new Langfuse org keys applied to the instance .env).
3. Launch the formal arm J trials (comfyui, white-jotter) with the established launcher; monitor with tight feedback loops.
4. Measure with the established framework (`/measure-experiment-results` approach; criteria + Langfuse pulls).

## Progress log

- 2026-10-16: plan written; workstreams W1-W4 dispatched to implementation agents.
- 2026-10-16 (late): the first relaunch at `eee67406` caught a STALE `header_unique` constraint LIVE.
  W2 moved the Header identity to `{name, endpoint, baseurl}`, but `db/neo4j/schema.py` still declared `(name, value, baseurl, project_id)`.
  Every second endpoint under one BaseURL returning an identical header value tripped the old key, so the curator dropped 1337 header deltas from the graph and the analysis feed in four minutes (fail-open warnings only).
  Hotfix branch `fix/header-constraint-reconcile` (`d7891d8`, merged `1163f33`): constraint updated; `init_schema` now reconciles a changed declaration against the live constraint (drop + recreate on key-set drift; undeclared constraints untouched); the unit tier pins the reconcile decision and the live tier asserts the applied header key set.
  E2E: a controlled two-delta probe raises ConstraintValidationFailed pre-fix and passes post-fix; the live DB migrated on agent restart; the declared-vs-live drift check is clean (16 declared, 3 L1 extras).
  The killed pre-fix attempt wrote no trial record (records are written at completion) and must never be measured.
- 2026-10-16 (late): formal trials relaunched on `1163f330` (stack fingerprint `542674eafc426da98ce66ed19ea47892faf633d67a243388d8299f96ab1ab3fe`), comfyui-1 first, then white-jotter-1.
