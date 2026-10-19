# Framing Declaration Pair Matrix

This note details the length-versus-encoding pair the parent body probes, read as cells rather than as payloads.
The obfuscation variants that turn a plain request into a pair are localised by the `defence-bypass` family at its framing step, so this note keeps the pair cells and the read-outs.
Concrete payload spellings are runtime knowledge-base facts and stay out of this note.

## Pair cells

| Cell | What the first hop reads | What the second hop reads | Where the surplus lands |
|---|---|---|---|
| Length against encoding | The declared length, so it forwards the whole body | The encoding terminator, so it ends the body early | The tail of the body stays on the origin socket as a prefix |
| Encoding against length | The encoding terminator, so it ends the body early | The declared length, so it reads only part of the body | The remainder stays on the origin socket for the next request |
| Duplicate declaration conflict | One member by its own precedence | The other member by its precedence | The boundary lands wherever the two precedences disagree |
| Encoding declaration ignored | The declared length after the obfuscated declaration is discarded | The declaration it still honours | The pair degrades into one of the two cells above |
| Framing field injected at a translation hop | The newer protocol's own framing encoding | A boundary re-derived from the forwarded field | The injected field becomes the origin's framing for the re-emitted request |

## Leftover accounting

Read the cell from the surplus side, because the surplus is the smuggled prefix.
A surplus that stays on the socket prepends to the next request on that connection, which is the poisoning primitive.
A surplus that the first hop already accounted for never reaches the origin, so the cell reads as a filtered or normalized verdict.
Record which hop consumed the boundary before choosing the cell, because the same declaration pair yields different cells on different hop orders.

## Read-outs

- Leftover bytes from one request appended to another request, which binds the probe to disclosure across the boundary.
- A timing gap between the probe and the clean sequential baseline, which marks a hop waiting for bytes the other hop already consumed.
- A differential marker response: two rapid requests carrying a unique token, where an unexpected or token-bearing second response proves socket poisoning.
- An anomalous response to a normal request, which fires when a victim's request is appended to the smuggled prefix and the origin answers the prefix.
- A refusal class produced by a front-end that rejects ambiguous framing, which closes the plain cells and leaves only the obfuscated pair.

## Discipline

Fingerprint the front-end strictness posture first, because a front-end that rejects or normalizes ambiguous framing closes the plain cells.
Probe one cell at a time over one connection, so each verdict attributes to the cell rather than to the combination.
Carry a unique placeholder token in every probe body, and keep the prefix short until the cell is confirmed.
Confirm against the clean sequential baseline before escalating to capture, and reach the origin directly where a direct path exists so the two framing views can be compared.
