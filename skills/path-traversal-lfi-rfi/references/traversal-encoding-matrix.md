# Traversal Encoding Matrix

This note details the encoding and path-shape families behind the normalization probes of the parent body, plus the high-value read targets those probes aim at.
Each row stays at the shape level because concrete path spellings and file locations are runtime knowledge-base facts.
Resolve the target's separator and decoding behaviour per hop at test time.

## Encoding families

- Single percent-encoding of separators and dot segments, which survives a front-end that decodes once.
- Double percent-encoding, where the front-end decodes to a second encoding that the application decodes again.
- Overlong and multi-byte forms of separators and dots, which legacy decoders accept as the plain character.
- Unicode dot and separator equivalents, which a normalization step maps to a path separator.
- Mixed case inside encoded sequences, where one hop compares case-sensitively.
- Null-byte and terminator truncation on legacy stacks, which cuts an appended suffix.
- Repeated decoding through several hops, where each hop agrees on a different number of passes.

## Dot and separator shapes

- Folded dot segments and repeated dot sequences that collapse to a traversal after normalization.
- Trailing dots and trailing slashes that survive a suffix check but resolve to the same location.
- Separator collapse differences: an alternate separator that one hop treats as a plain character and the next treats as a boundary.
- Prefix-forced bases: pad the traversal with extra segments to escape a base the application prepends, or supply an absolute path where a relative name is expected.
- Appended valid extensions that a resolution step strips before the read.

## Path shape

- Absolute paths supplied where the application joins a value onto a base.
- Nested route prefixes and front-end aliases, where the application root differs from the front-end root.
- Path parameters and encoded separators that survive the front-end and change the backend's resolution.
- Archive member names carrying the same shapes, which the extractor resolves at extraction time.
- Wrapper or scheme tokens inside the value, which select a handler rather than a file (see the inclusion variants).

## The hop discipline

- Vary one encoding axis per attempt, so each success attributes to exactly one decoding disagreement.
- Record which hop decoded the shape: the front-end, the application, or both in sequence.
- Keep the shape that reached the sink and the resolved path beside the request, so the effect stays attributable.
- Compare against an in-root control request before drawing conclusions from a masked response.

## High-value read targets

- Process identity and account stores.
- Application configuration, environment files, and secret stores.
- Source files, templates, and deployment descriptors.
- Log files and process caches.
- Key material, credential stores, and session or cache stores.
- Host metadata endpoints and orchestration descriptors reachable from the host.

## Adjudication

- Direct content disclosure is the strongest proof; keep it to one canonical small file.
- Masked responses answer through length, entity tag, or status shifts against the in-root control.
- Encoded-content disclosure counts when the returned bytes decode to valid source, even if the raw body is not plain text.
- An echoed input or a lone status change is not proof; retract the claim until a control differential or an out-of-band receipt confirms it.
