# GT unit well-formedness - arm J outcome assessment (Task Area 2, W2.3)

Status: complete (2026-10-17); corrected baseline added 2026-10-18 (section 2.4).
Branch: `feat/recon-coverage-and-eval-wellformedness`.
Plan: `docs/design/plans/2026-10-17-recon-coverage-and-eval-wellformedness.md`, W2.2 + W2.3.
Amendment 2026-10-18 (operator rulings): the M3 Service spine and the capability-gap statement handling were corrected (section 2.4); the corrected numbers are the arm K comparison baseline.
The original 2026-10-17 readings stay visible in sections 2.1-2.3 and are labelled as superseded where they change.

This document reports how well the four arm J produced graphs represent the ground-truth units of the vulnerability corpus.
It also reports Goal 2: the analysis-phase-only caching ratio against the 70% target.

## 1. What was measured

### 1.1 The criterion

Metric instrument: `tools/measure_gt_wellformedness.py` (D4) with unit tests at `tests/tools/test_measure_gt_wellformedness.py`.
Ground-truth specs: one `unit-spec.yaml` per bundle (D3) in the local corpus at `~/.local/share/polymerhus/vuln-groundtruth/<target>/<bundle>/unit-spec.yaml`.

Metrics per spec, as fixed by the plan (W2.2):

- M1 placement (gate): the produced L1 node that matches the unit key exists.
- M2 L0 grounding: share of required L0 items (endpoints and parameters) aggregated by the produced unit.
  For Service units the tool reads the unit's own `AGGREGATES` edges.
  For System units it reads the endpoints surfaced through the linked services, mirroring `attack.hunting.unit_projection`.
  An `EVIDENCED_BY` edge is accepted as the fallback.
- M3 typed backbone: share of required backbone items present and non-empty.
  For Service units the spine is the Service's own props: `business_function` resolves the managed `business_function_slug` prop, and the mechanism slots `api_paradigm` and `auth_methods` are System-side - measured by M4 as `EXPOSED_VIA -> RESTApi/GraphQLApi` and `AUTHENTICATED_BY -> AuthenticationMechanism` - and are not Service requirements (operator ruling 2026-10-18).
  For System units the backbone is the node description plus the threat-modeller sufficiency statements (keyword coverage over the node text); a statement declared `satisfied_by: capability_gap` counts as satisfied-by-declaration (operator ruling 2026-10-18).
- M4 service-to-system edges: share of required typed edges present.
  For Service units the requirement is outbound (`rel` plus target kind and discriminator mode).
  For System units the requirement is inbound: the GT Services that must carry an edge to the System.

Unit score = mean(M2, M3, M4), gated by M1 (a placement miss scores 0.0).
Target score = mean over the specs of one run.

Matching rules are strict where the corpus is strict: endpoint identity is (method, path), with a path-only match reported as `METHOD_MISMATCH`.
Parameter identity is (name, owning endpoint path), with position mismatches reported.
The spec declares the discriminator mode per edge (`exact`, `kind_any`, `any_of`).
WebPresentation targets and singletons use `exact`; shared RESTApi overlays use `kind_any` and record the actual discriminator.

Known limits, stated for honesty:

