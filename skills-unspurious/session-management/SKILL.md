---
name: session-management
description: Session lifecycle testing - regeneration at authentication, invalidation at logout and credential change, refresh rotation and reuse detection, identifier entropy, and cookie attribute assessment.
metadata:
  version: 1.0.0
---

# Session Management

Session management failures let a client-supplied session identifier outlive or outrank the authentication event that created it.
The class covers the whole lifecycle: issuance, elevation at the authentication boundary, rotation on credential change, revocation at logout and device removal, expiry, and the carriage of the identifier itself.
Session state is coupled to the systems around it: follow the authentication, authorization, and two-principal-authz procedures first where a finding depends on them, and name the property each kill chain consumes rather than restating those procedures.

## Attack Surface

- **Lifecycle events**: pre-authentication issuance, the login or federation callback boundary, logout, credential change, identifier change, device and session revocation, and expiry.
- **Carriers**: session cookies, bearer and refresh tokens used as session state, server-side stores keyed by a client-supplied identifier, identifiers carried in URLs, and federated session linkage.
- **Cookie attributes**: secure and script-inaccessible flags, cross-site sending semantics, domain and path scope, name-prefix guarantees, and persistence beyond the browser session.
- **Identifier material**: entropy, structure, derivation from counters or identity fields, and duplicate issuance under identical conditions.
- **Coupled systems**: the authentication procedure that issues the identifier, the authorization checks that consume it, and the two-principal procedures that compare it across principals; each is named at the step that needs it, never restated.
- **Scope note**: an attribute gap alone is a policy observation until a chain supplies impact; the chain names the class that owns the enabling property.

## Reconnaissance

### Lifecycle Mapping

- Enumerate every event that issues, elevates, rotates, or revokes an identifier per surface: interactive login, federation callback, refresh, logout, credential change, identifier change, and device removal.
- Record the identifier before and after each event, so the rotation question has a baseline rather than a memory.
- Note where session state lives: a server-side store, a self-contained token, or a mix, because revocation mechanics differ per store.
- Record the identifier's audience and scope: which services accept it and which privileges it carries.

### Identifier and Attribute Recording

- Collect a large sample of freshly issued identifiers under identical conditions before judging entropy.
- Record each cookie's attributes and prefix guarantees as delivered on an authenticated response, not only on the login page.
- Record whether identifiers ever travel in URLs, logs, or cacheable responses, since carriage is a separate exposure from invalidation.

### Coupled-System Reconnaissance

- Map the authentication procedure that issues the identifier and follow it first; the token and flow steps belong to `authentication-jwt` and `oauth`, named here rather than restated.
- Map the authorization checks that consume the identifier and follow the procedures owned by the authorization classes, because a live identifier after a downgrade is their access verdict to make.
- Hold two concrete sessions captured by real flows, with the principal handling owned by `two-principal-authz`.

## Detection Channels

- An identifier unchanged across the authentication boundary that then carries authenticated authority, which decides fixation.
- A replayed pre-event identifier that still returns the principal's own data after logout, credential change, identifier change, or device revocation, confirmed by body difference rather than status.
- A rotated identifier whose predecessor still answers, which reads as soft rotation rather than regeneration.
- A refreshed credential whose predecessor still mints sessions, or whose successor survives the predecessor's replay, which reads as missing rotation or missing reuse detection.
- Sibling sessions for one principal that stay live after a revocation event that should have ended them.
- Duplicate or structurally derived identifiers across a large identical-conditions sample, which reads as low entropy.
- An identifier that still authenticates after the identity that owns it was removed, downgraded, or moved, which reads as a stale authorization context.
- Cookie attribute and prefix gaps on the authenticated response, recorded as policy observations until a chain supplies impact.
- A federated session that outlives the identity-provider session or the application's own logout.

## Adversarial Capabilities

Session testing presupposes two concrete sessions captured by real flows plus control reads, and it consumes both.
- Hold an attacker session and a victim session captured by real flows, never placeholder values; the principal handling follows `two-principal-authz`.
- Replay a captured identifier explicitly rather than reusing a live client store, because logout may have overwritten the client-side copy.
- Keep a negative control (a garbage identifier) and a positive baseline (the live session) beside every claim, so a status-only echo never decides a finding.
- Collect identifiers in bulk under identical conditions for the entropy judgement.
- Trigger lifecycle events on the victim session while holding the attacker copy, so invalidation is tested rather than assumed.
- Read the application's own state under the replayed identifier, not only the response line.

## Trust Assumptions

