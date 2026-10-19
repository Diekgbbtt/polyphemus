---
name: proxy-techniques-channel-wrapping
description: Channel wrapping where one operation travels in a second carrier, covering carrier substitution when a sibling content type, verb, transport, endpoint, protocol version, or batch envelope reaches the same effect, guard parity gaps when the sibling carrier carries a weaker check or escapes a per-request guard, second-channel replay when a captured request is re-presented elsewhere, and capture positions when the exact request shape is observed before it is re-sent.
metadata:
  version: 1.0.0
---

# Channel Wrapping

A guard watches the carrier it inspects, and the operation can travel in another. This variant re-presents the same operation through a sibling content type, verb, transport, endpoint, session, or device, so the inspecting component reads a shape it does not guard. The goal is the effect reached through the carrier the control does not watch, with the operation itself unchanged.

## Attack Surface

- **Applicability**: centers on one operation that more than one carrier can reach.
- **Surface composition**: sibling content types and serialisations of one body, alternate verbs and method-override members for one route, second transports and endpoints for one effect, and second sessions or devices for one identity.
- **Widening factors**: carriers whose guard differs from the primary carrier's guard, and a channel position where the exact request shape is observable, both widen the surface.
- **Out-of-scope variant**: an operation reachable through exactly one carrier rides outside this variant, because there is no sibling to wrap into.

## Reconnaissance

- **Reconnaissance scope**: channel wrapping enumerates the carriers before crafting, because the mechanism is a carrier the guard does not watch.
- **Carrier list**: list every carrier that reaches the effect: content types, verbs, transports, endpoints, sessions, and devices.
- **Guard recording**: record the guard each carrier passes through, because a carrier with a weaker check is the bypass.
- **Refusal baseline**: establish the refusal baseline on the primary carrier, so a later pass on a sibling is attributable to the carrier.
- **Channel position**: note any channel position where the exact request is observable, since a captured shape can be re-presented unchanged.

## Detection Channels

- **Channel scope**: channel wrapping listens to the carrier the guard does not watch, so only the entries below are live here.
- **Sibling arrival**: the operation arriving through a sibling carrier while the primary carrier stays refused.
- **Primary wrap signal**: the sibling carrier returning another principal's data while the primary carrier stays refused, which is the primary wrap signal.
- **Protocol-version carrier**: a front tier that accepts a newer protocol and downgrades it for the origin, which proves a protocol-version carrier exists.
- **Shape match**: the captured request shape matching the re-presented shape field by field.
- **Paired baseline**: a paired baseline where one identical operation passes on one carrier and fails on another.
- **Weak-guard effect**: the effect appearing through a carrier whose guard is absent or weaker.
- **Guard parity**: a negative that holds across every carrier and carrier variant, which reads as guard parity.

## Adversarial Capabilities

- **Prerequisites**: channel wrapping presupposes a carrier inventory plus a channel position plus a repeatable baseline, and it consumes all three.
- **Paired answers**: send the operation on the primary carrier and on a sibling carrier, and read both answers.
- **Channel observation**: observe the channel where the request shape is visible, so the re-presented request matches the original.
- **Unchanged operation**: re-present the same operation unchanged across carriers, so the carrier is the only changed variable.
- **Second session**: hold a second session, device, or transport where identity binding is carrier-specific.

## Trust Assumptions

- **The agreement**: the guard trusts that the carrier it watches is the carrier that delivers the operation, and that every carrier of one operation carries the same check, holds the guard's carrier to the delivering carrier, holds sibling carriers to one check, and holds an identity's binding across every channel it can use.
- **The failing clause**: this variant breaks the carrier clause because the operation travels in a carrier the guard does not inspect, so the guard reports a compliant shape while the effect occurs elsewhere.
- **Claim discipline**: the pass is claimed only against the recorded refusal on the primary carrier, because an unguarded carrier proves nothing about parity.

## Key Vulnerabilities

### Carrier Substitution

- **Sibling carrier**: reach the effect through a sibling content type, serialisation, verb, or endpoint, because each carrier is parsed and guarded on its own.
- **Protocol version**: a protocol version is a carrier: a request that carries no framing declarations at all, a newer protocol the front tier accepts and downgrades, and an alternate framing each reach the origin through a shape the inspecting component does not parse.
- **Carrier location**: a value carried in a location the guard does not inspect is the same substitution with the location as the carrier, because the guard parses the body and the location while the sink reads another.
- **Batch envelope**: a batch envelope whose inner operations the guard does not parse is a carrier on its own, because the outer shape passes and the inner operations arrive unexamined.
- **Unchanged operation**: keep the operation identical across carriers so the carrier is the only changed variable.
- **Ownership**: the parent mechanism-selection step covers one carrier and cannot describe one operation through several, so this variant owns the carrier-substitution procedure.
- **Carrier substitution matrix**: see `references/carrier-substitution-matrix.md` for the carrier family table and the parity check.
- **Tier route inventory**: see `references/tier-route-inventory.md` for the sibling-route and version inventory that reaches one operation.

### Guard Parity Gaps

