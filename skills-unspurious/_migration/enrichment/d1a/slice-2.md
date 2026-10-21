# D1a enrichment - slice 2

*Work item W7, C4-full enrichment. REPORT ONLY. No suite skill was edited, no git command was run.*

## Slice header

Groups (each a level-1 directory under `skills-unspurious/`, parent plus variant leaves):

- `broken-function-level-authorization` - parent + 3 leaves (`bfla-alternate-path`, `bfla-client-identity-trust`, `bfla-deferred-execution`).
- `idor` - parent + 5 leaves (`idor-direct-object-swap`, `idor-collection-batch-scope`, `idor-deferred-artifact-redemption`, `idor-context-carrier-substitution`, `idor-nested-expansion-binding`).
- `information-disclosure` - parent + 3 leaves (`error-verbosity-disclosure`, `stored-artifact-disclosure`, `differential-oracle-disclosure`).
- `mass-assignment` - parent + 3 leaves (`mass-assignment-nested-relation-write`, `mass-assignment-bulk-collection-injection`, `mass-assignment-bulk-nested-relation-write`).
- `business-logic` - parent + 4 leaves (`concurrent-duplication`, `value-domain-manipulation`, `quota-window-slicing`, `async-boundary-abuse`).
- `two-principal-authz` - parent only.

Counts: 6 groups, 24 base skills (6 parents, 18 variant leaves). Source repos indexed: 4. Source skills read and assessed: 38. New-skill proposals: 2. Enrichment candidates: 26. References/scripts candidates: 10. Clean no-match verdicts: 4.

Source repo aliases used in paths below:

- `HS` = `/Users/diekgbbtt/hacking-skills/skills`
- `CBH` = `/Users/diekgbbtt/claude-bug-hunter/skills`
- `ACS` = `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted`
- `AWS` = `/Users/diekgbbtt/awsome-offensive-security-skill/skills`

Base skill paths are under `skills-unspurious/`.

Normative docs consulted: `docs/design/skills-variant-boundary.md` (boundary attributes: vuln-specific reconnaissance; attack-surface part family; communication protocol; trust-assumption difference; impact) and `docs/design/skills-ontology.md` (ordered notion sections = the ontology entities).

Reading of the algorithm applied here: sufficient class similarity routes to a macro semantic content diff and surgical enrichment onto an ontology entity; insufficient similarity routes to the boundary-attribute test; a boundary attribute that diverges yields a new-skill proposal; a diff that is big, spans several ontology entities, and touches a boundary attribute escalates from enrichment to a new-skill proposal. The operator's example is respected: a source that is a second-order technique whose baseline the suite already carries is a non-match.

---

### Group: broken-function-level-authorization

## broken-function-level-authorization

**Sources matched**

- `HS/web/authz/authz-bypass/SKILL.md` - vertical bypass by session swap, `X-Original-URL`/`X-Rewrite-URL` routing override, IP-header spoofing on IP-restricted admin.
- `HS/web/authz/bola-idor/SKILL.md` - object-level sibling, cross-referenced.
- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md` - role matrix, method switching, path/version bypass, parameter role injection, tenant-override headers.
- `ACS/W2/testing-for-broken-access-control/SKILL.md` - vertical/horizontal/function/tenant matrix with role-diff verdicts.
- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md` - forced browsing plus path-normalization bypass family.
- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md` - lab playbook: `X-Original-URL`, method swap, `Referer`-based check, cookie role flag.
- `CBH/hunt-spa-api/SKILL.md` - client-supplied privilege flags (`is_admin`, `role_id`, `account_type`, `requested_by`) that self-elevate, and route groups missing the middleware.
- `CBH/hunt-shadow-api/SKILL.md` - behavioural auth/validation regression between API versions.

**Similarity** sufficient. The base is a superset of every source: it already carries enforcement locus, identity source, and execution context as its three discriminators.

**Boundary** none. No source adds a fourth attribute; each source value lands inside an existing discriminator or an existing aspect (transport, encoding, selector values).

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-shadow-api/SKILL.md`: version-inventory plus a behavioural auth/validation diff between an old and the current version of one action, rather than only trying `/v1`.
- `DefensiveControl` <- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: the path-normalization bypass set (case, `./`, `..`, `;`, `%2f`, trailing dot/extension, double-encode) as a route-shadowing defeat for the alternate-path variant.
- `ObservableSignal` <- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md`: the 403-on-GET beside 200-on-PUT method-inconsistency pair as an explicit detection entry.
- `PayloadPattern` <- `CBH/hunt-spa-api/SKILL.md`: client-supplied privilege-flag fields (`is_admin`, `role_id`, `account_type`, `requested_by`) as the identity-trust candidate list.

**References/scripts candidates**

- none generalised; the source scripts here are concrete host/endpoint walkers and stay below the suite's abstraction level.

## bfla-alternate-path

**Sources matched**

- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md` - method and path/version bypass.
- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md` - URL-normalization bypass set.
- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md` - `X-Original-URL` and method-based bypass labs.
- `CBH/hunt-shadow-api/SKILL.md` - version-inventory and behavioural diff.
- `HS/web/authz/authz-bypass/SKILL.md` - `X-Original-URL`/`X-Rewrite-URL` override.

