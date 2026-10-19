---
name: proxy-techniques-dns-rebinding
description: Resolution rebinding where a name answers differently across lookups, covering lookup-count gaps when the connector resolves again after the check, record lifetime control when a short-lived answer can be changed between lookups, and address family answers when the second answer points at a different reach.
metadata:
  version: 1.0.0
---

# Resolution Rebinding

A name that is resolved twice can answer differently each time. This variant makes the approving lookup see an address the check accepts and the connecting lookup see the address the operation needs, by controlling the answer between the two. The goal is an approved destination whose connection lands somewhere the approval never covered.

## Attack Surface

- **Applicability**: centers on a destination that is resolved after it is approved, on a name whose answer the caller can change.
- **Surface composition**: lookups separated by a check, records with short lifetimes, wildcard and fallback answers, and connectors that resolve independently of the component that validated the destination.
- **Closing factors**: a path that pins the resolution to the approved address, and a connector that connects to the validated value rather than to the name, both close the surface.
- **Out-of-scope variant**: a destination supplied as a literal address rides outside this variant, because there is no lookup to answer twice.

## Reconnaissance

- **Reconnaissance scope**: rebinding maps the lookups before crafting, because the mechanism lives between two resolutions of one name.
- **Lookup tracing**: trace the destination from the approving component to the connector and count the lookups on the way.
- **Record lifetime**: record the record lifetime, the caching behaviour of each resolver, and the fallback answer for unknown names.
- **Refusal baseline**: establish the refusal baseline with a literal address the check rejects, so a later arrival is attributable to the second answer.
- **Connector identification**: note which connector the second lookup reaches, because only that connector's resolution behaviour matters.

## Detection Channels

- **Channel scope**: rebinding listens to the two answers of one name, so only the entries below are live here.
- **Divergent answers**: the second answer differing from the first, which proves the name was rebound between lookups.
- **Operated arrival**: an arrival at operated infrastructure in place of the approved destination, which proves the connection used the second answer.
- **Paired baseline**: a paired baseline where the same name reaches two different targets across one operation.
- **Interior action**: the interior service or origin acting on the operation the approved name carried.
- **Pinned resolution**: a negative that holds across every lookup pair and lifetime, which reads as a pinned resolution.

## Adversarial Capabilities

- **Prerequisites**: rebinding presupposes a controllable answer plus a lookup gap plus an arrival oracle, and it consumes all three.
- **Answer control**: control the answer of one name, with a lifetime short enough to change between the two lookups.
- **Arrival oracle**: hold an arrival oracle at the second answer's address, so the connection is provable rather than inferred.
- **Separate readings**: read the approving component's verdict and the connector's destination separately.
- **Pair repetition**: repeat the pair across lifetimes, because a resolver cache can collapse the two lookups into one.

## Trust Assumptions

- **The agreement**: the destination check trusts that the address it approved is the address the connection uses, holds the name to one resolution from the approving lookup to the connecting lookup, holds every resolver on the path to the same answer, and holds the connector to the value the check consumed.
- **The failing clause**: this variant breaks the resolution clause because the connector resolves the name again after the check, so the approved address and the connected address differ.
- **Claim discipline**: the arrival is claimed only when both answers are recorded for one operation, because one answer alone cannot show a rebind.

## Key Vulnerabilities

### Lookup-Count Gaps

- **Lookup count**: count the resolutions between the check and the connection, because each additional lookup is a chance for the answer to change.
- **Lookup race**: frame the gap as a race between a validating lookup and a fetching lookup: the check resolves once and the fetch re-resolves, so the answer only has to change inside that interval.
- **Pair repetition**: repeat the lookup pair until the race is won, because a resolver cache can collapse the two lookups into one answer on any single attempt.
- **Independent connector**: prefer the connector that resolves independently, since a connector fed the validated value resolves nothing.
- **Ownership**: the parent path-mapping step covers one destination value and cannot describe a name answered twice, so this variant owns the lookup-count procedure.

### Record Lifetime Control

