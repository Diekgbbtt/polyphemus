---
name: defence-bypass
description: Defence bypass testing for the control between the caller's input and the effect, covering matcher gaps when a filter lists shapes, decode disagreements when a pipeline normalises the value, structural re-reading when a component reads one member, permit enumeration gaps when a policy lists what may run, tier gaps when one layer holds the verdict, and accounting gaps when a limit counts one dimension or one request unit.
metadata:
  version: 1.0.0
---

# Defence Bypass

A control is defeated by finding the value, the route, or the attempt it does not evaluate. This family owns the control-agnostic bypass mechanics every class draws on: a matcher that lists shapes, a pipeline that decodes, a component that reads one member of a request, a permit that enumerates, a tier that holds a verdict, and a limit that counts. Each consuming class keeps its own exploit detail and names this family at its bypass step.

## Attack Surface

Bypass applicability centers on a control that stands between the caller's input and the effect, at any layer of the path.

**Input Matchers**
- Filters, blocklists, and keyword or signature matchers that inspect the caller's value as text before it reaches the sink
- Normalising layers in front of a matcher, which decide which spelling the matcher actually sees

**Decoding Pipelines**
- Components that decode, re-encode, or normalise a value between the check and the sink
- Multi-hop paths where each hop decodes a different number of times

**Request Readers**
- Components that read one structural member of a request: the framing declaration, the content type, the verb, the route, or the first occurrence of a duplicated member
- Tiers that re-frame a request in transit, so the emitted request no longer matches the received one

**Permission Sets**
- Policies that enumerate what may execute, what may be read cross-origin, what may run inside a confinement, or which elements and attributes survive sanitising
- Allowlists of names, extensions, operators, delegates, and capabilities

**Enforcement Tiers**
- The edge, gateway, middleware, or cache tier that holds a verdict the serving tier does not recompute
- Legacy and alternate routes that reach the same effect outside the current chain

**Accounting Limits**
- Rate limits, throttles, quotas, attempt thresholds, and lockout counters
- Limits scoped to one dimension: a principal, a window, a path, a connection, or a counter that propagates late

## Reconnaissance

Bypass work starts at the control, because a defeat claimed without the control's verdict is a story rather than a result.

### Control Inventory

- Enumerate every control between the caller's input and the effect, layer by layer, and record which layer evaluates which value
- Read the control's own policy surface: which directives are present, which values they permit, and which are missing
- Note where a control is absent, and record the absence with the test that showed it, phrased as an observed gap rather than a certainty

### Control Fingerprinting

- Fingerprint each control from its own signals: refusal bodies and status classes, challenge responses, shared-edge markers, added latency on a rejected request, and error classes that differ from the sink's
- Record the control's own identifying marker in its denial signal, because the marker names the control kind before any craft
- Identify the control kind from its behaviour: a matcher over literal shapes, a normalising pipeline, a behavioural detector, or a policy engine, because the mechanism follows the control rather than the payload
- Establish the oracle: a benign request the control admits and a hostile request it denies at the same position, so a later differential attributes to the control rather than to the sink
- Map the tier: read one request at the enforcing layer and at the serving layer, and record which layer answered

### Accounting Baseline

- Send a short burst of identical requests and read whether a limit engages, how it answers, and after how many attempts
- Record the dimension the limit counts beside the dimension the effect moves in, because a gap between the two is the throttle surface
- Treat a limit that throttles without blocking as a partial control, and keep the burst inside the narrowest window that answers the question

## Detection Channels

The family listens to the control's own verdict beside the sink's effect, so every entry below is live wherever a control sits.

- The control's denial signal on a probe: a refusal status, a block body, a challenge, or a sanitised response, which proves the control evaluated the input.
- The control's own identifying marker inside that denial signal, which fingerprints the control kind rather than the sink.
- A pass after a denial for the same effect, which shows the rule was stepped around rather than satisfied.
- The effect appearing at the sink while the control's verdict stayed silent, which is the primary bypass signal.
- A differential between the denied shape and the passed shape at one input position, which localises the rule the control applies.
- A second tier's verdict differing from the first tier's for one request, which proves a tier gap.
- A stale or cached verdict applied to a changed request, which proves the verdict was not recomputed.
- An attempt counter that does not move while the effect accumulates, which proves the accounting dimension is unwatched.
- A permitted route to a capability the policy claimed to prevent, which proves the permit enumeration was incomplete.
- The same request read as two different values by two components, which proves a structural disagreement.
- The sink's own error class or output shape, which separates a bypassed control from a broken request.

