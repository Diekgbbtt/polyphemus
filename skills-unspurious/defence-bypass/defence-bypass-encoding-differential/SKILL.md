---
name: defence-bypass-encoding-differential
description: Encoding differential bypass between the checking side and the consuming side of one value, covering decode-count gaps when each hop decodes a different number of times, folding gaps when normalisation maps two spellings onto one value, coercion or notation equivalence when a comparison folds a value the sink treats as distinct, and truncation or padding forms when the accepting side tolerates a shortened value.
metadata:
  version: 1.0.0
---

# Encoding Differential

A control that decodes a value evaluates the value it decoded, and the sink consumes the one it decodes. This variant finds the form that reads as benign on the checking side and as hostile on the consuming side, or the reverse, by counting the decodes on each side of the path. The goal is a value whose two readings differ, confirmed by the sink effect.

## Attack Surface

- **Applicability**: centers on a value that is decoded, normalised, or re-encoded between the check and the sink.
- **Surface composition**: layered encoding forms, overlong and width-variant spellings, case-folding and normalisation steps, and value families where the accepting side tolerates padding or truncation.
- **Widening factors**: multi-hop paths where each hop decodes a different number of times, and comparisons that normalise one side only, both widen the surface.
- **Out-of-scope variant**: a value that one component reads once and no later component re-reads rides outside this variant, because there is no second decode to disagree with.

## Reconnaissance

- **Reconnaissance scope**: encoding differentials are counted rather than guessed, because the differential lives in the decode steps of the path.
- **Hop tracing**: trace the value through every hop and record how many times each hop decodes it.
- **Refusal baseline**: establish the refusal baseline with the plainly decoded hostile value, so a later pass is attributable to the decode difference.
- **Layer probing**: probe one encoding layer at a time and note which hop reads the layered form as data and which reads it as syntax.
- **Folding behaviour**: record the folding behaviour of both sides: casing, width variants, and normalisation steps that map two spellings onto one value.

## Detection Channels

- **Channel scope**: encoding differentials listen to the two readings of one value, so only the entries below are live here.
- **Plain refusal**: the control's refusal on the plainly decoded value, which proves the comparison engaged.
- **Layered pass**: a pass for the same effect in a layered or folded form, which shows the two sides decoded the value differently.
- **Form differential**: the differential between the refused plain form and the passed encoded form at one position, which localises the decode step.
- **Normalisation step**: the control normalising the value before it evaluates its rule, which localises the step where the two readings diverge.
- **Hostile sink reading**: the effect appearing at the sink in the hostile reading while the control's verdict reports the benign one.
- **Sink reading**: the sink's own error class or decoded output, which names the reading the sink actually consumed.

## Adversarial Capabilities

- **Prerequisites**: encoding differentials presuppose decode-count knowledge plus layer control plus a repeatable baseline, and they consume all three.
- **Paired answers**: send the plain hostile value and the layered candidate to the same position, and read both answers.
- **One layer per attempt**: layer one encoding step per attempt, and record the layer at which the readings diverge.
- **Folding variants**: shape folding variants of the same value: casing, width, and normalisation equivalents.
- **Tolerant-value form**: hold a tolerant-value form for accepting sides that pad, truncate, or normalise before comparing.

## Trust Assumptions

- **The agreement**: the control trusts that the value it evaluates is the value the sink consumes, holds the decode count constant across the path, holds both sides to one folding rule, and holds the accepted value to the exact bytes the comparison approved.
- **The failing clause**: this variant breaks the decode-count clause because the checking side and the consuming side decode the same bytes a different number of times, so each reads a different value.
- **Claim discipline**: the differential is claimed only when both readings are recorded, because one reading alone cannot show a disagreement.

## Key Vulnerabilities

### Decode-Count Gaps

- **Divergence hop**: find the hop count at which the layered form reads as data on one side and as syntax on the other, because each decode step moves the boundary.
- **Layer stepping**: layer one encoding step per attempt and stop at the step where the effect appears, since further layers usually only re-encode the value.
- **Encoding depth**: select the encoding depth against the checker's own depth: equal-level encoding, over-encoding one element, and padding with segments the checker decodes away all keep the checker's reading benign while the consumer's reading moves.
- **Ownership**: the parent oracle step covers a single reading of the value and cannot describe two readings of one byte string, so this variant owns the decode-count procedure.
- **Encoding layer matrix**: see `references/encoding-layer-matrix.md` for the encode-depth and notation families behind the procedure.
- **Decode-count probe**: see `scripts/decode-count-probe.sh` for the layer-one-step-at-a-time probe with its depth guard.

### Folding and Normalisation Gaps

