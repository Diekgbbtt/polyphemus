---
name: proxy-techniques-redirect-chain
description: Redirect chain carry where an approved first hop forwards the operation onward, covering hop approval gaps when the check applies before the hop, nested hops when a second forwarder hides the final destination, and scheme switches when a hop changes the protocol the connection uses.
metadata:
  version: 1.0.0
---

# Redirect Chain

An approval applied to a first hop covers the hop rather than the arrival. This variant lands the operation on a destination the approver never saw, by forwarding it through one or more hops whose first destination the check accepted. The goal is an arrival at a target under control while every hop the check inspected stayed inside the approved set.

## Attack Surface

Redirect chain applicability centers on a destination check applied before a component follows a forwarded destination.
The surface holds redirecting endpoints, link expanders and previewers, callback and continuation values, and fetch paths that follow a location without re-checking it.
A chain of two or more hops, and a hop that changes the scheme or the host family, both widen the surface.
A path that re-validates the destination at every hop rides outside this variant, because each hop then carries its own approval.

## Reconnaissance

Redirect chains are mapped hop by hop before crafting, because the approval and the arrival are different places in the path.
- Enumerate the components that follow a forwarded destination, and note where the destination check sits relative to each follow.
- Establish the refusal baseline with a destination the check plainly rejects, so a later arrival is attributable to a hop.
- Record the chain in full: each hop's destination, its verdict, and whether the next hop was checked.
- Note the scheme and host families a hop may switch to, because a switch changes what the next check reads.

## Detection Channels

Redirect chains listen to the arrival rather than to the first hop, so only the entries below are live here.
- The operation arriving at the second hop, which proves the first hop forwarded it.
- A paired baseline where the approved first hop is reached directly and the chosen destination is reached only through the chain.
- The final target acting on the operation the approved first hop carried.
- The full chain recorded with each hop's destination and verdict, which shows where the approval stopped.
- A negative that holds across every chain length and hop, which reads as re-validation at each hop.

## Adversarial Capabilities

Redirect chains presuppose a first hop under control plus a follow-capable component plus an arrival oracle, and they consume all three.
- Host a redirecting endpoint whose destination is inside the approved set and whose next hop is the chosen target.
- Read where the destination check sits in the chain, because the mechanism needs one follow after the last check.
- Chain hops so the first destination satisfies the check and a later one carries the arrival.
- Confirm the arrival at operated infrastructure rather than inferring it from the first hop's response.

## Trust Assumptions

The destination check trusts that the destination it approved is the destination the operation arrives at.
The agreement holds the approval to the arrival rather than to the first hop, holds every hop to a destination the approver saw, and holds the scheme and the host family constant across the chain.
This variant breaks the forwarding clause because a hop forwards the operation past the approved destination, so the check approved a hop and the operation arrived elsewhere.
The arrival is claimed only when the chain is recorded in full, because a single hop cannot show where the approval stopped.

## Key Vulnerabilities

### Hop Approval Gaps

Place the approved destination at the first hop and the chosen target at the next, because the check runs before the follow.
Where the check's own trusted destination is itself a redirecting endpoint, place that endpoint first, so the approved value performs the forward and the approval covers the hop.
Where a second component applies its own destination filter to the followed value, clear that filter with the approved first hop and let the onward hop carry the arrival past it.
Confirm the check's position in the chain first, since a check after the follow carries the approval all the way.
The parent path-mapping step covers one destination and cannot describe an approval that covers a hop, so this variant owns the hop-approval procedure.

### Follower Kinds

A client library that follows a redirect by default is a follower the caller does not control, so the follow happens where no server-side location header is available to inspect; name `proxy-techniques-client-side-path-traversal` at the client-request step.
A client-side navigation sink fed by a URL source is a follower that emits no server-side location header at all, so the chain's arrival is visible only in the browser.
Treat a follower that re-validates each hop as a recorded negative rather than a dead end, and look for the follower that does not.

### Nested and Chained Hops

Add a forwarding layer so the final destination sits one hop deeper than the check's view, because a nested forwarder hides the arrival.
Keep every intermediate hop inside the approved set, and vary only the last one per attempt.
Treat a chain that stops at the second hop as re-validation evidence rather than a dead end.

### Scheme and Family Switching at a Hop

Switch the scheme or the host family at a hop, because the following component re-applies its policy to the new scheme rather than the old.
Prefer the switch whose next hop the policy admits, so the arrival needs no second bypass behind it.
Confirm the switched hop at the sink, because a scheme switch the follower refuses is a broken chain.

## Bypass Techniques

Relay shapes are tried only after the direct route is baselined, because a chain the check never inspected carried nothing.

- An approved first destination that forwards to a destination under control.
- The check's own trusted redirecting endpoint as the first hop, so the approved value performs the forward.
- A destination value shaped with userinfo, a protocol-relative form, a backslash, an encoded separator, a null or fragment terminator, or a look-alike host family, so the approver reads the approved destination.
- Two or more hops, so the arrival sits deeper than the check's view.
- A hop that switches scheme or host family, where the follower re-applies its policy.
- Continuation and callback values that the chain follows after the first check.
- A logout or post-action continuation whose rule is weaker than the primary check.

## Chaining Attacks

Redirect chains chain forward into the class that owns the effect, because an arrival is only the first hop.
- Hand the arrived destination to the class that owns the effect, and prove the class-specific consequence there.
- Chain into the destination parse differential where the checked value and the followed value parse differently.
- Chain into the cache step where the chain's arrival is stored under a key another caller reads.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Redirect chains record the chain first and craft the last hop second, because the approval's position is the mechanism.

1. **Enumerate the followers** - every component that follows a forwarded destination with the check's position relative to each follow, and the step completes when each follow carries the check that precedes it.
2. **Baseline the refusal** - send a destination the check rejects, and the step completes when a refusal is recorded or the absence of a destination check is recorded with the test that showed it.
3. **Record the chain** - each hop's destination, verdict, and next-hop check, and the step completes when the last checked hop is named.
4. **Craft the forwarding hop** - put the approved destination at the first hop and the chosen target at the next, and the step completes when the chain's last hop reaches the chosen target.
5. **Vary the chain** - add hops, switch scheme, and vary the final hop one per attempt, and the step completes when each variant carries an arrival or a recorded negative.
6. **Confirm the arrival** - prove the arrival at operated infrastructure, and the step completes when the arrival is attributed to the chain rather than to the first hop's own response.
7. **Attribute the carry** - pair the refused destination with the arrived chain, and the step completes when the hop that carried the approval past its destination is named from the pair.

## False Positives

Stop when every hop re-validated the destination, because a chain that carries its own approval is not a carry.

- A follower that re-checks each hop, confirmed by a refusal at the second hop.
- A chain whose last hop is the approved destination, where the check covered the arrival.
- An arrival whose source is the tester's client rather than a follower.
- A response body that names a destination without following it, where no connection was made.
- A simulator that answers every hop without a real follow.

## Pro Tips

Redirect chains reward chain recording plus control of every hop.

1. Record the chain in full before crafting, because the approval's position is the mechanism.
2. Own the first destination and the final one, so the arrival is a chosen target.
3. Vary the last hop only, so the carrying hop is nameable.
4. Confirm the arrival out of band, since a hop's own response is not an arrival.
5. Hand the arrived destination to the class that owns the effect, and stop at the narrowest proof.

## Summary

A destination check applied before a hop approves the hop rather than the arrival. Redirect chains place the approved destination first, the chosen target last, and claim the carry only when the chain is recorded in full.
