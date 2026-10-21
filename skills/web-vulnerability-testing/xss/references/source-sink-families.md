# Source and Sink Families

This note details the source and sink families summarised in the parent body.
Each family is listed by what it carries and what it renders into, so a source-to-sink trace reads one row per family.
Concrete payload spellings and framework bindings are runtime knowledge-base facts and stay out of this note.

## Source families

| Family | What it carries | Reach |
|---|---|---|
| URL components | A value in the query, the fragment, or the path | Per request, and the fragment never leaves the client |
| Cross-navigation state | The window-name property | Survives a cross-origin navigation, so a set-once value persists |
| Message channels | A payload posted from another document | Cross-document, gated only by the origin check the handler applies |
| Client storage | A value the application persisted on the client | Persists across sessions until the application clears it |
| Server data consumed on the client | A value the server emitted into a client-side sink | Per response, and the encoding applied at emit time may not match the sink |
| File metadata | Uploaded names and embedded properties | Renders on a retrieval view, not on the upload response |
| Client-side structure | A named element that shadows a global the application trusts | Owned by the `proxy-techniques-dom-clobbering` leaf, which carries the primitive and its gadget step |

## Sink families

| Family | The context it renders into | The encoding that neutralises it |
|---|---|---|
| Markup insertion | A node in the document tree | Element and attribute encoding for the exact parsing context |
| URL-bearing attributes | A slot a navigation or a load consumes | Scheme allowlist plus attribute encoding |
| Script strings | A literal inside a script block | Script-string encoding, with no quote or terminator surviving |
| Evaluators and timers | A string form the runtime executes | Removal of the string form, so only a function reference reaches it |
| Dynamic construction | A compiled or constructed code path | Constant construction, with no caller fragment inside it |
| Worker and document creation | A new execution context | Same-origin restriction plus constant content |
| Style contexts | A stylesheet or a style attribute | Style encoding, with no expression or import reaching it |

## Context-to-encoding matrix

Classify the sink before crafting anything: markup node, quoted attribute, unquoted attribute, URL slot, script string, evaluator, style, or active-content document node.
Record the encoding the application applies at that sink, then test with a marker that survives the encoder but changes meaning when the encoder is missing.
Treat structured-document and message renderers separately, because their execution rules differ from the browser's.
A value encoded exactly for its sink context is a negative result, not a finding.

## Sanitizer round trip

Feed the sanitizer's output back through the parser and compare the re-parsed result with the input that was cleaned.
Parsing-ambiguity pairs, where one namespace plus one foreign-content element re-parse into executable markup although each part alone is inert, are the seam the sanitizer's grammar does not model.
Markdown and diagram renderers post-process sanitized text, so test the renderer's own grammar as a second sanitizer.
A configuration gap is a pair of allowed elements and attributes that combine into a gadget with an allowed handler.

## Marker and payload discipline

Use a unique alphanumeric marker and search the no-marker baseline for it first, because a common word echoed by a help link reads as a reflection until the baseline clears it.
Keep the beacon-field family in view for blind and stored delivery: error messages, return and source parameters, identity fields, agent and referrer strings, addresses, and file names.
Carry one marker per payload to the listener, and treat a callback whose user agent belongs to a real browser as victim execution rather than a back-end fetch.
Keep a small curated set of shape families per context and iterate on encoding, rather than spraying catalogues.
Where a bypass is generic rather than class-specific, the `defence-bypass` family owns the matcher axes; this note keeps the source, the sink, and the render path.
