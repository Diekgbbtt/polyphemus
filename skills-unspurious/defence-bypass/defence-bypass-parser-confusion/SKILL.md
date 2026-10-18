---
name: defence-bypass-parser-confusion
description: Parser confusion bypass between two readers of one request, covering duplicate member precedence when the control reads one occurrence and the sink another, framing and content-type reading when each side consumes a different representation, and verb or location re-reading when the gate checks a member the executor overrides.
metadata:
  version: 1.0.0
---

# Parser Confusion

Two components read one request and each consumes a different member. This variant makes the control evaluate a member the sink never consumes, or the reverse, so the approved request and the executed request are different objects. The goal is an effect reached through a member the control's own reading never covered.

## Attack Surface

Parser confusion applicability centers on a request that more than one component reads before the effect executes.
The surface holds duplicated members whose precedence differs per reader, representations that a content-type declaration selects between, verbs and routes that an override member can restate, and value locations that a second path reads without the check.
Framing declarations that a transit tier re-derives, and shapes where a lenient reader accepts a structure a strict reader rejects, both widen the surface.
A request that exactly one component reads rides outside this variant, because there is no second reading to disagree with.

## Reconnaissance

Parser confusion maps the readers before crafting, because the disagreement lives between two readings rather than inside one.
- List the components that read the request and note which member each one consumes for the same effect.
- Establish the refusal baseline with the canonical single-member request, so a later pass is attributable to the second reading.
- Probe precedence by duplicating one member with two values and reading which value each layer acts on.
- Note the transit tiers that re-frame the request, because a re-framed request re-reads every member it re-emits.

## Detection Channels

Parser confusion listens to the two readings of one request, so only the entries below are live here.
- The control's refusal on the canonical single-member request, which proves the reading that evaluates the member engaged.
- A pass for the same effect in a duplicated or re-framed request, which shows the readers consumed different members.
- The differential between the refused canonical request and the passed re-read request at one member, which localises the disagreement.
- The effect appearing at the sink through a member the control's reading did not cover.
- The sink's own error class, which names the member the sink actually consumed.

## Adversarial Capabilities

Parser confusion presupposes a reader inventory plus member-shaping freedom plus a repeatable baseline, and it consumes all three.
- Send the canonical request and the duplicated candidate to the same position, and read both answers.
- Duplicate one member per attempt with two distinguishable values, so the consuming reader is nameable.
- Re-present the same effect through a second representation, a second verb, or a second location.
- Hold a transit tier in the path where one exists, so the re-framed request can be compared with the received one.

## Trust Assumptions

The control trusts that the request it reads is the request the sink executes.
The agreement holds one member to one consumer, holds every reader of the request to one precedence rule, holds the declared representation to the one the sink decodes, and holds the verb and the route to the values the gate evaluated.
This variant breaks the single-consumer clause because two readers resolve one member differently, so the control approves a request the sink never executes in that shape.
The pass is claimed only when both readings are recorded, because one reading alone cannot show a disagreement.

## Key Vulnerabilities

### Duplicate Member Precedence

Send one member twice with two distinguishable values, because the gate often reads the first occurrence while the sink reads the last.
Vary the ordering across attempts so each reader's precedence is established rather than assumed.
The parent craft step covers one value at one position and cannot describe two consumers of one member, so this variant owns the precedence procedure.

### Representation and Framing Reading

Re-present the same effect under a second content type or framing declaration, because some paths validate only the representation they expect.
Re-derive the request through the transit tier where one exists, since the emitted framing may no longer match the received one.
Treat a representation the sink decodes differently from the control as the completed probe.

### Verb and Location Re-reading

Restate the verb or the route through an override member, because the gate often evaluates the declared verb while the executor applies the override.
Move the same value to a second location that a sibling path reads without the check, and confirm which location the sink consumed.
Treat a location whose second path skips the check as the bypass, and keep the effect identical to the canonical request.

## Bypass Techniques

Bypass shapes slip past a reader that is present, so each one is tried after the canonical request is refused.
- Duplicate members with both orderings, because each reader resolves precedence for itself.
- Content-type and framing re-presentations of one effect, where each path validates one representation.
- Override members for the verb and the route, where the gate evaluates the declared value.
- Value relocation across equivalent request positions, where one position skips the check.
- Structural shape variants of one value, where a lenient reader accepts what a strict reader rejects.

## Chaining Attacks

Parser confusion chains forward into the class that owns the effect, because a passed reader is only the first layer.
- Hand the passed request to the class that owns the effect, and prove the class-specific consequence there.
- Stack with the encoding differential where the second reader also decodes the value differently.
- Stack with the tier gap where the second reading is served by a tier that skips the current chain.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Parser confusion inventories the readers first and duplicates second, because the disagreement lives between two readings.

1. **Inventory the readers** - every component that reads the request with the member it consumes, and the step completes when each member carries at least one named consumer.
2. **Baseline the canonical refusal** - send the single-member request and record the control's answer, and the step completes when a refusal is recorded or the absence of a reading control is recorded with the test that showed it.
3. **Duplicate one member** - send two occurrences with distinguishable values and read which value each layer acts on, and the step completes when each reader's precedence is recorded.
4. **Re-present the representation** - send the same effect under a second content type or framing, and the step completes when the second representation carries a passed or refused verdict.
5. **Restate verb and location** - move the effect to an override member and to a sibling location, one per attempt, and the step completes when each alternative carries a verdict naming the member the sink consumed.
6. **Confirm at the sink** - prove the effect through the member the control did not cover, and the step completes when the effect reproduces with the canonical member still refused.
7. **Attribute the pass** - pair the refused canonical request with the passed re-read request, and the step completes when the disagreeing member is named from the pair.

## False Positives

Stop when both readers consumed the same member, because an identical reading is not a disagreement.

- A reader that joins duplicated members before evaluating them, confirmed by a refusal at every ordering.
- A sink that reads the same occurrence the control read, where the request passed the control without changing meaning.
- A pass whose effect never reached the sink, where the request passed the control and broke later.
- A denial from a second control behind the first, which shows a stacked control rather than a bypass.
- A cached or simulator response that replays a stored verdict for the re-presented request.

## Pro Tips

Parser confusion rewards reader inventory plus one member per attempt.

1. Inventory the readers before crafting, because the disagreement is between components rather than inside one.
2. Duplicate one member per attempt so the consuming reader is nameable.
3. Keep the effect identical across re-presentations, since a changed effect invalidates the comparison.
4. Re-baseline after each pass, because a second control often reads the member the first one missed.
5. Confirm at the sink, because a control's silence is not the effect.

## Summary

Two components read one request and each consumes a different member. Parser confusion inventories the readers, duplicates one member per attempt, and claims the pass only when the sink's member is named.