**Similarity** sufficient. The base variant owns the middleware-stack-diff bent step that these sources instance.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-shadow-api/SKILL.md`: version-inventory plus behavioural regression diff as a concrete alternate-path delta.
- `DefensiveControl` <- `ACS/W2/bypassing-authentication-with-forced-browsing/SKILL.md`: normalization bypass set for the shadow-route step.
- `PreconditionEnvironment` <- `HS/web/authz/authz-bypass/SKILL.md`: proxy path-override headers (`X-Original-URL`, `X-Rewrite-URL`) present in the stack.

**References/scripts candidates**

- `scripts/bfla-role-matrix` <- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md`: generalised role-ladder by action by transport replay harness with an expected-role cell per action.

## bfla-client-identity-trust

**Sources matched**

- `CBH/hunt-spa-api/SKILL.md` - privilege flag derived from a client-supplied parameter.
- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md` - tenant/org override headers beside token.
- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md` - cookie-carried `Admin=true` and `roleid` request parameter.
- `ACS/W2/testing-for-broken-access-control/SKILL.md` - `X-Tenant-ID` header as identity.

**Similarity** sufficient. The base variant owns the identity-source precedence bent step.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md`: cookie-carried role flag and request-parameter role as identity sources beside token and header.
- `PreconditionEnvironment` <- `ACS/W2/exploiting-broken-function-level-authorization/SKILL.md`: tenant/organization selector headers present as identity carriers.
- Low-confidence: the two above are likely aspects of the existing selector-as-identity sub-block rather than new deltas.

**References/scripts candidates**

- none.

## bfla-deferred-execution

**Sources matched**

- `CBH/hunt-fintech-graphql/SKILL.md` - idempotency-key replay on mutations (timing primitive).
- `CBH/hunt-race-condition/SKILL.md` - not deep-read; owns the parallel-HTTP escalation.

**Similarity** insufficient. No source targets deferred finalize/approve or webhook replay under a different actor; the sources treat async replay as an idempotency or race concern and hand the timing primitive to another class.

**Boundary** none diverges. Execution context is the base's own discriminator; no source adds a value that bends a further step.

**New-skill proposals**

- none. Verdict: no match. A proposal here would need a source that owns a deferred-actor-check step; none does.

**Enrichment candidates**

- none. Verdict: no match (clean).

**References/scripts candidates**

- none.

---

### Group: idor

## idor

**Sources matched**

- `HS/web/authz/bola-idor/SKILL.md` - second-order and blind IDOR, JSON globbing, extension append, version downgrade.
- `HS/web/authz/authz-bypass/SKILL.md` - indirect reference swap, method and content-type variation.
- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` - batch-array inclusion, nested path, Relay node swap, Autorize.
- `ACS/W2/exploiting-idor-vulnerabilities/SKILL.md` - body, header, GraphQL, and bulk IDOR.
- `CBH/hunt-idor/SKILL.md` - chains, harvest-then-fetch, soft-delete temporal access, double-IDOR.
- `CBH/hunt-fintech-graphql/SKILL.md` - asymmetric source/destination binding check.
- `AWS/bug-hunting/api-security/broken-object-level-authorization/SKILL.md` - HPP, body ID override, content-type smuggling.
- `AWS/bug-hunting/web-vulnerabilities/idor-vulnerability-hunting/SKILL.md` - compound IDOR, wildcard, numeric-as-string, XML body.
- `AWS/bug-hunting/business-logic/insecure-direct-object-reference-idor/SKILL.md` - GUID leak then replay.
- `AWS/bug-hunting/apis/graphql-idor/SKILL.md` - node-id and alias batching.

**Similarity** sufficient. The base's four discriminators (cardinality, redemption timing, identity carrier, resource depth) contain every source value.

**Boundary** none. Note the operator's example explicitly: `HS/web/authz/bola-idor/SKILL.md` advertises second-order and blind IDOR, and the suite already carries both, the second-order case as `idor-deferred-artifact-redemption` and the blind case as a confirmation aspect. NOT proposed.

**New-skill proposals**

- none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: harvest a leaked identifier from one surface to fuel a second, distinct access (double-IDOR chaining) as a documented collection step.
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: the asymmetric binding check where the destination of a debit is validated but the source is not.
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: post-removal or soft-delete temporal access where a cached authorization context still passes after the policy table is updated.

