# Spec: Per-Endpoint Profiling (D16 discover-profile split, BUILT)

Status: ready-for-agent.
Branch: `fix/per-endpoint-profiling` (off `dev`).
Supersedes the D16 "Deferred (not built)" note in `recon-pipeline-forward-decisions.md` (the per-endpoint profiling split).
Relates to AMV-16-as-mislabelled-by-operator; the true anchor is D16/D27 in `recon-pipeline-forward-decisions.md`.

## Problem Statement

Recon profiles only BaseURLs, and a BaseURL profile is really the profile of its root `/` path.
A crawler- or JS-minted Endpoint such as `/api/v1/users`, discovered under a host whose root `/` serves HTML, is never itself classified.
Its host is labelled `webapp` from the root alone, so every deeper Endpoint inherits nothing and the API surface mounted under a non-API root is invisible.
The API-testing tools are gated on `BaseURL.profile`: `kiterunner` fires only where the root is `restapi`, `graphql-cop` only where the root is `graphql_api`.
Consequently an API mounted under a webapp root is never reached, and no produced Endpoint below `/` ever carries a `profile` the analyser or the tool gates can use.
From the operator's perspective: all produced endpoints must be profiled; profiling a BaseURL only ever profiles its root `/`, and that algorithm is defective by design.

## Solution

Every produced Endpoint is actively profiled, not just BaseURL roots.
The reprofile job is refactored so it consumes the Endpoint population and probes each Endpoint's own URL, deriving that Endpoint's `profile` from its own observed content-type via the existing `classify_profile` path.
The root `/` Endpoint is materialized for every BaseURL and profiled like any other Endpoint, so "profile the BaseURL" collapses to "profile its root `/` Endpoint" with no special BaseURL-level path.
`BaseURL.profile` is kept as a cheap mirror derived from the root `/` Endpoint's profile, so existing BaseURL readers (the analyser delivery-gate, current selectors) keep working while `Endpoint.profile` becomes the authoritative per-endpoint signal.
The API-testing tools are then re-scoped off the per-endpoint profiles: `graphql-cop` is pointed at the exact `graphql_api` Endpoints, and `kiterunner` is pointed at evidence-derived API-root prefixes computed from the host's `restapi` Endpoints.

## User Stories

1. As the recon operator, I want every produced Endpoint to carry a `profile`, so that the attack surface distinguishes API endpoints from web pages everywhere, not only at host roots.
2. As the recon operator, I want an Endpoint like `/api/v1/users` under a `webapp` root to be classified `restapi`, so that APIs mounted beneath a web root are no longer invisible.
3. As the recon operator, I want the root `/` Endpoint to exist and be profiled for every BaseURL, so that a host that crawlers only reached via deep paths still gets a baseline profile.
4. As the recon operator, I want `BaseURL.profile` to keep reflecting the root `/` Endpoint's profile, so that the analyser delivery-gate and existing selectors continue to work unchanged.
5. As the recon operator, I want the profiling pass to carry the project auth header, so that endpoints behind authentication return their true content-type instead of a login page and are not mis-profiled as `webapp`.
6. As the recon operator, I want endpoints deduplicated to a normalized path-template before probing, so that active per-endpoint profiling does not blow up request volume on a resource-constrained host.
7. As the recon operator, I want the profiling pass volume capped, so that a host exposing thousands of endpoints cannot exhaust the machine.
8. As the recon operator, I want `kiterunner` to fire against a host that exposes any `restapi` Endpoint, not only where the root `/` is `restapi`, so that APIs under a webapp root are enumerated.
9. As the recon operator, I want `kiterunner` scoped to an evidence-derived API-root prefix (for example `/api/` from `/api/v1/organizations`), so that it fuzzes under the real mount point rather than the host root.
10. As the recon operator, I want the API-root prefix cut before any version token, so that `kiterunner`'s own `v1`/`v2` wordlist entries fuzz the version position and discover unlinked or deprecated ("zombie") API versions.
11. As the recon operator, I want an endpoint with no API-noun in its path to fall back to its parent directory as the scan prefix, so that a JSON leaf under a plain path still yields a sensible fuzz base.
12. As the recon operator, I want the number of derived kiterunner targets per host capped, so that a host with many distinct API roots cannot fan out unboundedly.
13. As the recon operator, I want `graphql-cop` to audit the exact `graphql_api` Endpoint, so that a GraphQL surface at any path is audited, not only when the BaseURL root is GraphQL.
14. As the recon operator, I want Endpoints produced by the API tools themselves (`kiterunner`, `graphql-cop`) tagged with a profile by provenance, so that `Endpoint.profile` is complete without a second active-probe pass.
15. As the recon operator, I want the API-noun set to be a single maintained constant, so that the residual naming heuristic is small, explicit, and extensible.
16. As a downstream analyser, I want each Endpoint to expose a trustworthy `profile`, so that the surface model reflects REST/GraphQL/webapp per endpoint rather than per host root.
17. As a recon maintainer, I want the prefix-derivation to be a pure, deterministic function, so that it is unit-testable without a live network and honours the deterministic-first house rule.
18. As the recon operator, I want cross-domain APIs (for example `api.<tld>`) handled per-host by ordinary discovery and gating, so that no cross-domain scoping heuristic is needed as long as the host is in scope and enumerated.

