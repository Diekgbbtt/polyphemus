---
name: defence-bypass-attempt-batching
description: Attempt batching where a limit counts requests while the backend iterates a payload, covering array bodies when a list of values is tested in one counted request, alias sets when one operation envelope repeats a field under distinct names, multipart batches when inner operations ride an envelope the limiter does not parse, and fat requests when a body is consumed on a verb the counter treats as one read.
metadata:
  version: 1.0.0
---

# Attempt Batching

A limiter counts requests, and the backend executes whatever one request carries. This variant collapses many logical attempts into one counted unit: a payload the limiter reads once and the backend iterates, so the counter observes one attempt while the effect moves many. The goal is an attempt count the limiter never attributes to one principal, proved by the per-item effects of a single counted request.

## Attack Surface

- **Applicability**: centers on a limiter that counts requests in front of a backend that expands one request into several operations.
- **Surface composition**: array bodies where a list of values is tested in sequence, operation envelopes that accept several operations or repeat one field under distinct names, batch envelopes whose inner operations ride a multipart structure, and read-only requests whose body the backend still consumes.
- **Widening factors**: a backend that iterates every item of one payload, and an inspecting layer that parses the envelope's outer shape only, both widen the surface.
- **Out-of-scope variant**: a limiter that counts logical operations, or a backend that rejects a multi-item payload, rides outside this variant.

## Reconnaissance

- **Reconnaissance scope**: attempt batching reads the counting unit before crafting, because the mechanism is a unit mismatch rather than a rate.
- **Limiter baseline**: baseline the limiter with single-operation requests and record the threshold, the answer shape, and the counted dimension.
- **Carrier testing**: test one carrier at a time: an array body, a repeated field under distinct names, a multipart batch, and a body on a read-only verb.
- **Iteration record**: record whether the backend iterates the payload or rejects it, because the acceptance shape decides the carrier.
- **Per-item verdict**: read the response shape that returns a verdict per item, because a per-item verdict is the proof that every item executed.

## Detection Channels

- **Channel scope**: attempt batching listens to the counted request beside the per-item effects, so only the entries below are live here.
- **Per-item verdicts**: per-item verdicts returned inside one counted response, which proves the backend iterated the payload.
- **Counter movement**: several logical attempts executed while the attempt counter moved once, which proves the counting unit is the request.
- **Above-rate effect**: the effect reproduced above the configured rate from a single counted request.
- **Separate-request refusal**: the limiter's refusal for the same effect sent as separate requests, which establishes the unit gap by contrast.
- **Uncovered inner operation**: an inner operation executed while the inspecting layer's own verdict never covered it.
- **Uniform negative**: a negative that holds across every carrier, which reads as a backend that does not iterate payloads.

## Adversarial Capabilities

- **Prerequisites**: attempt batching presupposes carrier construction plus per-item distinguishable inputs plus a response read, and it consumes all three.
- **Carrier construction**: construct the carrier the backend accepts: a list body, a repeated field under distinct names, a batch envelope, or a body on a read-only verb.
- **Distinguishable items**: keep every item distinguishable, so each per-item verdict is attributable to its own input.
- **Per-item reading**: read the response per item rather than as one verdict, because the envelope answers once for many attempts.
- **Single-operation baseline**: hold the single-operation baseline, so the counted-unit gap is proved by contrast rather than asserted.

## Trust Assumptions

- **The agreement**: the limiter trusts that one counted request carries one logical attempt, and the backend trusts that every item of one payload is independently authorized and independently bounded, holds the counting unit to the operation, holds the envelope's items to one attempt each, and holds the inspecting layer to every operation the backend executes.
- **The failing clause**: this variant breaks the counting-unit clause because one request carries many operations, so the limiter reports a compliant request count while the effect moves at the item count.
- **Claim discipline**: the collapse is claimed only against the recorded refusal of the same effect sent as separate requests, because an unrefused baseline proves nothing about the unit.

## Key Vulnerabilities

### Carrier Families

- **Array body**: an array body where the backend tests each element in sequence while the limiter counts the request once.
- **Repeated field**: a repeated field under distinct names inside one operation envelope, so one request carries many attempts of one operation; name `graphql` at this step.
- **Batch envelope**: a batch envelope whose inner operations ride a multipart structure the inspecting layer does not parse.
- **Read-only-verb body**: a body carried on a read-only verb, where the backend still consumes the parameters the counter treats as one read.
- **Batching carriers**: see `references/batching-carriers.md` for the carrier catalogue and the per-carrier acceptance check.