**References/scripts candidates**

- `references/idor-two-account-matrix` <- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` plus `ACS/W2/exploiting-idor-vulnerabilities/SKILL.md`: generalised owner-versus-non-owner swap harness with a per-endpoint verdict and a masked-response differential.
- `scripts/idor-id-enumeration` <- `CBH/hunt-idor/SKILL.md` plus `AWS/bug-hunting/web-vulnerabilities/idor-vulnerability-hunting/SKILL.md`: sequential-ID wordlist generation and fuzzing against a parameterised base URL.

## idor-direct-object-swap

**Sources matched**

- `HS/web/authz/bola-idor/SKILL.md`, `ACS/W2/exploiting-idor-vulnerabilities/SKILL.md`, `AWS/bug-hunting/web-vulnerabilities/idor-vulnerability-hunting/SKILL.md`, `CBH/hunt-idor/SKILL.md`.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `PayloadPattern` <- `HS/web/authz/bola-idor/SKILL.md`: JSON globbing and extension append (`[id1,id2]`, `*`, `true`, `0`, `-1`, `.json`) as reference-shape variants inside the swap.
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: the control pair (owner request beside foreign request) as the deciding signal.

**References/scripts candidates**

- none beyond the parent entries.

## idor-collection-batch-scope

**Sources matched**

- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` - batch array including foreign IDs.
- `HS/web/authz/bola-idor/SKILL.md` - pagination manipulation.
- `CBH/hunt-idor/SKILL.md` - `?filter[user_id]=` indirect filter.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md`: bulk-export endpoint that accepts an array of identifiers and applies no per-item ownership check.
- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: indirect filter injection (`sort`, `filter[user_id]`) to skip scoping.

**References/scripts candidates**

- none.

## idor-deferred-artifact-redemption

**Sources matched**

- `HS/web/authz/bola-idor/SKILL.md` - second-order scheduled export.
- `CBH/hunt-idor/SKILL.md` - migration-job read, soft-delete token validity.
- `ACS/W2/exploiting-idor-vulnerabilities/SKILL.md` - invoice download by increment.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: post-removal token validity where a cached auth context still passes after the member is removed (temporal IDOR).
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: retrieval by a principal that did not create the artifact, persisted after a policy change.

**References/scripts candidates**

- none.

## idor-context-carrier-substitution

**Sources matched**

- `HS/web/authz/authz-bypass/SKILL.md` - `X-Original-URL` routing override.
- `ACS/W2/testing-for-broken-access-control/SKILL.md` - `X-Tenant-ID` header swap.
- `CBH/hunt-idor/SKILL.md` - short-lived per-resource token reuse; older API version.
- `AWS/bug-hunting/api-security/broken-object-level-authorization/SKILL.md` - content-type smuggling to a different parser.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: a per-resource short-lived token reused across users when only the format is validated.
- `AttackTechnique` <- `CBH/hunt-idor/SKILL.md`: check the same operation at a different API version, since authorization logic is often version-specific.

**References/scripts candidates**

- none.

## idor-nested-expansion-binding

**Sources matched**

- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` - nested resource path and Relay node swap.
- `AWS/bug-hunting/apis/graphql-idor/SKILL.md` - alias and batch multiplex.
- `CBH/hunt-fintech-graphql/SKILL.md` - nested counterparty PII on a shared type.
- `CBH/hunt-graphql/SKILL.md` - not deep-read; flag as a low-confidence candidate (the base names `graphql` as the owner of resolver mechanics).

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: a per-type field-level check missing on a shared type returned nested inside an unrelated query (top-level authorized, nested counterparty not).
- `AttackTechnique` <- `AWS/bug-hunting/apis/graphql-idor/SKILL.md`: alias multiplex of several principals' nodes in one request with a per-node verdict.

**References/scripts candidates**

- `scripts/idor-graphql-node-swap` <- `AWS/bug-hunting/apis/graphql-idor/SKILL.md`: relay node-id decode, modify, re-encode, replay.

---

### Group: information-disclosure

## information-disclosure

**Sources matched**

