# Upload Bypass Matrix

This note details the bypass families behind the exercise-bypass and validation-gap steps of the parent body.
Each row stays at the shape level because concrete extensions, media types, and content prefixes are runtime knowledge-base facts.
Resolve the accepted family list and its literal prefixes from the knowledge base for the target at test time.

## Extension games

- Alternate extensions that the interpreter behind the placement location still maps to a handler.
- Double extensions where the check extracts a different extension than the serving layer does.
- Mixed case and trailing separators, dots, or spaces that survive a case-sensitive or suffix-only check.
- Repeated dots and long paths ending in an allowed suffix.
- Truncation shapes on legacy stacks that cut the name before the rejected suffix is read.
- Name divergence between the multipart part name and the parameter name, where the later value wins.

## Declared-type games

- A client-declared media type that disagrees with the content, where the server trusts the declaration.
- A declared type that matches an accepted family while the content is interpreter-shaped.
- Part headers of a multipart body trusted over the assembled content.
- Metadata fields that carry a type or disposition consumed later, at finalize or at serving time.
- Direct-to-cloud headers the client sets on a presigned upload, which the storage layer then honours.

## Content-prefix games

- Prefix the payload with the short signature of an accepted family so a header-only or prefix-only check passes.
- A polyglot keeps both parses valid: the accepted family's parser and the interpreter that later consumes the file.
- The accepted family's signature set is a runtime knowledge-base fact, so resolve it per target rather than guessing.
- A prefix that satisfies an image parser while the trailing bytes satisfy an archive or interpreter parse covers two checks with one file.

## Polyglot families

- Image plus interpreter: a valid image head followed by interpreter content.
- Image plus archive: a valid image head that is also a readable archive, so an upload-time image check and a later metadata read both succeed.
- Document container with inner markup: the container passes the outer check while the inner component parses attacker content.
- Stream manifest shapes: a media file whose body references external segments, so the converter follows it during processing.

## Filename injection

- Lookalike characters, reserved characters, and device names that a name validator does not normalize.
- Path separators and traversal meaning inside the name, where the placement join trusts the name.
- Case-insensitive collisions that overwrite an existing file or a configuration name.
- Null-byte or terminator truncation on legacy stacks.

## Placement and structure

- Configuration files that map extensions or inject a prelude path, placed where the server reads them.
- Nested archives that re-expand into a second traversal or a second handler.
- Link entries and traversal entries inside an archive, which escape the extraction destination.
- Compression ratio shaped to exhaust the expander or the queue behind it.
- Finalize swaps in resumable flows, where metadata or the last chunk changes after the earlier checks ran.

## Probe discipline

- Vary one axis per attempt: extension, declared type, content prefix, or name shape, never two at once.
- Capture the final stored location, the served headers, and the served type for every accepted probe.
- Adjudicate on the server's behaviour after storage, not on the upload verdict alone.
- Keep a benign baseline upload of each accepted family beside the probes, so a refusal is attributable to the mutated axis.

## Expected verdicts

| Observation | Reading |
|---|---|
| Probe accepted, stored, and served executable | The placement clause failed; confirm execution through the served object |
| Probe accepted and stored, served as a download with a strict guard | Placement holds; the finding needs a second serving path |
| Probe rejected but retrievable through a secondary path | The gate and the serving path disagree; check the pre-verdict window |
| Probe transformed by a processor into a served artifact | The toolchain clause is in play; check the derived output |
| Probe accepted and stored outside the intended namespace | The placement join trusted the name; check for a follow-up read |