The class rests on one agreement: the session identifier is server-chosen, regenerated at every privilege change, and revocable at every event that ends the authority it carries.
The agreement holds the identifier to server-side generation rather than client acceptance, holds the authentication boundary to regeneration, holds logout, credential change, and device revocation to server-side invalidation of every sibling session, holds rotated credentials to single use with reuse detection, and holds every service that accepts the identifier to the same revocation state.
Sensitive position leaks when the identifier outlives its authority: it survives a boundary it should have been replaced at, an event it should have been revoked by, or an expiry it should have honoured.
Session-layer-only kill chains still rest on the coupled systems: fixation needs an acceptance or planting path that the authentication and cross-site mechanics provide, and forgery of a self-contained session needs the secret material and key-publicity properties owned by `crypto-weakness` and `authentication-jwt`.

## Key Vulnerabilities

### Regeneration at the Authentication Boundary

- Authenticate while carrying a pre-authentication identifier and compare the identifier before and after; a value carried across the boundary is the finding.
- Test whether an arbitrary client-chosen identifier is accepted before authentication, which turns fixation into a one-request plant.
- Treat a value change as a hypothesis rather than a verdict: confirm the predecessor is genuinely dead before concluding regeneration.

### Invalidation at Lifecycle Events

- Replay the pre-event identifier after logout, credential change, identifier change, and device or session revocation.
- Test sibling sessions, not only the acting session, because applications frequently end the acting session while a sibling stays live.
- Confirm invalidation server-side by replay, because a client-side cookie clear leaves the server record intact.

### Rotation and Reuse Detection

- Rotate a refresh credential once and compare predecessor with successor.
- Replay the predecessor, then test the successor: a predecessor that still mints, or a successor that survives the replay, is the persistence bug.
- Treat the whole credential family as the revocation unit, since per-token revocation leaves the family usable.

### Identifier Entropy and Structure

- Collect a large sample and measure structure and effective randomness rather than counting characters.
- Decode candidate identifiers and look for counters, timestamps, or identity fields; the derivation step belongs to `crypto-weakness` and `crypto-predictable-token`, named here rather than restated.
- Treat duplicates in a fresh sample as catastrophic rather than statistical noise.

### Cookie and Carrier Hygiene

- Record attribute and prefix gaps on authenticated responses as policy facts, then name the chain that supplies impact.
- Pair a script-access gap with a real script sink owned by `xss`, a cleartext carriage with a network position, a cross-site sending gap with a delivery owned by `csrf`, and a broad domain scope with a sibling-subdomain write path.

### Federated and Device-Bound Sessions

- Compare the application session's life with the identity-provider session's life at logout and at provider-side expiry; the flow steps belong to `oauth` and `authentication-jwt`.
- Test device-binding downgrade by replaying the plain identifier while the binding proof is stripped; an accepted plain identifier means the binding is advisory.

## Advanced Techniques

### Post-Removal and Stale-Context Validity

- Replay an identifier after the owning identity is removed, downgraded, or moved between scopes; a still-passing identifier reads as a stale authorization context, whose access verdict belongs to the authorization classes.
- Test cached or edge-held decisions separately from the session store, naming the `proxy-techniques` family at its shared-cache step.

### Bulk Issuance Sampling

- Sample in bulk across parallel flows to catch reuse and collisions that sequential sampling misses.
- Keep the sampling conditions identical, so the entropy judgement is defensible rather than anecdotal.

### Session-State Recovery

- Where the session is a self-contained token, test expiry, revocation-list coverage, and audience binding; the token mechanics belong to `authentication-jwt` and the key-basis clauses to `crypto-weakness`.
- Where the store is server-side, test consistency across replicas and intermediaries, naming the `proxy-techniques` family at its relay step rather than restating it.

## Bypass Techniques

