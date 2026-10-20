---
name: rate-limit-bypass
description: Rate-limit bypass testing for the accounting between repeated attempts and the effect they accumulate, covering limit classification when an admit answer is not the absence of a limit, counted-dimension gaps when the effect moves in a lane the counter does not observe, and reachability adjudication when a brute claim needs the keyspace, throughput, and lifetime math.
metadata:
  version: 1.0.0
---

# Rate Limit Bypass

A rate limit is a control that counts attempts and refuses past a threshold, and it fails wherever its counting model and the effect's reach disagree.
This class owns the accounting itself: classify the limit before concluding, record the dimension the counter observes, and adjudicate what the admitted repetition actually reaches.
The bypass mechanics stay with the skills that own them: the spread across lanes is `defence-bypass-throttle-evasion`, the batch collapse is `defence-bypass-attempt-batching`, the counter race is `race-conditions`, and the carrier substitution is `proxy-techniques-channel-wrapping`.

## Attack Surface

- **Applicability**: an operation that admits repeated attempts and is expected to count them, from authentication and verification steps through recovery, invitation, coupon, and lookup surfaces.
- **Limit kinds**: fixed and sliding windows, token buckets, hard lockouts, challenge injection, and silent throttling that answers while dropping the effect.
- **Counted dimensions**: a principal, an identifier, a session, an address, a route, a connection, or a window.
- **Bypass surfaces**: source and identity fields the edge may trust, identifier spellings the counter keys literally, sibling routes and versions, and carriers the counting layer does not parse.
- **Delegated mechanics**: the spread, the collapse, the race, and the carrier each belong to the skill that owns them, and this class names them at their steps.

## Reconnaissance

### Limit Discovery

- **Operation inventory**: list every operation where repetition is meaningful, because each one carries its own limiter or none.
- **Advertised metadata**: read the limit, remaining, reset, and retry fields where the layer advertises them, and record their absence with the test that showed it.
- **Burst baseline**: send a short burst of identical attempts and record the full answer per attempt: status, body, latency, and whether the known-good effect still fires.

### Dimension Recording

- **Counted dimension**: record what the limit keys on beside what the effect varies in, because the gap between the two is the surface.
- **Key literalness**: record whether the counter keys the raw identifier or the canonical value the backend resolves.
- **Tier mapping**: record the tier that counts and the tier that serves, because a verdict at one tier and an effect at another is a tier gap.
- **Quiet states**: record the admit-while-dropping state, because the limit's silence is not the absence of a limit.

## Detection Channels

- **Refusal or challenge**: the limit's own answer on a tight burst, which proves the accounting engaged.
- **Pass across lanes**: the same effect admitted across identities, routes, versions, or windows, which proves the counted dimension is narrower than the effect.
- **Key canonicalisation**: a folded identifier admitted while the canonical spelling is refused, which proves the counter keys the literal string.
- **Admit-versus-effect divergence**: a uniform admit answer while the known-good value stops being accepted, which is the silent-throttle signal.
- **Counter non-atomicity**: a concurrent burst admitted above the configured rate, which proves the counter races.
- **Batch collapse**: one counted request carrying many logical attempts, which proves the counting unit is the request rather than the operation.
- **Quota metadata**: the limit, remaining, reset, and retry fields, which localise the window and the threshold.
- **Rotation delta**: the refusal returning when rotation stops, which is the proof of a source-field bypass rather than a fast run.

## Adversarial Capabilities

- **Attempt volume**: enough attempts to cross a threshold and read the answer, kept inside the narrowest burst the question needs.
- **Multiple lanes**: more than one identity, session, address, route, or version to compare.
- **Timing control**: the ability to place attempts at window edges and inside the counter's propagation gap.
- **A known-good value**: a value the effect accepts, so an admit answer is distinguished from a dropped effect.
- **A reachability model**: the keyspace, the observed throughput, and the artifact lifetime, so the claim is adjudicated rather than asserted.

## Trust Assumptions

- **The agreement**: the limiter trusts that the dimension it counts is the dimension the effect moves in, that its counter observes every attempt before the next one, that its key is the canonical identity of the thing it counts, that its counting unit is the operation, and that its answer reflects the effect.
- **The failing clause**: this class breaks the accounting agreement at whichever clause fails: the counted dimension, the propagation, the key canonicalisation, the counting unit, or the answer-to-effect correspondence.
- **Claim discipline**: a bypass is claimed only against a recorded refusal or a recorded throttle, because a limit that never engaged proves nothing about its scope.

## Key Vulnerabilities

### Limit Classification

- **Four states**: hard lockout, soft source throttle, challenge injection, and silent shadow-throttle, each calling for a different bypass and a different severity.
- **Admit is not absent**: an admit status without a refusal does not mean no limit, because the silent state drops the effect while answering.
- **Ownership**: the classification belongs to this class; the spread mechanics belong to the `defence-bypass` family.

### Counted-Dimension Gaps

- **Dimension mismatch**: the effect moves in a lane the counter does not observe: a second identity, a second address, a sibling route, a sibling version, or a carrier the counting layer does not parse.
- **Key canonicalisation**: the counter keys a literal spelling while the backend resolves the canonical entity, so case, whitespace, encoding, and suffix variants mint a fresh key for one entity.
- **Delegation**: the spread is `defence-bypass-throttle-evasion`, the carrier is `proxy-techniques-channel-wrapping`, the source-field trust is `proxy-techniques-relay-forwarding`, and the route or version divergence is `defence-bypass-edge-origin-differential`.

### Counting-Unit and Window Gaps

- **Counting unit**: a batch envelope carrying many logical operations counts once, so the counter observes one while the effect moves many; name `defence-bypass-attempt-batching` at this step.
- **Non-atomic counter**: a concurrent burst read-modify-writes the counter, so attempts above the configured rate pass; name `race-conditions` at this step.
- **Propagation and window**: a counter that records late or resets at a window edge admits a burst the configured rate would refuse.

