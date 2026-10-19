---
name: defence-bypass-throttle-evasion
description: Throttle evasion where a limit counts one dimension and the effect moves in another, covering dimension gaps when a per-entity limit meets a multi-identity or multi-path effect, key canonicalisation when the counter keys a literal the backend folds, propagation gaps when a burst outruns the counter or the window, silent throttling when the limit answers while dropping the effect, and partial limits when the control throttles without ever blocking.
metadata:
  version: 1.0.0
---

# Throttle Evasion

A limit counts one dimension, and the effect can move in another. This variant reads the accounting rather than the rule: which dimension the counter observes, how long it takes to observe it, and whether the limit blocks or merely slows. The goal is the effect accumulating at a rate the counter never attributes to one principal, one path, or one window.

## Attack Surface

Throttle evasion applicability centers on a limit that stands between repeated attempts and the effect they accumulate.
The surface holds per-entity attempt counters, per-path and per-endpoint limits, windowed quotas, lockout thresholds, and challenge responses that gate further attempts.
A limit scoped to one dimension while the effect is reachable from several, and a counter that propagates slower than the effect accumulates, both widen the surface.
The operation's own field validation must be satisfied before a concurrent payload reaches the counting layer, because a request the operation rejects never reaches the counter.
A limit that blocks the first attempt rides outside this variant, because there is no second attempt to spread.

## Reconnaissance

Throttle evasion baselines the accounting before spreading, because a limit that never engaged cannot be evaded.
- Send a short burst of identical attempts and record whether the limit engages, how it answers, and after how many attempts.
- Classify the limit into one of four states before spreading: hard lockout, soft source throttle, challenge injection, or silent shadow-throttle, because an admit status alone does not mean no limit.
- Record the dimension the counter observes: a principal, a session, an address, a path, a connection, or a window.
- Record whether the counter keys the identifier's literal spelling or the canonical value the backend resolves, because the gap between the two is a counted-dimension gap.
- Probe each path to the effect separately, because enforcement often differs across paths.
- Note whether the limit blocks or only slows, and whether a challenge replaces the refusal after the threshold.

## Detection Channels

Throttle evasion listens to the counter beside the effect, so only the entries below are live here.
- The limit's refusal or challenge on a tight burst, which proves the accounting engaged.
- A pass for the same effect spread across identities, paths, or windows, which shows the counter observed a different dimension.
- The differential between the refused tight burst and the passed spread attempts at one effect, which localises the counted dimension.
- An attempt counter that does not move while the effect accumulates, which proves the accounting dimension is unwatched.
- A uniform admit answer while the known-good value stops being accepted, which is the silent-throttle signal.
- The delta between the rotated run and the un-rotated run, which is the proof of a source-field bypass rather than a fast run.
- The effect appearing at the sink while the limit's verdict stayed silent or slowed only.
- The sink's own error class, which separates a throttled attempt from a refused one.

## Adversarial Capabilities

Throttle evasion presupposes an accounting baseline plus multiple lanes plus repeatable attempts, and it consumes all three.
- Send a tight burst and a spread burst to the same effect, and read both answers.
- Hold more than one identity, session, address, or path where the limit is scoped to one of them.
- Time attempts against the window and the counter's propagation, because both decide whether an attempt is counted.
- Read the limit's answer shape, since a challenge and a refusal call for different spreads.

## Trust Assumptions

The limit trusts that the dimension it counts is the dimension the effect moves in, and that every lane reaches the counter before the next attempt.
The agreement holds the counter's scope to every route to the effect, holds the window to every lane that consumes it, and holds the answer to a refusal once the threshold is crossed.
This variant breaks the counted-dimension clause because the effect accumulates through a dimension the counter does not observe, so the limit reports a compliant rate while the effect grows.
The spread is claimed only against the recorded refusal of the tight burst, because an inactive limit proves nothing about its scope.

## Key Vulnerabilities

### Counted-Dimension Gaps

Spread the effect across the dimension the counter does not observe: several identities under a per-session limit, several paths under a per-endpoint limit, or several addresses under a per-client one.
Fold the identifier where the counter keys its literal spelling and the backend resolves the canonical value, because case, whitespace, encoding, and suffix variants each mint a fresh key for one entity.
Where the counter counts requests and the backend iterates one payload into several operations, the counting unit itself is the gap; name `defence-bypass-attempt-batching` at that step.
Probe each path to the effect separately, because enforcement often differs across the paths that reach one operation.
The parent accounting-baseline step covers one lane's answer and cannot describe one effect spread across lanes, so this variant owns the spread procedure.

### Propagation and Window Gaps

Fire inside the gap between an attempt and the counter that records it, because a counter that propagates late admits a burst.
Align attempts to the window's edges where the counter resets, so one effect consumes two windows.
Treat a spread that succeeds only at a window edge as window evidence rather than as a scope gap.

### Partial-Limit Gaps

Read whether the limit refuses or only slows, because a limit that throttles without blocking leaves the effect reachable at a lower rate.
Continue at the rate the limit admits and record the accumulated effect, since a partial limit is a delay rather than a control.
Treat a challenge that a single solved attempt clears as a partial limit, and record what the clearance costs.

## Bypass Techniques

Bypass shapes slip past a limit that is present, so each one is tried after the tight burst is refused.
- Identity, session, and address rotation under a per-entity counter.
- Path and endpoint rotation under a per-route counter.
- Bursts timed inside the counter's propagation gap.
- Identifier canonicalisation variants that mint a fresh key for one entity while the backend resolves the same value.
- Concurrent attempts inside a window whose rule counts outcomes within a time span rather than attempts at a rate.
- Attempts aligned to window edges so one effect consumes two windows.
- A batch envelope the counter counts once while the backend iterates it; name `defence-bypass-attempt-batching` at that step.
- Continued attempts at the rate a partial limit admits.

## Chaining Attacks

Throttle evasion chains forward into the class that owns the effect, because a spread attempt is only the first layer.
- Hand the spread to the class that owns the effect, and prove the class-specific consequence there.
- Stack with the tier gap where the counter sits at one tier and the effect is served at another.
- Stack with the race class at the concurrency step, since a spread burst and a concurrent burst reinforce each other.
- Name the class at its own step rather than restating its procedure here.

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

Stop when the limit refused every lane, because a controlled rate is not an evasion.

- A limit that refuses the effect across every identity, path, and window.
- A limit that never engaged, where no counter or threshold was observed at any rate.
- A spread whose effect never reached the sink, where the attempts passed and each request broke later.
- A challenge solved once, which is a clearance cost to record rather than a bypass.
- A simulator response that answers every attempt without accounting for it.

## Pro Tips

Throttle evasion rewards accounting discipline plus lane discipline.

1. Baseline the limit before spreading, because the counted dimension is the whole mechanism.
2. Spread one dimension per attempt so the uncounted lane is nameable.
3. Read the limit's answer shape, since a challenge and a refusal call for different spreads.
4. Keep the burst as narrow as the question allows, and record the rate at which the effect accumulates.
5. Hand the accumulation to the class that owns the effect, and stop at the narrowest proof.

## Summary

A limit counts one dimension and the effect moves in another. Throttle evasion baselines the accounting, spreads the effect across the uncounted lane, and claims the spread only against the recorded refusal of a tight burst.
