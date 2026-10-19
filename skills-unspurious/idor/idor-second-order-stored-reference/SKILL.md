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

- **Applicability**: centers on a pair of operations, one that saves a reference and one that later resolves it on the server's own initiative: scheduled jobs, reports, exports, notifications, rendering paths, and any flow that dereferences a saved field rather than a request parameter.
- **Stored carriers**: a foreign object identifier, an owner or scope field, a saved destination field, or a reference carried into a template or a message.
- **Trigger kinds**: immediate, scheduled, or fired by an unrelated action of the victim or the system.
- **Output surfaces**: the caller's own view, a message, a report, or a downstream write, each of which decides whether the resolved object is observable.
- **Out of scope**: live single-request swaps stay in the sibling direct variant, and artifacts the application creates and another caller redeems stay in the deferred sibling, so neither rides here.

## Reconnaissance

### Stored-Field Inventory

- **Dereference sweep**: enumerate create and update actions whose fields are later dereferenced, and separate the fields that select an object from the fields that describe one.
- **Forward trace**: trace each saved field forward to the operation that resolves it, including scheduled, notification, and rendering paths.
- **Check recording**: record which resolving paths re-run an authorization check and which trust the value because an entitled caller stored it.

### Baseline and Output Mapping

- **Own-state capture**: capture each principal's own stored state, so a planted value has a baseline to differ from.
- **Output mapping**: note where the resolved object's output surfaces, because a resolution the caller never observes is not yet provable.
- **Trigger enumeration**: list the triggers that fire each resolving operation, including delayed and unrelated-action triggers, before planting anything.

## Detection Channels

- **Foreign resolution**: a later operation that resolves the stored reference to another principal's object, observed in the caller's own view or in a message the caller receives, decides the finding.
- **Stale stored binding**: a stored reference that keeps resolving after a scope change, such as a downgrade or an ownership move.
- **Write-side resolution**: a write under the stored reference landing on another principal's object.
- **Trigger-path gap**: a scheduled or triggered operation whose output names another principal's data without a request-time parameter.

## Adversarial Capabilities

- **Prerequisites**: stored-reference testing presupposes two principals, write access to at least one storable field, and the ability to trigger the resolving operation, and it consumes all three.
- **Two principals**: hold the planting principal's session plus a victim principal's session whose object identifiers are known.
- **Persisted plant**: write a chosen reference into a field the caller may legitimately set, and confirm the write persisted before relying on it.
- **Trigger reach**: trigger the resolving operation, including scheduled, delayed, and unrelated-action triggers.
- **Output reading**: read the caller's own view and the notification path to observe what the trigger resolved.
- **State snapshotting**: snapshot the caller's stored state before and after each trigger, so the verdict attributes to the resolving operation.
- **Principal handling**: follow the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

- **The agreement**: an object reference arriving with a request is private to the caller, any surrounding authorization already binds the referenced object to that caller, identity arriving through surrounding channels belongs to the same caller, a token accepted by one service transfers only to its intended audience, and a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
- **The stored-reference clause fails**: where a later operation resolves a stored reference without re-binding it to the caller, so the write-time check stands in for a check at use.
- **The use-time clause fails**: where the resolving operation trusts the stored value because an entitled caller wrote it, rather than because the current caller is entitled to the resolved object.

## Key Vulnerabilities

### Plant-and-Trigger Sequencing

- **Separated write and trigger**: plant one foreign reference into a field the caller may set, then trigger the operation that resolves it, and judge the outcome by whose object the server used.
- **Gap ownership**: keep the planted reference and the trigger request separate, because the finding lives in the gap between them.
- **Parent delta**: the parent swap step covers live substitution and cannot describe a write-then-trigger sequence, so this variant owns the plant-and-trigger procedure.

### Resolving-Operation Inventory

- **Resolver sweep**: enumerate every operation that dereferences stored state: scheduled jobs, reports, exports, notifications, rendering paths, and saved-destination flows.
- **Per-resolver verdict**: test each resolving operation separately, because each carries its own re-binding discipline.
- **Silent-check candidate**: treat a resolving operation whose design names no caller check as the first candidate.

### Stored-Scope Persistence

