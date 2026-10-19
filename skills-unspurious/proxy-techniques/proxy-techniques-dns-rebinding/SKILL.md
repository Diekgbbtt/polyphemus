---
name: proxy-techniques-dns-rebinding
description: Resolution rebinding where a name answers differently across lookups, covering lookup-count gaps when the connector resolves again after the check, record lifetime control when a short-lived answer can be changed between lookups, and address family answers when the second answer points at a different reach.
metadata:
  version: 1.0.0
---

# Resolution Rebinding

A name that is resolved twice can answer differently each time. This variant makes the approving lookup see an address the check accepts and the connecting lookup see the address the operation needs, by controlling the answer between the two. The goal is an approved destination whose connection lands somewhere the approval never covered.

## Attack Surface

Resolution rebinding applicability centers on a destination that is resolved after it is approved, on a name whose answer the caller can change.
The surface holds lookups separated by a check, records with short lifetimes, wildcard and fallback answers, and connectors that resolve independently of the component that validated the destination.
A path that pins the resolution to the approved address, and a connector that connects to the validated value rather than to the name, both close the surface.
A destination supplied as a literal address rides outside this variant, because there is no lookup to answer twice.

## Reconnaissance

Rebinding maps the lookups before crafting, because the mechanism lives between two resolutions of one name.
- Trace the destination from the approving component to the connector and count the lookups on the way.
- Record the record lifetime, the caching behaviour of each resolver, and the fallback answer for unknown names.
- Establish the refusal baseline with a literal address the check rejects, so a later arrival is attributable to the second answer.
- Note which connector the second lookup reaches, because only that connector's resolution behaviour matters.

## Detection Channels

Rebinding listens to the two answers of one name, so only the entries below are live here.
- The second answer differing from the first, which proves the name was rebound between lookups.
- An arrival at operated infrastructure in place of the approved destination, which proves the connection used the second answer.
- A paired baseline where the same name reaches two different targets across one operation.
- The interior service or origin acting on the operation the approved name carried.
- A negative that holds across every lookup pair and lifetime, which reads as a pinned resolution.

## Adversarial Capabilities

Rebinding presupposes a controllable answer plus a lookup gap plus an arrival oracle, and it consumes all three.
- Control the answer of one name, with a lifetime short enough to change between the two lookups.
- Hold an arrival oracle at the second answer's address, so the connection is provable rather than inferred.
- Read the approving component's verdict and the connector's destination separately.
- Repeat the pair across lifetimes, because a resolver cache can collapse the two lookups into one.

## Trust Assumptions

The destination check trusts that the address it approved is the address the connection uses.
The agreement holds the name to one resolution from the approving lookup to the connecting lookup, holds every resolver on the path to the same answer, and holds the connector to the value the check consumed.
This variant breaks the resolution clause because the connector resolves the name again after the check, so the approved address and the connected address differ.
The arrival is claimed only when both answers are recorded for one operation, because one answer alone cannot show a rebind.

## Key Vulnerabilities

### Lookup-Count Gaps

Count the resolutions between the check and the connection, because each additional lookup is a chance for the answer to change.
Frame the gap as a race between a validating lookup and a fetching lookup: the check resolves once and the fetch re-resolves, so the answer only has to change inside that interval.
Repeat the lookup pair until the race is won, because a resolver cache can collapse the two lookups into one answer on any single attempt.
Prefer the connector that resolves independently, since a connector fed the validated value resolves nothing.
The parent path-mapping step covers one destination value and cannot describe a name answered twice, so this variant owns the lookup-count procedure.

### Record Lifetime Control

Serve an answer with a lifetime short enough to change between the approving and the connecting lookup.
Confirm the resolver's caching behaviour first, because a cache that outlives the check collapses the two lookups into one answer.
Treat an answer that survives both lookups as a pinned resolution rather than a rebind.

### Address Family Answers

Point the second answer at the reach the operation needs, including families the approving check treats as external and the connector treats as interior.
Keep the first answer benign and the second minimal, because the first answer is the one the check reads.
Confirm the arrival out of band, since a connection that never happened is not a rebind.

## Bypass Techniques

Relay shapes are tried only after the direct route is baselined, because a name that never rebound carried nothing.

- A name whose answer changes between the approving and the connecting lookup.
- A lifetime short enough to expire inside the gap between the two lookups.
- A wildcard or fallback answer that covers the label the operation uses.
- An answer-name family whose first answer is benign and whose second answer is the operated reach, kept as a pattern rather than a concrete name.
- Address families that the approving check and the connector classify differently.
- Repeated pairs across lifetimes, because a resolver cache can collapse the lookups.

## Chaining Attacks

Rebinding chains forward into the class that owns the effect, because a changed answer is only the first hop.
- Hand the reached destination to the class that owns the effect, and prove the class-specific consequence there.
- Chain into a forwarded hop, because the second answer can itself be a redirecting destination.
- Chain into the destination parse differential where the approved and connected values also parse differently.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Rebinding baselines the pair first and answers second, because a single lookup cannot show a rebind.

1. **Trace the lookups** - every resolution between the approving component and the connector, and the step completes when each lookup carries the component that performs it.
2. **Baseline the refusal** - send a literal address the check rejects, and the step completes when a refusal is recorded or the absence of a destination check is recorded with the test that showed it.
3. **Record the answer** - note the record lifetime, the resolver caching behaviour, and the fallback answer, and the step completes when the lifetime that fits inside the lookup gap is named.
4. **Serve the second answer** - change the answer between the two lookups, and the step completes when the approving lookup reads the benign answer and the connector reads the operated one.
5. **Confirm the arrival** - prove the connection at operated infrastructure, and the step completes when the arrival is attributed to the connector rather than to the caller.
6. **Attribute the rebind** - pair the approved answer with the connected answer, and the step completes when the rebind is named from the pair.

## False Positives

Stop when the resolution stayed pinned, because one answer across both lookups is not a rebind.

- A connector fed the validated value, which resolves nothing and connects to the approved address.
- A resolver cache that outlives the check, confirmed by one answer across the pair.
- An arrival whose source is the tester's client rather than the target's connector.
- A destination supplied as a literal address, which has no lookup to answer twice.
- A simulator that answers the second lookup itself without a real connection.

## Pro Tips

Rebinding rewards lookup counting plus lifetime control.

1. Count the lookups before crafting, because each one is a chance for the answer to change.
2. Keep the first answer benign and the second minimal, since the check reads the first.
3. Confirm the resolver's caching behaviour, because a cache can collapse the pair into one answer.
4. Prove the arrival out of band, since an unproved connection is not a rebind.
5. Hand the reached destination to the class that owns the effect, and stop at the narrowest proof.

## Summary

A name resolved after its check can answer with a different address each time. Resolution rebinding controls the answer between the approving and the connecting lookup, and claims the rebind only when both answers are recorded.
