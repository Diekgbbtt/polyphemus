---
name: idor
description: IDOR/BOLA testing for object-level authorization failures and cross-account data access
metadata:
  version: 1.0.0
---

# IDOR

Object-level authorization failures (BOLA/IDOR) lead to cross-account data exposure and unauthorized state changes across APIs, web, mobile, and microservices. Treat every object reference as untrusted until proven bound to the caller.

## Attack Surface

**Scope**
- Horizontal access: reach another subject's objects of the same type
- Vertical access: reach privileged objects or actions
- Cross-tenant access: break isolation boundaries in multi-tenant systems
- Cross-service access: a token or context accepted by the wrong service

**Reference Locations**
- Paths, query parameters, structured bodies, form data, headers, cookies
- Token claims, schema-layer arguments, socket messages, RPC messages

**Identifier Forms**
- Integers, generated identifiers, slugs
- Composite keys that join two scopes in one value
- Opaque tokens, encoded blobs

**Relationship References**
- Parent, owner, account, tenant, organization, team, project, and subscription references

**Expansion and Projection Knobs**
- Field selection, include, expand, and populate parameters on read operations
- Often resolved without their own authorization check in resolvers or serializers

## Reconnaissance

### Parameter Analysis

- Pagination and cursors: offset, limit, cursor, and continuation handles often reveal or accept another tenant's state
- Directory and list endpoints as seeders: search, list, suggest, and export operations leak object identifiers for later steps
- Find undocumented filters, such as soft-delete or impersonation selectors, that widen the object set

### Reference Enumeration

- Alternate value types for one identifier: numeric versus textual forms, scalars versus arrays, arrays versus objects
- Edge values: null, empty, zero, negative, and the maximum integer
- Duplicate keys and parameter pollution, where parser precedence decides which value reaches the lookup
- Case and alias variants of the reference name, so the gate and the lookup read different fields
- Traversal-shaped values inside virtual namespaces

### Identifier Sources

- Logs, exports, client bundles, analytics endpoints, messages, and public activity
- Time-derived identifiers, which may be guessable within a window

## Detection Channels

- Foreign content or metadata returned for a non-owner identifier, which decides the finding.
- A page window that returns another principal's objects after cursor manipulation.
- Count and size anomalies between the control window and the adversarial window, which confirm scope failure without reading full content.
- An import acknowledgement that persists foreign-keyed rows, which confirms a create-path binding gap.
- An error shape that differs between owned and foreign identifiers, which signals a missing binding even when content is masked.
- Status, size, and timing differentials between the control attempt and the swapped attempt, which confirm blind access.
- Conditional-request validators that match for a foreign object, which confirm its existence without full content.
- Foreign artifact content returned to a non-creator.
- A stale or cross-scope stored link that still redeems, which signals missing scope and expiry binding.
- A privileged response that follows a contradictory identity header while the token stays constant, which signals header precedence failure.
- A token scoped for one service that a second service accepts, which signals missing audience binding.
- An async effect applied to a foreign object after gateway passage, which signals context loss in the consumer.
- Privileged sub-fields present in an expanded response to a non-owner.
- A child object returned through an authorized parent without its own check, which signals a missing per-hop binding.
- Per-node decisions inside one multiplexed response that favour foreign callers.
- A stored or cached authorization context that still passes for a removed, downgraded, or moved principal, which signals a temporal binding gap.
- One member of a paired argument answering with foreign data while its counterpart is refused, which signals an asymmetric binding.

## Adversarial Capabilities

Object-level testing presupposes two principals, identifier collection, and reach across every transport, and it consumes all three.
- Hold an owner session and a non-owner session, plus a privileged session where vertical access is in scope.
- Collect valid identifiers per principal from list, search, and export surfaces.
- Swap one reference at a time while the session stays constant, so a success attributes to the binding rather than to the role.
- Reach the same resource through each transport and encoding the target exposes.
- Read differentials (status, size, validator, timing) when content stays masked.
- Snapshot state before and after write attempts to confirm durable foreign effects.

## Trust Assumptions

