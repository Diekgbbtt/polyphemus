---
name: two-principal-authz
description: Two-principal authorization testing - A creates state, B acts on A's object (BOLA/IDOR, share/token, nested resources)
metadata:
  version: 1.0.0
---

# Two-Principal Authorization

Use this methodology for any mutating or access-controlled operation: one principal creates state, a second principal acts on it, and the check under test is whether the application binds each object and action to the right caller. It serves every class where authorization is the failing agreement, and it stays the same across them: two principals, owned objects, and every channel the operation exposes. Discover endpoints, methods, and field names at runtime from evidence rather than assuming them.

## Attack Surface

**Principals**
- **Principal set**: two identities the application issues (registered, invited, or guest), plus a privileged identity where vertical access is in scope.

**Object References**
- **Identifiers returned to the owner**: lists, documents, share grants, child objects, job handles, and exported artifacts.
- **Carriers**: paths, query parameters, structured bodies, headers, cookies, and message fields.

**Access Grants**
- **Grant flows**: share, invite, and token flows, and the scope each one declares: object, subtree, action set, and time window.

**Application Scope**
- **Operation scope**: any mutating or access-controlled operation the two principals can reach, across web, API, schema-layer, socket, and background surfaces.

## Reconnaissance

### Endpoint Discovery

- **Evidence-derived shapes**: derive verb, path shape, and field names from evidence (client bundles, interface descriptions, prior traffic); a wrong-verb response is not a negative.
- **Operation inventory**: inventory every operation that creates, reads, changes, or deletes an object, plus its nested children and deferred artifacts.
- **Grant-flow recording**: record grant and share flows and the token or link each one issues.

### Principal Setup

- **Principal creation**: create two principals through whatever path the application exposes, and keep both sessions for reuse.
- **Privileged identity**: add a privileged identity where vertical access is in scope.

### Object Harvesting

- **Owner object creation**: have the owner create at least one object per type, and capture the identifiers the application returns.
- **Identifier collection**: collect further owner identifiers from list, search, export, notification, and message surfaces.

### Baseline Matrix

- **Expected outcomes**: for each operation, record the expected outcome for owner, second principal, and any privileged role.
- **Matrix recording**: record the matrix before any test and keep it as the reusable artifact the later verdicts cite, so every cell is a stated expectation rather than a remembered one.
- **Channel differences**: note enforcement differences per channel before testing, because protections often differ by path.

## Detection Channels

- **Cross-principal read**: the second principal reads content or metadata belonging to the owner, which decides the finding.
- **Cross-principal write**: a write under the second principal's session lands on the owner's object and persists.
- **Grant scope excess**: a grant token acts outside its intended scope: another object, another action, or a later window.
- **Per-hop gap**: a nested child returns inside an authorized parent's read, which proves a per-hop gap.
- **Scope gap**: a list, export, or count surface returns the owner's objects to the second principal, which proves a scope gap without reading full content.
- **Masked differential**: a status, length, validator, or timing differential between owned and foreign identifiers, which confirms a binding gap when content is masked.
- **Channel inconsistency**: one channel enforces while another refuses or accepts, which proves enforcement is not uniform.
- **Token-only success**: an action succeeds with the grant token alone and no other credential, which reads as a token-scope gap.
- **Wrong-scope resolution**: a cross-tenant or cross-role reference resolves to the wrong scope.
- **Auth-bypass signal**: a mandatory-field or validation error that names a business field proves the request reached the logic layer without an authorization check, which reads as an auth-bypass signal.
- **Temporal binding gap**: an identifier that still passes after the principal that owns it was removed, revoked, or downgraded, which reads as a temporal binding gap.
- **Silent enforcement**: an empty result or null for the owner's object, which reads as silent enforcement rather than exposure.

## Adversarial Capabilities