- **Fold shaping**: shape casing, width, and normalisation equivalents that map onto the approved value on one side and onto a distinct value on the other.
- **Folding side**: confirm which side folds, because a comparison that folds admits spellings the sink still treats as distinct.
- **Stop condition**: treat a fold that both sides apply identically as a stop condition rather than a bypass.
- **Coercion family**: coercion-equivalent forms are the folding family of a comparison: a numeric-looking string, an empty or null value, a boolean spelling, a single value and its list-wrapped form, and a zero value can each equal the approved value on one side while remaining distinct on the other.
- **Comparison strictness**: read whether the comparison is loose or strict before crafting, because a strict comparison closes the coercion family and leaves only the notation and decode gaps.

### Notation and Address Folding

- **Notation shaping**: shape a value's notation so one side folds it onto the approved value and the other connects or resolves the same text differently: decimal, octal, and hexadecimal address forms, short and mapped address forms, and trailing-dot or width variants.
- **Folding versus decode**: treat notation folding as a folding gap rather than a decode gap, because the text is well formed on both sides and only the resolution differs.
- **Resolved value**: confirm the resolved value on the consuming side, because a notation both sides resolve alike carries nothing.

### Overlong and Truncation Forms

- **Overlong spelling**: use an overlong or separator-equivalent spelling where a decoder resolves it after the comparison has read it as data.
- **Padded or truncated form**: use a padded or truncated form where the accepting side tolerates a shortened value the comparison measured at full length.
- **Sink confirmation**: confirm the form at the sink, because a tolerated form that the sink rejects is a broken request rather than a bypass.

## Bypass Techniques

- **Bypass scope**: bypass shapes slip past a comparison that is present, so each one is tried after the plain hostile value is refused.
- **Encoding layers**: single, double, and nested encoding layers, because each hop decodes a different number of times.
- **Mixed encodings**: mixed encodings inside one value, so one side reads a separator the other side reads as data.
- **Overlong spellings**: overlong and separator-equivalent spellings that resolve after the comparison.
- **Case and width folds**: case, width, and normalisation equivalents where one side folds and the other does not.
- **Coercion equivalents**: coercion-equivalent forms where one side's comparison folds them and the other's does not.
- **Notation forms**: address and numeric notation forms that resolve differently on each side of the comparison.
- **Character-set parameter**: a declared character-set parameter that makes the checking side read a different byte string than the consumer.
- **Padded and truncated forms**: padded and truncated forms where the accepting side tolerates a shortened value.

## Chaining Attacks

- **Chain scope**: encoding differentials chain forward into the class that owns the effect, because a passed comparison is only the first layer.
- **Effect hand-off**: hand the passed value to the class that owns the effect, and prove the class-specific consequence there.
- **Signature-evasion stack**: stack with the signature evasion where the comparison also lists literal shapes.
- **Parser-confusion stack**: stack with the parser confusion where the layered value also changes a structural member.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Encoding differentials count the decodes first and layer second, because the differential lives in the hop count.

1. **Trace the value** - every hop between the caller's input and the sink with its decode behaviour, and the step completes when each hop carries a decode count and a folding rule.
2. **Baseline the plain refusal** - send the plainly decoded hostile value and record the control's answer, and the step completes when a refusal is recorded or the absence of a comparison is recorded with the test that showed it.
3. **Layer one step** - re-send the same effect in a singly layered form, and the step completes when the layered form carries a passed or refused verdict.
4. **Continue to the divergence** - add one layer per attempt until the two readings diverge, and the step completes when the layer at which the readings differ is named.
5. **Confirm both readings** - record the benign reading on the checking side and the hostile reading at the sink, and the step completes when both readings carry evidence.
6. **Attribute the pass** - pair the refused plain form with the passed layered form, and the step completes when the decode step that admits the value is named from the pair.

## False Positives

- **Stop condition**: stop when both sides read the value the same way, because an identical reading is not a differential.

- **Early resolution**: a decoder that resolves the layered form before the comparison, confirmed by a refusal at every layer.
- **Data reading**: a sink that reads the layered form as data, where the value passed the comparison without changing meaning.
- **Broken request**: a pass whose effect never reached the sink, where the shape passed the comparison and the request broke later.
- **Matching folds**: a comparison that folds exactly as the sink folds, which admits no spelling the sink treats as distinct.
- **Cached or simulated answer**: a cached or simulator response that replays a stored verdict for the layered form.

## Pro Tips

- **Discipline**: encoding differentials reward hop counting plus one layer per attempt.
- **Count decodes**: count decodes per hop before crafting, because the differential is a count rather than a payload shape.
- **One layer per attempt**: layer one step per attempt so the admitting decode is nameable.
- **Both readings**: record both readings, since one reading cannot show a disagreement.
- **Identical sink reading**: prefer the layered form whose sink reading is identical to the plain hostile value, because it needs no second procedure.
- **Sink confirmation**: confirm at the sink, because a comparison's silence is not the effect.

## Summary

A comparison evaluates one reading of a value while the sink consumes another. Encoding differentials count the decodes per hop, layer one step per attempt, and claim the pass only when both readings are recorded.