- **Control scope**: session controls fail open through acceptance and planting paths rather than payload shapes, so each defeat names the coupled system that supplies it.
- **Client-chosen identifiers**: an accepted client-supplied identifier defeats regeneration requirements, because the attacker chooses the value in advance.
- **Soft rotation**: a rotated identifier whose predecessor stays valid defeats the regeneration control while appearing to satisfy it.
- **Client-validated tokens**: a self-contained token that logout clears only client-side defeats server-side revocation by replay of the captured value.
- **Prefix and scope gaps**: an absent host-only prefix or a broad domain scope lets a sibling subdomain or a non-secure context overwrite the identifier.
- **Cache and history restoration**: a cached authenticated response or a restored history entry defeats the client-side half of logout.
- **Planting through coupled mechanics**: an accepted identifier in a URL or a cross-site-deliverable request plants the value; `csrf` owns the delivery mechanics and this class records only the session verdict.
- **Coupled-system requirements**: fixation and self-contained-token forgery rest on properties owned by `authentication-jwt`, `oauth`, `two-principal-authz`, and `crypto-weakness`; name the owner at the step that consumes the property.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Fixation to session takeover: plant a known identifier before the victim authenticates, then ride the elevated session; the planting path is supplied by an acceptance flaw, a cross-site delivery, or a sibling-subdomain write.
- Stolen session to persistent access: pair a session that survives credential change with a cookie-theft primitive, so the victim's reset does not evict the attacker; `xss` and `information-disclosure` own the theft step.
- Refresh reuse to durable access: a leaked refresh credential without reuse detection mints access indefinitely; the leak source stays with the class that finds it.
- Session to authorization: an identifier that stays live after a downgrade or a removal hands a stale privilege set to the authorization classes, which own the access verdict.
- Session swap to cross-principal access: swap a session between principals under one request shape, naming `two-principal-authz` at the principal step.

## Testing Methodology

1. **Map the lifecycle** - enumerate every issue, elevate, rotate, and revoke event per surface, and the step completes when each event names its identifier and its store.
2. **Capture two real sessions** - an attacker and a victim identifier from real flows, with a negative control and a live baseline, and the step completes when every later claim has a control beside it (principal handling follows `two-principal-authz`).
3. **Test regeneration** - authenticate while carrying a pre-authentication identifier and compare before with after, and the step completes when each authentication surface carries a regenerated or carried verdict.
4. **Test invalidation** - replay the pre-event identifier after logout, credential change, identifier change, and device revocation, including sibling sessions, and the step completes when every event and every sibling carries a dead or live verdict confirmed by body difference.
5. **Test rotation and reuse** - rotate once, replay the predecessor, then test the successor, and the step completes when the credential family carries a rotation and reuse-detection verdict.
6. **Sample entropy in bulk** - collect a large identical-conditions sample and judge structure and effective randomness, and the step completes when the sample supports or rejects a low-entropy claim.
7. **Assess carriers and coupling** - record attributes, prefixes, URL carriage, and federated linkage, then name the coupled authentication, authorization, and token procedures each requirement belongs to, and the step completes when every carrier observation carries a chain verdict or a policy-only verdict.
8. **Confirm the effect** - re-read the application's own state under the replayed identifier and rule out cached, edge, and public responses before filing, and the step completes when every positive shows the principal's own data rather than a status echo.

## False Positives

- A status-only echo: a cached or public response that returns success for every caller; confirm with a body difference against the authenticated baseline and a garbage-identifier negative control.
- An attribute gap with no chain: missing flags are policy observations until a script sink, a network position, or a cross-site delivery supplies impact.
- A value change taken as proof of safety: confirm the predecessor is genuinely dead before concluding rotation.
- A long or random-looking identifier taken as proof of entropy: decode and measure a large sample instead.
- A duplicate-looking identifier that came from a stale cache rather than from fresh issuance.
- An identifier that passes for a re-created identity rather than a stale session, confirmed by comparing the identity the application returns.
- A federated auto-login the identity provider intended rather than an application-side single-logout gap.
- A session pinned to a network origin or expired lazily, which mimics invalidation when retested from a different address after a delay.

## Pro Tips

1. Capture both sessions by real flows and replay captured values explicitly; never judge from a client store that logout may have overwritten.
2. Body-diff every positive against the authenticated baseline and keep a garbage-identifier negative control beside it.
3. Re-test from a second address and after a short delay, because some servers expire lazily or pin sessions to a network origin.
4. Test sibling sessions at every revocation event, not only the acting session; sibling survival is the persistent-access primitive.
5. Sample identifiers in bulk under identical conditions, since a small sample proves nothing about entropy.
6. Follow the authentication, authorization, and two-principal procedures first where the finding depends on them, and record only the session verdict here.
7. Report the coupled property that makes the chain work, so a session finding is never filed as a standalone.
8. Prefer the smallest proof: one replay of a pre-event identifier against one protected read that returns the principal's own data.

## Summary

A session identifier must be server-chosen, regenerated at authentication, revoked at every event that ends its authority, and single-use across rotation.
Test each lifecycle event with two real sessions, confirm every positive by body difference, and state the coupled authentication, authorization, or crypto property each chain consumes.