- **Prerequisites**: two-principal authorization testing presupposes two identities, owner-created objects, and reach across every transport, and it consumes all three.
- **Principal registration**: register or obtain two principals, plus a privileged identity where vertical access is in scope.
- **Object creation**: create and own objects under the first principal, and capture the identifiers the application returns.
- **Grant holding**: hold the owner's grant flows and the token or link each issues.
- **Identifier corpus**: hold a harvested identifier corpus from other surfaces before any swap, so the attempt uses real identifiers rather than guesses.
- **Cross-principal replay**: replay every operation under the second principal's session with the owner's identifiers.
- **Masked comparison**: compare the second principal's responses by status, size, validator, and timing whenever the content stays masked.
- **State snapshots**: snapshot state before and after each write so a durable foreign effect is attributable.

## Trust Assumptions

- **The trust premise**: the class rests on one agreement: a principal may act on an object only where the application has bound that object and that action to that principal at the moment of use.
- **The agreement**: it holds every operation to a subject-object-action check, holds grants to their declared scope, holds nested and batch operations to a per-item check, and holds every transport to the same enforcement.
- **The exposure**: cross-principal position leaks when the binding is missing: the owner's identifier works under the second principal's session, a grant exceeds its scope, a child rides an authorized parent, or one channel enforces while another does not.
- **Shared agreement**: this methodology carries the shared agreement; each class it serves states the precise clause its own variants break.

## Key Vulnerabilities

### Missing Object Binding

- **Unbound resolution**: the operation resolves the identifier without checking that the caller owns or may act on it.
- **Batch and import gaps**: batch, bulk, and import paths validate only the first element or skip create-time checks.
- **Type-swap reach**: alternate value types for one identifier reach a differently enforced lookup.
- **Paired arguments bind separately**: where one request names a source and a destination, test which member carries the check, because a validated destination beside an unchecked source is the common asymmetry.

### Grant Scope Excess

- **Grant excess**: a share or invite token grants more than its label claims: more objects, more actions, or a longer window.
- **Token survival**: tokens that survive revocation, re-delivery to another principal, or redemption outside their declared scope.

### Nested and Deferred Objects

- **Unchecked child**: a child object reached through an authorized parent without its own check.
- **Foreign artifact retrieval**: deferred artifacts (jobs, exports, stored links) retrieved by a principal that did not create them.

### Channel Inconsistency

- **Transport inconsistency**: one transport enforces the binding while another (schema layer, socket, RPC, or background job) does not.
- **Cache and conditional gaps**: cached or conditional responses returned without re-checking the caller's binding.
- **Header precedence**: header precedence failures where a proxy or gateway injects identity the application trusts.

### Vertical and Tenant Mixing

- **Vertical reach**: a lower-privileged principal reaching a higher-privileged object or action.
- **Tenant mixing**: a tenant or organization reference mixed with a resource that belongs to another tenant.

## Advanced Techniques

**Matrix Discipline**
- **Matrix first**: build the subject-object-action matrix first, and add operations as they are discovered; a missing cell is an untested claim.
- **Control pairs**: test each cell with a control pair: the owner's request and the second principal's request under identical shaping.
- **Extend the control pair to whole route families**: establish one endpoint that is demonstrably gated on the same stack, then compare a sibling route family against it, so a differing response is attributable to the binding rather than to the stack.

**Identifier Collection**
- **Surface harvesting**: harvest identifiers from list, search, export, notification, and message surfaces rather than brute-forcing them.
- **Opaque identifiers**: treat opaque identifiers as untrusted but collectable.

**Grant Analysis**
- **Grant decoding**: decode opaque grant tokens where the design allows, and record the scope they declare.
- **Grant lifecycle**: test revocation, re-delivery, expiry, and cross-principal redemption separately.

**Blind and Masked Confirmation**
- **Masked differentials**: where content stays masked, use status, length, validator, and timing differentials.
- **State snapshots**: snapshot state before and after write attempts to confirm a durable foreign effect.

