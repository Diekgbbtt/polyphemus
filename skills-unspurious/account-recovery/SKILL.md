---
name: account-recovery
description: Recovery-flow flaws where the artifact that proves control of an identity channel is exposed, predictable, unbound, or long-lived, and where identity transitions complete without the intended proof.
metadata:
  version: 1.0.0
---

# Account Recovery

A recovery flow grants a credential or an identity change on the strength of a proof that the requester controls the channel the account names.
The application trusts that the artifact it issues is unguessable, single-use, short-lived, and bound to the account and the requested transition, that the delivery destination is built from server-side state, and that the identity the artifact names is the identity it changes.
The class covers the request step, the artifact lifecycle, the binding between artifact and account, the identity transitions the flow reaches, and every alternate recovery factor.

## Attack Surface

- **Applicability**: centers on a request step that issues a recovery artifact, a completion step that consumes it, and a delivery channel between them.
- **Entry points**: recovery, reset, unlock, identity-change, and passwordless entries, including any endpoint that issues a session or a credential from an identifier alone.
- **Identity transitions**: the credential set, the address or identifier change, the factor reset, and the session issue the flow can reach.
- **Artifact carriers**: the delivery channel, the response body, the request address, and any redirect or embedded resource the artifact travels through.
- **Alternate factors**: knowledge answers, a secondary channel, and a support-assisted path, each carrying its own proof strength.
- **Identity naming**: the field that names the account is the join between the requester and the account the artifact will change.

## Reconnaissance

### Entry-Point and Artifact Mapping

- **Entry-point inventory**: enumerate every recovery and identity-transition entry point and record the request and completion endpoints with every field each one accepts.
- **Artifact-shape recording**: record the artifact shape, its length, alphabet, lifetime, and single-use behavior, and whether a re-issue supersedes the previous artifact.
- **Raw-delivery reading**: record the delivery channel and read the raw delivery, because the artifact's full form commonly exists only in the link that is sent.
- **End-to-end baseline**: complete the flow for a test identity first, so a later effect is attributable to one changed value.

### Oracle and Control Mapping

- **Oracle comparison**: compare the request-step response between a known and an unknown identity, including status, body, length, and timing, and record the difference.
- **Limit recording**: record the rate limit on the request step and on the completion step separately.
- **Binding recording**: record the binding the completion step enforces, whether session, device, address, or none, and the identity field the completion step honors.

## Detection Channels

- **Enumeration oracle**: a measurably different response for a known and an unknown identity at the request step, which is the enumeration oracle.
- **Body-returned artifact**: the artifact returned in the response body instead of the channel, which is an immediate completion path.
- **Reused artifact**: a consumed artifact accepted a second time, which shows the single-use clause is unenforced.
- **Expired artifact**: an artifact accepted after its intended lifetime, which shows the expiry clause is unenforced.
- **Unbound artifact**: an artifact accepted from a different session, device, or address, which shows the binding clause is unenforced.
- **Request-built destination**: the delivery link's host or scheme decided by a request value, which shows the destination is built from request state.
- **Foreign-channel completion**: the flow completing for an identity whose channel the tester does not control, which is the class's own success signal.
- **Low-entropy alternate factor**: an alternate factor accepting a low-entropy answer, which shows the recovery strength sits below the primary credential.
- **Artifact-free session issue**: a session issued with no artifact consumed, which shows the flow can be short-circuited.

## Adversarial Capabilities

- **Readable channel**: hold a readable channel for a test identity, and read the raw delivery including every value in the link.
- **Second identity**: hold a second identity to observe cross-account effects and to confirm a swap changes the account the flow targets.
- **Artifact sampling**: sample several artifacts to compare shape and entropy before claiming predictability.
- **Replay and reuse submission**: submit one artifact more than once, from a second session, and across its intended lifetime.
- **Identity-field control**: supply the identity value through every field the request and completion steps accept.

## Trust Assumptions

