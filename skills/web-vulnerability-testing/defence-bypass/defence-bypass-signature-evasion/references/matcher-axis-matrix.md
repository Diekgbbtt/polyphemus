# Matcher Axis Matrix

This note holds the axis list a signature matcher is probed along, what each axis reads on either side of the check, and the order the axes are swept in.

## The Axis List

| Axis | What the matcher reads | What the sink reads | When the axis applies |
|---|---|---|---|
| Casing | The exact case of the listed shape | A case-insensitive grammar | The rule set carries one case of a keyword, operator, or element name |
| Separator substitute | A specific separator character | Any separator its parser treats as equivalent | The sink accepts a sibling separator the list does not carry |
| Whitespace and comment insertion | A contiguous shape | A shape whose ignored spans the parser strips | The grammar has a comment, folding, or whitespace-skip rule the matcher does not model |
| Token boundary | A contiguous literal | The reassembled value | A token can be split across positions the sink joins |
| Quote insertion | The literal spelling of a token | The token after quote removal | The grammar permits quotes inside a token |
| Evaluated substitution | The written spelling | The evaluated result | The grammar evaluates an expression before use |
| Equivalent operator or alias | The obvious operator or name | A sibling operator or alias with the same effect | The grammar carries more than one spelling of one operation |
| Depth padding | A nesting or segment count | The count after its own decode | The matcher counts depth and the sink decodes away padding |
| Encoding layer | The encoded bytes | The decoded value | The checking side and the consuming side decode a different number of times |
| Grammar alternate | One element or handler spelling | Every alternate the parser accepts | The matcher lists one spelling of an element, attribute, or handler |

## Sweep Order

Sweep the cheapest axis first and stop at the first pass that reaches the sink, because heavy craft spends attempts and raises the control's sensitivity.
The order runs: casing, separator substitute, whitespace or comment insertion, token boundary, equivalent operator or alias, depth padding, then encoding layers.
Encoding layers come last because a layered value changes every later comparison, which makes the admitting axis harder to attribute.
Where the control is a behavioural detector rather than a signature matcher, the axis list does not apply: the probe is a baseline deviation, and the spelling variants are recorded as refusals of a different control kind.

## Reading a Refusal

A refusal on the obvious spelling establishes the rule set engaged, and a pass on a candidate spelling establishes the axis the list omits.
A refusal for a spelling that passed moments earlier reads as a rule set growing between attempts rather than as a dead end.
A pass whose effect never reaches the sink is a broken request rather than a bypass, so every candidate carries the effect unchanged.
Keep the effect identical across axes, because a changed effect invalidates the comparison between the refused spelling and the passed one.

## Control-Kind Split

A rule-set gap is defined against a matcher that lists literal shapes.
A normalising pipeline is probed by decode depth rather than by spelling.
A parser-strict front end is probed by structural member and framing rather than by token spelling.
Name the control kind before selecting the axis, because the axis list is a property of the matcher rather than of the payload.