- **Short lifetime**: serve an answer with a lifetime short enough to change between the approving and the connecting lookup.
- **Cache confirmation**: confirm the resolver's caching behaviour first, because a cache that outlives the check collapses the two lookups into one answer.
- **Pinned resolution**: treat an answer that survives both lookups as a pinned resolution rather than a rebind.

### Address Family Answers

- **Second answer**: point the second answer at the reach the operation needs, including families the approving check treats as external and the connector treats as interior.
- **Benign first answer**: keep the first answer benign and the second minimal, because the first answer is the one the check reads.
- **Out-of-band confirmation**: confirm the arrival out of band, since a connection that never happened is not a rebind.

## Bypass Techniques

- **Bypass scope**: relay shapes are tried only after the direct route is baselined, because a name that never rebound carried nothing.

- **Changing answer**: a name whose answer changes between the approving and the connecting lookup.
- **Short lifetime**: a lifetime short enough to expire inside the gap between the two lookups.
- **Wildcard answer**: a wildcard or fallback answer that covers the label the operation uses.
- **Answer-name family**: an answer-name family whose first answer is benign and whose second answer is the operated reach, kept as a pattern rather than a concrete name.
- **Address families**: address families that the approving check and the connector classify differently.
- **Repeated pairs**: repeated pairs across lifetimes, because a resolver cache can collapse the lookups.

## Chaining Attacks

- **Chain scope**: rebinding chains forward into the class that owns the effect, because a changed answer is only the first hop.
- **Effect hand-off**: hand the reached destination to the class that owns the effect, and prove the class-specific consequence there.
- **Forwarded hop**: chain into a forwarded hop, because the second answer can itself be a redirecting destination.
- **Parse-differential stack**: chain into the destination parse differential where the approved and connected values also parse differently.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Rebinding baselines the pair first and answers second, because a single lookup cannot show a rebind.

1. **Trace the lookups** - every resolution between the approving component and the connector, and the step completes when each lookup carries the component that performs it.
2. **Baseline the refusal** - send a literal address the check rejects, and the step completes when a refusal is recorded or the absence of a destination check is recorded with the test that showed it.
3. **Record the answer** - note the record lifetime, the resolver caching behaviour, and the fallback answer, and the step completes when the lifetime that fits inside the lookup gap is named.
4. **Serve the second answer** - change the answer between the two lookups, and the step completes when the approving lookup reads the benign answer and the connector reads the operated one.
5. **Confirm the arrival** - prove the connection at operated infrastructure, and the step completes when the arrival is attributed to the connector rather than to the caller.
6. **Attribute the rebind** - pair the approved answer with the connected answer, and the step completes when the rebind is named from the pair.

## False Positives

- **Stop condition**: stop when the resolution stayed pinned, because one answer across both lookups is not a rebind.

- **Validated-value connector**: a connector fed the validated value, which resolves nothing and connects to the approved address.
- **Outliving cache**: a resolver cache that outlives the check, confirmed by one answer across the pair.
- **Tester-side arrival**: an arrival whose source is the tester's client rather than the target's connector.
- **Literal destination**: a destination supplied as a literal address, which has no lookup to answer twice.
- **Simulator**: a simulator that answers the second lookup itself without a real connection.

## Pro Tips

- **Discipline**: rebinding rewards lookup counting plus lifetime control.
- **Lookup count**: count the lookups before crafting, because each one is a chance for the answer to change.
- **Benign first answer**: keep the first answer benign and the second minimal, since the check reads the first.
- **Cache confirmation**: confirm the resolver's caching behaviour, because a cache can collapse the pair into one answer.
- **Out-of-band proof**: prove the arrival out of band, since an unproved connection is not a rebind.
- **Effect hand-off**: hand the reached destination to the class that owns the effect, and stop at the narrowest proof.

## Summary

A name resolved after its check can answer with a different address each time. Resolution rebinding controls the answer between the approving and the connecting lookup, and claims the rebind only when both answers are recorded.