- **The agreement**: the recovery flow grants a credential or an identity change only to the party that proves control of the channel the account names, the artifact is unguessable, single-use, short-lived, and bound to the account, the session, and the requested transition, the delivery destination is built from server-side state, and the identity the artifact names is the identity it changes.
- **The channel-proof clause fails**: the flow completes for an identity the requester does not control, including through an alternate factor that proves less than the channel.
- **The lifecycle clause fails**: an artifact is predictable, exposed before delivery, reusable, long-lived, or not superseded by a re-issue.
- **The binding clause fails**: an artifact is accepted from any session, device, or address, or the identity field is honored without a join to the account the artifact was issued for.
- **The destination clause fails**: the delivery link's host or scheme is built from a request value, so the artifact is delivered to a destination the requester chose.

## Key Vulnerabilities

### Request-Step Oracles

- **Enumeration oracle**: response text, status, length, or timing differs between a known and an unknown identity; name `weak-credential-discovery` at the enumeration step rather than restating its procedure here.
- **Artifact exposure**: the artifact is returned in the response body, written to a log, or carried in a request address where the ambient referrer policy leaks it to a third party.
- **Unbounded requesting**: no effective rate limit on the request step, so the flow can be flooded or the artifact space walked; name `defence-bypass` at the throttle step.

### Artifact Lifecycle Gaps

- **Predictability**: an artifact derived from the identity, a counter, or a time value, so the space is enumerable once the derivation is known; name `crypto-weakness` at the derivation step.
- **Reuse**: a consumed artifact accepted again, in the same session or a later one.
- **No expiry**: an artifact accepted long after it was issued, or after a newer artifact superseded it.
- **Cross-account swap**: the identity field supplied at completion is honored over the account the artifact was issued for, so one account's artifact changes another account's credential.

### Binding and Destination Gaps

- **Unbound artifact**: accepted from any session, device, or address, so link forwarding is enough to complete the flow.
- **Request-built destination**: the delivery link is assembled from a request-supplied host, scheme, or path, which is a host-value problem owned by `header-injection`.
- **Cross-context completion**: the completion step runs in a session that never requested the artifact, with no join recorded.

### Identity-Transition Reach

- **Address change without re-authentication**: the identity change completes with no proof to the current address, so a transient session becomes a durable address change.
- **Factor reset through recovery**: the recovery flow resets or replaces the second factor, which converts a recovery weakness into a factor bypass; name `mfa-bypass` at the factor step.
- **Session issue without the artifact**: an entry that issues a session from an enumerable identifier alone.
- **Pre-account seeding**: an attacker-controlled channel is attached to an identity before the victim completes it, so the victim inherits the seeded state.

## Advanced Techniques

- **Transition sequencing**: change the identity to an attacker-controlled channel first, then run the recovery flow, so the artifact is delivered to the attacker without touching the artifact's own checks.
- **Re-issue window**: request a second artifact and test whether the first stays valid, because supersession is a separate control from expiry.
- **Alternate-factor reach**: test the knowledge-answer and support-assisted paths separately, since each carries its own strength and limit.
- **Passwordless entry by identifier**: probe the entries that issue a session or set a credential from an identifier alone, because they are recovery flows without an artifact.
- **Delivery-path reading**: read every redirect and embedded resource the delivery link touches, because the artifact commonly leaks before the victim clicks; name `proxy-techniques` at the carrier step.
- **Cross-session completion**: complete the flow in a second session that never requested the artifact, which separates the binding clause from the artifact clause.

## Bypass Techniques

