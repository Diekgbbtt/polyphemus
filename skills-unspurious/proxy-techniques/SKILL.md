---
name: proxy-techniques
description: Proxy and interception technique testing for the components between the caller and the origin, covering resolution rebinding when a name answers differently across lookups, forwarded destinations when an approved hop lands elsewhere, destination parse disagreements when two components read one value, carrier substitution when the operation travels in a second channel, shared-cache keying when a stored response reaches another caller, and relay-forwarded values the origin trusts.
metadata:
  version: 1.0.0
---

# Proxy Techniques

Every request travels a path of components that resolve, forward, redirect, cache, or re-present it, and each one is a place to make the operation arrive somewhere the caller could not reach directly. This family owns the generic intermediary mechanics: a name rebound between lookups, a forwarded destination, two readings of one destination value, a second carrier, a shared-cache key, and a relay-forwarded field the origin trusts. Each consuming class keeps its own exploit detail and names this family at its proxy step.

## Attack Surface

Proxy applicability centers on a component between the caller and the effect that carries, resolves, forwards, stores, or re-presents the operation.

**Resolvers**
- Name resolution between the approving lookup and the connecting lookup, where a second answer reaches a different address
- Short-lived records, wildcard answers, and fallback resolution that the caller can influence

**Redirectors and Forwarders**
- Components that answer with a destination and follow it, including nested hops and hops that switch scheme
- Components that re-validate, or fail to re-validate, the destination at each hop

**Relays and Gateways**
- Components that forward the request with their own view of the authority, the client address, the scheme, or the destination
- Forwarding and rewrite fields that the origin trusts past the boundary the relay controls

**Shared Caches**
- Components that store a response under a key and serve it to a later caller
- Selectors the key covers, selectors it omits, and key normalisation that collapses entries

**Second Carriers**
- A second content type, verb, transport, endpoint, session, or device that reaches the same operation
- Capture positions where the exact request shape is observed before it is re-presented

**Consumer Libraries**
- Client and library components that resolve a destination value for their own connection at a different moment than the enforcing side
- Components that complete a relative value against their own base

## Reconnaissance

Proxy work starts at the path, because an intermediary whose contribution is not separated from the direct route proves nothing.

### Path Mapping

- List every component between the caller and the effect, and record what each one does with the destination, the authority, the framing, and the response
- Record where the destination is approved, where it is resolved, and where it is connected to, because the moment of each decides the mechanism
- Note every caller-influenced input at each hop: destination values, authority and forwarding fields, cache-relevant selectors, and the choice of carrier

### Intermediary Characterisation

- Characterise each hop: what it keys on, what it forwards, whether it re-resolves, and what it stores
- Read the intermediary's own state where it is reachable, such as a stored entry, a forwarded field set, or a stored verdict
- Establish the arrival oracle: operated infrastructure that proves the second hop, the second carrier, or the interior destination was reached

### Direct-Route Baseline

- Send the same operation directly and through the intermediary, and record both answers
- Keep the operation identical across the pair, so the only changed variable is the path it travelled
- Record a negative that holds across every hop and carrier, because it reads as a path that carries nothing the caller can influence

## Detection Channels

The family listens to the path rather than to one component, so every entry below is live wherever an intermediary sits.

- The operation arriving at a second hop, a second carrier, or an operated endpoint, which proves the intermediary carried it.
- A shared cache serving a response to a later caller under a key the caller influenced or reads.
- A resolver's second answer differing from the first, which proves the name was rebound between lookups.
- A verdict from a tier the direct route never consults.
- The origin acting on a value the caller supplied through the relay's own fields.
- The same destination value read as two different targets by two components.
- A direct-route baseline that differs from the intermediary route for one identical operation.
- The chain or carrier recorded hop by hop with each hop's destination and verdict, which localises the hop that stopped checking.
- The captured request shape matching the re-presented shape field by field.
- An arrival whose source is the intermediary rather than the caller, which separates a relay effect from a client-side request.
- A negative that holds across every carrier and hop, which reads as a path that carries nothing the caller can influence.

