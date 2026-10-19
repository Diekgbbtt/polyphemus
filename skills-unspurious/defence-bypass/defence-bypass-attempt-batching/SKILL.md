---
name: defence-bypass-attempt-batching
description: Attempt batching where a limit counts requests while the backend iterates a payload, covering array bodies when a list of values is tested in one counted request, alias sets when one operation envelope repeats a field under distinct names, multipart batches when inner operations ride an envelope the limiter does not parse, and fat requests when a body is consumed on a verb the counter treats as one read.
metadata:
  version: '1.0.0'
---

# Attempt Batching

A limiter counts requests, and the backend executes whatever one request carries. This variant collapses many logical attempts into one counted unit: a payload the limiter reads once and the backend iterates, so the counter observes one attempt while the effect moves many. The goal is an attempt count the limiter never attributes to one principal, proved by the per-item effects of a single counted request.

## Attack Surface

Attempt batching applicability centers on a limiter that counts requests in front of a backend that expands one request into several operations.
The surface holds array bodies where a list of values is tested in sequence, operation envelopes that accept several operations or repeat one field under distinct names, batch envelopes whose inner operations ride a multipart structure, and read-only requests whose body the backend still consumes.
A backend that iterates every item of one payload, and an inspecting layer that parses the envelope's outer shape only, both widen the surface.
A limiter that counts logical operations, or a backend that rejects a multi-item payload, rides outside this variant.

## Reconnaissance

Attempt batching reads the counting unit before crafting, because the mechanism is a unit mismatch rather than a rate.
- Baseline the limiter with single-operation requests and record the threshold, the answer shape, and the counted dimension.
- Test one carrier at a time: an array body, a repeated field under distinct names, a multipart batch, and a body on a read-only verb.
- Record whether the backend iterates the payload or rejects it, because the acceptance shape decides the carrier.
- Read the response shape that returns a verdict per item, because a per-item verdict is the proof that every item executed.

## Detection Channels

Attempt batching listens to the counted request beside the per-item effects, so only the entries below are live here.
- Per-item verdicts returned inside one counted response, which proves the backend iterated the payload.
- Several logical attempts executed while the attempt counter moved once, which proves the counting unit is the request.
- The effect reproduced above the configured rate from a single counted request.
- The limiter's refusal for the same effect sent as separate requests, which establishes the unit gap by contrast.
- An inner operation executed while the inspecting layer's own verdict never covered it.
- A negative that holds across every carrier, which reads as a backend that does not iterate payloads.

## Adversarial Capabilities

Attempt batching presupposes carrier construction plus per-item distinguishable inputs plus a response read, and it consumes all three.
- Construct the carrier the backend accepts: a list body, a repeated field under distinct names, a batch envelope, or a body on a read-only verb.
- Keep every item distinguishable, so each per-item verdict is attributable to its own input.
- Read the response per item rather than as one verdict, because the envelope answers once for many attempts.
- Hold the single-operation baseline, so the counted-unit gap is proved by contrast rather than asserted.

## Trust Assumptions

The limiter trusts that one counted request carries one logical attempt, and the backend trusts that every item of one payload is independently authorized and independently bounded.
The agreement holds the counting unit to the operation, holds the envelope's items to one attempt each, and holds the inspecting layer to every operation the backend executes.
This variant breaks the counting-unit clause because one request carries many operations, so the limiter reports a compliant request count while the effect moves at the item count.
The collapse is claimed only against the recorded refusal of the same effect sent as separate requests, because an unrefused baseline proves nothing about the unit.

## Key Vulnerabilities

### Carrier Families

- An array body where the backend tests each element in sequence while the limiter counts the request once.
- A repeated field under distinct names inside one operation envelope, so one request carries many attempts of one operation; name `graphql` at this step.
- A batch envelope whose inner operations ride a multipart structure the inspecting layer does not parse.
- A body carried on a read-only verb, where the backend still consumes the parameters the counter treats as one read.

### Counting-Unit Gap

- The counter observes requests and the effect moves in operations, so the admitted attempt count is the carrier's item count rather than the request count.
- Prefer the carrier with the highest item count per counted request, because the amplification is the item count itself.
- Treat a carrier the backend expands into expensive per-item work as an amplification surface rather than as a brute enabler only.

### Guard Parity

- The inspecting layer parses the envelope's outer shape and not the inner operations, so each inner operation reaches the backend unexamined; name `proxy-techniques-channel-wrapping` at this step.
- Compare what each layer counts and what each layer parses, because a carrier can pass both a rate limiter and a request-shape filter at once.

## Bypass Techniques

Bypass shapes slip past a limit that is present, so each one is tried after the single-operation baseline is refused.

- A list body whose elements are tested in one counted request.
- A repeated field under distinct names inside one operation envelope.
- A batch envelope of inner operations the limiter does not parse.
- A body carried on a read-only verb whose parameters the backend still consumes.
- A nested or duplicate shape whose items the backend expands while the key counts the envelope once.

## Chaining Attacks

Attempt batching chains forward into the class that owns the effect, because a collapsed attempt set is only the first layer.
- Hand the admitted attempt set to the class that owns the outcome: `weak-credential-discovery` for the credential brute and `business-logic` for the value abuse.
- Name `race-conditions` at its fan-out step, because one counted request that expands into several concurrent operations is the same carrier read as a timing primitive.
- Name `graphql` at its batching step where the envelope is an operation set.
- Name `rate-limit-bypass` at its counting-unit step, because the classification of the limit belongs to that class.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Attempt batching reads the counting unit first and the carrier second, because the mechanism is a unit mismatch.

1. **Baseline the limiter** - single-operation requests with the threshold, the answer shape, and the counted dimension recorded, and the step completes when the limiter's answer is recorded or its absence is recorded with the test that showed it.
2. **Enumerate the carriers** - every payload shape the operation accepts that can carry more than one item, and the step completes when each carrier carries an accepted or rejected verdict.
3. **Test the envelope** - send one carrier with distinguishable items and read the response shape, and the step completes when the per-item verdicts prove the backend iterated the payload.
4. **Measure the amplification** - the item count per counted request beside the single-operation threshold, and the step completes when the admitted attempt count is stated as a number.
5. **Confirm per-item effects** - one distinguishable effect per item, and the step completes when each executed item is attributable to its own input.
6. **Attribute the collapse** - pair the refused single-operation run with the admitted envelope, and the step completes when the counting unit is named from the pair.

## False Positives

Stop when the envelope executed once or the limiter counted the items, because neither is a collapse.

- A backend that rejects or ignores a multi-item payload, confirmed across every carrier.
- An envelope whose items are counted individually by the limiter, confirmed by a refusal at the same threshold.
- A response that answers the envelope once with no per-item verdict, which proves nothing about iteration.
- An envelope whose items are all rejected by the operation itself, where the carrier passed and the attempts never executed.
- A simulator response that answers the envelope without expanding it.

## Pro Tips

Attempt batching rewards counting-unit discipline plus per-item attribution.

1. Read the counting unit before crafting, because the mechanism is a mismatch rather than a rate.
2. Test one carrier at a time so the accepted envelope is nameable.
3. Keep every item distinguishable, since a shared response cannot attribute an item.
4. Prefer the carrier with the highest item count per counted request, because the amplification is the item count.
5. Pair the refused single-operation run with the admitted envelope, since the pair is the proof.
6. Hand the admitted set to the class that owns the effect, and stop at the narrowest proof.

## Summary

A limiter counts requests while the backend iterates what one request carries. Attempt batching reads the counting unit, finds the carrier the backend expands, and claims the collapse only when the per-item effects of one counted request are recorded against the refused single-operation baseline.
