# steel_crawl - live non-functional report

**Date:** 2026-11-03.
**Scope:** the three live targets on the eval server: ComfyUI (no auth), SiyuCMS (admin form login), PrestaShop (back-office cookie).
**Gate:** `tests/e2e/test_steel_crawl_e2e.py`; the catalogue is `ASSERTIONS.md`.
**Method:** each run starts a real target stack, mints a real pre-authenticated Steel session in the deployed agent container, places the real AuthContext and project `authn` skill through the app API, and runs the production `steel_crawl` phase with `run_pipeline(..., job_subset=["steel_crawl"], with_analysis=False)`.
The gateway verdict is a static selection of the already-minted account so the crawl's own latency is measured; the gateway's live turn is covered by its own e2e suite.
Every other component is the deployed one: the Steel CLI, the raw-CDP sidecar, the Jev policy (TypeSafe SystemOne), the ledger, the HTTP-history edge, the parser, the curator, and the graph.

## 1. Measured runs

| target | run | stop | wall | flows | endpoints | parameters | scripts | realtime | pages | actions | removed | declared | edge created/dupes | ledger | manifest |
| - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |
| ComfyUI | `e2e-comfyui-20261103T135159Z` | `frontier_empty` (complete) | 29.8 s | 560 | 538 | 32 | 482 | 9 | 1 | 0 | 0 | 0 | 542 / 18 | 13.2 MB | 0.5 MB |
| SiyuCMS | `e2e-siyucms-20261103T091856Z` | `session_deadline` (partial) | 941.3 s | 12,863 | 184 | 16 | 67 | 0 | 7 | 109 | 6 | 1 | 700 / 12,163 | 47.7 MB | 0.2 MB |
| PrestaShop | `e2e-prestashop-20261103T075740Z` | `session_deadline` (partial) | 950.7 s | 10,654 | 117 | 68 | 71 | 0 | 1 | 59 | 1 | 0 | 1,190 / 9,464 | 64.4 MB | 0.2 MB |

All runs: 0 edge rejections, 0 unrecoverable pages, the session catalogue clean after the stop, and the `steel_crawl` job `success`.
The final SiyuCMS and PrestaShop runs report `session_closed=true` from the engine itself; the earlier runs' catalogues were empty after the stop.

## 2. Count audit: manifest counts versus graph counts

The run table reports **manifest** statistics. The knowledge graph is smaller by construction: the curator drops static and out-of-scope records, and the graph `MERGE` keys on the record identity. The difference is not lost evidence.

### ComfyUI: 538 endpoints

- The 538 observed endpoints reduce to **57 graph endpoints** after the vendor-script classifier:
  - 17 under `/assets/` (the application chunks), 16 under `/extensions/`, 5 under `/scripts/`, 18 under `/api/`, and 1 root.
  - 435 of the 452 `/assets/` endpoints are third-party PrimeVue modules: 268 `lib/primevue`, 156 `lib/@primevue`, and 11 `lib/@primeuix`. They are real library source and theme data, not application code. The classifier drops them from the graph and keeps them as `ScriptAsset` evidence.
  - 19 generated vendor bundles (5.3 MB total with the app chunks) are already dropped by the generated-bundle rule before the vendor classifier.
- The filter drops 34 parser endpoints: 31 static (CSS, fonts, images) and 3 external (CDN). The vendor classifier drops 435 library scripts; the remaining difference is the script-channel duplicate.
- The final run has 32 manifest parameter records and 6 graph parameters. The extra records are vendor-path, static, or duplicate variants; the graph keeps only `/api/history` and `/api/userdata` query keys.
- The manifest endpoints are unique. The 435 library scripts are structural duplicates of the observed library URLs; the graph `MERGE` and the vendor rule remove them, so they do not inflate the graph.
- **Verdict:** the 538 is a legitimate capture count, but it is not 538 application routes. The 57-node graph is 38 application/custom scripts, 18 API routes, and the root. The PrimeVue library family is third-party source and does not belong in the target graph.

### Vendor-script sample audit

Twenty samples from the live target and the crawl ledger show two families:

| sample family | examples | size and lines | minified | target `/api/` | verdict |
| - | - | - | - | - | - |
| Application chunks | `index--PH2IHOc.js`, `index-CLA0XGYE.js`, `GraphView-*.js`, `ComfyQueueButton-*.js`, `audioService-*.js`, `mathUtil-*.js` | 502 B to 1.64 MB; 3 to 84 lines; 1.4% to 4.2% whitespace | yes (Vite/Rollup) | the main bundle has `/api/download/models/833921`; the smaller chunks import the API client | legitimate JS analysis surface; source maps present; no `_0x` obfuscation |
| PrimeVue library | `lib/primevue/button`, `lib/primevue/dialog`, `lib/primevue/datatable`, `lib/@primevue/core/config`, `lib/@primeuix/styled`, `lib/@primevue/themes/aura/button` | 123 B to 272 KB; 4 to 6,425 lines; 9% to 34% whitespace | no; readable library source or theme tokens | none | third-party library; noise as a target Endpoint |