- **Response uniformization**: measure the request-step response across identities, because a uniform message with a timing or length difference is still an oracle.
- **Throttle defeat**: a limit that slows without blocking is not enforcement; name `defence-bypass` at the throttle step rather than restating the evasion mechanics here.
- **Binding defeat**: complete from a second session, device, or address where the artifact carries no join to the requester.
- **Lifetime defeat**: use an artifact outside its intended window, and after a re-issue, where neither control is enforced.
- **Supersession defeat**: keep the first artifact valid across a re-issue, where the flow issues a second artifact without invalidating the first.
- **Cross-account identity swap**: supply a different identity at completion where the artifact is not joined to the account it was issued for.
- **Old-address confirmation**: where the flow confirms an address change only to the new address, the current address owner never sees the change.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Recovery plus a credential oracle**: a recovered credential pairs with an unbound artifact, and `weak-credential-discovery` owns the credential step.
- **Recovery plus a factor gap**: the recovery path issues a session without the factor, and `mfa-bypass` owns the factor step.
- **Recovery plus cross-site delivery**: a cross-site request reaches the request step where the flow accepts it, and `csrf` owns the delivery step.
- **Recovery plus a claimed mail host**: a taken-over host that receives the delivery converts a takeover into recovery-artifact interception, and `subdomain-takeover` owns the claim step.
- **Recovery plus a host-value sink**: a request-built delivery destination redirects the artifact, and `header-injection` owns the host-value step.
- **Recovery plus an identity change**: the recovery flow reaches an identity transition that is itself weakly authorized, and `two-principal-authz` owns the cross-account step.

## Testing Methodology

Recovery testing baselines the delivery first and mutates one control second, because no artifact finding is meaningful without the raw artifact.

1. **Inventory entry points** - list every recovery and identity-transition entry point with its fields and delivery channel, and the step completes when no entry point is unlisted.
2. **Baseline the flow** - complete a recovery for a test identity and read the raw delivery, and the step completes when the artifact, its channel, and the resulting state are recorded.
3. **Probe the request step** - compare a known and an unknown identity, test artifact exposure, and test the request limit, and the step completes when the oracle, the exposure, and the limit each carry a verdict.
4. **Probe the artifact lifecycle** - reuse a consumed artifact, replay an aged one, and re-issue to test supersession, and the step completes when each lifecycle shape carries a verdict.
5. **Probe the binding** - complete from a second session, device, and address, and swap the identity field, and the step completes when each binding shape carries a verdict.
6. **Probe the identity transitions** - test the address change, the factor reset, and every entry that issues a session without an artifact, and the step completes when each transition carries a reach verdict.
7. **Confirm the completion** - complete the flow on a second account the tester does not own the channel of, and record the exact shape, and the step completes when the finding carries a reproducible shape and the state it reached.

## False Positives

- **Timing noise**: a response difference that is timing noise rather than an oracle, confirmed by repeating the measurement across identities.
- **Hidden validation component**: an artifact that looks predictable but carries a server-validated component that is not visible in its delivered form.
- **Freshly generated credential**: a displayed temporary credential that is freshly generated rather than the stored original.
- **Pre-authenticated session**: a session issued because the tester was already authenticated, confirmed by the pre-request state.
- **Own-channel confirmation**: an identity change confirmed to the current address, where the tester also controls that channel.
- **Slow-only rate limit**: a rate limit that slows rather than blocks, which is a weak control rather than a missing one; report it as the strength finding it is.
- **Own-delivery completion**: a completion that only works while the tester holds the artifact from its own delivery, which is the flow working as intended.

## Pro Tips

- **Raw-delivery reading**: read the raw delivery, because the artifact's full form commonly exists only in the link that is sent.
- **Sampling before claims**: sample several artifacts before claiming predictability, and name the derivation only when it reproduces.
- **Second-session testing**: test from a second session and a second device; a binding gap is invisible from the requesting session.
- **Isolated identity swap**: keep the identity-field swap as its own attempt so the cross-account effect stays attributable.
- **Transition sweep**: sweep the transitions after recovery, because the flow commonly reaches more than the credential it names.
- **Second-account completion**: confirm completion on a second account, then stop at the narrowest proof that shows it.

## Summary

A recovery flow is safe only when its artifact is unguessable, single-use, short-lived, and joined to the account it changes, and when every transition it reaches carries its own proof.
Test the artifact and the transition set together, because the flow is as strong as its weakest accepted path.