- **Scope-change retrigger**: re-trigger the resolving operation after a scope change: a downgrade, an ownership move, or a removal.
- **Stale read**: a stored reference that keeps resolving after the entitlement changed reads as a stale binding rather than a one-off.
- **Observable output**: confirm the resolved output in the caller's own view, because a stale binding that never surfaces is not yet a finding.

### Write-Side Resolution

- **Write test**: test whether the resolving operation writes to the stored target rather than reading it, because a write under a planted reference carries the larger impact.
- **Victim reread**: confirm the foreign write by re-reading the victim's object rather than by the response echo.

## Bypass Techniques

- **Trigger-path variation**: vary the trigger path rather than the reference, because scheduled, delayed, and unrelated-action triggers reach the same resolver through different guards.
- **Stored-shape variation**: vary the stored shape, because scalar, array, and nested-object forms of one reference can reach the resolver through different binders.
- **Re-save before trigger**: re-save the reference immediately before the trigger where a normalization step would otherwise rewrite it.
- **Delivery handoff**: where the trigger arrives through a cross-site or navigational delivery, name `csrf` for the delivery mechanics and record only the binding verdict here.
- **Parser handoff**: name the `defence-bypass` family at its parser step where a stored shape reaches the resolver through a different binder.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Harvest to plant**: feed identifiers harvested from the caller's own surfaces into the planted field, then let the trigger resolve them.
- **Read to direct swap**: pivot a confirmed foreign read into a direct swap against the resolved identifiers, keeping each step's verdict separate.
- **Write to escalation**: pivot a confirmed foreign write into an escalation the resolving operation performs with elevated authority, naming the authorization classes at the access verdict.
- **Stale binding to session**: hand a stale stored binding to the session class where the resolving operation also shows an identifier outliving its authority.

## Testing Methodology

1. **Derive the request shape from evidence** - collect client, interface, and history material, with completion when the create, save, and trigger shapes are inferable.
2. **Build the stored-field inventory** - enumerate every field a later operation dereferences, with completion when each stored field names its resolving operation.
3. **Establish principals** - acquire one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. **Plant one reference per attempt** - write a foreign identifier into a field the caller may set, with completion when every stored field carries a planted attempt beside its unmodified baseline.
5. **Trigger the resolver** - drive each resolving operation including scheduled and unrelated-action paths, with completion when every trigger carries a resolved-whose-object verdict.
6. **Confirm persistence and scope** - re-trigger after a scope change and re-read the target of any write, with completion when every positive shows a durable foreign effect rather than a response echo.
7. **Retry before verdict** - resubmit failures with the inferred shapes, with completion when no probe is judged on a wrong-shape or unpersisted plant.

## False Positives

- **By-construction scope**: stored references the design resolves to the caller's own scope, confirmed by the resolution rule before filing.
- **Public resources**: resources the design exposes publicly, since reachability without sensitivity is not a binding failure.
- **Unobservable trigger**: a trigger that never surfaced the resolved object, which is a latent gap rather than a finding until the output is observable.
- **Silent enforcement**: a resolving operation that returns an empty or refused shape while the owner's view holds data.
- **Unpersisted plant**: a plant that never persisted, because the resolving operation cannot be judged on a value the store rejected.

## Pro Tips

- **Separated write and trigger**: separate the write from the trigger in every test, because the gap between them is where the binding is missing.
- **Trigger-first inventory**: inventory resolving operations before planting, since the trigger is the scarce resource rather than the reference.
- **Scope-change retrigger**: re-trigger after a scope change, because stale stored bindings outlive the entitlement that justified them.
- **Caller-view confirmation**: confirm the resolved object in the caller's own view, since a trigger whose output the caller never sees is not yet provable.
- **Smallest proof**: prefer the smallest proof: one planted reference and one trigger that returns the victim's data to the planter.
- **Failed-trigger caution**: never conclude resistance from a failed trigger alone, since the schedule, the shape, or the persistence may be wrong while the binding is absent.

## Summary

A reference stored by an entitled caller is not thereby bound to that caller at use.
Plant one foreign reference, trigger the operation that resolves it, and file every case where the server used an object the planter does not own.
