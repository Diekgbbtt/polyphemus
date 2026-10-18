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

Redeem applies where creation and retrieval split across two requests joined by an artifact handle.
The handle may be a job or task identifier, an export download token, or a stored link with scope and expiry binding.
File and object storage paths ride inside this variant as scope-and-expiry redemption while storage needs no content analysis beyond key and signature binding.
Live single-action swaps stay in the sibling direct variant, and only two-phase create-then-redeem lives here.

## Reconnaissance

Map every creation endpoint that returns a retrievable handle before redeeming anything.
Record the handle lifecycle from history and client material, including scope, expiry, and finalize or approve transitions.
Collect one handle per principal by creating jobs, exports, and stored links under each role until each role owns redeemable artifacts.
Capture the baseline retrieval for the creating principal before attempting foreign redemption.

## Detection Channels

Foreign artifact content returned to a non-creator decides the finding.
A stale or cross-scope stored link that still redeems signals missing scope and expiry binding.
Finalize, cancel, and approve transitions that accept another actor's handle confirm write-side redemption gaps.
Timing and size differentials between the creator retrieval and the foreign retrieval confirm blind redemption.

## Adversarial Capabilities

This variant presupposes working sessions for at least a creator and a foreign redeemer, with an approver role where the flow names one.
It consumes the ability to create artifacts as an allowed actor and hold their handles past creation.
It consumes the ability to replay those handles under a different principal after a delay.
Principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

The feature executes under the agreement that an object reference arriving with a request is private to the caller, that any surrounding authorization already binds the referenced object to that caller, that identity arriving through surrounding channels belongs to the same caller, that a token accepted by one service transfers only to its intended audience, and that a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
The agreement fails when the retrieval path redeems a stored artifact without rechecking the binding that creation established.

## Key Vulnerabilities

Two-phase create-then-redeem binding is the bent step this variant owns over the parent.
Create an export, task, or stored link as an allowed actor, then retrieve, cancel, or approve the same handle as a foreign actor.
Mutate stored-link key prefixes and replay stale or swapped share handles to probe scope and expiry enforcement.
Decide each handle separately, since creation-time checks never cover retrieval-time binding.

## Bypass Techniques

Vary key casing and encoding shapes on stored-link handles to probe normalization gaps in scope checks.
Coerce content-disposition and conditional-request shapes on retrieval while holding the handle constant, reading only the binding verdict.
Treat cache-key confusion as defeat detail shared with the proxy-techniques family at its shared-cache step, recording only the redemption verdict here.

## Chaining Attacks

Feed handles harvested from notifications, emails, client logs, and webhook deliveries into foreign redemption attempts.
Pivot a confirmed export read into direct object access against the identifiers the artifact exposes.
Pivot a confirmed job approval into state changes the foreign actor could never create directly, keeping each step's verdict separate.

## Testing Methodology

1. Derive the request shape from evidence by collecting client, interface, and history material, with completion when creation and retrieval shapes plus handle fields are inferable.
2. Build the subject-artifact-action matrix by enumerating each role against each handle type and retrieval action, with completion when every redeem, cancel, and approve action has an expected-principal cell.
3. Establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. Create handles by executing creation flows under each role, with completion when every role owns a redeemable artifact with recorded scope and expiry.
5. Redeem across principals by replaying each handle under a foreign session, with completion when every handle has a foreign retrieval attempt beside its creator baseline.
6. Decide scope and expiry by mutating key prefixes and replaying stale and swapped handles, with completion when every mutation carries its own binding verdict.
7. Verify persistence and effect with role-separated rereads of artifact state, with completion when each transition is confirmed present or absent rather than assumed.

## False Positives

Discard artifacts the design shares deliberately, confirming shared scope before filing.
Discard expired handles that the service rejects for every caller including the creator, verifying rejection symmetrically.
Discard metadata acknowledgements that reference a handle without returning its content or effect, confirming no data or transition leaks.
Discard silent-enforcement responses that withhold foreign artifacts while the creator view succeeds, confirming withholding rather than hidden exposure.

## Pro Tips

Create handles under every role before redeeming, since symmetric baselines decide asymmetric verdicts.
Track scope and expiry per handle explicitly, since retrieval paths fail on exactly those two clauses.
Test finalize, cancel, and approve transitions as well as reads, since write-side redemption gaps carry the larger impact.
Prove impact with role-separated before-and-after diffs of artifact state, since paired evidence survives scrutiny.
Name the proxy-techniques family at edge-reached retrieval steps rather than restating its mechanics.

## Summary

Retrieval-time binding must recheck the caller against the artifact on every redeem.
Create as one actor and redeem as another, and file every handle that answers a foreign caller.