**Cross-Reference Discipline**
- **Schema-layer steps**: where the operation is a schema-layer resolver step, the graphql class owns the mechanics.
- **Race steps**: where a race window is suspected, hand the TOCTOU step to the race-conditions class.

## Bypass Techniques

- **Alternate transports**: alternate transports and encodings for the same operation, since enforcement differs per path.
- **Parser-shape variants**: duplicate keys, mixed case, and alias names, so the gate and the lookup read different fields.
- **Method variation**: method variation, including read verbs that accept state changes.
- **Edge values**: edge values and type-swapped forms for one reference.
- **Cached responses**: cached, conditional, and partial responses that return another principal's content.
- **Token-only requests**: grant-token-only requests, without the principal's session, to test the token path on its own.
- **Proxy-family naming**: name the proxy-techniques family at its carrier and shared-cache steps for alternate transports, encodings, and cached responses, rather than restating those mechanics here.
- **Defence-family naming**: name the defence-bypass family at its parser step for duplicate keys, mixed case, and alias names, rather than restating the parser mechanics here.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **CSRF plus authorization**: force a victim to act on an object you discovered.
- **Race plus authorization**: slip a modification past a spot check with concurrent requests.
- **Stored content plus authorization**: reach another principal's data through a rendering path.
- **Authorization failure plus escalation**: use a vertical binding gap to reach a privileged surface, then hand token validation to the token class.
- **Grant excess plus enumeration**: widen a single grant into a set of reachable objects.
- **Account-takeover catalogue**: the cross-class catalogue of primitives whose terminal proof is a second account reached from the attacker's own session is in `references/account-takeover-chains.md`, and each primitive's mechanism stays with its owning class.

## Testing Methodology

1. **Create two principals** - Register, invite, or obtain a guest, and keep both sessions for reuse
2. **Owner creates a resource** - One object per type, with its identifier captured from the response
3. **Record grants** - Where a share, invite, or token flow exists, have the owner issue one and keep the token
4. **Second principal acts on the owner's object** - Read, write, delete, and nested child actions under the second principal's credentials, and separately with the grant token alone
5. **Vary the channel** - Repeat on every transport and encoding the operation accepts
6. **Confirm the effect** - Snapshot state before and after; the proof pair is the owner's requests plus the second principal's successful request on the owner's identifier
7. **File on first success** - Record the confirmed cross-principal finding as soon as the second principal reaches the owner's object, rather than exploring further classes

The owner-versus-second-principal replay is driven by `scripts/two-principal-swap-harness`, which records one verdict per operation, reads the masked differential where content stays hidden, and warns when the route control is not gated.

## False Positives

- **Public objects**: public or intentionally shared objects.
- **Self-created identifiers**: success on identifiers the second principal created itself, which is not a binding failure.
- **Silent enforcement**: an empty result or opaque error for the owner's object, which hides rather than exposes.
- **In-scope grants**: a grant acting exactly within its declared scope.
- **Uniform refusals**: operations refused on every channel for every non-owner principal.

## Pro Tips

- **Returned identifiers**: identify objects by what the application returned, not by brute-forced identifiers.
- **Seeder surfaces**: test list, search, export, and notification surfaces first; they are rich identifier seeders.
- **Method coverage**: never stop at one method: read, write, delete, and child operations bind separately.
- **Wrong-verb caution**: a single wrong-verb or placeholder-identifier response is not a negative; derive the real shape from evidence.
- **Channel comparison**: compare channels, not only roles; enforcement often differs per transport.
- **Grant-token validation**: validate a grant token twice: alongside the principal's session and alone.
- **Masked differentials**: use masked-response differentials when content is not returned.
- **First-success filing**: file the finding on the first confirmed cross-principal effect, with the owner/foreign request pair as evidence.

## Summary

Authorization must bind subject, object, and action at the moment of use on every channel: anything a caller can name must be re-checked against the caller. The methodology is the same for every class it serves, and the proof is always the same pair: the owner's object, reached by the second principal.
