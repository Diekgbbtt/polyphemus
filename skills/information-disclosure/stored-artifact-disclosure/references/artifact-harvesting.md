# Artifact Harvesting

The artifact channel is a fetch, parse, and triage procedure, and this reference holds the families, the location shapes, and the reconstruction recipes behind it.
It serves the fetch-and-read step of `stored-artifact-disclosure` and the artifact enumeration step of the `information-disclosure` parent.
The harvest completes when every family carries a candidate location, and every fetched candidate carries a parsed read-out or a ruled-out verdict.

## Artifact Families

- **Version-control metadata**: the repository metadata directory and its objects, which reconstruct the whole history rather than one revision.
- **Editor and operating-system metadata**: desktop and directory metadata files that list paths and names a listing surface would not.
- **Archives and backups**: rotated, dated, and editor-generated copies of files that were removed from the live tree.
- **Configuration and environment dumps**: environment files, status dumps, deployment manifests, and diagnostic pages served without an actor.
- **Build outputs and provenance files**: build-info and provenance documents carrying the revision, the build time, and the dependency versions.
- **Asset and dependency manifests**: manifest files that name every emitted asset and, frequently, the route names behind them.
- **Interface specification documents**: published and archived specifications that enumerate operations, fields, and privileged paths.
- **Cross-domain policy files**: policy documents that name the hosts and origins the application trusts.
- **Client bundles and source maps**: shipped scripts, their maps, their lazily loaded chunks, and any embedded environment values.
- **Serialized page state and static data payloads**: state embedded in a rendered page or shipped as a static data file.
- **Listing surfaces and crawl directives**: directory listings, sitemaps, and crawl directives that name unreferenced routes.
- **Observability and administrative panels**: metrics, health, trace, and console surfaces whose gating decides what triage may read.

## Location Shapes

The family names a location; the shape finds the instance.

- The family's conventional names and their common variants, including the dated and prefixed forms.
- The directory-listing route beside a known path, which reveals siblings of a discovered file.
- The crawl directive and the sitemap that name routes meant to stay unreferenced.
- The bundle's own source-map reference, read from the shipped script rather than guessed.
- The archived copy of a removed specification, which often stays indexed after the live link is withdrawn.
- Case, extension, and parent-directory variants of one location, because a server's lookup rules decide which spelling resolves.

## Reconstruction Recipes

- **Source-map extraction**: fetch the map, extract the embedded sources, and grep the extracted tree for secrets, internal hosts, and endpoint names; the map frequently carries the whole original tree, not one file.
- **Version-control reconstruction**: walk the exposed metadata directory and rebuild the repository, then read the history for credentials that were removed from the current revision.
- **Specification parse**: parse each specification for paths, methods, and privileged operations, then diff an archived specification against the live one to find operations the current version dropped.
- **Chunk sweep**: fetch every emitted chunk, including the lazily loaded ones, because values migrate to the parts the initial load never fetches.
- **Bundle grep**: read the bundle and its maps for route shapes, feature flags, internal hosts, and environment values, then record each as a candidate rather than as a finding.
- **Manifest read**: read asset and dependency manifests for the emitted route names and the exact component versions.

## Triage Order

Convert each byte into a scoped follow-on in this order, so the highest-value material is read first.

- Credentials and control-plane keys, which scope direct access attempts owned by `weak-credential-discovery`.
- Cross-tenant data and cached foreign content, which scope access verdicts owned by `idor`.
- Internal paths and maps that enable an inclusion or fetch pivot, owned by the file-access and fetch classes.
- Banners, documentation, and versions with no reachable surface, which carry no chain on their own.

## The Rotation Rule

Content-hashed build artifacts rotate on every deploy, so a not-found at a previously recorded artifact location is a new build rather than remediation.
Re-derive the live location before every verdict, and never record an absence as a fix.

## Delegation

- Live schema-interface querying is owned by the `stored-artifact-disclosure` body and its `scripts/schema-reconstruction` helper; the query dialect stays owned by `graphql`.
- Cache-key mechanics are owned by `proxy-techniques-cache-deception`; only the authorization delta is recorded here.
- Credential validation against the issuing service is owned by `weak-credential-discovery`.
- The version-to-known-flaw chain is owned by the `information-disclosure` chaining section.

## False Positives

- Intentional public documentation with no exploitation path.
- A redacted dump whose sensitive fields stay redacted across replays.
- A version banner with no reachable vulnerable surface and no chain.
- A recorded artifact location that now answers not-found, which is a rotation rather than a fix.