## Implementation Decisions

### Profiling job (the reprofile refactor)

- Refactor the existing reprofile job so it consumes `Endpoint` instead of `BaseURL`.
It probes each Endpoint's own URL and derives that Endpoint's `profile` from its own content-type through the unchanged `classify_profile` path (reuse, not a new classifier).
- Materialize a root `/` Endpoint for every BaseURL when no crawler produced one, so the root is always present to be probed and every host receives a baseline profile.
- Keep `BaseURL.profile`, written as a mirror of the root `/` Endpoint's profile in the same pass.
`Endpoint.profile` is authoritative for the new per-endpoint gating; `BaseURL.profile` exists only for backward compatibility with existing BaseURL readers.
- The profiling pass carries the project auth header, exactly as the other request-based tools do.
- Endpoints are deduplicated to a normalized `(host, path-template)` key before probing, and the pass reuses the existing per-job concurrency ceiling, so active per-endpoint probing stays bounded on the constrained host.
- Position the profiling pass after all crawl/JS Endpoint producers and before the API-enumeration phases, so the per-endpoint profiles are available to gate `kiterunner` and `graphql-cop`.
- Endpoints produced by the API tools themselves are profiled by provenance rather than re-probed: a `kiterunner` Endpoint is `restapi` by construction, a `graphql-cop` Endpoint is `graphql_api` by construction.

### classify_profile

- `classify_profile` is extended to classify any probed Endpoint URL, not only a BaseURL and its root `/` Endpoint.
The existing content-type and host-label signals are unchanged; the change is that the parser now applies the classification to every probed Endpoint and stamps `Endpoint.profile`.

### kiterunner scope derivation (the evidence-derived prefix algorithm)

- `kiterunner` consumes `Endpoint` with `consumes_where` `profile == restapi`.
Because `AssetSelector` is a per-asset predicate that cannot aggregate over a host's endpoint set, a dedicated deterministic derivation runs in `kiterunner`'s input-preparation seam (the same seam `jsluice` already uses to bypass the plain command template).
- The derivation, per host, from that host's `restapi` Endpoints:
  - For each endpoint path, find the LAST segment that is an API-noun; the prefix is the path up to and including that segment.
  This keeps any non-standard mount before it (`/backend/api/v1/x` -> `/backend/api/`) and drops everything after it, versions included (`/api/v1/organizations` -> `/api/`; `/rest/v2/orders` -> `/rest/`).
  - Version tokens matching `^v\d+$` are NOT API-nouns and are never part of the prefix; they are left inside the fuzz space so kiterunner's wordlist discovers them, including zombie versions.
  - An endpoint whose path contains no API-noun falls back to its parent directory as the prefix (`/checkout/summary` -> `/checkout/`).
  - Group endpoints by derived prefix; each distinct prefix becomes one kiterunner scan target `<scheme>://<host><prefix>`.
  - Cap the derived targets per host at 3, keeping the prefixes that cover the most endpoints.