The main `index--PH2IHOc.js` is truncated at the 1 MB body cap (declared 1.64 MB). The source map sits beyond the captured prefix; the JS analysis phase must fetch it. The library modules have source maps too, but their content carries no target-specific surface.

The classifier uses the vendor roots above. A vendor-path script whose body carries `/api/`, the target host, `/graphql`, `/rest/`, `/wp-json/`, or `/ajax` stays in the graph. The `ScriptAsset` record keeps every vendor URL for version analysis, so a known outdated jQuery or CKEditor path is still visible.

The path rule is not 100% proof. Application code can live under `/lib/` (Magento-style layouts, custom Node apps, monorepo shared modules), and a vendor file can carry target configuration. The content signal covers the common cases; a project-specific allowlist can cover the rest.

### SiyuCMS: 5,657 parameters

- The 5,657 manifest records split by position into 5,606 path, 46 query, and 5 body records.
- The parser reduces them to 2,587 records; the filter to 2,534; the graph identity set to **28** before the fix.
- The 5,657 to 28 difference is a **99.5% duplicate/noise rate**:
  - 2,482 records are `uploads_id` on 21 image files under `/uploads/YYYYMMDD/<hash>.png`; each image repeats 100 to 210 times.
  - The remaining bulk is a family of base64 data-URI path names (128 repeats each); the current URL and parameter-name caps remove them from a new crawl.
  - The legitimate survivors are `search` (query) and the five login/register fields (`username`, `password` on login; `email`, `password`, `password2` on register).
- **The 22 false positives:** 21 `uploads_id` parameters on the image date directories and 1 `plugins_id` parameter on the `select2` directory of a static JavaScript URL. The old curator did not remove them because `/uploads/` is a preserve segment and the `.js` endpoint is surface by D17.
- The old curator did remove 26 static CSS `plugins_id` records and 1 external `date` parameter on `/ad.js`.
- **The fix:** the extractor no longer mints a path parameter from a URL whose final segment has a static-file extension. The curator also drops such a path parameter from any historical manifest. Replaying the saved SiyuCMS manifest through the current filter gives **6 unique parameter identities**, exactly the search query and the five form fields.
- **The final run:** `e2e-siyucms-20261103T091856Z` has 184 manifest endpoints and 16 manifest parameters. The graph has **78 endpoints** and **6 parameters**:
  - 78 endpoints: 28 `/template/`, 21 `/uploads/`, 19 `/static/`, 8 `/index/`, 1 `/index.php/`, and 1 root. Ten are application routes; the rest are theme, upload, and static assets kept by the preserve/JavaScript recall bias.
  - 6 parameters: `search`, `email`, `password`, `password2` (register), `username`, `password` (login).
  - The other 10 manifest parameters are one external `date` on `/ad.js` and nine inline image data-URI path segments. The existing out-of-scope filter drops them.
- **Verdict:** the 5,657 is not a legitimate parameter count. It is duplicate observation plus two path-identifier false-positive families. The final run writes 6 legitimate parameters and keeps the file endpoints for upload and theme evidence.

### Where the filter runs

`curator.curate` calls `filter_deltas` before the graph write. `filter_deltas` drops static endpoints, out-of-scope hosts, parameters anchored to static paths, and path parameters on static-file URLs. The graph `MERGE` then collapses the remaining duplicate identities. The saved SiyuCMS graph still shows the historical 28; the next run writes 6.

The two authenticated targets stop at the 15-minute wall (`session_deadline`), not the 300-action cap.
The frontier is time-bounded, not exhausted; the partial flag is correct.

## 2. N1 - N10 results

