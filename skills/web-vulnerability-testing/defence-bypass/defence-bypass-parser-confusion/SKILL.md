---
name: defence-bypass-parser-confusion
description: Parser confusion bypass between two readers of one request, covering duplicate member precedence when the control reads one occurrence and the sink another, framing and content-type reading when each side consumes a different representation, framing-declaration obfuscation when a normalising front end re-derives the boundary, and verb or location re-reading when the gate checks a member the executor overrides.
metadata:
  version: 1.0.0
---

# Parser Confusion

Two components read one request and each consumes a different member. This variant makes the control evaluate a member the sink never consumes, or the reverse, so the approved request and the executed request are different objects. The goal is an effect reached through a member the control's own reading never covered.

## Attack Surface

- **Applicability**: centers on a request that more than one component reads before the effect executes.
- **Surface composition**: duplicated members whose precedence differs per reader, representations that a content-type declaration selects between, verbs and routes that an override member can restate, and value locations that a second path reads without the check.
- **Widening factors**: framing declarations that a transit tier re-derives, and shapes where a lenient reader accepts a structure a strict reader rejects, both widen the surface.
- **Out-of-scope variant**: a request that exactly one component reads rides outside this variant, because there is no second reading to disagree with.

## Reconnaissance

- **Reconnaissance scope**: parser confusion maps the readers before crafting, because the disagreement lives between two readings rather than inside one.
- **Reader inventory**: list the components that read the request and note which member each one consumes for the same effect.
- **Refusal baseline**: establish the refusal baseline with the canonical single-member request, so a later pass is attributable to the second reading.
- **Precedence probe**: probe precedence by duplicating one member with two values and reading which value each layer acts on.
- **Strictness ranking**: rank the readers by strictness where possible, because a lenient reader accepts a structure the strict one rejects and that pair is the gap.
- **Transit tiers**: note the transit tiers that re-frame the request, because a re-framed request re-reads every member it re-emits.

## Detection Channels

- **Channel scope**: parser confusion listens to the two readings of one request.
- **Canonical refusal**: the control's refusal on the canonical single-member request, which proves the reading that evaluates the member engaged.
- **Re-read pass**: a pass for the same effect in a duplicated or re-framed request, which shows the readers consumed different members.
- **Member differential**: the differential between the refused canonical request and the passed re-read request at one member, which localises the disagreement.
- **Uncovered member**: the effect appearing at the sink through a member the control's reading did not cover.
- **Override applied**: a response stored under a different member's key than the one sent, which proves the executor applied an override.
- **Timing differential**: a timing differential between a normal request and a re-framed one, which confirms a boundary disagreement when both answers look alike.
- **Sink error class**: the sink's own error class, which names the member the sink actually consumed.

## Adversarial Capabilities

- **Prerequisites**: parser confusion presupposes a reader inventory plus member-shaping freedom plus a repeatable baseline, and it consumes all three.
- **Paired answers**: send the canonical request and the duplicated candidate to the same position, and read both answers.
- **One member per attempt**: duplicate one member per attempt with two distinguishable values, so the consuming reader is nameable.
- **Re-presentation**: re-present the same effect through a second representation, a second verb, or a second location.
- **Transit-tier access**: hold a transit tier in the path where one exists, so the re-framed request can be compared with the received one.

## Trust Assumptions

- **The agreement**: the control trusts that the request it reads is the request the sink executes, holds one member to one consumer, holds every reader of the request to one precedence rule, holds the declared representation to the one the sink decodes, and holds the verb and the route to the values the gate evaluated.
- **The failing clause**: this variant breaks the single-consumer clause because two readers resolve one member differently, so the control approves a request the sink never executes in that shape.
- **Claim discipline**: the pass is claimed only when both readings are recorded, because one reading alone cannot show a disagreement.

## Key Vulnerabilities

### Duplicate Member Precedence