The class rests on one agreement: every object reference is bound to the caller at the moment of use, in the service that holds the object.
The agreement holds the reference to a value the caller is entitled to name, holds every hop of a nested read to the same check, holds the batch or window operation to a per-item check, and holds a deferred artifact to the identity that created it.
Sensitive position leaks when the binding is missing anywhere: a sibling read, a child resolver, a mid-array element, a redelivered delivery, or a second service.
Each variant breaks one clause: the direct-binding clause, the scope-binding clause, the deferral clause, the carrier clause, or the per-hop clause.

## Key Vulnerabilities

### Horizontal and Vertical Access

- Swap object references between principals using the same token to probe horizontal access
- Repeat with lower-privilege tokens to probe vertical access
- Target partial updates for silent unauthorized modifications
- Where one request names a source and a destination (a paired transfer, a copy, a move), test which member carries the check: a validated destination beside an unchecked source is the common asymmetric gap, and each member needs its own verdict

### Bulk and Batch Operations

- Batch endpoints often validate only the first element; include foreign references mid-array
- Import operations referencing foreign keys may bypass create-time checks

### Secondary References

- Use list, search, notification, message, and callback surfaces to collect valid identifiers
- Fetch or mutate the collected objects directly
- Pagination manipulation to skip filters and pull other principals' pages
- Chain one harvested identifier into a second, distinct access: an identifier leaked by one surface (a message, an export, a shared record) fuels an access the first surface never exposed, so harvest before you swap

### Job and Task Objects

- Access another principal's job handle to retrieve its results
- Cancel or approve another principal's jobs by referencing their handles

### File and Object Storage

- Direct object paths and weakly scoped signed links
- Key-prefix changes, disposition tricks, and stale links reused across tenants
- Share tokens replaced with tokens from other tenants, including case and encoding variants

### Schema-Layer Reads

- Enforce resolver-level checks; do not rely on a top-level gate
- Verify field and edge resolvers bind the resource to the caller on every hop
- Abuse batching and aliases to retrieve several principals' nodes in one request
- Global node lookups resolve any typed object by identifier; decode and swap the raw identifier
- Overfetching through fragments on privileged types

### Microservices and Gateways

- Token confusion: a token scoped for one service accepted by another because verification checks the signature but not the audience
- Header trust: proxies and gateways injecting or trusting identity headers; try overriding or removing them
- Context loss: async consumers reprocess work without re-checking authorization

### Multi-Tenant

- Probe tenant scoping through headers, subdomains, and path parameters
- Mix the tenant of the token with a resource from another tenant
- Test rollups and admin views that aggregate several tenants

### Socket and Message Layers

- Authorization per subscription: ensure channel and topic names cannot be guessed from identifiers
- Subscribe and publish checks must run server-side, not only at the handshake
- Send messages naming another principal's identifiers after joining one's own channels

### RPC Layers

- Direct message fields often bypass HTTP-layer middleware; validate references with a generic client holding another principal's token

### Integrations

- Callbacks and webhooks referencing foreign objects processed without verifying ownership
- Third-party importers syncing data into the wrong tenant because the tenant binding is missing

## Bypass Techniques

**Parser and Transport**
- Content-type switching between structured, form, and multipart bodies
- Method tunnelling through override headers or fields, or a read verb on an endpoint that accepts state changes
- Duplicate keys and array injection to bypass naive validators
- Version fallback and path decoration: replay the same action through older version prefixes and through extension-appended path forms, because authorization logic is frequently version-specific and extension handlers frequently skip the middleware
- Static keyword swap: replace a self-referential reference keyword with a numeric or opaque identifier, so the lookup stops resolving from session context

**Parameter Pollution**
- Duplicate parameters in query or body to influence server-side precedence; try both orderings
- Mixed case and alias names so the gate and the backend disagree

**Cache and Gateway**
- Cache keys that omit the authorization or tenant binding, which expose cached objects to other users
- Manipulate the key-variation and accept fields
- Redirect chains and conditional or partial responses that leak content across tenants
- Name the proxy-techniques family at the shared-cache and relay steps rather than restating its mechanics

**Race Windows**
- Change the referenced identifier between the check and the use with parallel requests