- `CBH/hunt-source-leak/SKILL.md` - source maps, `.git`, Swagger, build-info, `.DS_Store`, webpack chunks, content-hash rotation.
- `CBH/hunt-spa-api/SKILL.md` - JS bundle route and secret harvest.
- `CBH/hunt-shadow-api/SKILL.md` - spec archive via Wayback, version diff.
- `CBH/hunt-exceptional-conditions/SKILL.md` - verbose errors, fail-open.
- `CBH/hunt-cache-poison/SKILL.md` - cache deception and cache-miss forcing.
- `CBH/hunt-ntlm-info/SKILL.md` - not deep-read; NTLM Type-2 metadata disclosure (flag, low-confidence, likely a concrete aspect).
- `ACS/W5/exploiting-excessive-data-exposure-in-api/SKILL.md` - response over-fetch, debug headers, error leaks.
- `ACS/W5/detecting-broken-object-property-level-authorization/SKILL.md` - BOPLA, sensitive-property classification.
- `ACS/W5/testing-for-sensitive-data-exposure/SKILL.md` - secret scanning, source maps, `.git`, masking.
- `ACS/W5/performing-graphql-introspection-attack/SKILL.md` - schema reconstruction from field suggestions.
- `AWS/bug-hunting/deep-dive-labs/info-disclosure/SKILL.md` - lab playbook.
- `AWS/bug-hunting/api-security/api-enumeration-fuzzing-discovery/SKILL.md` - Swagger/OpenAPI disclosure.
- `AWS/bug-hunting/deep-dive-labs/cache-deception/SKILL.md` - path-mapping and delimiter labs.

**Similarity** sufficient for the three existing mechanisms (failure verbosity, single-response artifact fetch-and-read, two-response differential comparison).

