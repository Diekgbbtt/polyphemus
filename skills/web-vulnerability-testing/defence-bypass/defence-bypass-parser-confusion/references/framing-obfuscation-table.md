# Framing Obfuscation Table

This note holds the framing-declaration variants that make two readers of one request derive different boundaries, and the reader pairs each variant targets.
The desync class owns the exploitation procedure; this table only localises the disagreement so the family can name the class at its own step.

## Declaration Obfuscation Variants

| Variant | What the normalising front end reads | What the origin reads | Reader pair it targets |
|---|---|---|---|
| Separator or whitespace before the value | A declaration whose value is malformed or unrecognised | A declaration with a valid value | Front end ignores what the origin honours |
| Folded continuation line | A declaration with an embedded newline | A declaration whose value continues | Front end rejects or splits what the origin joins |
| Case variant of the declaration name | An unrecognised declaration | The declaration it honours case-insensitively | Front end ignores what the origin matches |
| Duplicate declaration, one non-standard | One of the two occurrences by its own precedence | The other occurrence by its precedence | Both readers honour the same name differently |
| Declaration split across a line break | An unrecognised or truncated declaration | A complete declaration | Front end's parser stops where the origin's continues |
| Declaration carried in a hop-by-hop field | A field it strips before forwarding | A field it re-derives or honours | An intermediary removes the evidence the next reader needs |
| Declaration absent, older protocol version | A request with no declaration at all | A request whose boundary it derives from the connection | A version that carries no framing metadata |
| Downgrade re-derivation | A newer protocol's own framing encoding | An older protocol's re-derived boundary | The translation hop between two protocol versions |

## Reader Pairs

The disagreement is always between two readers of one boundary: declaration against declaration, declaration against terminator, or length against boundary.
Enumerate the readers before crafting: the front-end proxy, the load balancer, the translation hop, the origin server, and any cache that keys on the request shape.
Rank the readers by strictness, because a lenient reader accepts a structure the strict one rejects and that pair is the gap.
Record which reader re-frames the request in transit, because the emitted request no longer matches the received one and the boundary must be re-derived rather than assumed.

## Confirmation Discipline

Confirm the disagreement with a timing differential between a normal request and a re-framed one, because both answers often look alike in status and body.
Pair a canonical single-boundary request with the re-framed candidate, so the reader that consumed the wrong member is nameable.
Treat a refusal at the second reader as re-validation evidence rather than a dead end, and move to the next variant.
A 400 or 500 produced by a parser that intentionally rejects an ambiguous request is not a desync, so record the refusal class before claiming one.
