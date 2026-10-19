---
name: idor-second-order-stored-reference
description: Second-order object-binding testing that plants a foreign reference in stored state and triggers the later operation that resolves it. Use when a stored field decides a later server-side read, when a job, report, or export resolves a saved reference, when the create path validates the caller and the trigger path never re-binds.
metadata:
  version: 1.0.0
---

# IDOR Second-Order Stored Reference

Second-order object binding fails when the reference a later operation resolves was stored earlier, so the check performed at write time is mistaken for a check at use time.
The leading word is stored: every probe writes one reference into the caller's own state and triggers the operation that resolves it, then reads whose object the server actually used.

## Attack Surface

Stored applies where one operation saves a reference and a later operation resolves it on the server's own initiative: scheduled jobs, reports, exports, notifications, rendering paths, and any flow that dereferences a saved field rather than a request parameter.
The stored reference may be a foreign object identifier, an owner or scope field, a saved destination field, or a reference carried into a template or a message.
The trigger may be immediate, scheduled, or fired by an unrelated action of the victim or the system.
Live single-request swaps stay in the sibling direct variant, and artifacts the application creates and another caller redeems stay in the deferred sibling, so neither rides here.

## Reconnaissance

Map every operation that resolves stored state before planting anything.
- Enumerate create and update actions whose fields are later dereferenced, and separate the fields that select an object from the fields that describe one.
- Trace each saved field forward to the operation that resolves it, including scheduled, notification, and rendering paths.
- Record which resolving paths re-run an authorization check and which trust the value because an entitled caller stored it.
- Capture each principal's own stored state, so a planted value has a baseline to differ from.
- Note where the resolved object's output surfaces: the caller's own view, a message, a report, or a downstream write.

## Detection Channels

Foreign content returned to the planting caller decides the finding.
A later operation that resolves the stored reference to another principal's object, observed in the caller's own view or in a message the caller receives, confirms second-order binding.
A stored reference that keeps resolving after a scope change, such as a downgrade or an ownership move, confirms a stale stored binding.
A write under the stored reference landing on another principal's object confirms the write-side case.
A scheduled or triggered operation whose output names another principal's data confirms the trigger-path gap without a request-time parameter.

## Adversarial Capabilities

Stored-reference testing presupposes two principals, write access to at least one storable field, and the ability to trigger the resolving operation, and it consumes all three.
- Hold the planting principal's session plus a victim principal's session whose object identifiers are known.
- Write a chosen reference into a field the caller may legitimately set, and confirm the write persisted before relying on it.
- Trigger the resolving operation, including scheduled, delayed, and unrelated-action triggers.
- Read the caller's own view and the notification path to observe what the trigger resolved.
- Snapshot the caller's stored state before and after each trigger, so the verdict attributes to the resolving operation.
- Principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

The feature executes under the agreement that an object reference arriving with a request is private to the caller, that any surrounding authorization already binds the referenced object to that caller, that identity arriving through surrounding channels belongs to the same caller, that a token accepted by one service transfers only to its intended audience, and that a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
The agreement fails when a later operation resolves a stored reference without re-binding it to the caller, so the write-time check stands in for a check at use.

## Key Vulnerabilities

### Plant-and-Trigger Sequencing

Plant one foreign reference into a field the caller may set, then trigger the operation that resolves it, and judge the outcome by whose object the server used.
Keep the planted reference and the trigger request separate, because the finding lives in the gap between them.
The parent swap step covers live substitution and cannot describe a write-then-trigger sequence, so this variant owns the plant-and-trigger procedure.

### Resolving-Operation Inventory

Enumerate every operation that dereferences stored state: scheduled jobs, reports, exports, notifications, rendering paths, and saved-destination flows.
Test each resolving operation separately, because each carries its own re-binding discipline.
Treat a resolving operation whose design names no caller check as the first candidate.

### Stored-Scope Persistence

Re-trigger the resolving operation after a scope change: a downgrade, an ownership move, or a removal.
A stored reference that keeps resolving after the entitlement changed reads as a stale binding rather than a one-off.
Confirm the resolved output in the caller's own view, because a stale binding that never surfaces is not yet a finding.

### Write-Side Resolution

Test whether the resolving operation writes to the stored target rather than reading it, because a write under a planted reference carries the larger impact.
Confirm the foreign write by re-reading the victim's object rather than by the response echo.

## Bypass Techniques

Vary the trigger path rather than the reference: scheduled, delayed, and unrelated-action triggers reach the same resolver through different guards.
Vary the stored shape: scalar, array, and nested-object forms of one reference can reach the resolver through different binders.
Re-save the reference immediately before the trigger where a normalization step would otherwise rewrite it.
Where the trigger arrives through a cross-site or navigational delivery, name `csrf` for the delivery mechanics and record only the binding verdict here.
Name the `defence-bypass` family at its parser step where a stored shape reaches the resolver through a different binder.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Feed identifiers harvested from the caller's own surfaces into the planted field, then let the trigger resolve them.
Pivot a confirmed foreign read into a direct swap against the resolved identifiers, keeping each step's verdict separate.
Pivot a confirmed foreign write into an escalation the resolving operation performs with elevated authority, naming the authorization classes at the access verdict.
Hand a stale stored binding to the session class where the resolving operation also shows an identifier outliving its authority.

## Testing Methodology

1. Derive the request shape from evidence by collecting client, interface, and history material, with completion when the create, save, and trigger shapes are inferable.
2. Build the stored-field inventory by enumerating every field a later operation dereferences, with completion when each stored field names its resolving operation.
3. Establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. Plant one reference per attempt by writing a foreign identifier into a field the caller may set, with completion when every stored field carries a planted attempt beside its unmodified baseline.
5. Trigger the resolver by driving each resolving operation including scheduled and unrelated-action paths, with completion when every trigger carries a resolved-whose-object verdict.
6. Confirm persistence and scope by re-triggering after a scope change and by re-reading the target of any write, with completion when every positive shows a durable foreign effect rather than a response echo.
7. Retry failures with the inferred shapes before judging, with completion when no probe is judged on a wrong-shape or unpersisted plant.

## False Positives

Discard stored references the design resolves to the caller's own scope by construction, confirming the resolution rule before filing.
Discard resources the design exposes publicly, since reachability without sensitivity is not a binding failure.
Discard a trigger that never surfaced the resolved object, which is a latent gap rather than a finding until the output is observable.
Discard silent enforcement where the resolving operation returns an empty or refused shape while the owner's view holds data.
Discard a plant that never persisted, because the resolving operation cannot be judged on a value the store rejected.

## Pro Tips

Separate the write from the trigger in every test, because the gap between them is where the binding is missing.
Inventory resolving operations before planting, since the trigger is the scarce resource rather than the reference.
Re-trigger after a scope change, because stale stored bindings outlive the entitlement that justified them.
Confirm the resolved object in the caller's own view, since a trigger whose output the caller never sees is not yet provable.
Prefer the smallest proof: one planted reference and one trigger that returns the victim's data to the planter.
Never conclude resistance from a failed trigger alone, since the schedule, the shape, or the persistence may be wrong while the binding is absent.

## Summary

A reference stored by an entitled caller is not thereby bound to that caller at use.
Plant one foreign reference, trigger the operation that resolves it, and file every case where the server used an object the planter does not own.
