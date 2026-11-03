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
| ComfyUI | `e2e-comfyui-20261103T025611Z` | `frontier_empty` (complete) | 30.1 s | 564 | 538 | 52 | 482 | 11 | 1 | 0 | 0 | 0 | 546 / 18 | 13.3 MB | 0.4 MB |
| SiyuCMS | `e2e-siyucms-20261103T023716Z` | `session_deadline` (partial) | 951.2 s | 11,811 | 186 | 5,657 | 66 | 0 | 6 | 106 | 6 | 1 | 611 / 11,200 | 200.4 MB | 19.1 MB |
| PrestaShop | `e2e-prestashop-20261103T071922Z` | `session_deadline` (partial) | 963.8 s | 10,793 | 117 | 67 | 71 | 0 | 1 | 61 | 1 | 0 | 1,241 / 9,552 | 67.6 MB | 0.2 MB |

All runs: 0 edge rejections, 0 unrecoverable pages, the session catalogue clean after the stop, and the `steel_crawl` job `success`.

The two authenticated targets stop at the 15-minute wall (`session_deadline`), not the 300-action cap.
The frontier is time-bounded, not exhausted; the partial flag is correct.

## 2. N1 - N9 results

| id | requirement | result | evidence |
| - | - | - | - |
| N1 | no secret in the evidence | pass | the summary, the phase result, and the recon stats carry no cookie, token, or non-degenerate password. The SiyuCMS seeded credential is degenerate (`password == username == "admin"`), and `admin` is a legitimate path segment; the check excludes a password equal to the public username, and keeps cookie/token values strict. |
| N2 | no source-map request | pass | no edge artifact URL contains `.map` or `sourceMappingURL` on any target. |
| N3 | scope is the base host plus subdomains | pass | every navigated page is `t-1618c524.target`; every graph `Endpoint` is anchored to it. SiyuCMS captures external analytics subresources as evidence; the noise filter keeps them out of the graph. |
| N4 | no forbidden action executed | pass | the removed fingerprints and the executed action fingerprints are disjoint on every run. The SiyuCMS run removed the login form and the logout control and declared the login form endpoint without submitting it. |
| N5 | capture completeness | pass | every page has a document flow; every run has scripts and bodies; `edge.created` equals the ledger artifact count (after dedup); the ComfyUI flow-only run produced a non-empty v2 manifest. |
| N6 | bounded runtime and action cap | pass | every run is bounded by 900 s; the wall stop is `session_deadline`; the action cap is `operator_cancel` with exactly `STEEL_CRAWL_MAX_ACTIONS`; finalize runs in every case. |
| N7 | determinism and schema stability | pass | every manifest is `steel-crawl/v2`; the v1 parser still consumes the same delta vocabulary; the run/stats counts are internally consistent. Repeated ComfyUI runs differ in flow count (cache state), never in schema or invariants. |
| N8 | observability and traceability | pass | the recon run is `complete`, one `steel_crawl` job is `success`, the graph endpoint/parameter count equals the noise-filtered parser count, the ledger and edge are readable, and the session catalogue is clean. |
| N9 | resource bounds on hostile surfaces | pass | the URL cap, parameter-name cap, parameter dedup, realtime frame caps, ledger body dedup, and flush dedup keep the run proportional to the distinct capture budget. The same PrestaShop crawl that previously produced a 5.3 GB ledger and a 2.6 GB manifest (and was OOM-killed at 13.7 GB RSS) now produces a 67.6 MB ledger and a 0.2 MB manifest. |

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

## 4. Residual risks and limits

- **Coarse effect signal.** `state_key` uses `(normalized URL, ax_hash, overlay_flags)`. A local-state mutation that changes neither the accessible tree nor an overlay is not a new state. This is the accepted coarse signal; the crawl still submits a form once per `(state, fingerprint)`.
- **Authz residual risk.** The crawl records the authenticated surface it reached; it does not prove that a lower-privileged account is denied. Role-differential probing is out of scope.
- **Time-bounded coverage.** SiyuCMS and PrestaShop stop at 900 s. The counts above are a measured sample, not a proof of full frontier exhaustion.
- **External subresources.** The edge captures external analytics flows; the graph keeps only the target host. The evidence therefore contains third-party URLs, and the manifest does not.
- **Deployed API lag.** The deployed app API predates `overview.auth_probe`. The scaffold places the API-valid overview and writes the full file to `/srv/data/<project>/auth/overview.yaml`; the runtime store reads that file. A deployed API upgrade removes the workaround.
- **Static gateway in the harness.** The crawl walkthroughs use a deterministic gateway verdict for the already-minted account; the gateway's own model turn is covered by `tests/e2e/test_gateway_*` and `eval/steel-e2e-395`. The crawl still runs the real authenticated-context oracle.
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