### Counting-Unit Gap

- **Unit mismatch**: the counter observes requests and the effect moves in operations, so the admitted attempt count is the carrier's item count rather than the request count.
- **Highest item count**: prefer the carrier with the highest item count per counted request, because the amplification is the item count itself.
- **Amplification surface**: treat a carrier the backend expands into expensive per-item work as an amplification surface rather than as a brute enabler only.

### Guard Parity

- **Outer-shape parsing**: the inspecting layer parses the envelope's outer shape and not the inner operations, so each inner operation reaches the backend unexamined; name `proxy-techniques-channel-wrapping` at this step.
- **Count and parse comparison**: compare what each layer counts and what each layer parses, because a carrier can pass both a rate limiter and a request-shape filter at once.

## Bypass Techniques

- **Bypass scope**: bypass shapes slip past a limit that is present, so each one is tried after the single-operation baseline is refused.

- **List body**: a list body whose elements are tested in one counted request.
- **Repeated field**: a repeated field under distinct names inside one operation envelope.
- **Batch envelope**: a batch envelope of inner operations the limiter does not parse.
- **Read-only-verb body**: a body carried on a read-only verb whose parameters the backend still consumes.
- **Nested shape**: a nested or duplicate shape whose items the backend expands while the key counts the envelope once.

## Chaining Attacks

- **Chain scope**: attempt batching chains forward into the class that owns the effect, because a collapsed attempt set is only the first layer.
- **Outcome hand-off**: hand the admitted attempt set to the class that owns the outcome: `weak-credential-discovery` for the credential brute and `business-logic` for the value abuse.
- **Race pointer**: name `race-conditions` at its fan-out step, because one counted request that expands into several concurrent operations is the same carrier read as a timing primitive.
- **GraphQL pointer**: name `graphql` at its batching step where the envelope is an operation set.
- **Limit-class pointer**: name `rate-limit-bypass` at its counting-unit step, because the classification of the limit belongs to that class.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Attempt batching reads the counting unit first and the carrier second, because the mechanism is a unit mismatch.

1. **Baseline the limiter** - single-operation requests with the threshold, the answer shape, and the counted dimension recorded, and the step completes when the limiter's answer is recorded or its absence is recorded with the test that showed it.
2. **Enumerate the carriers** - every payload shape the operation accepts that can carry more than one item, and the step completes when each carrier carries an accepted or rejected verdict.
3. **Test the envelope** - send one carrier with distinguishable items and read the response shape, and the step completes when the per-item verdicts prove the backend iterated the payload.
4. **Measure the amplification** - the item count per counted request beside the single-operation threshold, and the step completes when the admitted attempt count is stated as a number.
5. **Confirm per-item effects** - one distinguishable effect per item, and the step completes when each executed item is attributable to its own input.
6. **Attribute the collapse** - pair the refused single-operation run with the admitted envelope, and the step completes when the counting unit is named from the pair.

## False Positives

- **Stop condition**: stop when the envelope executed once or the limiter counted the items, because neither is a collapse.

- **Rejected payload**: a backend that rejects or ignores a multi-item payload, confirmed across every carrier.
- **Per-item counting**: an envelope whose items are counted individually by the limiter, confirmed by a refusal at the same threshold.
- **Single-answer response**: a response that answers the envelope once with no per-item verdict, which proves nothing about iteration.
- **Rejected items**: an envelope whose items are all rejected by the operation itself, where the carrier passed and the attempts never executed.
- **Simulator answer**: a simulator response that answers the envelope without expanding it.

## Pro Tips

- **Discipline**: attempt batching rewards counting-unit discipline plus per-item attribution.
- **Unit reading**: read the counting unit before crafting, because the mechanism is a mismatch rather than a rate.
- **One carrier per attempt**: test one carrier at a time so the accepted envelope is nameable.
- **Distinguishable items**: keep every item distinguishable, since a shared response cannot attribute an item.
- **Highest item count**: prefer the carrier with the highest item count per counted request, because the amplification is the item count.
- **Proof pair**: pair the refused single-operation run with the admitted envelope, since the pair is the proof.
- **Effect hand-off**: hand the admitted set to the class that owns the effect, and stop at the narrowest proof.

## Summary

A limiter counts requests while the backend iterates what one request carries. Attempt batching reads the counting unit, finds the carrier the backend expands, and claims the collapse only when the per-item effects of one counted request are recorded against the refused single-operation baseline.
