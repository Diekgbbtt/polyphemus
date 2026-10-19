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
- Two identities the application issues (registered, invited, or guest), plus a privileged identity where vertical access is in scope

**Object References**
- Identifiers returned to the owner: lists, documents, share grants, child objects, job handles, and exported artifacts
- Carriers: paths, query parameters, structured bodies, headers, cookies, and message fields

**Access Grants**
- Share, invite, and token flows, and the scope each one declares: object, subtree, action set, and time window

**Application Scope**
- Any mutating or access-controlled operation the two principals can reach, across web, API, schema-layer, socket, and background surfaces

## Reconnaissance

### Endpoint Discovery

- Derive verb, path shape, and field names from evidence (client bundles, interface descriptions, prior traffic); a wrong-verb response is not a negative
- Inventory every operation that creates, reads, changes, or deletes an object, plus its nested children and deferred artifacts
- Record grant and share flows and the token or link each one issues

### Principal Setup

- Create two principals through whatever path the application exposes, and keep both sessions for reuse
- Add a privileged identity where vertical access is in scope

### Object Harvesting

- Have the owner create at least one object per type, and capture the identifiers the application returns
- Collect further owner identifiers from list, search, export, notification, and message surfaces

### Baseline Matrix

- For each operation, record the expected outcome for owner, second principal, and any privileged role
- Note enforcement differences per channel before testing, because protections often differ by path

## Detection Channels

- The second principal reads content or metadata belonging to the owner, which decides the finding.
- A write under the second principal's session lands on the owner's object and persists.
- A grant token acts outside its intended scope: another object, another action, or a later window.
- A nested child returns inside an authorized parent's read, which proves a per-hop gap.
- A list, export, or count surface returns the owner's objects to the second principal, which proves a scope gap without reading full content.
- A status, length, validator, or timing differential between owned and foreign identifiers, which confirms a binding gap when content is masked.
- One channel enforces while another refuses or accepts, which proves enforcement is not uniform.
- An action succeeds with the grant token alone and no other credential, which reads as a token-scope gap.
- A cross-tenant or cross-role reference resolves to the wrong scope.
- An empty result or null for the owner's object, which reads as silent enforcement rather than exposure.

## Adversarial Capabilities

Two-principal authorization testing presupposes two identities, owner-created objects, and reach across every transport, and it consumes all three.
- Register or obtain two principals, plus a privileged identity where vertical access is in scope.
- Create and own objects under the first principal, and capture the identifiers the application returns.
- Hold the owner's grant flows and the token or link each issues.
- Replay every operation under the second principal's session with the owner's identifiers.
- Compare the second principal's responses by status, size, validator, and timing whenever the content stays masked.
- Snapshot state before and after each write so a durable foreign effect is attributable.

## Trust Assumptions

The class rests on one agreement: a principal may act on an object only where the application has bound that object and that action to that principal at the moment of use.
The agreement holds every operation to a subject-object-action check, holds grants to their declared scope, holds nested and batch operations to a per-item check, and holds every transport to the same enforcement.
Cross-principal position leaks when the binding is missing: the owner's identifier works under the second principal's session, a grant exceeds its scope, a child rides an authorized parent, or one channel enforces while another does not.
This methodology carries the shared agreement; each class it serves states the precise clause its own variants break.

## Key Vulnerabilities

### Missing Object Binding

- The operation resolves the identifier without checking that the caller owns or may act on it
- Batch, bulk, and import paths validate only the first element or skip create-time checks
- Alternate value types for one identifier reach a differently enforced lookup

### Grant Scope Excess

- A share or invite token grants more than its label claims: more objects, more actions, or a longer window
- Tokens that survive revocation, re-delivery to another principal, or redemption outside their declared scope

### Nested and Deferred Objects

- A child object reached through an authorized parent without its own check
- Deferred artifacts (jobs, exports, stored links) retrieved by a principal that did not create them

### Channel Inconsistency

- One transport enforces the binding while another (schema layer, socket, RPC, or background job) does not
- Cached or conditional responses returned without re-checking the caller's binding
- Header precedence failures where a proxy or gateway injects identity the application trusts