## Adversarial Capabilities

Proxy work presupposes a carrier under control plus an arrival oracle plus a second lane, and it consumes all three.

- Control a carrier: a redirecting endpoint, a name whose resolution the caller can change, or a relay the caller can influence.
- Observe a channel position, so the exact request shape is known before it is re-presented.
- Operate arrival infrastructure that proves the second hop or the interior destination was reached.
- Hold a second channel, endpoint, session, or device that reaches the same operation.
- Shape the destination value: its spelling, its separators, its encoding, and its duplicate members.
- Read a shared cache's stored response for a key the caller can name or collide with.
- Compare the direct route and the intermediary route with one identical operation.

## Trust Assumptions

Every path rests on one agreement: each component between the caller and the effect reads the same request the origin reads, and every hop preserves the caller's intent from the check to the effect.
The agreement holds the destination to one resolution from the approving lookup to the connecting lookup, holds every hop to a destination the approver saw, holds every reader of a destination value to one parse, holds the carrier the control watches to the carrier that delivers, holds the shared-cache key to everything that varies the response, and holds the relay's own fields to values the origin may trust.
Each variant breaks one clause: the resolution clause, the forwarding clause, the parse clause, the carrier clause, the cache-key clause, or the relay-field clause.
An effect that passes through an intermediary is claimed only when the intermediary's contribution is separated from the direct route.

## Key Vulnerabilities

### Resolution Rebinding

- A name is resolved more than once along the path, and the second answer is the one the connection uses.
- A short lifetime or a caller-influenced record lets the second answer point somewhere the first lookup never approved.

### Forwarded Destinations

- An approved first destination forwards the operation to a second one, so the approval covers a hop rather than the arrival.
- Nested hops and scheme switches multiply the forwarding, because each hop re-applies or skips its own check.

### Destination Parse Disagreement

- Two components read one destination value differently: the approver reads one authority or path and the consumer connects to another.
- Separator, userinfo, fragment, case, trailing-dot, and encoded forms land differently on the two readers.

### Carrier Substitution

- The same operation travels in a second content type, verb, transport, endpoint, session, or device, so the component that inspects one carrier never sees it.
- A captured request re-presented through a second carrier keeps the operation and changes the path.

### Shared-Cache Keying

- A stored response is keyed on less than everything that varies it, so a later caller reaches a response produced for another.
- Selectors the key omits, normalisation that collapses entries, and suffixes that change an entry's reach all deliver the same outcome.

### Relay-Field Trust

- An intermediary supplies the authority, the client address, the scheme, or the destination, and the origin treats the supplied value as its own observation.
- Values the caller can influence reach the origin through the relay's own fields rather than through the request body.

## Advanced Techniques

**Chain the Intermediaries**
- A rebound name into a forwarded hop into a shared-cache key multiplies the reach, because each component trusts the one before it.

**Keep Every Hop Under Control**
- Own the first destination and the second, so the chain's arrival is a chosen target rather than a discovered one.

**Prove Arrival Out of Band**
- Confirm the second hop at operated infrastructure before crafting the next hop, so a silent hop is not mistaken for a blocked one.

**Pair the Routes**
- Send one identical operation directly and through the intermediary, because the pair is what separates the path's contribution from the effect.

## Bypass Techniques

Relay shapes are tried only after the direct route is baselined, because an intermediary that never carried the operation is not a proxy effect.

- Destination spelling and encoding variants that decode differently on each side of the path.
- Duplicate destination members, where precedence decides which component reads which value.
- A second carrier for one operation: content type, verb, transport, endpoint, session, or device.
- Hop chaining, where an approved first destination forwards to a destination under control.
- Key shaping for a shared cache: selectors the key omits, separators it collapses, and suffixes that change an entry's reach.
- Relay fields that carry a caller-supplied value into the origin's trust.

## Chaining Attacks

A carried operation is a mechanism rather than a finding, so the path hands forward to the class that owns the effect.

