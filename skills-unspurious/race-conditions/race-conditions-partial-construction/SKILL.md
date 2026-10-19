---
name: race-conditions-partial-construction
description: Different-request races against a transient mid-creation state, synchronising a list of distinct requests into one window, targeting the object before its creation sequence settles, and completing the objective through the path that wins.
metadata:
  version: 1.0.0
---

# Partial-Construction Race

Partial construction fires a list of different requests inside one synchronised window so an object is usable before its creation sequence finishes.
This variant owns the different-request synchronisation plus the mid-creation window targeting that identical-input bursts never describe.
The goal is an objective completed through the winning path, such as a confirmation accepted before validation, a recovery destination rebound against a reset in flight, or a checkout applied to an account still being provisioned.

## Attack Surface

- **Applicability**: centers on a multi-phase creation or verification workflow where the object exists in a usable but unverified state between two phases.
- **Window shape**: the gap between the phase that creates the object and the phase that validates, provisions, or locks it.
- **Request diversity**: the burst carries distinct requests aimed at distinct phases rather than one request repeated, so one state machine is attacked from several sides at once.
- **Sibling workflows**: a second workflow that reads or writes the same identity or contact field widens the surface, because two writers on one field are the raw material.
- **Out-of-scope shapes**: identical-input bursts, dedup-key replay, guard omission, and intra-request fan-out ride in the parent and its siblings.

## Reconnaissance

### Phase Mapping

- **Phase enumeration**: list the creation, validation, and completion phases of each workflow and record which phase leaves the object usable.
- **Usable-state recording**: record the state the object answers in per phase, so the mid-creation window is a named gap rather than a guess.
- **Identity-field recording**: record every workflow that writes the same identity or contact field, because the collision needs two writers.

### Window Estimation

- **Timing triage**: time the phase pair single, then sequential, then concurrent, so the backend's serialisation behaviour is recorded before any burst.
- **Baseline capture**: fire the request list one member at a time and record each sequential outcome, so a later concurrent win attributes to synchronisation rather than to a permissive workflow.
- **Window widening**: note slow dependencies or large payloads that widen the creation-to-validation gap.

## Detection Channels

- **Sequential-versus-synchronised verdict**: the same request list fails one member at a time and completes when fired in one window.
- **Mid-creation acceptance**: a validation or completion step accepts an object whose creation phase has not finished.
- **Cross-workflow divergence**: a sibling workflow acts on the identity field before the creating workflow's write lands.
- **Winning-path attribution**: exactly one member of the list produces the durable objective while the others are refused.
- **Response collapse**: the list's responses return together rather than in sequence, which reads as one server-side interleaving.

## Adversarial Capabilities

- **Different-request construction**: compose a list of distinct requests, one per phase and per sibling workflow, rather than repeating one request.
- **Window synchronisation**: release the list in one synchronised window on warmed connections.
- **Multi-identity reach**: hold the sessions or identities each member of the list needs.
- **Durable readback**: re-read the authoritative record after the window settles to confirm which path committed.
- **Sequential control**: keep the same list available as a sequential baseline for the same session.

## Trust Assumptions

- **The agreement**: the workflow trusts that a phase sequence is only ever observable as a sequence: an object becomes usable once its creation completes, a validation reads a settled record, and one identity field has one writer at a time.
- **The failing clause**: this variant breaks the settled-object clause because the object answers its completion step while the creation sequence is still in flight, so a distinct request reaches it in the mid-creation state.

## Key Vulnerabilities

### Mid-Creation Window Targeting

- **Transient-state usability**: the object answers the completion step before the creation step has committed, so the completion is accepted against a partially built record.
- **Window ownership**: the parent concurrent-requests step prescribes identical inputs and cannot describe a list of distinct requests, so this variant owns the different-request burst.
- **Minimal list discipline**: keep the list as small as the phase map allows, because every extra member adds noise without adding a phase.

### Cross-Workflow Phase Collision

- **Identity-field contention**: two workflows write one identity or contact field, and the window lets the second write land against the first workflow's in-flight state.
- **Sequence inversion**: a recovery, provisioning, or fulfilment action proceeds against a record the creating workflow has not settled.
- **Completion through the winner**: treat the winning member of the list as the finding and the other members as its controls.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no spelling changes the different-request window itself.
- **Channel widening**: identity rotation across sessions widens the burst when a per-entity throttle caps one principal.
- **Window widening**: slow dependencies or large payloads widen the creation-to-validation gap so the list lands inside it.
- **Guard-timing steering**: per-entity throttles, dedup keys, and guard checks are defeated at their timing step, which the parent and its siblings own; name the defence-bypass family there rather than restating it.
- **Channel wrapping**: name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Authorization chaining**: hand a mid-creation record that carries another principal's identity to the two-principal-authz skill at the authorization-principal step.
- **Value chaining**: hand a completed objective to business-logic invariant checks to test a value or entitlement gained outside the intended sequence.
- **Recovery-flow chaining**: hand a rebound identity or contact field to the recovery flow that later issues the token, so the token lands at the attacker destination.
- **Provisioning chaining**: hand a record that exists but is unprovisioned to the workflow that grants the entitlement, and stop at the narrowest durable proof.

## Testing Methodology

Partial construction runs phase mapping first and the synchronised list last, because a distinct-request burst without a mapped window is only noise.
1. **Model the phase sequence** - record the creation, validation, and completion phases plus the identity fields each workflow writes, and the step completes when every phase carries its usable-state verdict.
2. **Baseline sequentially** - fire the request list one member at a time and record the outcome per member, and the step completes when every member carries its sequential verdict.
3. **Estimate the window** - time the phase pair single, then sequential, then concurrent, and the step completes when the backend's serialisation behaviour is recorded.
4. **Fire the synchronised list** - release the distinct requests in one window on warmed connections, and the step completes when each member carries its committed-or-refused verdict.
5. **Confirm through the winner** - re-read the authoritative record and demonstrate the objective completed through the winning path, and the step completes when the completion is reproducible with a minimal repeatable request list.

## False Positives

- **Stop condition**: stop when the evidence shows the phases serialise, because a distinct-request burst that cannot overlap is only a request list.
- **Sequential equivalence**: the same list completes sequentially, which reads as a permissive workflow rather than a race.
- **Per-member permission**: a member completes because the caller is entitled to it, with no mid-creation state involved.
- **Transient-only completion**: the objective appears in one response while no authoritative record carries it after the window settles.
- **Serialised phases**: locks or an ordered queue hold the phase sequence, confirmed by sequential-equivalent outcomes across every burst.

## Pro Tips

- **Phase mapping first**: prefer mapping the phase sequence first, because the window lives between two named phases rather than in raw timing.
- **Distinct requests**: favor distinct requests over repeated ones, since a repeated request never reaches a different phase.
- **One control member per list**: keep one control member per list so the winning path stays attributable.
- **Settled re-read**: re-read the authoritative record after the window, because a mid-creation response alone proves nothing.
- **Window widening**: widen the window with slow dependencies only after the first list shows a partial effect.

## Summary

A workflow that exposes an object mid-creation hands its completion step to whoever fires the right request list inside one window.
Partial construction maps the phases, synchronises a list of distinct requests, and proves the objective completed through the winning path before any authorization or value chain begins.
