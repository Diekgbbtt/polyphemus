# Encoding Layer Matrix

This note holds the encode-depth and notation-equivalence families behind the decode-count procedure, and the probe order that keeps one variable per attempt.

## Encode Depth

| Depth | Form the checking side reads | Form the consuming side reads | When it applies |
|---|---|---|---|
| Plain | The hostile value | The hostile value | The baseline, never a bypass on its own |
| Single layer | The encoded text as data | The hostile value after one decode | One hop decodes and the other does not |
| Double layer | The singly decoded text, still benign | The hostile value after the second decode | The checking side decodes once and the consumer decodes twice |
| Nested or mixed | A partially decoded text | The hostile value assembled from mixed coders | The two sides apply different coders in a different order |
| Overlong or width variant | A distinct byte string | The canonical character | A decoder folds the overlong form after the check |
| Declared character-set switch | A byte string read under the declared set | The same bytes read under the sink's set | The declaration makes the checking side read a different string than the consumer |

The layer count is the mechanism: each hop decodes a different number of times, so the probe adds one layer per attempt and stops at the first layer where the two readings diverge.

## Notation Equivalence

| Family | What one side resolves | What the other side keeps | Confirmation |
|---|---|---|---|
| Case and width | The canonical character | A distinct byte string | The sink resolves the canonical value |
| Numeric and address notation | One address or number | A different address or number | The consuming side connects or resolves the different value |
| Dot segments and separator equivalents | A normalised path | The original path | The router resolves a path the check did not see |
| Coercion equivalents | The approved value | A distinct value | The comparison folds and the sink does not, or the reverse |
| Padding and truncation | A shortened or padded value | The full value | The accepting side tolerates what the comparison measured at full length |

Coercion equivalents are the folding family of a comparison: a numeric-looking string, an empty or absent value, a boolean spelling, a single value and its list-wrapped form, and a zero value each equal the approved value on one side while remaining distinct on the other.
Read whether the comparison is loose or strict before crafting, because a strict comparison closes the coercion family and leaves the notation and decode gaps.

## Padding Arithmetic

Depth is a count: the segments above the value minus the upward segments yields the arriving depth.
Where the checking side counts depth or segments, pad the value with segments the checker decodes away, so the checker's count stays inside its bound while the consumer's count leaves it.
Select the encoding depth against the checker's own depth: equal-level encoding, over-encoding one element, and padding to a non-negative checker depth are three distinct selections with different observables.
Treat a checker that encodes before counting as a recorded negative rather than a dead end, and move to the next layer.

## Probe Order and Reading

Trace every hop first and record its decode count and its folding rule, because the differential is a count rather than a payload shape.
Baseline the plainly decoded hostile value, then add one layer per attempt and stop at the layer where the verdict changes.
Record both readings for every pass: the benign reading the checking side consumed and the hostile reading the sink consumed.
A comparison that folds exactly as the sink folds admits no spelling the sink treats as distinct, so it is a stop condition rather than a bypass.
