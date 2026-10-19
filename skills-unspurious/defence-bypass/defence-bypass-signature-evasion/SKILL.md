---
name: defence-bypass-signature-evasion
description: Signature evasion past a matcher's rule set, covering token splitting and separator substitutes when the list matches literal keywords, comment and whitespace insertion when the list matches contiguous shapes, equivalent operators when the list matches only the obvious spelling, and depth padding or alternate grammar forms when the matcher counts nesting or lists one element spelling.
metadata:
  version: 1.0.0
---

# Signature Evasion

A matcher that lists shapes is defeated by every equivalent shape the list omits. This variant steps around the rule set rather than the control itself: the same effect is expressed in a spelling, a token split, or an equivalent form the list does not carry. The goal is a passed probe that the control's own denial baseline frames as a bypass.

## Attack Surface

Signature evasion applicability centers on a matcher that inspects the caller's value as text before the value reaches the sink.
The surface holds keyword and signature lists, blocklists of names or tokens, delimiter-sensitive parsers in front of the effect, and normalising layers that decide which spelling the matcher sees.
A list that carries the obvious spelling only, and a matcher whose grammar the sink accepts more broadly than the list enumerates, both widen the surface.
A matcher that never inspects the caller's input rides outside this variant, because there is no rule set to step around.

## Reconnaissance

Signature evasion maps the rule set before crafting, because an uncharacterised matcher cannot be attributed.
- Establish the denial baseline: send the obvious spelling of the effect and record the control's refusal signal.
- Probe the list's breadth one axis at a time: casing, separators, whitespace, token boundaries, comments, and equivalent operators.
- Note which axis the matcher normalises and which it passes untouched, since the untouched axis is the bypass.
- Confirm the sink's acceptance separately from the control's answer, because a passed probe that the sink rejects is a broken request rather than a bypass.

## Detection Channels

Signature evasion listens to the matcher's rule set rather than to the sink's behaviour, so only the entries below are live here.
- The control's refusal signal on the obvious spelling, which proves the rule set engaged.
- A pass for the same effect in a second spelling, which shows the rule was stepped around rather than satisfied.
- The differential between the refused spelling and the passed spelling at one position, which localises the axis the list misses.
- The effect appearing at the sink while the refusal signal stays silent.
- A refusal for a spelling that passed moments earlier, which reads as a rule set growing between attempts rather than as a dead end.
- The sink's own error class, which separates a bypassed matcher from a request the sink itself rejected.

## Adversarial Capabilities

Signature evasion presupposes a denial baseline plus spelling control plus repeated attempts, and it consumes all three.
- Send the obvious spelling and the candidate spelling to the same position, and read both answers.
- Shape the value along one axis per attempt: casing, separator, whitespace, token boundary, comment, or equivalent operator.
- Repeat the attempt across the remaining axes after each pass, because a list often grows between attempts.
- Keep the effect identical across spellings, so the only changed variable is the spelling.

## Trust Assumptions

The control trusts that its rule set enumerates every spelling of the effect it means to prevent.
The agreement holds the list to the sink's accepted grammar, holds the matcher's normalisation to the sink's normalisation, and holds the effect to one canonical spelling at the sink.
This variant breaks the enumeration clause because the sink accepts a spelling the list does not carry, so the matcher reports a clean probe while the effect passes.
A pass is claimed only against the recorded refusal, because a spelling that was never denied proves nothing about the rule set.

## Key Vulnerabilities

### Token Boundary Gaps

Split a denied token into fragments the sink reassembles and the list does not match, because the matcher reads a contiguous literal.
Rejoin the fragments through a concatenation form the sink evaluates, and confirm the rejoin at the sink rather than at the matcher.
The parent craft step covers only one variable per attempt and cannot describe reassembly, so this variant owns the fragmentation procedure.
The reassembly set includes quote insertion inside the token and an evaluated substitution that emits the token at the sink, because the matcher reads the spelling while the sink reads the value.

### Separator and Whitespace Gaps

Substitute a separator, comment, or whitespace form that the sink treats as equivalent and the list treats as a distinct string.
Rotate the substitute family when one form is refused, because lists usually grow one literal at a time.
Treat a whitespace form that survives the matcher and parses at the sink as the completed probe.