### Reachability Adjudication

- **Keyspace and lifetime**: a brute claim needs the keyspace size, the observed throughput, and the artifact lifetime, because the reachable attempt count is throughput times lifetime.
- **Predictability**: where the artifact is predictable or its lifetime unbounded, the reachability collapses; name `weak-credential-discovery` and `crypto-weakness` at their steps.
- **Impact hand-off**: the reached outcome belongs to the consuming class, and a limit gap with no reachable outcome is informational rather than a finding.

## Advanced Techniques

- **Admit-versus-effect seed**: place a known-good value at a known position inside the burst, so the silent state is detected rather than misread as an open endpoint.
- **Rotation delta**: prove a source-field or identity bypass by re-running without rotation and showing the refusal returns, because the delta is the proof.
- **Window-edge alignment**: consume two windows with one logical effect where the counter resets at a fixed boundary.
- **Quiet pacing**: continue at the rate a partial limit admits, because a partial limit is a delay rather than a control.

## Bypass Techniques

- **Bypass scope**: bypass shapes are tried only after the burst baseline records a refusal, a challenge, or a throttle.
- **Spread**: move the effect across a lane the counter does not observe, one lane per attempt; name `defence-bypass-throttle-evasion` at this step.
- **Collapse**: carry many logical attempts in one counted request; name `defence-bypass-attempt-batching` at this step.
- **Canonicalise**: fold the identifier so the counter mints a fresh key for the same entity.
- **Race**: outrun the counter's read-modify-write with a concurrent burst; name `race-conditions` at this step.
- **Carry**: re-present the attempt through a carrier the counting layer does not parse; name `proxy-techniques-channel-wrapping` at this step.
- **Re-route**: reach the same operation through a sibling route or version the limit never covered; name `defence-bypass-edge-origin-differential` at this step.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chaining scope**: a bypassed limit is a mechanism rather than a finding, so the admitted repetition hands forward to the class that owns the outcome.
- **Credential layer**: `weak-credential-discovery` for the credential and token brute, and `crypto-weakness` where the artifact's entropy is the failing clause.
- **Auth-adjacent flows**: `mfa-bypass` where the repeated operation is the second-factor verification step, and `account-recovery` where it is the recovery step.
- **Counter race**: `race-conditions` at the non-atomic counter step.
- **Logic layer**: `business-logic` where the repetition abuses a value, a quota, or a coupon.
- **Enforcement tier**: `defence-bypass-edge-origin-differential` where the limit exists at one tier and the effect is served at another.

## Testing Methodology

Rate-limit work classifies the limit first and adjudicates the reach second, because an admit answer and an open endpoint are not the same finding.

1. **Inventory the limited operations** - every operation where repetition is meaningful, and the step completes when each operation carries the expected limit.
2. **Baseline the burst** - a short burst of identical attempts with status, body, latency, and known-good effect recorded per attempt, and the step completes when the answer is classified into one of the four states or the limit's absence is recorded with the test that showed it.
3. **Record the counted dimension** - the key, the window, and the tier the counter observes, and the step completes when the dimension and the canonicalisation rule are both named.
4. **Test the key** - fold the identifier one way per attempt and record which spellings mint a fresh key, and the step completes when the canonicalisation gap is named or refused.
5. **Test the lanes** - spread one dimension per attempt across identities, routes, versions, and carriers, and the step completes when the lane the counter ignores is named.
6. **Test the unit and the window** - a batch envelope, a concurrent burst, and window-edge attempts, and the step completes when the counting unit and the window boundary are both recorded.
7. **Adjudicate reachability** - the keyspace, the throughput, and the artifact lifetime with the reachable attempt count, and the step completes when the claim is bounded by the math rather than by the probe.
8. **Attribute and stop** - separate a limit bypass from an absent limit and from a class-specific gap, and the step completes when the narrowest proof carries its attribution.

## False Positives

- **Stop condition**: stop when the limit held, never engaged, or the admitted repetition reaches nothing, because none of the three is a bypass.
- **Absent limit**: no counter, threshold, or answer change at any rate, recorded with the test that showed it.
- **Genuine enforcement**: a refusal or challenge that holds across every lane, key spelling, unit, and window.
- **Broken request**: attempts that pass the limit and never reach the effect, where the request failed later.
- **Client-side-only pacing**: a client-enforced delay with no server-side counter, which is a control gap to report rather than a bypass.
- **Lockout misread as throttle**: a lockout that also refuses the correct value is a denial-of-service surface rather than a brute enabler.
- **Replay or simulator**: a response that answers attempts without accounting for them.
- **Reachability gap**: an admitted repetition whose keyspace and lifetime make the outcome unreachable, so the claim stays informational until the math holds.

## Pro Tips

- **Discipline**: rate-limit work rewards classification plus key reading plus the reachability math.
- **Classify first**: classify before concluding, because the silent state is the one that false-negatives the finding.
- **Literal key**: read the key literally, since the canonicalisation gap is often the whole bypass.
- **Delta proof**: prove with the delta: the rotated run beside the un-rotated run, not one fast run.
- **Bounded volume**: stay inside the question, because volume spends attempts and raises the control's sensitivity.
- **Math first**: do the math before the claim, since throughput times lifetime is the severity argument.
- **Delegated naming**: name the owning skill at each delegated step rather than restating its procedure.

## Summary

A limit counts attempts, and it fails wherever its counting model and the effect's reach disagree. Rate-limit bypass classifies the limit before concluding, records the counted dimension, the key, the unit, and the window, and adjudicates the outcome with the keyspace, the throughput, and the artifact lifetime before handing the class its step.