**Blind Channels**
- Use differential responses (status, size, validator, timing) to detect existence
- Error shape often differs for owned versus foreign objects
- Header-only and conditional requests can confirm existence without full content

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- IDOR + CSRF: force victims to trigger unauthorized changes on objects you discovered
- IDOR + stored scripting: pivot into other principals' sessions through data you gained access to
- IDOR + server-side fetches: exfiltrate internal identifiers, then access their corresponding resources
- IDOR + race: bypass spot checks with simultaneous requests
- Identifier swap to identity change: reach the identity-change path for a foreign object, then drive the reset flow to takeover; the terminal primitive is the changed contact field, and the reset steps belong to the authentication classes
- Artifact read to session theft: an artifact whose download name or headers the caller influences feeds a delivery that hands over a session; the session class owns the theft verdict
- Relationship write to ownership: a relation or membership write that changes an owner field turns the object into the caller's; the mass-assignment class owns the bind verdict
- Soft-delete persistence: an identifier that still resolves after removal keeps the access alive, so record the temporal primitive rather than a second swap
- Double-IDOR: chain two distinct identifier swaps so the terminal write lands on a foreign object, keeping each swap's verdict separate

## Testing Methodology

Before any probe, derive the verb, path pattern, and body field names from evidence (client bundles, interface descriptions, prior traffic) and retry with the inferred shape rather than concluding from one wrong-verb or placeholder-identifier request.

1. **Build matrix** - Subject × Object × Action matrix (who can do what to which resource)
2. **Obtain principals** - At least two: owner and non-owner, plus a privileged role where vertical access is in scope
3. **Collect identifiers** - Capture at least one valid object identifier per principal from list, search, or export surfaces
4. **Cross-channel testing** - Exercise every action (read, write, delete, export) while swapping identifiers, tokens, and tenants
5. **Transport variation** - Test across web, mobile, API, schema layer, socket, and RPC transports
6. **Consistency check** - The same rule must hold regardless of transport, content-type, serialization, or gateway
7. **Confirm the effect** - Snapshot before and after each write attempt, and the step completes when every claim carries a durable foreign-effect verdict

## Variants

- idor-direct-object-swap - Swap single object references to expose missing caller binding, with a cross-principal control pair and blind differentials where content is masked.
- idor-collection-batch-scope - Scope set-level collections and batch endpoints for per-item binding gaps, including mid-array foreign keys and import paths.
- idor-deferred-artifact-redemption - Redeem deferred artifacts to test retrieval-time caller binding, including job results, exports, and stored links.
- idor-context-carrier-substitution - Substitute identity carriers to expose precedence, audience, and async context gaps where a header, token, or delivery overrides the caller.
- idor-nested-expansion-binding - Expand nested and projected sub-resources to test per-hop caller binding inside an authorized parent.
- idor-second-order-stored-reference - Plant a foreign reference in stored state, then trigger the later operation that resolves it without re-binding the caller.

## False Positives

- Public or anonymous resources by design
- Soft-private data whose content is already public
- Idempotent metadata lookups that reveal no sensitive content
- Correct row-level checks enforced across all channels
- An empty result or null returned for another principal's resource, which is silent enforcement rather than exposure; compare against the owner's view to confirm

## Pro Tips

1. Test list, search, and export endpoints first; they are rich identifier seeders
2. Build a reusable identifier corpus from logs, notifications, messages, and client bundles
3. Toggle content-types and transports; authorization middleware often differs per stack
4. In the schema layer, validate at resolver boundaries; never trust parent authorization to cover children
5. In multi-tenant apps, vary tenant headers, subdomains, and path parameters independently
6. Check batch and background job endpoints; they frequently skip per-item checks
7. Inspect gateways for header trust and cache key composition
8. Treat opaque identifiers as untrusted; obtain them from leaks and test binding
9. Use timing, size, and validator differentials for blind confirmation when content is masked
10. Prove impact with precise before-and-after diffs and role-separated evidence

## Summary

Authorization must bind subject, action, and specific object on every request, regardless of identifier opacity or transport. If the binding is missing anywhere, the system is vulnerable.
