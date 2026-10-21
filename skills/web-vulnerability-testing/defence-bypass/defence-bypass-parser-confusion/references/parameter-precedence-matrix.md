# Parameter Precedence Matrix

This note holds the four precedence rules a reader can apply to a duplicated member, the reader kinds that apply them independently, and the probe that establishes each reader's rule rather than assuming it.

## The Four Precedence Rules

| Rule | What the reader keeps | What it discards | Observable |
|---|---|---|---|
| First occurrence | The first value it parses | Every later occurrence | A verdict matching the first value only |
| Last occurrence | The last value it parses | Every earlier occurrence | A verdict matching the last value only |
| List collecting | Every occurrence, ordered | Nothing | A response carrying both values or a length that grows with the count |
| Joined form | Every occurrence, concatenated | Nothing | A response carrying the values joined by a separator the reader chose |

## Reader Kinds

Each reader of one request resolves precedence for itself, so the probe compares them pairwise rather than assuming one rule for the path.
The reader kinds are: the query-string parser, the body parser, the framework's parameter binder, the gateway or front-end normaliser, the cache that keys on the request, and the router that derives a destination.
A reader that joins or collects duplicated members before evaluating them closes the disagreement, and that is a stop condition for the member rather than a dead end for the request.

## Probe Procedure

Send one member twice with two distinguishable values, then vary the ordering across attempts, so each reader's rule is established from its own verdict.
Record the response per ordering: which value each layer acted on, which value the body carried, and which value the router or cache consumed.
A payload split across duplicated occurrences is the same probe with the effect as the second half, and the joiner that reassembles it is the reader whose rule is the gap.
Duplicate members in the header family follow the same four rules, because a header reader and a body reader resolve precedence independently.

## Split-Payload Notes

Where the checking side inspects each occurrence separately and the consuming side joins them, a payload split across the duplicates reassembles after the check.
Where the checking side joins the occurrences and the consuming side reads one of them, the effect hides inside the joined text the check evaluated as a whole.
Where the two sides read different occurrences of the same member, the effect needs no reassembly at all, because the consumer simply reads the occurrence the check did not evaluate.
Keep the effect identical across orderings, so the admitting rule is attributable to the ordering rather than to a changed payload.
