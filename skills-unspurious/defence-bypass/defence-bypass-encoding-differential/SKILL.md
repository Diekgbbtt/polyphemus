---
name: defence-bypass-encoding-differential
description: Encoding differential bypass between the checking side and the consuming side of one value, covering decode-count gaps when each hop decodes a different number of times, folding gaps when normalisation maps two spellings onto one value, and truncation or padding forms when the accepting side tolerates a shortened value.
metadata:
  version: 1.0.0
---

# Encoding Differential

A control that decodes a value evaluates the value it decoded, and the sink consumes the one it decodes. This variant finds the form that reads as benign on the checking side and as hostile on the consuming side, or the reverse, by counting the decodes on each side of the path. The goal is a value whose two readings differ, confirmed by the sink effect.

## Attack Surface

Encoding differential applicability centers on a value that is decoded, normalised, or re-encoded between the check and the sink.
The surface holds layered encoding forms, overlong and width-variant spellings, case-folding and normalisation steps, and value families where the accepting side tolerates padding or truncation.
Multi-hop paths where each hop decodes a different number of times, and comparisons that normalise one side only, both widen the surface.
A value that one component reads once and no later component re-reads rides outside this variant, because there is no second decode to disagree with.

## Reconnaissance

Encoding differentials are counted rather than guessed, because the differential lives in the decode steps of the path.
- Trace the value through every hop and record how many times each hop decodes it.
- Establish the refusal baseline with the plainly decoded hostile value, so a later pass is attributable to the decode difference.
- Probe one encoding layer at a time and note which hop reads the layered form as data and which reads it as syntax.
- Record the folding behaviour of both sides: casing, width variants, and normalisation steps that map two spellings onto one value.

## Detection Channels

Encoding differentials listen to the two readings of one value, so only the entries below are live here.
- The control's refusal on the plainly decoded value, which proves the comparison engaged.
- A pass for the same effect in a layered or folded form, which shows the two sides decoded the value differently.
- The differential between the refused plain form and the passed encoded form at one position, which localises the decode step.
- The effect appearing at the sink in the hostile reading while the control's verdict reports the benign one.
- The sink's own error class or decoded output, which names the reading the sink actually consumed.

## Adversarial Capabilities

Encoding differentials presuppose decode-count knowledge plus layer control plus a repeatable baseline, and they consume all three.
- Send the plain hostile value and the layered candidate to the same position, and read both answers.
- Layer one encoding step per attempt, and record the layer at which the readings diverge.
- Shape folding variants of the same value: casing, width, and normalisation equivalents.
- Hold a tolerant-value form for accepting sides that pad, truncate, or normalise before comparing.

## Trust Assumptions

The control trusts that the value it evaluates is the value the sink consumes.
The agreement holds the decode count constant across the path, holds both sides to one folding rule, and holds the accepted value to the exact bytes the comparison approved.
This variant breaks the decode-count clause because the checking side and the consuming side decode the same bytes a different number of times, so each reads a different value.
The differential is claimed only when both readings are recorded, because one reading alone cannot show a disagreement.

## Key Vulnerabilities

### Decode-Count Gaps

Find the hop count at which the layered form reads as data on one side and as syntax on the other, because each decode step moves the boundary.
Layer one encoding step per attempt and stop at the step where the effect appears, since further layers usually only re-encode the value.
The parent oracle step covers a single reading of the value and cannot describe two readings of one byte string, so this variant owns the decode-count procedure.

### Folding and Normalisation Gaps

Shape casing, width, and normalisation equivalents that map onto the approved value on one side and onto a distinct value on the other.
Confirm which side folds, because a comparison that folds admits spellings the sink still treats as distinct.
Treat a fold that both sides apply identically as a stop condition rather than a bypass.

### Overlong and Truncation Forms

Use an overlong or separator-equivalent spelling where a decoder resolves it after the comparison has read it as data.
Use a padded or truncated form where the accepting side tolerates a shortened value the comparison measured at full length.
Confirm the form at the sink, because a tolerated form that the sink rejects is a broken request rather than a bypass.

## Bypass Techniques

Bypass shapes slip past a comparison that is present, so each one is tried after the plain hostile value is refused.
- Single, double, and nested encoding layers, because each hop decodes a different number of times.
- Mixed encodings inside one value, so one side reads a separator the other side reads as data.
- Overlong and separator-equivalent spellings that resolve after the comparison.
- Case, width, and normalisation equivalents where one side folds and the other does not.
- Padded and truncated forms where the accepting side tolerates a shortened value.

## Chaining Attacks

Encoding differentials chain forward into the class that owns the effect, because a passed comparison is only the first layer.
- Hand the passed value to the class that owns the effect, and prove the class-specific consequence there.
- Stack with the signature evasion where the comparison also lists literal shapes.
- Stack with the parser confusion where the layered value also changes a structural member.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Encoding differentials count the decodes first and layer second, because the differential lives in the hop count.

1. **Trace the value** - every hop between the caller's input and the sink with its decode behaviour, and the step completes when each hop carries a decode count and a folding rule.
2. **Baseline the plain refusal** - send the plainly decoded hostile value and record the control's answer, and the step completes when a refusal is recorded or the absence of a comparison is recorded with the test that showed it.
3. **Layer one step** - re-send the same effect in a singly layered form, and the step completes when the layered form carries a passed or refused verdict.
4. **Continue to the divergence** - add one layer per attempt until the two readings diverge, and the step completes when the layer at which the readings differ is named.
5. **Confirm both readings** - record the benign reading on the checking side and the hostile reading at the sink, and the step completes when both readings carry evidence.
6. **Attribute the pass** - pair the refused plain form with the passed layered form, and the step completes when the decode step that admits the value is named from the pair.

## False Positives

Stop when both sides read the value the same way, because an identical reading is not a differential.

- A decoder that resolves the layered form before the comparison, confirmed by a refusal at every layer.
- A sink that reads the layered form as data, where the value passed the comparison without changing meaning.
- A pass whose effect never reached the sink, where the shape passed the comparison and the request broke later.
- A comparison that folds exactly as the sink folds, which admits no spelling the sink treats as distinct.
- A cached or simulator response that replays a stored verdict for the layered form.

## Pro Tips

Encoding differentials reward hop counting plus one layer per attempt.

1. Count decodes per hop before crafting, because the differential is a count rather than a payload shape.
2. Layer one step per attempt so the admitting decode is nameable.
3. Record both readings, since one reading cannot show a disagreement.
4. Prefer the layered form whose sink reading is identical to the plain hostile value, because it needs no second procedure.
5. Confirm at the sink, because a comparison's silence is not the effect.

## Summary

A comparison evaluates one reading of a value while the sink consumes another. Encoding differentials count the decodes per hop, layer one step per attempt, and claim the pass only when both readings are recorded.