- The System statement check is a keyword proxy over the node text, not a semantic judgment.
- `kind_any` accepts a RESTApi overlay under any discriminator, because the pipeline's convention uses shared overlays (`core-rest`, `manager-rest`, `same-origin-json-api`) where the corpus authors per-service names (`<slug>::rest`).
- Capability-gap carriers declared in the specs (path-position file names, JSON body fields) are excluded from M2 by design.
- A statement the spec itself declares a capability gap (wj-004's log sink and outbound lookup) is satisfied-by-declaration, not by evidence: the chain's own `capability_gaps` text names it unobservable.

### 1.2 The spec format (D3)

Each spec carries: `schema: gt-unit-spec/v1`, `bundle`, `vulnerability` (type, fault class, location), `unit` (kind plus match: `business_function_slug` for Services, `kind` + `discriminator` for Systems), `typed_backbone.required`, `edges_to_l0` (`mode`, `endpoints`, `parameters`, `capability_gaps`), `service_to_system_edges` (`mode`, `required`), and `threat_modeller_sufficiency` statements for System units.

Sources for every field: `l1-profile.md` (render block and field notes), `l0-surface.yaml`, and `chain.md` inside the bundle.
The 13 bundles cover 11 distinct units; `Service:user-data-file` (comfyui-001/002) and `System:AuthorizationSystem` (white-jotter-002/004) appear twice with chain-specific requirements.

## 2. Results

### 2.1 Target scores

| run | project id | target score |
|---|---|---|
| comfyui base | `2df3ad9d-eb9c-4789-a118-44139a745ca2` | 0.25 |
| comfyui formal | `d04b947f-d6c3-48be-9b18-1c4eef851241` | 0.28 |
| white-jotter base | `bf0d9408-d403-457f-b769-076dd9cd9138` | 0.33 |
| white-jotter formal | `f16de150-b032-4566-871b-2df6fa4d48a9` | 0.50 |

No run reaches the well-formedness bar; the formal white-jotter run is the best at half.
M1 passes for all 13 specs in all four runs: the analyser always placed the unit under the right name.

### 2.2 Per-unit scores across the four runs

| spec | unit | comfyui base | comfyui formal | wj base | wj formal |
|---|---|---|---|---|---|
| comfyui-001 | Service:user-data-file (CWE-200) | 0.13 | 0.13 | - | - |
| comfyui-002 | Service:user-data-file (CWE-79) | 0.13 | 0.13 | - | - |
| comfyui-003 | Service:image-upload (CWE-79) | 0.47 | 0.47 | - | - |
| comfyui-004 | Service:image-viewing (CWE-22) | 0.51 | 0.51 | - | - |
| comfyui-005 | Service:manager-preferences (CWE-79) | 0.13 | 0.30 | - | - |
| comfyui-006 | Service:model-download (CWE-918) | 0.13 | 0.13 | - | - |
| wj-001 | Service:account-sign-in (CWE-1392) | - | - | 0.47 | 0.60 |
| wj-002 | System:AuthorizationSystem (CWE-284) | - | - | 0.13 | 0.61 |
| wj-003 | Service:article-publishing (CWE-79) | - | - | 0.36 | 0.36 |
| wj-004 | System:AuthorizationSystem (CWE-94) | - | - | 0.07 | 0.63 |
| wj-005 | Service:book-search (CWE-89) | - | - | 0.47 | 0.47 |
| wj-006 | Service:book-cover-serving (CWE-22) | - | - | 0.47 | 0.47 |
| wj-007 | Service:account-registration (CWE-639) | - | - | 0.36 | 0.36 |

### 2.3 Metric-level reading

- M2 endpoints (formal runs): 6 of 24 required endpoints are aggregated (comfyui 1/13, wj 5/11).
  The single comfyui match is `GET /view` on image-viewing.
- M2 parameters: 0 of 17 required parameters are aggregated in every run, both targets.
  L0 `Parameter` nodes exist (`keywords` on `/api/search`, `rid` on `/admin/role/menu`, `EXPR` on the comfyui view routes), yet no Service aggregates any.
- M2 System units: wj-002 formal reaches 1/3 through linked services (`GET /api/admin/user`); wj-004 formal reaches 1/1.
  The base run reaches 0 on all System endpoints, because the base analyser attached no service to the AuthorizationSystem on those routes.
- M3 Services: the value 2/5 is invariant across all runs and all Services.
  `exposure` and `service_contract` are present; `api_paradigm`, `auth_methods`, and `business_function` are absent.
- M3 Systems: wj-002 formal covers all five items (description plus all four statements, including the 302-redirect refusal shape and the per-route filter).
  wj-004 formal covers two of five: the description and the route name, but not the log sink, the parameter carrier, or the lookup semantics.
- M4 (formal runs): 17 of 30 required edges are present (comfyui 5/13, wj 12/17).
  Missing comfyui edges follow the missing aggregates (`user-data-file`, `model-download`, `manager-preferences`).
  In white-jotter the misses are specific: `AUTHORIZED_BY` from `account-registration`, `EXPOSED_VIA RESTApi` from `article-publishing` and `book-search`.

### 2.4 Corrected baseline (2026-10-18)

Operator rulings corrected three criterion inputs; the tool and the corpus specs were amended, and the tool keeps 15 unit tests plus a clean 13-spec lint.

- The Service spine counts `business_function` (the managed `business_function_slug`), `exposure`, and `service_contract`.
- `api_paradigm` and `auth_methods` left the Service requirements: the domain model places them System-side (`docs/design/l1-domain-model-catalogue.md` section 3), and M4 already measures the edges.
- wj-004 statements S1 (log/principal) and S4 (lookup) carry `satisfied_by: capability_gap`, matching the spec's own declared capability gaps.

Corrected target scores:

| run | project id | before | corrected |
|---|---|---|---|
| comfyui base | `2df3ad9d-eb9c-4789-a118-44139a745ca2` | 0.25 | 0.45 |
| comfyui formal | `d04b947f-d6c3-48be-9b18-1c4eef851241` | 0.28 | 0.48 |
| white-jotter base | `bf0d9408-d403-457f-b769-076dd9cd9138` | 0.33 | 0.49 |
| white-jotter formal | `f16de150-b032-4566-871b-2df6fa4d48a9` | 0.50 | 0.66 |

Corrected per-unit scores:

| spec | comfyui base | comfyui formal | wj base | wj formal |
|---|---|---|---|---|
| comfyui-001 | 0.33 | 0.33 | - | - |
| comfyui-002 | 0.33 | 0.33 | - | - |
| comfyui-003 | 0.67 | 0.67 | - | - |
| comfyui-004 | 0.71 | 0.71 | - | - |
| comfyui-005 | 0.33 | 0.50 | - | - |
| comfyui-006 | 0.33 | 0.33 | - | - |
| wj-001 | - | - | 0.67 | 0.80 |
| wj-002 | - | - | 0.13 | 0.61 |
| wj-003 | - | - | 0.56 | 0.56 |
| wj-004 | - | - | 0.20 | 0.77 |
| wj-005 | - | - | 0.67 | 0.67 |
| wj-006 | - | - | 0.67 | 0.67 |
| wj-007 | - | - | 0.56 | 0.56 |

Reading: every produced Service now passes the spine 3/3, and every remaining deficit is a defect the D-classes name (M2 items, M4 edges).
wj-004's remaining M3 miss is S2 alone (the `username` carrier), which no L0 node witnesses.
These corrected numbers are the arm K comparison baseline.

## 3. Goal 2 - analysis-phase cache ratios

Source: the durable per-project usage surface, `GET http://127.0.0.1:8080/projects/{id}/usage` on the eval host.
Analysis-phase roles: `triager`, `assigner`, `mechanism_typist`.

| run | triager | assigner | mechanism_typist | analysis aggregate | mean of roles |
|---|---|---|---|---|---|
| comfyui base | 68.5% | 71.2% | 88.9% | 86.4% | 76.2% |
| comfyui formal | 63.7% | 69.9% | 91.3% | 88.6% | 75.0% |
| wj base | 65.0% | 71.8% | 90.2% | 87.8% | 75.7% |
| wj formal | 60.9% | 66.8% | 91.3% | 89.0% | 73.0% |

Verdict: Goal 2 is met on all four runs under either reading (aggregate 86.4%-89.0%, mean of roles 73.0%-76.2%), against the 70% target.
The weakest role is the triager (60.9%-68.5%); the typist is the cache anchor at 88.9%-91.3%.
`cache_detail_omitted` is 0 in every role of every run, so no reading is silent.

## 4. Diagnosed surface

Five defect classes explain the failures.
Each class names the layer that owns the fix.

### D-1 XHR-only manager surface (recon discovery; existing ticket #353)

All four comfyui manager-side specs (`user-data-file` x2, `manager-preferences`, `model-download`) score M2 0.0.
No Endpoint node in either comfyui run carries `userdata`, `manager`, or `queue` in its path.
The history store of the formal run contains 117 `userdata` URLs, including `GET /api/userdata?dir=.&recurse=true&split=false&full_info=true` (status 200) and `POST /api/userdata/hunt_marker.txt?overwrite=true` (status 200).
The routes exist and work; recon never minted them into L0.
This is the class already ticketed as #353 (client-side XHR routes behind a UI tab), now with a fresh evidence comment (2026-10-17); the measurement quantifies its outcome cost at four of six comfyui units ungrounded.

### D-2 Method-blind recon (recon probing; ticket #365)

Required endpoints that need POST are probed, minted, and reported as GET only.
Evidence per case:

- `POST /api/register` (wj-007): L0 holds `GET /api/register` (200, httpx); the history holds `GET /api/register` 200 and `POST /api/api/register` 405 - the POST was issued against the chained twin, not the real path.
- `POST /api/login` (wj-001): L0 holds `GET /api/login` (jsluice, status NULL); no POST record on the real path.
- `POST /api/admin/content/article` (wj-003): L0 holds GET only (jsluice); the only POST 200 on that path is a hunt-phase write.
- `POST /upload/image` and `POST /upload/mask` (comfyui-003): L0 holds `GET /upload/image` 404 and `GET /api/upload/image` 404; no POST was ever sent.

The GT units whose exploit chain is a write route therefore fail M2 at the recon layer, not at the analysis layer.

### D-3 History is not materialised into L0 (recon ingestion; feeds #353)

The formal comfyui run captured 33,554 flows; the produced graph holds 335 Endpoints and exactly one `steel`-sourced node (`GET /` 307).
No recon code path reads `history.sqlite3` into L0 endpoints (`rg history.sqlite3 src/polymerhus` finds no reader).
The triager can search those transactions; the L1 contract cannot reference them.
Everything the browser observed and the probers missed - manager routes, POSTs, query parameters - is invisible to every layer above recon.

### D-4 Parameter surface is unusable (recon minting #366; analysis proposals #367)

Two independent defects share one outcome (0/17 parameter items matched):

- Recon mints placeholder names. The comfyui `Parameter` nodes on the view routes are named `EXPR` and `EXPREXPREXPR` on `/view`, `/viewvideo`, `/api/view`, and `/internal/view`; the real names (`filename`, `subfolder`, `type`) arrive in captured query strings but never become node names.
- Analysis never aggregates `Parameter` nodes. The white-jotter graph holds a correct `keywords` Parameter on `/api/search`, and `book-search` still aggregates only the Endpoint.

### D-5 Typed spine mechanism slots are System-side (resolved, operator ruling 2026-10-18)

The earlier reading - "the pipeline re-homes `api_paradigm` and `auth_methods` away from the Service, and `business_function` is genuinely absent" - was wrong.
The operator's ruling, grounded in `docs/design/l1-domain-model-catalogue.md` section 3, corrected the criterion:

- `api_paradigm` and `auth_methods` are mechanism slots: System-side, reached by an edge (`EXPOSED_VIA -> RESTApi/GraphQLApi`; `AUTHENTICATED_BY -> AuthenticationMechanism`).
  They are no longer Service spine requirements, and M4 measures them where the GT expects them.
- `business_function` IS a Service attribute: the managed `business_function_slug` prop carries it, and the criterion now resolves the field to that prop.
- The Service spine is `business_function`, `exposure`, `service_contract`; every produced Service passes it (section 2.4).

### D-6 RESTApi discriminator convention (recorded, not scored)

Produced overlays are shared (`core-rest`, `manager-rest`, `same-origin-json-api`); the corpus authors per-service names (`<slug>::rest`).
The criterion scores these edges at kind level and records the actual discriminator, so the divergence is visible but is not counted as a failure.

## 5. Reproduce

Spec lint and unit tests:

```bash
python3 -m pytest tests/tools/ -q
python3 tools/measure_gt_wellformedness.py --lint
```

Live measurement (Neo4j is reachable only through the eval host):

```bash
ssh -f -N -L 17487:127.0.0.1:7687 eval-server-polyphemus
CREDS=$(ssh -q eval-server-polyphemus "grep -E '^NEO4J_(USER|PASSWORD)=' /opt/polymerhus-dev/eval/instances/eval-server-1/.env")
NUSER=$(echo "$CREDS" | sed -n 's/^NEO4J_USER=//p' | tr -d '"'); NPASS=$(echo "$CREDS" | sed -n 's/^NEO4J_PASSWORD=//p' | tr -d '"')
python3 tools/measure_gt_wellformedness.py --target comfyui --project d04b947f-d6c3-48be-9b18-1c4eef851241 \
    --label comfyui-formal --uri bolt://127.0.0.1:17487 --user "$NUSER" --password "$NPASS"
python3 tools/measure_gt_wellformedness.py --target white-jotter --project f16de150-b032-4566-871b-2df6fa4d48a9 \
    --label wj-formal --uri bolt://127.0.0.1:17487 --user "$NUSER" --password "$NPASS"
```

Goal 2 numbers (run on the eval host, the API is bound to its loopback):

```bash
ssh -q eval-server-polyphemus 'python3 - <<PY
import json, urllib.request
for pid in ("d04b947f-d6c3-48be-9b18-1c4eef851241", "2df3ad9d-eb9c-4789-a118-44139a745ca2",
            "f16de150-b032-4566-871b-2df6fa4d48a9", "bf0d9408-d403-457f-b769-076dd9cd9138"):
    u = json.load(urllib.request.urlopen(f"http://127.0.0.1:8080/projects/{pid}/usage"))
    roles = ("triager", "assigner", "mechanism_typist")
    c = sum(u["by_agent"][r]["context_tokens"]["cached"] for r in roles)
    n = sum(u["by_agent"][r]["context_tokens"]["uncached"] for r in roles)
    print(pid, f"{100.0 * c / (c + n):.1f}%")
PY'
```

Counter-evidence for D-1..D-4 (history store):

```bash
docker exec -i ph-dd131acc-kali-1 python3 - <<'PY'
import sqlite3
con = sqlite3.connect("file:/data/d04b947f-d6c3-48be-9b18-1c4eef851241/http-history/history.sqlite3?mode=ro", uri=True)
print(con.execute("SELECT count(*) FROM flows_fts WHERE url LIKE '%userdata%'").fetchone())
PY
```

## 6. Verdict

The analysis phase places every GT unit correctly, and it attaches the Systems where the underlying data allows it.
The well-formedness gap is dominated by the recon layer: unprobed client-side surfaces, GET-only probing, an unmined history store, and a placeholder-parameter surface.
Two white-jotter System specs show the intended behaviour at the analysis layer: `wj-002` states five of five threat-modeller facts in the formal run, and `wj-004` still lacks the JNDI-relevant facts (log sink, carrier, lookup).
Goal 2 passes with margin on all four runs.

Next: W2.4 and W2.5 select the relevant L0 chunks per GT unit and derive the optimal typist and assigner paths plus the failure-mode clusters (`docs/experiments/2026-10-17-typist-assigner-optimal-paths.md`).

Corrected baseline (2026-10-18, section 2.4): comfyui 0.45 base / 0.48 formal, white-jotter 0.49 base / 0.66 formal; these corrected numbers are the arm K comparison point.