| id | requirement | result | evidence |
| - | - | - | - |
| N1 | no secret in the evidence | pass | the summary, the phase result, and the recon stats carry no cookie, token, or non-degenerate password. The SiyuCMS seeded credential is degenerate (`password == username == "admin"`), and `admin` is a legitimate path segment; the check excludes a password equal to the public username, and keeps cookie/token values strict. |
| N2 | no source-map request | pass | no edge artifact URL contains `.map` or `sourceMappingURL` on any target. |
| N3 | scope is the base host plus subdomains | pass | every navigated page is `t-1618c524.target`; every graph `Endpoint` is anchored to it. SiyuCMS captures external analytics subresources as evidence; the noise filter keeps them out of the graph. |
| N4 | no forbidden action executed | pass | the removed fingerprints and the executed action fingerprints are disjoint on every run. The SiyuCMS run removed the login form and the logout control and declared the login form endpoint without submitting it. |
| N5 | capture completeness | pass | every page has a document flow; every run has scripts and bodies; `edge.created` equals the ledger artifact count (after dedup); the ComfyUI flow-only run produced a non-empty v2 manifest. |
| N6 | bounded runtime and action cap | pass | every run is bounded by 900 s; the wall stop is `session_deadline`; the action cap is `operator_cancel` with exactly `STEEL_CRAWL_MAX_ACTIONS`; finalize runs in every case. |
| N7 | determinism and schema stability | pass | every manifest is `steel-crawl/v2`; the v1 parser still consumes the same delta vocabulary; the run/stats counts are internally consistent. Repeated ComfyUI runs differ in flow count (cache state), never in schema or invariants. |
| N8 | observability and traceability | pass | the recon run is `complete`, one `steel_crawl` job is `success`, the graph endpoint/parameter count equals the noise-filtered parser count, the ledger and edge are readable, the engine reports `session_closed=true`, and the session catalogue has no entry after the stop. |
| N9 | resource bounds on hostile surfaces | pass | the URL cap, parameter-name cap, parameter dedup, realtime frame caps, ledger body dedup, and flush dedup keep the run proportional to the distinct capture budget. The same PrestaShop crawl that previously produced a 5.3 GB ledger and a 2.6 GB manifest (and was OOM-killed at 13.7 GB RSS) now produces a 64.4 MB ledger and a 0.2 MB manifest. |
| N10 | vendor script legitimacy | pass | the ComfyUI graph has 57 endpoints: 17 application `/assets/` chunks, 16 `/extensions/`, 5 `/scripts/`, 18 `/api/`, and the root. The 435 PrimeVue library scripts are `ScriptAsset` evidence, not endpoints; the app chunks stay. The classifier keeps a vendor-path body that carries `/api/`, the target host, `/graphql`, `/rest/`, `/wp-json/`, or `/ajax`. |

## 2.1 HTTP-history database verification

The crawler writes `http-artifact/v1` records to the per-project SQLite store through the authenticated edge.
The database change was verified in the contract tier and on the deployed topology.

- `tests/kali/test_http_history_store.py` covers the WAL mode, project isolation, content-addressed bodies, body durability, the schema-version guard, retention, and the read path.
- `tests/kali/test_http_history_edge.py` covers the bearer token, the 100-artifact and 8 MiB caps, the created/duplicate/rejected counts, the base64 body map, the real `record_if_absent`, and a crawler-to-edge-to-read-service roundtrip.
- `tests/recon/crawl/steel/test_history.py` covers the normalizer, the deterministic content id, replay lineage, the batch caps, the retry cursor, and the URL-cap fact.
- The live check started the edge in the Kali container on port 8002 with a bearer token and `/data` as the store root.
  The agent normalized a capped flow, flushed it twice, and read it back through `HttpHistoryService`.
  The first flush created one artifact; the second counted one duplicate.
  The store reported `artifact_count=1`, `body_count=1`, and `schema_version=http-artifact/v1`.
  The URL-cap fact and the body bytes survived.
  The temporary project and edge process were removed after the check.
- The deployed entrypoint was verified after a Kali and agent restart: both services carried the shared compose token, the entrypoint logged `HTTP-history edge ready on 0.0.0.0:8002`, and the agent posted a synthetic artifact to `http://kali:8002`; the read service returned it and counted the duplicate.
- The three-target gate uses the same edge code in-process (`eval/steel-crawl-e2e/phase_runner.py`), so the edge and store are not mocked in the crawl walkthroughs.

## 3. Defects the live gate found and fixed

1. **Restore invalidated the CLI refs.** A rollback reloads the document, and the compact snapshot's `@ref` values are document-scoped. The engine now takes exactly one fresh snapshot after a restore and re-projects the cached candidates; the root starts without an initial restore.
2. **The wall stop was reported as the action cap.** The deadline and the action cap now have separate predicates; `session_deadline` and `operator_cancel` are distinct stop reasons.
3. **A nested `value_shape` was written to Neo4j.** The graph cannot store a nested map. The parser flattens it to `value_shape_type` and `value_shape_length_band`; a unit predicate asserts every graph property is scalar.
4. **Static-path parameters survived the endpoint filter.** A parameter anchored to a dropped static endpoint could re-create it through the edge MERGE. The filter now drops parameters whose `endpoint_path` is static, and a payload-sized path segment is not a parameter name.
5. **The ledger and manifest were unbounded.** A 162 KiB base64 path segment became a parameter name on every flow. The run produced a 5.3 GB ledger and a 2.6 GB manifest, and the phase runner was OOM-killed at 13.7 GB RSS. The fixes:
   - a 2 KiB request-URL cap with the original length in the artifact;
   - a 256-character parameter-name cap;
   - one manifest record per parameter identity;
   - one ledger body per distinct digest, with the flush attaching it once;
   - a 16 KiB realtime frame prefix, an 8 MiB per-run payload budget, and a 20,000-frame cap, with size and digest always recorded.