## Adversarial Capabilities

Bypass testing presupposes a control oracle plus request-shaping freedom plus repeatable attempts, and it consumes all three.

- Send a benign probe and a hostile probe to the same position, and read both verdicts before any claim.
- Observe the control's signals and the sink's effect separately, so a denial attributes to the layer that gave it.
- Shape the value's spelling, the request's structure, the verb, the route, and the carrier the request travels in.
- Reach more than one tier or route for the same effect, so the verdicts can be compared.
- Repeat attempts inside the accounting window, from more than one identity where the limit is per-entity.
- Keep a current benign baseline, so a change in the control's behaviour stays attributable.
- Hold out-of-band confirmation for effects that return no body.

## Trust Assumptions

Every control rests on one agreement: it stands between the caller's input and the effect, and it evaluates the same value, in the same reading, against the same rule, at the same tier, on every attempt, before the effect consumes it.
The agreement holds the control's reading of a value to the sink's reading, holds the rule set to every spelling of the effect, holds the permit to every route to the capability, holds the verdict to the tier that serves the effect, and holds the accounting to every dimension the effect can move in and to the unit it counts.
Each variant breaks one clause: the reading clause, the enumeration clause, the permit clause, the tier clause, or the accounting clause.
Sensitive effects leak when a clause fails, because the control then reports a verdict on a request the sink never consumed in that shape.

## Key Vulnerabilities

### Matcher Gaps

- A matcher keys off literal shapes: keywords, tokens, delimiters, signatures. Every equivalent shape the rule set omits passes it.
- Alternate spellings, token boundaries, separator substitutes, comment insertion, and equivalent operators reach the same effect unlisted.

### Decode Disagreement

- The checking side and the consuming side decode one value a different number of times, or in a different order, so each reads a different value.
- Layered, overlong, nested, and separator-equivalent forms land differently on the two sides of the decode.

### Structural Reading Differences

- A component reads one member of a request while the sink reads another: the framing declaration, the content type, the verb, the route, or the first of a duplicated pair.
- Re-framing in transit emits a request whose members no longer match the ones the control approved.

### Permit Enumeration Gaps

- A permit enumerates routes to a capability, and every route outside the enumeration reaches the same capability: an allowed element that combines into a gadget, an alias for a filtered name, an indirection to a denied attribute, a delegate that reaches the same operation.
- The gap is the enumeration rather than the rule, because the policy meant to prevent the effect and the route it forgot delivers it.

### Tier Gaps

- The control is enforced at one tier and the effect is served at another: edge versus core, gateway versus service, the current chain versus a legacy route, a stored verdict versus a live check.
- A tier that reuses a verdict across a changed request serves an effect the enforcing tier would have denied.

### Accounting Gaps

- A limit counts one dimension while the effect is reachable through another: a principal, a window, a path, a connection, or a counter that propagates late.
- A limit that throttles without blocking, and a window that resets per lane, both leave the effect reachable at a lower rate.

## Advanced Techniques

**Tier Mapping Before Crafting**
- Determine which tier decides and which tier serves before shaping anything, because the mechanism follows the gap.

**Mechanism Order**
- Order the attempts from the cheapest signal to the most specific: the control's fingerprint, then its decoding, then the protocol-level shape, then the parser quirk, then the rule-specific gap, because each step narrows the next one.

**One Variable Per Attempt**
- Change one thing per attempt and record the control's verdict on both sides, so the admitting rule is attributable.

**Stacked Controls**
- Re-probe after every layer, because a second control often sits behind the first and answers a shape the first one passed.

**Attribution Discipline**
- Separate a bypassed control from an absent control, from a sink fault, and from a class-specific gap, and name which one the evidence supports.

## Bypass Techniques

Bypass shapes slip past a control that is present, so each one is tried after the baseline verdict reports enforcement.

- Spelling and case variants of the same value, because a matcher's rule set is finite.
- Encoding layering, where the checking side decodes a different number of times than the consuming side.
- Structural re-reading: the same effect expressed through a second member, framing, verb, or route.
- Permit probing: an unlisted route to the capability the policy meant to prevent.
- Tier comparison: one request sent against the enforcing tier and the serving tier.
- Accounting spread: the same effect moved across the dimension the limit counts.
- Accounting collapse: many logical attempts carried in one counted request, where the limit counts the request and the backend iterates the payload.
- Ordered escalation: fingerprint the control, then its decoding, then the protocol-level shape, then the parser quirk, then the rule-specific gap, because a failed attempt still narrows the next one.