- Hand the carried operation to the class that owns the effect, and prove the class-specific consequence there.
- Chain the families, because a carried operation past a destination check lands on a control the defence-bypass family owns.
- Hand a hop that reaches a second surface to the class that consumes that surface.
- Keep the carry minimal: the smallest arrival that proves the path, then the class's own procedure.
- Name the class at its own step rather than restating its checks: `ssrf` at its relay hops, `business-logic` at its channel-wrapping step, `idor` at its shared-cache step, and `header-injection` at its keying step.

## Testing Methodology

Proxy work baselines the direct route first and carries the operation second, because an unseparated effect proves nothing.

1. **Inventory the path** - every component between the caller and the effect with what it does to the destination, the framing, and the response, and the step completes when each hop names its caller-influenced inputs.
2. **Baseline the direct route** - the same operation sent directly with its answer recorded, and the step completes when the direct route's verdict is recorded for comparison.
3. **Characterise the intermediaries** - what each hop keys on, forwards, re-resolves, and stores, and the step completes when every hop carries a characterisation or a recorded negative.
4. **Establish the arrival oracle** - operated infrastructure that proves the second hop, the second carrier, or the interior destination was reached, and the step completes when an arrival is attributed to the intermediary rather than to the caller.
5. **Select the mechanism** - the mechanism the intermediary's behaviour admits, and the step completes when the selection names the clause it breaks.
6. **Craft the carrier** - the destination value, the hop chain, or the key shape, one variable per attempt, and the step completes when each attempt carries its arrival verdict.
7. **Confirm through the intermediary** - the effect arrives through the intermediary and not through the direct route, and the step completes when the paired comparison separates the two.
8. **Attribute and stop** - separate the intermediary's effect from a client-side request and from a direct-route success, and the step completes when the narrowest proof carries its attribution.

## Variants

- proxy-techniques-dns-rebinding - Change the answer a name resolves to between the approving lookup and the connecting lookup, so the approved name reaches a different address.
- proxy-techniques-redirect-chain - Land the operation on a destination the approver never saw by forwarding it through one or more hops that the first approval covered.
- proxy-techniques-url-parser-differential - Exploit two readings of one destination value, where the component that approves it and the component that connects to it parse different authorities or paths.
- proxy-techniques-channel-wrapping - Re-present the same operation through a second content type, verb, transport, endpoint, session, or device that the inspecting component does not watch.
- proxy-techniques-cache-deception - Make a shared cache store or serve a response under a key the caller influences or reads, so a later caller reaches content produced for another.
- proxy-techniques-relay-forwarding - Supply the authority, the client address, the scheme, or the destination through a relay's own fields, and read whether the origin trusts the supplied value.

## False Positives

Stop when the evidence shows the path carried nothing or the caller's own client made the request, because neither is a proxy effect.

- An arrival whose source is the tester's client rather than an intermediary, which reads as a client-side request.
- A direct-route success mistaken for a carried operation, confirmed by the paired baseline.
- A shared cache serving the tester's own session entry under a key that names the tester.
- A name whose answer never changed between the approving and the connecting lookup.
- A hop that re-validated the destination, confirmed by a refusal at the second hop.
- A relay field the origin ignores, confirmed by the absence of any effect from the supplied value.
- A simulator or mock that answers the second hop itself without a real connection.

## Pro Tips

Proxy work rewards path mapping plus paired baselines plus arrival proof.

1. Baseline the direct route before crafting anything, because the pair is what attributes the effect to the path.
2. Keep every hop under control, so the chain's arrival is a chosen target.
3. Prove arrival out of band before crafting the next hop, since a silent hop is not a blocked one.
4. Send one variable per attempt so the hop or key that admitted the operation is nameable.
5. Read the intermediary's own state where it is reachable rather than inferring it from the response.
6. Hand the carried operation to the class that owns the effect, and stop at the narrowest proof.

## Summary

An operation that travels through an intermediary can arrive where the caller could not reach directly, and every hop trusts the one before it. This family maps the path, separates the intermediary's contribution from the direct route, and confirms the arrival before handing the class its step.