### Equivalent Operator and Alias Gaps

Reach the same operation through a sibling operator, an alias, or a second name the list does not carry.
Prefer the alias whose effect is identical at the sink, so the bypass needs no second procedure behind it.
Treat a refused sibling as a rule-set growth signal rather than as a dead end, and move to the next equivalent form.
In a query or expression grammar, vary the operator's spelling, its case, and its encoding, and try an obscure sibling operator that reaches the same evaluation, because the rule set usually lists the obvious operator only.

### Depth-Counting and Grammar Gaps

Where the matcher counts depth or nesting, pad the value with segments the matcher decodes away so its count stays inside its bound while the sink's own depth leaves it.
Enumerate the grammar's alternate tags, handlers, and attribute forms where the matcher lists one spelling of an element, because each alternate reaches the same parse.
Keep the effect identical across the alternates, so a refused alternate is attributable to the rule set rather than to a broken request.

## Bypass Techniques

Bypass shapes slip past a matcher that is present, so each one is tried after the refusal baseline reports enforcement.
- Casing and encoding variants of one denied literal, because a list keys off exact spelling.
- Comment and whitespace insertion inside a denied shape, where the sink's parser ignores what the matcher reads.
- Token splitting with reassembly at the sink, where the matcher has no grammar to reassemble.
- Sibling operators and aliases for a denied name, where the list carries one spelling of the operation.
- Fragmenting a multi-part signature across request positions that the sink joins.
- The ordered axis sweep: casing, single encoding, double encoding, escape sequences, entity forms, and overlong forms, because the cheapest axis that admits the shape is the finding.
- A control-kind split: a rule-set gap is defined against a signature matcher, while a behavioural or anomaly detector calls for a baseline deviation rather than a new spelling.

## Chaining Attacks

Signature evasion chains forward into the class that owns the effect, because a passed matcher is only the first layer.
- Hand the passed shape to the class that owns the effect, and prove the class-specific consequence there.
- Stack with the encoding differential where the matcher's normalisation and the sink's decode disagree.
- Stack with the parser confusion where the matcher inspects a member the sink does not consume.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Signature evasion baselines the refusal first and crafts second, because a pass without a refusal is unattributable.

1. **Locate the matcher** - the layer that inspects the value and the value it inspects, and the step completes when the inspecting layer and the inspected position are both recorded.
2. **Baseline the refusal** - send the obvious spelling of the effect and record the control's answer, and the step completes when a refusal signal is recorded or the absence of a matcher is recorded with the test that showed it.
3. **Probe the axes** - casing, separators, whitespace, token boundaries, comments, and equivalent operators, one axis per attempt, and the step completes when every axis carries a passed or refused verdict.
4. **Craft the passed shape** - express the same effect in the spelling the list omits, and the step completes when the shape passes the matcher and the effect is reproducible at the sink.
5. **Confirm at the sink** - prove the effect rather than the pass, and the step completes when the sink's own output or state change carries the proof.
6. **Attribute the pass** - pair the refused baseline with the passed shape, and the step completes when the admitting axis is named from the pair.

## False Positives

Stop when the pass came from an absent or uninvolved matcher, because neither is a bypass.

- A matcher that is absent: record the absence with the test that showed it rather than a defeat.
- A refusal that came from the sink rather than the matcher, confirmed by the sink's own error class.
- A pass whose effect never reached the sink, where the shape passed the matcher and the request broke later.
- A cached or simulator response that replays a stored answer without evaluating the spelling.
- A list that grew between attempts, where the second spelling was refused after the first passed.

## Pro Tips

Signature evasion rewards axis discipline plus sink-side confirmation.

1. Probe one axis at a time so the admitting axis is nameable.
2. Keep the effect identical across spellings, since a changed effect invalidates the comparison.
3. Prefer the alias or sibling operator whose effect is identical, because it needs no second procedure.
4. Re-baseline after every pass, since lists often grow one literal at a time.
5. Confirm at the sink, because a matcher's silence is not the effect.

## Summary

A matcher lists shapes, and the sink accepts more shapes than the list carries. Signature evasion keeps the effect constant, moves one axis per attempt, and claims a pass only against the recorded refusal.