## Chaining Attacks

A bypass is a mechanism rather than a finding, so the defeated control hands forward to the class that owns the effect.

- Hand the defeated control to the class that owns the effect, and prove the class-specific consequence there.
- Name the class at its own step rather than restating it: `rce` at its filter step, `xss` at its generic bypass, `idor` at its parser step, and `race-conditions` at its edge-versus-core step.
- Chain the layers, because each defeated control becomes the baseline for the next one on the path.
- Hand a bypass that opens a second surface to the class that consumes that surface.
- Keep a control whose rule was only revealed as reconnaissance for the class rather than as a finding.

## Testing Methodology

Bypass work runs the control first and the effect second, because an unattributed differential proves nothing.

1. **Inventory the controls** - every control between the caller's input and the effect, layer by layer, and the step completes when every layer names the value it evaluates.
2. **Fingerprint each control** - its signals, its policy surface, and its answer to a benign probe, and the step completes when an admission and a denial are both recorded at the same position.
3. **Establish the oracle** - a known-denied probe and a known-admitted control, and the step completes when a differential attributes to the control rather than to the sink.
4. **Map the tier** - which tier decides and which tier serves, and the step completes when one verdict is read at both tiers.
5. **Baseline the accounting** - a short burst against the limit, and the step completes when the limit's response, threshold, and counted dimension are recorded, or its absence is recorded with the test that showed it.
6. **Select the mechanism** - the mechanism the control's kind admits, ordered from fingerprint to decoding to protocol to parser quirk to rule-specific gap, and the step completes when the selection names the clause it breaks and the order the attempts follow.
7. **Craft one variable** - one shape change per attempt with the control's verdict recorded before and after, and the step completes when the attempt carries its verdict pair.
8. **Confirm the effect at the sink** - the smallest effect that proves the input arrived in a shape the control did not evaluate, and the step completes when the effect reproduces and the control's post-state is recorded.
9. **Attribute and stop** - separate the bypass from an absent control and from a class-specific gap, and the step completes when the narrowest proof carries its attribution and the refused original beside the passed shape is recorded as the proof pair.

## Variants

- defence-bypass-signature-evasion - Step around a matcher's rule set by expressing the same effect in a spelling, token split, or equivalent form the list omits.
- defence-bypass-encoding-differential - Exploit a decode-count or normalisation disagreement between the checking side and the consuming side of one value.
- defence-bypass-parser-confusion - Make two readers of one request disagree, so the control evaluates a member the sink never consumes.
- defence-bypass-allowance-gap - Reach a capability through a route the permit, policy, or confinement enumeration omits.
- defence-bypass-edge-origin-differential - Compare the enforcing tier's verdict with the serving tier's, and reach the effect where the verdict is not recomputed.
- defence-bypass-throttle-evasion - Move the effect across the dimension a limit does not count, inside the window the limit watches.
- defence-bypass-attempt-batching - Collapse many logical attempts into one counted request, so the limit counts the request while the backend iterates the payload.

## False Positives

Stop when the evidence shows the control held or never engaged, because neither is a bypass.

- A control that is absent: record the absence with the test that showed it rather than a defeat.
- A control that never evaluated the input, such as a client-side check or a probe the rule set does not inspect.
- A denial that came from the sink rather than from the control, confirmed by the sink's own error class.
- A cached, stale, or simulator response that replays a stored verdict without evaluating the attempt.
- A probe shape denied while the effect passes: the control evaluated the probe, not the effect.
- A class-specific gap misread as a control defeat, where the class's own procedure owns the failure.
- An effect that never reached the sink, where the shape passed the control and the request broke later.

## Pro Tips

Bypass work rewards verdict discipline plus one-variable attempts plus minimal craft.

1. Record the control's verdict before and after every attempt, because a claim without the pair is not attributable.
2. Change one variable at a time so the admitting rule can be named from the evidence.
3. Prefer the smallest shape change that passes, since heavy craft spends attempts and raises the control's sensitivity.
4. Re-probe after each layer, because a second control often answers a shape the first one passed.
5. Read the control's own policy surface first; a missing directive is a gap rather than a bypass.
6. Hand the effect to the class that owns it, and stop at the narrowest proof.
7. Keep the benign baseline fresh so a change in the control's behaviour stays attributable.

## Summary

A control reports a verdict on the value it evaluates, and every gap between that value and the one the sink consumes is a bypass. This family maps the control, selects the mechanism its kind admits, and confirms the effect at the sink before handing the class its step.