6. **PrestaShop admin controllers returned 500 on a fresh target.** This is a target runtime defect, not a crawl defect:
   - the Symfony cache was root-owned when the bootstrap scripts ran as root;
   - the 30 s PHP limit is shorter than the ~100 s cold container compile on the emulated amd64 host;
   - the Steel CLI's CDP navigate timeout is shorter than that compile.

   The scaffold now runs the bootstrap as `www-data`, raises the PHP limit to 300 s, and warms the entry page in-container before the browser navigates.
7. **The safety check compared element ids across pages.** Element ids are page-local (`e5`, `n13`), so a removed element on one page and an executed element on another could collide or mask a real overlap. The action record now carries the element fingerprint, and the check compares fingerprints.
8. **The evidence read stopped at the first edge page.** The phase runner read only the first 200 edge artifacts, so a submitted form whose 2xx response fell outside that page looked failed. The runner now paginates every edge artifact.
9. **The URL-cap fact was silently dropped.** The normalizer passed `url_truncated` and `url_original_length` into the local `RequestRecord`, but the model did not declare the fields; pydantic's default `extra=ignore` discarded them. The edge stored a clipped URL as the real one. The fields are declared, the read views expose them, and a cross-model field-set test prevents the next drift.
10. **The edge port collided with the eval MCP server.** The edge defaulted to 8001, but the eval instance runs a second MCP server on 8001. The edge now defaults to 8002, and the deployment test asserts the edge port is distinct from the MCP port. A failed edge start is now logged loudly.

## 4. Residual risks and limits

- **Coarse effect signal.** `state_key` uses `(normalized URL, ax_hash, overlay_flags)`. A local-state mutation that changes neither the accessible tree nor an overlay is not a new state. This is the accepted coarse signal; the crawl still submits a form once per `(state, fingerprint)`.
- **Authz residual risk.** The crawl records the authenticated surface it reached; it does not prove that a lower-privileged account is denied. Role-differential probing is out of scope.
- **Time-bounded coverage.** SiyuCMS and PrestaShop stop at 900 s. The counts above are a measured sample, not a proof of full frontier exhaustion.
- **External subresources.** The edge captures external analytics flows; the graph keeps only the target host. The evidence therefore contains third-party URLs, and the manifest does not.
- **Deployed API lag.** The deployed app API predates `overview.auth_probe`. The scaffold places the API-valid overview and writes the full file to `/srv/data/<project>/auth/overview.yaml`; the runtime store reads that file. A deployed API upgrade removes the workaround.
- **Static gateway in the harness.** The crawl walkthroughs use a deterministic gateway verdict for the already-minted account; the gateway's own model turn is covered by `tests/e2e/test_gateway_*` and `eval/steel-e2e-395`. The crawl still runs the real authenticated-context oracle.
- **Steel session churn.** One ComfyUI rerun failed in target setup at `steel navigate` with `CDP error (Page.navigate): Session with given id not found`; a clean rerun passed in 231 s. The scaffold mints a fresh session per run, and the Steel runtime can lose a session between start and the first attach. The crawl reports `unknown_session` or `session_missing` cleanly in that case; it never starts a replacement.
- **The seeded SiyuCMS credential is degenerate.** `password == username == "admin"`; the target should be re-seeded with a distinct password. The N1 check is honest about the identifier but cannot distinguish the password from a path segment in that deployment.

## 5. Reproduction

```
rsync -a --delete --exclude .git --exclude .venv --exclude __pycache__ \
  ./ eval-server-polyphemus:/opt/steel-crawl-e2e/
ssh eval-server-polyphemus
cd /opt/steel-crawl-e2e
STEEL_CRAWL_E2E=1 STEEL_CRAWL_E2E_REPO=/opt/steel-crawl-e2e \
  /opt/eval-venv/bin/python -m pytest tests/e2e/test_steel_crawl_e2e.py \
  -k <target> -s -q --confcutdir=/opt/steel-crawl-e2e/tests/e2e
```

The catalogue (`ASSERTIONS.md`) names every predicate and its yielding assertion; the operator runbook (`OPERATOR.md`) names every prerequisite and failure branch.

## 6. Final verification note

The final PrestaShop run (`e2e-prestashop-20261103T075740Z`) reached `session_deadline` in 950.7 s and recorded `session_closed=true`.
The operator SSH client was interrupted by its own timeout after the run finished, so the pytest process did not print its summary line.
The run's persisted evidence was then checked with the test module's own `_assert_common` and the PrestaShop-specific assertions; all passed, including the graph counts, the safety fingerprints, the form check, the secret check, and the session lifecycle.
