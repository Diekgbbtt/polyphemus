---
name: defence-bypass-throttle-evasion
description: Throttle evasion where a limit counts one dimension and the effect moves in another, covering dimension gaps when a per-entity limit meets a multi-identity or multi-path effect, key canonicalisation when the counter keys a literal the backend folds, propagation gaps when a burst outruns the counter or the window, silent throttling when the limit answers while dropping the effect, and partial limits when the control throttles without ever blocking.
metadata:
  version: 1.0.0
---

# Throttle Evasion

A limit counts one dimension, and the effect can move in another. This variant reads the accounting rather than the rule: which dimension the counter observes, how long it takes to observe it, and whether the limit blocks or merely slows. The goal is the effect accumulating at a rate the counter never attributes to one principal, one path, or one window.

## Attack Surface

- **Applicability**: centers on a limit that stands between repeated attempts and the effect they accumulate.
- **Surface composition**: per-entity attempt counters, per-path and per-endpoint limits, windowed quotas, lockout thresholds, and challenge responses that gate further attempts.
- **Widening factors**: a limit scoped to one dimension while the effect is reachable from several, and a counter that propagates slower than the effect accumulates, both widen the surface.
- **Qualifying condition**: the operation's own field validation must be satisfied before a concurrent payload reaches the counting layer, because a request the operation rejects never reaches the counter.
- **Out-of-scope variant**: a limit that blocks the first attempt rides outside this variant, because there is no second attempt to spread.

## Reconnaissance

- **Reconnaissance scope**: throttle evasion baselines the accounting before spreading, because a limit that never engaged cannot be evaded.
- **Burst baseline**: send a short burst of identical attempts and record whether the limit engages, how it answers, and after how many attempts.
- **Limit classification**: classify the limit into one of four states before spreading: hard lockout, soft source throttle, challenge injection, or silent shadow-throttle, because an admit status alone does not mean no limit.
- **Counted dimension**: record the dimension the counter observes: a principal, a session, an address, a path, a connection, or a window.
- **Key literalness**: record whether the counter keys the identifier's literal spelling or the canonical value the backend resolves, because the gap between the two is a counted-dimension gap.
- **Per-path probing**: probe each path to the effect separately, because enforcement often differs across paths.
- **Block versus slow**: note whether the limit blocks or only slows, and whether a challenge replaces the refusal after the threshold.
- **Limit-state classifier**: see `references/rate-limit-state-classifier.md` for the four limit states and the shadow-throttle seed test.

## Detection Channels

- **Channel scope**: throttle evasion listens to the counter beside the effect, so only the entries below are live here.
- **Refusal or challenge**: the limit's refusal or challenge on a tight burst, which proves the accounting engaged.
- **Spread pass**: a pass for the same effect spread across identities, paths, or windows, which shows the counter observed a different dimension.
- **Dimension differential**: the differential between the refused tight burst and the passed spread attempts at one effect, which localises the counted dimension.
- **Unwatched accounting**: an attempt counter that does not move while the effect accumulates, which proves the accounting dimension is unwatched.
- **Silent-throttle signal**: a uniform admit answer while the known-good value stops being accepted, which is the silent-throttle signal.
- **Rotation delta**: the delta between the rotated run and the un-rotated run, which is the proof of a source-field bypass rather than a fast run.
- **Silent verdict**: the effect appearing at the sink while the limit's verdict stayed silent or slowed only.
- **Sink error class**: the sink's own error class, which separates a throttled attempt from a refused one.

## Adversarial Capabilities

- **Prerequisites**: throttle evasion presupposes an accounting baseline plus multiple lanes plus repeatable attempts, and it consumes all three.
- **Paired bursts**: send a tight burst and a spread burst to the same effect, and read both answers.
- **Lane inventory**: hold more than one identity, session, address, or path where the limit is scoped to one of them.
- **Timing control**: time attempts against the window and the counter's propagation, because both decide whether an attempt is counted.
- **Answer-shape reading**: read the limit's answer shape, since a challenge and a refusal call for different spreads.

## Trust Assumptions

- **The agreement**: the limit trusts that the dimension it counts is the dimension the effect moves in, and that every lane reaches the counter before the next attempt, holds the counter's scope to every route to the effect, holds the window to every lane that consumes it, and holds the answer to a refusal once the threshold is crossed.
- **The failing clause**: this variant breaks the counted-dimension clause because the effect accumulates through a dimension the counter does not observe, so the limit reports a compliant rate while the effect grows.
- **Claim discipline**: the spread is claimed only against the recorded refusal of the tight burst, because an inactive limit proves nothing about its scope.

## Key Vulnerabilities

### Counted-Dimension Gaps