### Vertical and Tenant Mixing

- A lower-privileged principal reaching a higher-privileged object or action
- A tenant or organization reference mixed with a resource that belongs to another tenant

## Advanced Techniques

**Matrix Discipline**
- Build the subject-object-action matrix first, and add operations as they are discovered; a missing cell is an untested claim
- Test each cell with a control pair: the owner's request and the second principal's request under identical shaping

**Identifier Collection**
- Harvest identifiers from list, search, export, notification, and message surfaces rather than brute-forcing them
- Treat opaque identifiers as untrusted but collectable

**Grant Analysis**
- Decode opaque grant tokens where the design allows, and record the scope they declare
- Test revocation, re-delivery, expiry, and cross-principal redemption separately

**Blind and Masked Confirmation**
- Where content stays masked, use status, length, validator, and timing differentials
- Snapshot state before and after write attempts to confirm a durable foreign effect

**Cross-Reference Discipline**
- Where the operation is a schema-layer resolver step, the graphql class owns the mechanics
- Where a race window is suspected, hand the TOCTOU step to the race-conditions class

## Bypass Techniques

- Alternate transports and encodings for the same operation, since enforcement differs per path
- Duplicate keys, mixed case, and alias names, so the gate and the lookup read different fields
- Method variation, including read verbs that accept state changes
- Edge values and type-swapped forms for one reference
- Cached, conditional, and partial responses that return another principal's content
- Grant-token-only requests, without the principal's session, to test the token path on its own
- Name the proxy-techniques family at its carrier and shared-cache steps for alternate transports, encodings, and cached responses, rather than restating those mechanics here.
- Name the defence-bypass family at its parser step for duplicate keys, mixed case, and alias names, rather than restating the parser mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- CSRF plus authorization: force a victim to act on an object you discovered
- Race plus authorization: slip a modification past a spot check with concurrent requests
- Stored content plus authorization: reach another principal's data through a rendering path
- Authorization failure plus escalation: use a vertical binding gap to reach a privileged surface, then hand token validation to the token class
- Grant excess plus enumeration: widen a single grant into a set of reachable objects

## Testing Methodology

1. **Create two principals** - Register, invite, or obtain a guest, and keep both sessions for reuse
2. **Owner creates a resource** - One object per type, with its identifier captured from the response
3. **Record grants** - Where a share, invite, or token flow exists, have the owner issue one and keep the token
4. **Second principal acts on the owner's object** - Read, write, delete, and nested child actions under the second principal's credentials, and separately with the grant token alone
5. **Vary the channel** - Repeat on every transport and encoding the operation accepts
6. **Confirm the effect** - Snapshot state before and after; the proof pair is the owner's requests plus the second principal's successful request on the owner's identifier
7. **File on first success** - Record the confirmed cross-principal finding as soon as the second principal reaches the owner's object, rather than exploring further classes

## False Positives

- Public or intentionally shared objects
- Success on identifiers the second principal created itself, which is not a binding failure
- Silent enforcement: an empty result or opaque error for the owner's object, which hides rather than exposes
- A grant acting exactly within its declared scope
- Operations refused on every channel for every non-owner principal

## Pro Tips

1. Identify objects by what the application returned, not by brute-forced identifiers
2. Test list, search, export, and notification surfaces first; they are rich identifier seeders
3. Never stop at one method: read, write, delete, and child operations bind separately
4. A single wrong-verb or placeholder-identifier response is not a negative; derive the real shape from evidence
5. Compare channels, not only roles; enforcement often differs per transport
6. Validate a grant token twice: alongside the principal's session and alone
7. Use masked-response differentials when content is not returned
8. File the finding on the first confirmed cross-principal effect, with the owner/foreign request pair as evidence

## Summary

Authorization must bind subject, object, and action at the moment of use on every channel: anything a caller can name must be re-checked against the caller. The methodology is the same for every class it serves, and the proof is always the same pair: the owner's object, reached by the second principal.
