---
name: idor-direct-object-swap
description: Swap single object references to expose missing caller binding. Use when one request carries one identifier, when a cross-principal control pair can decide the verdict, when a blind differential must confirm hidden access.
metadata:
  version: 1.0.0
---

# IDOR Direct Object Swap

Single-reference swap testing decides whether one caller reaches one foreign object through an evidence-derived request paired against a control.
The leading word is swap: every probe substitutes exactly one identifier and reads the verdict beside its control.

## Attack Surface

Swap applies where a request names one object and the service answers with that object's data or state change.
The reference may arrive in any carrier the runtime graph locates, and it may use any identifier form the knowledge base records.
Trust direction labels change reporting only, so horizontal, vertical, and cross-tenant attempts share this one procedure.
Tenant selectors that only route without carrying identity stay inside this variant as aspects.

## Reconnaissance

Map every carrier that names a single object before swapping anything.
Collect client bundles, interface documents, prior HTTP history, and recon notes until the real method, path pattern, and body field shapes are inferable.
Harvest one valid identifier per principal from cooperative list, search, or export endpoints until each role owns a seeded corpus.
Confirm the owner's baseline request succeeds with the inferred verb and fields before judging any foreign attempt.

## Detection Channels

Foreign content or metadata returned for a non-owner identifier decides the finding.
The owner's request beside the foreign request under identical shaping, with only the reference differing, is the deciding pair.
An error shape that differs between owned and foreign identifiers signals a missing binding even when content is masked.
Status, size, and timing differentials between the control and the swapped attempt confirm blind access.
Conditional-request validators that match for a foreign object confirm its existence without full content.

## Adversarial Capabilities

This variant presupposes working sessions for at least an owner and a non-owner, with an elevated role where the matrix names one.
It consumes the ability to call endpoints directly with a substituted reference while holding the token constant.
It consumes the ability to hold a control response beside every swapped attempt for comparison.
Principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

The feature executes under the agreement that an object reference arriving with a request is private to the caller, that any surrounding authorization already binds the referenced object to that caller, that identity arriving through surrounding channels belongs to the same caller, that a token accepted by one service transfers only to its intended audience, and that a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
The agreement fails when the service substitutes a foreign identifier without rebinding it to the caller.

## Key Vulnerabilities

Control-paired substitution is the bent step this variant owns over the parent.
Substitute one foreign identifier into an evidence-derived request while replaying the owner's control unchanged.
Repeat the pair across every action the matrix names, including partial-update framings that mutate silently.
Read the verdict from the differential between the two responses, never from a single status alone.

### Paired-Argument Binding

- Where one request names a source and a destination (a transfer, a copy, a move), substitute one member while the other stays owned, and read which member the check follows.
- A validated destination beside an unchecked source is the common asymmetry, so record one verdict per member rather than one per request.
- Treat a refusal on the validated member as a held guard for that member only, because the unchecked member still needs its own attempt.

## Bypass Techniques

Coerce the transport framing when a first attempt is rejected, varying content type and serialization while keeping the swapped identifier constant.
Reshape the reference itself: array-wrapped, wildcard, boolean-coerced, zero, negative, and fractional numeric forms, and extension-appended path forms, since a parser that coerces one form can match a broader set than the gate expects.
Pollute duplicate reference fields with both orderings and read which occurrence the service honors.
Treat parser disagreements as defeat detail shared with the defence-bypass family at its parser step, recording only the authorization verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Feed identifiers harvested from list, search, notification, and export channels into direct swaps.
Pivot a confirmed read into a cross-site trigger against the discovered object where the engagement permits it.
Pivot exfiltrated content into further session or object discovery, keeping each chained step's verdict separate.

## Testing Methodology

1. Derive the request shape from evidence by collecting client, interface, and history material, with completion when the real method, path pattern, and field shapes are inferable.
2. Build the subject-object-action matrix by enumerating each role against each object and action, with completion when every action on each object has an expected-principal cell.
3. Establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. Seed the corpus by capturing one valid identifier per principal, with completion when each principal has a recorded identifier.
5. Swap with control pairing by substituting one foreign identifier per attempt beside its unchanged control, with completion when every matrix action has a swapped attempt beside its control.
6. Confirm blind cases with differentials by comparing status, size, validator, and timing signals, with completion when every masked response has a decided verdict rather than an assumption.
7. Retry failures with the inferred verb and fields before judging, with completion when no probe is judged on a wrong-verb or placeholder-identifier attempt.

## False Positives

Discard resources the design exposes publicly, since reachability without sensitivity is not a binding failure.
Discard soft-privatized content already public elsewhere, confirming publicity before filing.
Discard metadata lookups that return no sensitive content for the foreign identifier.
Discard silent-enforcement responses that return an empty shape for the foreign identifier while the owner view holds data, confirming the data is actually missing rather than hidden by the response shape.

## Pro Tips

Seed identifiers from list, search, and export endpoints first, since they are the richest corpus source.
Vary content types and transports independently, since authorization middleware often differs per stack.
Treat opaque identifier forms as untrusted and harvest them rather than guessing, since opacity is never a binding.
Prove impact with before-and-after diffs captured under separated roles, since paired evidence survives scrutiny.
Never conclude resistance from a single wrong-verb or placeholder-identifier attempt, since the shape may be wrong while the binding is absent.

## Summary

Single-reference binding must tie caller, action, and the exact object on every request.
Swap each identifier beside its control, and file every differential that favors the foreign caller.