- **Dimension spread**: spread the effect across the dimension the counter does not observe: several identities under a per-session limit, several paths under a per-endpoint limit, or several addresses under a per-client one.
- **Identifier folding**: fold the identifier where the counter keys its literal spelling and the backend resolves the canonical value, because case, whitespace, encoding, and suffix variants each mint a fresh key for one entity.
- **Counting unit**: where the counter counts requests and the backend iterates one payload into several operations, the counting unit itself is the gap; name `defence-bypass-attempt-batching` at that step.
- **Per-path probing**: probe each path to the effect separately, because enforcement often differs across the paths that reach one operation.
- **Ownership**: the parent accounting-baseline step covers one lane's answer and cannot describe one effect spread across lanes, so this variant owns the spread procedure.

### Propagation and Window Gaps

- **Propagation gap**: fire inside the gap between an attempt and the counter that records it, because a counter that propagates late admits a burst.
- **Window edges**: align attempts to the window's edges where the counter resets, so one effect consumes two windows.
- **Window evidence**: treat a spread that succeeds only at a window edge as window evidence rather than as a scope gap.

### Partial-Limit Gaps

- **Refuse versus slow**: read whether the limit refuses or only slows, because a limit that throttles without blocking leaves the effect reachable at a lower rate.
- **Admitted rate**: continue at the rate the limit admits and record the accumulated effect, since a partial limit is a delay rather than a control.
- **Clearance cost**: treat a challenge that a single solved attempt clears as a partial limit, and record what the clearance costs.

## Bypass Techniques

- **Bypass scope**: bypass shapes slip past a limit that is present, so each one is tried after the tight burst is refused.
- **Identity rotation**: identity, session, and address rotation under a per-entity counter.
- **Route rotation**: path and endpoint rotation under a per-route counter.
- **Propagation-gap bursts**: bursts timed inside the counter's propagation gap.
- **Key canonicalisation**: identifier canonicalisation variants that mint a fresh key for one entity while the backend resolves the same value.
- **Window concurrency**: concurrent attempts inside a window whose rule counts outcomes within a time span rather than attempts at a rate.
- **Window-edge alignment**: attempts aligned to window edges so one effect consumes two windows.
- **Batch envelope**: a batch envelope the counter counts once while the backend iterates it; name `defence-bypass-attempt-batching` at that step.
- **Partial-rate continuation**: continued attempts at the rate a partial limit admits.

## Chaining Attacks

- **Chain scope**: throttle evasion chains forward into the class that owns the effect, because a spread attempt is only the first layer.
- **Effect hand-off**: hand the spread to the class that owns the effect, and prove the class-specific consequence there.
- **Tier-gap stack**: stack with the tier gap where the counter sits at one tier and the effect is served at another.
- **Race stack**: stack with the race class at the concurrency step, since a spread burst and a concurrent burst reinforce each other.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Throttle evasion baselines the accounting first and spreads second, because an inactive limit is not an evasion.

1. **Baseline the limit** - a short burst of identical attempts with the answer, the threshold, and the counted dimension recorded, and the step completes when the limit's response is recorded or its absence is recorded with the test that showed it.
2. **Probe each path** - one attempt per route to the effect, and the step completes when each route carries an enforced or unenforced verdict.
3. **Enumerate the dimensions** - the lanes the counter could observe and the lanes the effect can use, and the step completes when the uncounted lane is named.
4. **Spread one dimension** - repeat the effect across the uncounted lane, and the step completes when the spread passes while the tight burst stays refused.
5. **Time the window and the counter** - attempt at the window edge and inside the propagation gap, one timing per attempt, and the step completes when the timing that admits the attempt is named.
6. **Measure the accumulation** - record the effect reached at the admitted rate, and the step completes when the accumulated effect is reproducible with a minimal attempt set.
7. **Attribute the spread** - pair the refused tight burst with the passed spread, and the step completes when the uncounted dimension is named from the pair.

## False Positives

- **Stop condition**: stop when the limit refused every lane, because a controlled rate is not an evasion.

- **Uniform refusal**: a limit that refuses the effect across every identity, path, and window.
- **Inactive limit**: a limit that never engaged, where no counter or threshold was observed at any rate.
- **Broken request**: a spread whose effect never reached the sink, where the attempts passed and each request broke later.
- **Clearance cost**: a challenge solved once, which is a clearance cost to record rather than a bypass.
- **Simulator answer**: a simulator response that answers every attempt without accounting for it.

## Pro Tips

- **Discipline**: throttle evasion rewards accounting discipline plus lane discipline.
- **Baseline first**: baseline the limit before spreading, because the counted dimension is the whole mechanism.
- **One dimension per attempt**: spread one dimension per attempt so the uncounted lane is nameable.
- **Answer-shape reading**: read the limit's answer shape, since a challenge and a refusal call for different spreads.
- **Narrow bursts**: keep the burst as narrow as the question allows, and record the rate at which the effect accumulates.
- **Effect hand-off**: hand the accumulation to the class that owns the effect, and stop at the narrowest proof.

## Summary

A limit counts one dimension and the effect moves in another. Throttle evasion baselines the accounting, spreads the effect across the uncounted lane, and claims the spread only against the recorded refusal of a tight burst.