- **Duplicate sending**: send one member twice with two distinguishable values, because the gate often reads the first occurrence while the sink reads the last.
- **Ordering variation**: vary the ordering across attempts so each reader's precedence is established rather than assumed.
- **Precedence rules**: establish the precedence rule from the reader inventory: first-occurrence, last-occurrence, list-collecting, and joined forms are the four rules a reader can apply, and the response names the rule each reader follows.
- **Ownership**: the parent craft step covers one value at one position and cannot describe two consumers of one member, so this variant owns the precedence procedure.
- **Precedence matrix**: see `references/parameter-precedence-matrix.md` for the four precedence rules and the probe that establishes each reader's rule.

### Representation and Framing Reading

- **Representation switch**: re-present the same effect under a second content type or framing declaration, because some paths validate only the representation they expect.
- **Declaration obfuscation**: obfuscate the framing declaration itself so a normalising front end re-derives the boundary differently: a separator or whitespace variant before the declaration's value, a folded continuation, a case variant, or a second declaration of the same framing, because the front end's normalisation decides which form it evaluates.
- **Transit re-derivation**: re-derive the request through the transit tier where one exists, since the emitted framing may no longer match the received one.
- **Completed probe**: treat a representation the sink decodes differently from the control as the completed probe.
- **Framing table**: see `references/framing-obfuscation-table.md` for the declaration variants and the reader pairs they target.

### Verb and Location Re-reading

- **Override restatement**: restate the verb or the route through an override member, because the gate often evaluates the declared verb while the executor applies the override.
- **Override positions**: the override positions are the declared-verb field, the routed-path field, and the form member that names a verb, and each is honoured by a different executor.
- **Value relocation**: move the same value to a second location that a sibling path reads without the check, and confirm which location the sink consumed.
- **Unchecked location**: treat a location whose second path skips the check as the bypass, and keep the effect identical to the canonical request.

## Bypass Techniques

- **Bypass scope**: bypass shapes slip past a reader that is present, so each one is tried after the canonical request is refused.
- **Duplicate members**: duplicate members with both orderings, because each reader resolves precedence for itself.
- **Re-presentations**: content-type and framing re-presentations of one effect, where each path validates one representation.
- **Override members**: override members for the verb and the route, where the gate evaluates the declared value.
- **Value relocation**: value relocation across equivalent request positions, where one position skips the check.
- **Structural variants**: structural shape variants of one value, where a lenient reader accepts what a strict reader rejects.

## Chaining Attacks

- **Chain scope**: parser confusion chains forward into the class that owns the effect, because a passed reader is only the first layer.
- **Effect hand-off**: hand the passed request to the class that owns the effect, and prove the class-specific consequence there.
- **Encoding-differential stack**: stack with the encoding differential where the second reader also decodes the value differently.
- **Tier-gap stack**: stack with the tier gap where the second reading is served by a tier that skips the current chain.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

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

- **Stop condition**: stop when both readers consumed the same member, because an identical reading is not a disagreement.
- **Joining reader**: a reader that joins duplicated members before evaluating them, confirmed by a refusal at every ordering.
- **Same occurrence**: a sink that reads the same occurrence the control read, where the request passed the control without changing meaning.
- **Broken request**: a pass whose effect never reached the sink, where the request passed the control and broke later.
- **Stacked control**: a denial from a second control behind the first, which shows a stacked control rather than a bypass.
- **Cached or simulated answer**: a cached or simulator response that replays a stored verdict for the re-presented request.

## Pro Tips

- **Discipline**: parser confusion rewards reader inventory plus one member per attempt.
- **Reader inventory**: inventory the readers before crafting, because the disagreement is between components rather than inside one.
- **One member per attempt**: duplicate one member per attempt so the consuming reader is nameable.
- **Constant effect**: keep the effect identical across re-presentations, since a changed effect invalidates the comparison.
- **Re-baseline**: re-baseline after each pass, because a second control often reads the member the first one missed.
- **Sink confirmation**: confirm at the sink, because a control's silence is not the effect.

## Summary

Two components read one request and each consumes a different member. Parser confusion inventories the readers, duplicates one member per attempt, and claims the pass only when the sink's member is named.