**Boundary** one divergence found, on the attack-surface part family, for excessive data exposure (a normal resource response carrying fields beyond the caller's entitlement). The trust assumption and the impact are shared, so it is a sibling class rather than a fourth variant of this class. A second, weaker divergence is version-consistency for shadow APIs.

**New-skill proposals**

- source: `ACS/W5/exploiting-excessive-data-exposure-in-api/SKILL.md` (plus `ACS/W5/detecting-broken-object-property-level-authorization/SKILL.md`, `ACS/W5/testing-for-sensitive-data-exposure/SKILL.md`)
  [NEW] target: `excessive-data-exposure`
  rationale: The base information-disclosure decomposes by elicitation-observation mechanism (failure verbosity, single-response artifact fetch-and-read, two-response differential comparison). Over-fetch, a single resource response that carries fields the caller is not entitled to see (password hashes, national identifiers, internal notes, a full user object embedded in an unrelated response), is a single-response read of an ordinary resource, not of a deployable artifact. No parent step covers "read every field of an ordinary response against the caller's entitlement": P4 fetches artifacts and API documents, and the class's cross-channel entry fires only on disagreement between two representations of one object. The diverging boundary attribute is the attack-surface part family (API response body field sets versus channels and deployables). The impact (confidentiality) and the trust assumption ("every channel renders exactly what the caller is entitled to see") are shared, so the correct shape is a new sibling class, not a variant of information-disclosure. Confidence medium: an acceptable alternative is a fourth information-disclosure variant if the operator prefers no new parent, but the covering step is genuinely absent, so a variant would leave the parent's method under-specified.
- source: `CBH/hunt-shadow-api/SKILL.md` (plus `AWS/bug-hunting/api-security/api-enumeration-fuzzing-discovery/SKILL.md`, `CBH/hunt-spa-api/SKILL.md`)
  [NEW] target: `api-version-consistency` (shadow or zombie API)
  rationale: OWASP API9 improper inventory management. The finding is a behavioural security regression between an old and the current version of the same operation (weaker auth, missing rate limit, dropped validation), not a disclosure and not a single enforcement-locus gap. The diverging boundary attribute is the trust assumption: the current control set is assumed to apply to every reachable version, and an old version breaks that clause. Confidence low-medium: this is a recon-adjacent class; the operator may prefer to keep the version surface inside the `bfla-alternate-path` and idor-parent older-version aspects, or place it in a recon group rather than a vulnerability class. Flagged for the operator's judgement.

**Enrichment candidates**

- `ObservableSignal` <- `CBH/hunt-source-leak/SKILL.md`: content-hashed build artifacts rotate on every deploy, so a 404 at a previously recorded artifact URL is a new build, not remediation; re-derive the live hash before each verdict. (Belongs in `## False Positives` and `## Pro Tips`.)
- `AttackTechnique` <- `ACS/W5/performing-graphql-introspection-attack/SKILL.md`: reconstruct a disabled schema from field-suggestion errors ("did you mean") and error messages, the Clairvoyance pattern.
- `AttackTechnique` <- `CBH/hunt-source-leak/SKILL.md`: fetch-parse-triage of a downloaded artifact for embedded metadata (paths, versions, endpoint names) and for auth-gated observability panels as one procedure.
- `Artifact` <- `CBH/hunt-source-leak/SKILL.md`: additional deployable families (asset manifest, build-info, package manifests, server config, `.DS_Store`, crossdomain policy).
- `ObservableSignal` <- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md`: a leak inside the body of a redirect response that fires before the 3xx is followed.
- `PreconditionEnvironment` <- `CBH/hunt-cache-poison/SKILL.md`: an origin that caches a dynamic or authenticated response under a static-looking path key. Flag: the base's own grey point assigns generic cache mechanics to the `proxy-techniques` family; propose only the authorization-delta step.

**References/scripts candidates**

- `scripts/artifact-sweep` <- `CBH/hunt-source-leak/SKILL.md` plus `ACS/W5/testing-for-sensitive-data-exposure/SKILL.md`: parameterised artifact-path list with status, size, and content-type triage.
- `references/source-map-reconstruction` <- `CBH/hunt-source-leak/SKILL.md`: generalised source-map download, `sourcesContent` extraction, and secret grep.

## error-verbosity-disclosure

**Sources matched**

- `CBH/hunt-exceptional-conditions/SKILL.md` - malformed input, fail-open, cross-framework error signatures.
- `AWS/bug-hunting/deep-dive-labs/info-disclosure/SKILL.md` - error-message and debug-page labs.
- `ACS/W5/testing-for-sensitive-data-exposure/SKILL.md` - error-response leakage step.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `ObservableSignal` <- `CBH/hunt-exceptional-conditions/SKILL.md`: fail-open, where the error path executes the action rather than only disclosing, as a signal distinct from disclosure.
- `AttackTechnique` <- `CBH/hunt-source-leak/SKILL.md`: debug, actuator, version, and build-info endpoint enumeration as the debug-surface delta beyond malformed-input triggering.
- `PayloadPattern` <- `CBH/hunt-exceptional-conditions/SKILL.md`: the one-assumption-at-a-time break set (wrong type, malformed body, oversized field, null byte).

**References/scripts candidates**

- none; the source scripts are concrete error-signature scanners that stay below the abstraction level.

## stored-artifact-disclosure

**Sources matched**

- `CBH/hunt-source-leak/SKILL.md`, `CBH/hunt-spa-api/SKILL.md`, `AWS/bug-hunting/api-security/api-enumeration-fuzzing-discovery/SKILL.md`, `ACS/W5/performing-graphql-introspection-attack/SKILL.md`, `ACS/W5/exploiting-excessive-data-exposure-in-api/SKILL.md`.

**Similarity** sufficient for the fetch-parse-triage mechanism.

**Boundary** none for this variant.

**Enrichment candidates**

- `ObservableSignal` <- `CBH/hunt-source-leak/SKILL.md`: content-hash rotation as a false-positive and pro-tip entry (a stale artifact URL is a new build).
- `AttackTechnique` <- `ACS/W5/performing-graphql-introspection-attack/SKILL.md`: schema reconstruction from field-suggestion errors when introspection is closed.
- `Artifact` <- `CBH/hunt-source-leak/SKILL.md`: additional deployable families.
- `AttackTechnique` <- `CBH/hunt-spa-api/SKILL.md`: route and secret harvest from lazy-loaded async chunks, not only the shell-referenced bundles.

**References/scripts candidates**

- `scripts/schema-reconstruction` <- `ACS/W5/performing-graphql-introspection-attack/SKILL.md`: generalised field-suggestion brute-force that harvests a schema from error messages when introspection is disabled.

## differential-oracle-disclosure

**Sources matched**

- `CBH/hunt-cache-poison/SKILL.md` - cache deception, cache-miss forcing, unkeyed input.
- `AWS/bug-hunting/deep-dive-labs/cache-deception/SKILL.md` - path-mapping, delimiter, and normalization labs.
- `CBH/hunt-shadow-api/SKILL.md` - field-exposure diff between versions.
- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md` - redirect-body leak.

**Similarity** sufficient for the two-response oracle mechanism.

**Boundary** none. Web cache deception is a cacheability decision (path extension, delimiter, normalization) rather than an identity-key omission; the base's grey point assigns generic cache mechanics to the `proxy-techniques` family, so only the deception step is proposed here.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: force the cache to store an authenticated response via a static-looking path append or delimiter, then read it unauthenticated (web cache deception).
- `AttackTechnique` <- `CBH/hunt-cache-poison/SKILL.md`: force a cache miss with a cache-busting query parameter rather than `Cache-Control: no-cache`, which CDNs ignore.
- `ObservableSignal` <- `AWS/bug-hunting/deep-dive-labs/cache-deception/SKILL.md`: origin-versus-cache path-normalization disagreement where the cached key does not match the resource the origin served.

**References/scripts candidates**

- none.

---

### Group: mass-assignment

## mass-assignment

**Sources matched**

- `HS/web/authz/mass-assignment/SKILL.md` - field families, nested objects, array assignment, framework allowlist bypass.
- `ACS/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md` - hidden parameter discovery, financial and temporal fields, relationship manipulation.
- `ACS/W5/testing-api-for-mass-assignment-vulnerability/SKILL.md` - privilege-field categories, state-change verification, framework-specific binder shapes.
- `ACS/W5/detecting-broken-object-property-level-authorization/SKILL.md` - BOPLA, sensitive-property classification, GraphQL property exposure.
- `CBH/hunt-api-misconfig/SKILL.md` - mass assignment, OData `$expand` navigation-property IDOR.
- `CBH/hunt-fintech-graphql/SKILL.md` - admin-shaped input fields accepted by a public mutation.
- `AWS/bug-hunting/api-security/api-mass-assignment-exploitation/SKILL.md` - response-leaked field names, HPP, blind field discovery.
- `AWS/bug-hunting/apis/mass-assignment-exploitation/SKILL.md` - not deep-read; flag low-confidence (duplicate of the above surface).
- `AWS/bug-hunting/deep-dive-labs/api-testing-labs/SKILL.md` - discount-object mass-assignment lab.
- `AWS/bug-hunting/deep-dive-labs/access-control/SKILL.md` - `roleid` profile-update lab.

**Similarity** sufficient. The base's two discriminators (binding depth, binding cardinality) contain the source values; content-type switching and shape reshaping are already aspects.

**Boundary** none.

**New-skill proposals**

- none.

**Enrichment candidates**

- `PayloadPattern` <- `ACS/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`: temporal and audit fields (`created_at`, `updated_at`, `created_by`) as a candidate family for audit-log manipulation.
- `AttackTechnique` <- `ACS/W5/testing-api-for-mass-assignment-vulnerability/SKILL.md`: framework-specific binder shapes (model-nested key, form-bracket keys, ORM operator `$set`, `_id` override) as binder-differential probes. Flag: `$set` and `_id` cross into `nosql-injection`; propose only the binder-differential framing.
- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: OData `$expand` navigation-property binding where authorization decorators cover the top-level entity set but not the joined entity. Flag: OData is a distinct protocol; check the boundary before adding.
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: admin-shaped input fields (`status`, `override`) accepted by a mutation the client never exposes.
- `PreconditionEnvironment` <- `ACS/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`: an exposed OpenAPI `components.schemas` enumerating every model field, including privileged ones.

**References/scripts candidates**

- `scripts/mass-assignment-field-sweep` <- `ACS/W5/testing-api-for-mass-assignment-vulnerability/SKILL.md`: generalised candidate-field dictionary with a per-field persisted-or-rejected verdict and a re-fetch verification.
- `references/mass-assignment-field-dictionary` <- `HS/web/authz/mass-assignment/SKILL.md` plus `ACS/W5/exploiting-mass-assignment-in-rest-apis/SKILL.md`: sensitive-field families (role, ownership, limits, flags, billing, temporal).

## mass-assignment-nested-relation-write

**Sources matched**

- `ACS/W5/detecting-broken-object-property-level-authorization/SKILL.md` - nested property write.
- `CBH/hunt-api-misconfig/SKILL.md` - OData `$expand` joined-entity gap.
- `HS/web/authz/mass-assignment/SKILL.md` - nested object and array assignment.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-api-misconfig/SKILL.md`: the joined-entity authorization gap on a navigation-property expansion as a nested-write shape.
- `PayloadPattern` <- `HS/web/authz/mass-assignment/SKILL.md`: nested-object and array-for-scalar shapes reaching a child binder.

**References/scripts candidates**

- none.

## mass-assignment-bulk-collection-injection

**Sources matched**

- none directly. The anthropic, claude-bug-hunter, and awsome mass-assignment sources do not cover per-position mid-array smuggling with per-item verdicts.

**Similarity** insufficient. No source adds a bent step to this variant; the base is the authority for it.

**Boundary** none diverges (cardinality is the base's own discriminator).

**New-skill proposals**

- none. Verdict: no match (clean). Recorded because a reader could expect a bulk source; the corpus is silent.

**Enrichment candidates**

- none.

**References/scripts candidates**

- none.

## mass-assignment-bulk-nested-relation-write

**Sources matched**

- none directly. No source covers the product of batch position and nested relation.

**Similarity** insufficient.

**Boundary** none diverges.

**New-skill proposals**

- none. Verdict: no match (clean).

**Enrichment candidates**

- none.

**References/scripts candidates**

- none.

---

### Group: business-logic

## business-logic

**Sources matched**

- `HS/web/logic/business-logic-flaws/SKILL.md` - price/quantity tampering, workflow skip, coupon reuse, race on balance.
- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md` - workflow map, price/quantity, step bypass, race, referral/reward abuse, role logic.
- `CBH/hunt-business-logic/SKILL.md` - coupon race, negative quantity, decimal overflow, client-math trust, archived-price swap, unvalidated webhook.
- `CBH/hunt-fintech-graphql/SKILL.md` - money-movement mutations, decimal scalars, idempotency replay, alias batching.
- `AWS/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md` - integer overflow, currency/type mismatch, workflow order, race.
- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md` - identity-domain, state-machine, gift-card circular, email-parsing labs.
- `AWS/bug-hunting/logic-flaws/2fa-bypass/SKILL.md` - state-mismatch and response manipulation. Flag: MFA bypass is an authentication class; treat as a boundary case, not a business-logic delta.
- `CBH/hunt-race-condition/SKILL.md` - not deep-read; owns the timing primitive.

**Similarity** sufficient for the four technique discriminators (concurrent duplication, value-domain oracles, window-lifecycle slicing, async-boundary triggering).

**Boundary** none for the four discriminators. Two source items cross a boundary and are noted, not proposed: invitation/delegation escalation above the inviter's ceiling is an authorization-binding concern (owned by `two-principal-authz` or `broken-function-level-authorization`), and unauthenticated internal or employee surfaces are a `broken-function-level-authorization` concern.

**New-skill proposals**

- none.

**Enrichment candidates**

- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md` plus `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: inconsistent-identity-domain logic (register under an allowed domain, then move the identity to a privileged domain) as a state-transition check.
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md`: a flawed state machine where dropping a role-selection request leaves the default role privileged.
- `AttackTechnique` <- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: invitation or delegation abuse where the inviter grants a role above its own ceiling. Flag: boundary to `two-principal-authz`.
- `AttackTechnique` <- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: gift-card circular value (buy with gift balance) and change-as-credit; belongs with value-domain manipulation.
- `ObservableSignal` <- `CBH/hunt-business-logic/SKILL.md`: an unvalidated payment-provider webhook (no signature) as a downstream-trust signal; belongs with async-boundary abuse.

**References/scripts candidates**

- `references/business-logic-value-probes` <- `CBH/hunt-business-logic/SKILL.md` plus `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md`: the negative, zero, float, overflow, and currency value probe set.

## concurrent-duplication

**Sources matched**

- `CBH/hunt-business-logic/SKILL.md` - coupon, fee-credit, and gift-card race.
- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md` - coupon and transfer race.
- `AWS/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md` - concurrent coupon script.
- `CBH/hunt-fintech-graphql/SKILL.md` - idempotency replay and alias batching.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: single-request alias-batched duplicate submission as a pre-parallel confirmation step, before escalating to parallel HTTP.
- `ObservableSignal` <- `CBH/hunt-business-logic/SKILL.md`: a second distinct transaction identifier from an identical idempotency key.

**References/scripts candidates**

- `scripts/business-logic-race-harness` <- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md` plus `AWS/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md`: generalised concurrent-request harness for one-time operations, naming `race-conditions` for the timing primitive.

## value-domain-manipulation

**Sources matched**

- `CBH/hunt-business-logic/SKILL.md` - decimal overflow, negative quantity, currency, archived-price swap.
- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md` - negative, zero, extreme, float, overflow.
- `AWS/bug-hunting/logic-flaws/business-logic-bypass/SKILL.md` - integer overflow, currency/type mismatch.
- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md` - integer-overflow and exceptional-input labs.
- `CBH/hunt-fintech-graphql/SKILL.md` - custom decimal scalar fallback under scientific notation or oversized input.

**Similarity** sufficient.

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: a custom `Decimal`/`Money` scalar that falls back to native float parsing under scientific notation or oversized strings, reintroducing rounding error.
- `AttackTechnique` <- `CBH/hunt-business-logic/SKILL.md`: mid-flow price-version swap against an archived price (cart-state TOCTOU) as a value-domain case.
- `AttackTechnique` <- `AWS/bug-hunting/deep-dive-labs/business-logic/SKILL.md`: identity-domain and email-truncation boundary cases feeding an entitlement change.

**References/scripts candidates**

- none beyond the parent value-probe reference.

## quota-window-slicing

**Sources matched**

- `ACS/W6/testing-for-business-logic-vulnerabilities/SKILL.md` - referral and reward caps, usage limits.
- `CBH/hunt-business-logic/SKILL.md` - IP-header rate-limit rotation. Flag: this is rate-limit bypass, owned by `weak-credential-discovery` or `brute-force`, not window slicing.

**Similarity** insufficient. No source covers reset-edge timing or reserve-complete-release lifecycles; the closest source owns the timing primitive elsewhere.

**Boundary** none diverges.

**New-skill proposals**

- none. Verdict: no match (clean).

**Enrichment candidates**

- none.

**References/scripts candidates**

- none.

## async-boundary-abuse

**Sources matched**

- `CBH/hunt-business-logic/SKILL.md` - unvalidated webhook, internal/employee surface.
- `CBH/hunt-fintech-graphql/SKILL.md` - non-atomic multi-entry ledger writes across a GraphQL resolver.

**Similarity** sufficient (thin).

**Boundary** none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-business-logic/SKILL.md`: an unvalidated payment-provider webhook (no HMAC) as a downstream-trust trigger.
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: a resolver that writes debit, credit, and fee entries as separate statements, opening a between-call mutation window.

**References/scripts candidates**

- none.

---

### Group: two-principal-authz

## two-principal-authz

**Sources matched**

- `HS/web/authz/bola-idor/SKILL.md` - two-account setup, control pair, differential confirmation.
- `HS/web/authz/authz-bypass/SKILL.md` - horizontal and vertical session swap.
- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` - baseline capture for two accounts, Autorize.
- `ACS/W2/testing-for-broken-access-control/SKILL.md` - role matrix and cross-tenant checks.
- `CBH/hunt-idor/SKILL.md` - two-account replay, all verbs, cross-tenant.
- `CBH/hunt-spa-api/SKILL.md` - control endpoint and route-family comparison.
- `CBH/hunt-fintech-graphql/SKILL.md` - asymmetric source/destination binding.
- `AWS/bug-hunting/api-security/broken-object-level-authorization/SKILL.md` - two controlled accounts, never blind.
- `AWS/bug-hunting/business-logic/insecure-direct-object-reference-idor/SKILL.md` - two-account validation.

**Similarity** sufficient. The base is the parent methodology; every source is a concrete instance of its steps.

**Boundary** none.

**New-skill proposals**

- none.

**Enrichment candidates**

- `AttackTechnique` <- `CBH/hunt-spa-api/SKILL.md`: establish a control endpoint that is gated, then compare a whole route family against it (a route-group differential, not only an object control pair).
- `AttackTechnique` <- `CBH/hunt-fintech-graphql/SKILL.md`: asymmetric binding where the destination of a debit is validated but the source is not.
- `AttackerCapability` <- `CBH/hunt-idor/SKILL.md`: hold a harvested identifier corpus from other surfaces before the swap.
- `ObservableSignal` <- `CBH/hunt-spa-api/SKILL.md`: a 400 "field X is mandatory" response that reached business-logic validation without an auth check, as an auth-bypass signal.
- `ObservableSignal` <- `CBH/hunt-idor/SKILL.md`: a post-removal or soft-delete token still passing (temporal binding gap).

**References/scripts candidates**

- `scripts/two-principal-swap-harness` <- `ACS/W2/testing-api-for-broken-object-level-authorization/SKILL.md` plus `CBH/hunt-idor/SKILL.md`: generalised owner-versus-non-owner replay with a per-operation verdict and masked-response differentials.

---

## Slice summary

**Counts**

- Groups: 6. Base skills: 24 (6 parents, 18 leaves).
- Source repos: 4. Source skills read and assessed: 38.
- New-skill proposals: 2 (`excessive-data-exposure` medium confidence; `api-version-consistency` low-medium confidence).
- Enrichment candidates: 26 across the six groups.
- References/scripts candidates: 10.
- Clean no-match verdicts: 4 (`bfla-deferred-execution`, `mass-assignment-bulk-collection-injection`, `mass-assignment-bulk-nested-relation-write`, `quota-window-slicing`).
- Low-confidence matches flagged: 5 (NTLM info disclosure; OData `$expand`; GraphQL resolver mechanics owned by `graphql`; web cache deception owned by `proxy-techniques`; `2fa-bypass` as an authentication boundary case).

**Strongest findings**

1. `excessive-data-exposure` new-skill proposal. Three sources agree on a covering step the base information-disclosure genuinely lacks; the attack-surface part family diverges while the trust assumption and impact are shared, so a sibling class is the correct shape. Medium confidence with a stated variant alternative.
2. Content-hashed artifact rotation for `stored-artifact-disclosure`. The insight that a 404 at a recorded artifact URL is a new build, not remediation, corrects a real false negative that closes live findings. Belongs in `## False Positives` and `## Pro Tips`.
3. Schema reconstruction from field-suggestion errors for `stored-artifact-disclosure`. A genuinely new technique when introspection is disabled, generalisable into a `references/` scripted test.
4. The asymmetric source-versus-destination binding check from `CBH/hunt-fintech-graphql`. It sharpens both `two-principal-authz` and the idor parent, and it is the sharpest decision-grade addition to the authorization core.
5. `api-version-consistency` new-skill proposal. OWASP API9 shadow and zombie APIs are not carried by any group in the suite. Low-medium confidence because the operator may prefer the recon or aspect home.

**Overall verdict for the slice**

Every source is a class-level match to its base skill, and the base suite is a superset of the sources' concrete payloads, tooling, and output formats, which the abstractness rule excludes. The slice is therefore mostly a surgical-enrichment case, with two boundary-attribute divergences (over-fetch, version consistency) and a small set of decision-grade additions to detection signals, false positives, and scripted references. No source justified proposing a second-order technique whose baseline the suite already carries.