- **Guard comparison**: compare the guard on each carrier, because a sibling carrier often carries a weaker check or none.
- **Type-bound check**: a check bound to one content type is skipped by the same operation re-encoded into a sibling type, because the guard reads the declared type rather than the consumed body.
- **Persistent second channel**: a persistent second channel bypasses a guard and an accounting rule that both watch requests rather than the channel, so the effect travels while neither the check nor the counter fires.
- **Absent-check preference**: prefer the carrier whose check is absent rather than weaker, since the effect then needs no second bypass behind it.
- **Upgrade-shaped path**: treat an upgrade-shaped or informational path as a sibling carrier whose check differs from the primary path's.

### Second-Channel Replay

- **Second-channel replay**: re-present a captured request through a second channel, session, or device where the identity binding is carrier-specific.
- **Signed-message replay**: a signed message replayed inside its validity window or in a second session proves the signature is bound neither to the principal nor to the freshness window, because a binding that held would refuse the replay.
- **One binding per attempt**: change one binding element per attempt: the channel, the session, or the device.
- **Upgrade handshake**: an upgrade-shaped handshake the front tier and the origin read differently opens a carrier the front tier stops parsing, so the inspecting component and the terminating component disagree about where the request ends.
- **Completed probe**: treat a channel where proof-of-possession is absent as the completed probe.

### Capture and Re-present

- **Capture and re-present**: observe the request at a channel position where its exact shape is visible, and re-present it unchanged with one member altered.
- **Byte-identical re-presentation**: keep the re-presented request byte-identical apart from the changed member, so the change is the only variable.
- **Client-side capture**: treat a capture position inside the tester's own client as a client-side artifact rather than a channel.

## Bypass Techniques

- **Bypass scope**: relay shapes are tried only after the direct route is baselined, because a carrier that was never guarded carried nothing.

- **Sibling content types**: sibling content types and serialisations of one body, where each path validates one representation.
- **Alternate verbs**: alternate verbs and override members for one route.
- **Second transports**: second transports, endpoints, and upgrade-shaped paths whose checks differ.
- **Protocol version**: a protocol version the front tier accepts and the origin parses differently.
- **Uninspected location**: a value carried in a location the guard does not inspect.
- **Batch envelope**: a batch envelope whose inner operations the guard does not parse.
- **Persistent channel**: a persistent second channel that escapes a per-request guard and its accounting.
- **Second sessions**: second sessions, channels, and devices for one identity.
- **Captured request**: a captured request re-presented unchanged through a carrier the guard does not watch.

## Chaining Attacks

- **Chain scope**: channel wrapping chains forward into the class that owns the effect, because a sibling carrier is only the first hop.
- **Effect hand-off**: hand the effect reached through the sibling carrier to the class that owns it, and prove the class-specific consequence there.
- **Tier-gap stack**: chain into the tier gap where the sibling carrier is served by a tier that skips the current chain.
- **Throttle stack**: chain into the throttle step where the second carrier also resets the accounting.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Channel wrapping enumerates the carriers first and wraps second, because the mechanism is the unguarded carrier.

1. **Enumerate the carriers** - every content type, verb, transport, endpoint, session, and device that reaches the effect, and the step completes when each carrier names its guard.
2. **Baseline the primary carrier** - send the operation on the primary carrier and record the answer, and the step completes when a refusal is recorded or the absence of a guard is recorded with the test that showed it.
3. **Probe carrier parity** - send one identical operation on each sibling carrier, and the step completes when each carrier carries a passed or refused verdict.
4. **Capture the shape** - observe the request at a channel position where its exact shape is visible, and the step completes when the re-presentable shape is recorded.
5. **Re-present through the sibling** - send the captured request through the carrier with the weaker guard, one member altered per attempt, and the step completes when the effect reproduces on the sibling carrier while the primary stays refused.
6. **Attribute the wrap** - pair the refused primary carrier with the passed sibling, and the step completes when the unguarded carrier is named from the pair.

## False Positives

- **Stop condition**: stop when every carrier refused the operation, because guard parity is not a wrap.

- **Refusing sibling**: a sibling carrier that refuses the operation, confirmed across the carrier inventory.
- **Watched carrier**: a carrier the guard does watch, where the operation passed for a class-specific reason rather than the carrier.
- **Broken request**: a pass whose effect never reached the sink, where the carrier passed and the request broke later.
- **Client-side capture**: a capture position inside the tester's own client rather than on the channel.
- **Simulator answer**: a simulator response that answers the sibling carrier without reaching the effect.

## Pro Tips

- **Discipline**: channel wrapping rewards carrier inventory plus an unchanged operation.
- **Carrier enumeration**: enumerate the carriers before crafting, because the mechanism is a carrier the guard does not watch.
- **Unchanged operation**: keep the operation identical across carriers so the carrier is the only changed variable.
- **No-check preference**: prefer the carrier with no check over one with a weaker check.
- **Byte-identical re-presentation**: re-present a captured request byte-identical apart from the changed member.
- **Effect hand-off**: hand the effect to the class that owns it, and stop at the narrowest proof.

## Summary

A guard watches one carrier while the operation can travel in another. Channel wrapping enumerates the carriers, re-presents the unchanged operation through the unguarded one, and claims the wrap only against the refusal on the primary carrier.
