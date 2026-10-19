# Deserialization Format Signatures

This note details the marker shapes behind the shape-fingerprinting step of the parent body.
Each row stays at the shape level because concrete prefixes, media types, and carrier names are runtime knowledge-base facts.
Resolve the literal marker for a fingerprinted family from the knowledge base at test time, and record the observed head beside the finding so the verdict stays attributable.

## Where a marker appears

- The body of a request or response, in raw bytes or one encoding layer deep.
- A cookie value or a hidden form field that round-trips into server state.
- A header value the application stores and re-reads.
- An uploaded file, a message payload, or a stored column read by a later job.
- A cache entry holding an encoded value the application decodes on read.

## Marker shapes per format family

| Format family | Marker shape | Where the discriminator sits |
|---|---|---|
| Type-tagged binary object graph | Leading bytes are a short magic number; the encoded carrier begins with the stable encoded head of those bytes | The head survives one encoding layer, so decode once and re-read it |
| Text type-tag document | A printable head carrying a type tag plus a field or length grammar | The tag names a class rather than a primitive, which marks polymorphic resolution |
| Self-executing encoding | The document head is a directive the decoder evaluates during decode | The head is code, so any accepted input is execution by design |
| Integrity-gated state blob | An opaque encoded token with a carrier name and often a trailing binding segment | The head is not a magic number, so the tamper response is the discriminator |
| Wrapper-triggered metadata read | A path-like value naming a wrapper scheme | The marker is the scheme token inside the path, not the bytes |
| Interpolated reference | A plain string whose value is a lookup directive | The marker is the directive prefix inside an otherwise ordinary field |
| Nested envelope | An encoding or compression layer around any row above | The outer head names the encoding, so strip layers one at a time |

## Decoding discipline

- Strip exactly one encoding layer per attempt, then re-read the head; a base64 body often hides a binary magic number.
- Record the decode chain with each observed head, so a marker that survives several layers is not mistaken for a different family.
- Compare the head against the accepted-family list for the sink: a marker that matches no accepted family is evidence for a wrapper or nested envelope rather than for a decode sink.
- Prefer a decode error or a class-resolution error as the family confirmation when the head is masked or truncated.

## Content-type and carrier cues

- A media type declaring a native serialization marks the family even when the body is opaque.
- A cookie or hidden field whose name marks a state carrier is a cue, never proof; confirm the round trip into server state.
- A body that the server returns modified after a write, or that changes behaviour when one byte is flipped, is the cheapest carrier confirmation.
- A carrier name is a runtime knowledge-base fact: resolve it per framework from the knowledge base rather than treating the name itself as the finding.

## What each marker proves

- A magic head proves the family is in play, not that the bytes reach a decode sink.
- A tamper response proves a verifier runs before rehydration, which routes the run to the signed-forgery variant.
- A decode or resolution error proves attacker bytes reach a decoder, which is the sink confirmation the chain step needs.
- A carrier round trip proves the value is state the application reads back, which raises the sink priority.

## False positives

- An encoded value that decodes to plain text with no type tag, which is transport encoding rather than a serialized graph.
- A magic head on stored data that no code path decodes.
- An opaque carrier whose bytes are never influenced by the caller.
- A framework marker on a hardened endpoint that rejects the blob before any resolution attempt.