- The API-noun set is a single maintained constant:
`{api, apis, rest, restapi, graphql, gql, rpc, jsonrpc, grpc, soap, xmlrpc, gateway, data, internal, external, private, partner, edge, proxy}`.
Version handling is the separate `^v\d+$` pattern; versions are excluded from the prefix.
- Open verification for the implementer: confirm `kiterunner`'s base-URL / relative-route semantics against `routes-small.kite`, so a path-inclusive wordlist entry appended to a `/api/` base does not double-prefix.

### graphql-cop

- `graphql-cop` consumes the `graphql_api` Endpoint directly (`consumes = Endpoint`, `consumes_where` `profile == graphql_api`), targeting the exact endpoint URL, rather than gating on `BaseURL.profile`.

### Model currency

- Update the D16 and D27 records in `recon-pipeline-forward-decisions.md` to mark the per-endpoint profiling split BUILT, and update `recon/CONTEXT.md` for the `Endpoint.profile` term and the derivation, in the same change.

## Testing Decisions

Good tests here assert external behaviour at pure seams: an input (a probed URL, a raw tool stdout, a set of endpoint paths) maps to an output (a `profile`, a set of deltas, a set of scan-target prefixes).
No test asserts on internal call structure; the unit tier mocks Neo4j per the testing-tiers discipline.

- `classify_profile` (existing seam, `test_noise_filter.py`): parametrized path/content-type -> profile cases for per-endpoint classification, mirroring the existing D16 profile tests.
- `parse_httpx` (existing seam, `test_httpx_parser.py`): a probed endpoint URL yields an Endpoint delta carrying its own `profile`; a BaseURL with no crawler-produced root yields a materialized root `/` Endpoint; `BaseURL.profile` mirrors the root Endpoint's profile.
- The prefix-derivation function (the one new pure seam): parametrized path-set -> derived-prefix cases covering last-noun cut, non-standard mount, version exclusion, parent-dir fallback, multi-prefix grouping, and the 3-target cap; shaped like `test_selectors.py` / `test_urls_helper.py`.
- `build_batch_command` (existing seam, `test_batching.py`): the derived prefixes become kiterunner scan targets, mirroring the jsluice batching tests.
- `JOBS`/`PHASES` (existing seam, `test_jobs.py`): the reprofile job consumes `Endpoint`; `kiterunner`/`graphql-cop` consume the new profile-gated selectors; the profiling pass is ordered after crawlers and before the API phases; `validate_job_subset` still holds.

Green unit tests at these seams are a sufficient correctness bar for this refactor; live behaviour is exercised later by the E2E targets, out of scope here.

## Out of Scope

- Contract/introspection discovery (OpenAPI/Swagger fetch, GraphQL `{__schema}` introspection): rejected by the operator (a hidden API exposes no schema; a documented API is mapped externally).
- A longest-common-prefix scoping algorithm: dropped in favour of the noun-cut with parent-dir fallback.
- LLM-driven scope selection: rejected against the deterministic-first house rule.
- A second profiling pass after the API phases: unnecessary given provenance-tagging of API-tool Endpoints.
- Migrating the analyser delivery-gate off `BaseURL.profile`: `BaseURL.profile` is retained as a root-derived mirror, so no analyser-side change is required here.
- arjun: left untouched (its rate-limit and cert handling are a separate concern).
- The katana/jsluice parameter-discovery extension: separate branch `feat/katana-jsluice-param-discovery`.

## Further Notes

- The zombie-API discovery property is intentional: cutting the prefix before version tokens hands the version position to kiterunner's wordlist, so unlinked or deprecated API versions surface rather than only the linked one.
- The residual naming heuristic is confined to the single API-noun constant plus the `^v\d+$` version pattern; the gate itself (does this host expose an API at all?) is content-type driven via the per-endpoint `profile`, not naming-driven.
- Cross-domain APIs are a discovery/scope concern, not a scoping-algorithm concern: an `api.<tld>` host is its own BaseURL, gated on its own `restapi` endpoints, provided it is in scope and enumerated.
- Auth-on-probe and endpoint dedup+cap are hard constraints on the active per-endpoint probe, surfaced by the design pressure-test: an unauthenticated probe returns a login page and mis-profiles a real API endpoint as `webapp`, and unbounded probing is exactly the resource class that broke arjun.
