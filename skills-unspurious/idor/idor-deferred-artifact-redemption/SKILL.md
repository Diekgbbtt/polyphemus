---
name: idor-deferred-artifact-redemption
description: Redeem deferred artifacts to test retrieval-time caller binding. Use when a job result outlives its creation request, when an export download follows a task identifier, when a stored link carries scope and expiry.
metadata:
  version: 1.0.0
---

# IDOR Deferred Artifact Redemption

Deferred redemption testing decides whether a retrieval path rebinds a stored artifact to the caller that redeems it.
The leading word is redeem: every probe creates as one actor and redeems as another across a time gap.

## Attack Surface

- **Redeem**: applies where creation and retrieval split across two requests joined by an artifact handle.
- **Handle forms**: the handle may be a job or task identifier, an export download token, or a stored link with scope and expiry binding.
- **Storage paths**: file and object storage paths ride inside this variant as scope-and-expiry redemption while storage needs no content analysis beyond key and signature binding.
- **Out-of-scope swaps**: live single-action swaps stay in the sibling direct variant, and only two-phase create-then-redeem lives here.

## Reconnaissance

- **Creation-endpoint mapping**: map every creation endpoint that returns a retrievable handle before redeeming anything.
- **Lifecycle recording**: record the handle lifecycle from history and client material, including scope, expiry, and finalize or approve transitions.
- **Handle collection**: collect one handle per principal by creating jobs, exports, and stored links under each role until each role owns redeemable artifacts.
- **Baseline capture**: capture the baseline retrieval for the creating principal before attempting foreign redemption.

## Detection Channels

- **Foreign artifact content**: foreign artifact content returned to a non-creator decides the finding.
- **Stale link redemption**: a stale or cross-scope stored link that still redeems signals missing scope and expiry binding.
- **Post-revocation redemption**: a handle or link that still redeems after the creating principal was removed, revoked, or downgraded signals a cached authorization context rather than a live binding.
- **Write-side transitions**: finalize, cancel, and approve transitions that accept another actor's handle confirm write-side redemption gaps.
- **Blind differentials**: timing and size differentials between the creator retrieval and the foreign retrieval confirm blind redemption.

## Adversarial Capabilities

- **Prerequisites**: this variant presupposes working sessions for at least a creator and a foreign redeemer, with an approver role where the flow names one.
- **Artifact creation**: it consumes the ability to create artifacts as an allowed actor and hold their handles past creation.
- **Delayed replay**: it consumes the ability to replay those handles under a different principal after a delay.
- **Principal handling**: principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

- **The agreement**: the feature executes under the agreement that an object reference arriving with a request is private to the caller, that any surrounding authorization already binds the referenced object to that caller, that identity arriving through surrounding channels belongs to the same caller, that a token accepted by one service transfers only to its intended audience, and that a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
- **The failing clause**: the agreement fails when the retrieval path redeems a stored artifact without rechecking the binding that creation established.

## Key Vulnerabilities

- **Bent step**: two-phase create-then-redeem binding is the bent step this variant owns over the parent.
- **Two-phase redemption**: create an export, task, or stored link as an allowed actor, then retrieve, cancel, or approve the same handle as a foreign actor.
- **Post-revocation replay**: replay a handle after the creating principal was removed, revoked, or downgraded, because a retrieval path that trusts a cached authorization context keeps the artifact redeemable past the entitlement.
- **Link mutation**: mutate stored-link key prefixes and replay stale or swapped share handles to probe scope and expiry enforcement.
- **Per-handle verdicts**: decide each handle separately, since creation-time checks never cover retrieval-time binding.

## Bypass Techniques

- **Key-shape variation**: vary key casing and encoding shapes on stored-link handles to probe normalization gaps in scope checks.
- **Retrieval framing**: coerce content-disposition and conditional-request shapes on retrieval while holding the handle constant, reading only the binding verdict.
- **Delegated cache handling**: treat cache-key confusion as defeat detail shared with the proxy-techniques family at its shared-cache step, recording only the redemption verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Handle harvesting**: feed handles harvested from notifications, emails, client logs, and webhook deliveries into foreign redemption attempts.
- **Export-to-read pivot**: pivot a confirmed export read into direct object access against the identifiers the artifact exposes.
- **Approval pivot**: pivot a confirmed job approval into state changes the foreign actor could never create directly, keeping each step's verdict separate.

## Testing Methodology

1. **Request-shape derivation** - derive the request shape from evidence by collecting client, interface, and history material, with completion when creation and retrieval shapes plus handle fields are inferable.
2. **Matrix build** - build the subject-artifact-action matrix by enumerating each role against each handle type and retrieval action, with completion when every redeem, cancel, and approve action has an expected-principal cell.
3. **Principal setup** - establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. **Handle creation** - create handles by executing creation flows under each role, with completion when every role owns a redeemable artifact with recorded scope and expiry.
5. **Cross-principal redemption** - redeem across principals by replaying each handle under a foreign session, with completion when every handle has a foreign retrieval attempt beside its creator baseline.
6. **Scope and expiry decisions** - decide scope and expiry by mutating key prefixes and replaying stale and swapped handles, with completion when every mutation carries its own binding verdict.
7. **Persistence verification** - verify persistence and effect with role-separated rereads of artifact state, with completion when each transition is confirmed present or absent rather than assumed.

## False Positives

- **Shared artifacts**: discard artifacts the design shares deliberately, confirming shared scope before filing.
- **Expired handles**: discard expired handles that the service rejects for every caller including the creator, verifying rejection symmetrically.
- **Metadata acknowledgements**: discard metadata acknowledgements that reference a handle without returning its content or effect, confirming no data or transition leaks.
- **Silent enforcement**: discard silent-enforcement responses that withhold foreign artifacts while the creator view succeeds, confirming withholding rather than hidden exposure.

## Pro Tips

- **Symmetric baselines**: create handles under every role before redeeming, since symmetric baselines decide asymmetric verdicts.
- **Scope and expiry tracking**: track scope and expiry per handle explicitly, since retrieval paths fail on exactly those two clauses.
- **Transition testing**: test finalize, cancel, and approve transitions as well as reads, since write-side redemption gaps carry the larger impact.
- **Post-revocation retest**: re-test each handle after a revocation event, since a handle that survives the creator's removal is the persistent-access primitive.
- **Paired evidence**: prove impact with role-separated before-and-after diffs of artifact state, since paired evidence survives scrutiny.
- **Family naming**: name the proxy-techniques family at edge-reached retrieval steps rather than restating its mechanics.

## Summary

Retrieval-time binding must recheck the caller against the artifact on every redeem.
Create as one actor and redeem as another, and file every handle that answers a foreign caller.
