# Control Bypass Evaluation Order

This note holds the attempt order the family's mechanism-selection step follows, and the control kinds that order assumes.
The order is cheap-signal-first, because each attempt narrows the next one whether it passes or is refused.

## Fingerprint Before Craft

Read the control's own denial signal before shaping anything: the refusal status class, the block body, the challenge, the shared-edge marker, and any error class that differs from the sink's.
A signature matcher refuses the literal shape it lists; a behavioural or anomaly detector refuses a baseline deviation rather than a spelling; a policy engine refuses a route it did not enumerate; a counter refuses a rate rather than a shape.
The control kind decides the mechanism, so a mechanism chosen from the payload rather than from the control kind spends attempts on the wrong clause.
Where the denial signal carries the control's own identifying marker, the marker names the control kind before any craft.
Record the admission and the denial at the same input position, because a differential without both readings attributes to nothing.

## The Attempt Order

1. Control fingerprint: read the denial signal, the policy surface, and the tier that answered.
2. Encoding: one encode layer per attempt, because the checking side and the consuming side decode a different number of times.
3. Parser quirks: a second representation, member, or framing the checking side does not parse, because the two sides disagree on what a valid request is.
4. Protocol-level shape: a version, framing, or location the inspecting layer does not watch, because the guard covers one protocol reading.
5. Rule-specific gap: the unlisted route to the capability, because the rule set enumerates routes and every omission reaches the same effect.

The parser-quirk step is where most attempts end, because modern controls share the parser assumptions of the components they front and the disagreement survives there.

## Mechanism by Control Kind

| Control kind | What it evaluates | Mechanism the order selects |
|---|---|---|
| Signature matcher | A literal shape in the value | Spelling, separator, whitespace, token-boundary, and equivalent-operator variants |
| Normalising pipeline | The value after its own decode | A layered or folded form whose two readings differ |
| Request reader | One structural member of the request | A second member, representation, framing, verb, or location |
| Policy or permit engine | An enumerated route to a capability | A route the enumeration omits |
| Tier verdict | A decision held at one layer | A sibling route, a stored verdict, or the serving tier's scope |
| Counter or limiter | A counted dimension or unit | Spread across an uncounted lane, or collapse into one counted unit |

## Attempt Discipline

Change one variable per attempt and record the control's verdict before and after, so the admitting rule is named from the pair rather than from memory.
Re-probe after every pass, because a second control often sits behind the first and answers a shape the first one passed.
A refused attempt is still evidence: it narrows the rule set, the decode depth, or the member the control reads.
Keep the benign baseline fresh, because a control whose behaviour changed mid-run makes every later differential unattributable.
Stop at the narrowest proof that carries the effect, and record the refused original beside the passed shape.

## Freshness and the Live Path

A bypass shape's survival depends on the parser generation and the configuration in the live path, not on the shape's reputation.
Confirm the control's own normalisation before rule evaluation, because that behaviour localises the step where the two readings diverge.
Where the control's rule set grows between attempts, read the second refusal as a growth signal rather than as a dead end, and move to the next equivalent shape.
An absent control is recorded with the test that showed its absence, never as a defeat.
