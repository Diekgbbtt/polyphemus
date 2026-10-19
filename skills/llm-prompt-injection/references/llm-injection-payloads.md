# LLM Injection Payload Shapes

This note details the phrase families behind the override, breakout, extraction, and exfiltration steps of the parent body and its variants.
Each entry is a shape with placeholder tokens rather than a verbatim phrase, because a verbatim phrase is a runtime knowledge-base fact and a phrase that worked once is a KB candidate, not a suite literal.
Fill each placeholder from the target's observed templating, guard behaviour, and sink inventory.

## Override phrase families

| Family | Shape | What it bends |
|---|---|---|
| Authority claim | `[AUTHORITY-CLAIM]` + `[NEW-TASK]` | The model treats the claim as a higher-privilege instruction than its own developer text |
| Supersede claim | `[SUPERSEDE-CLAIM]` + `[NEW-TASK]` | The model treats earlier instructions as deprecated |
| Fabricated role marker | `[ROLE-MARKER]` + `[TASK]` | The model reads the marker as an instruction block rather than as data |
| Authorization wrapper | `[AUTHORIZED-TEST-CLAIM]` + `[TASK]` | The model treats the request as sanctioned and drops its refusal |
| Hypothetical wrapper | `[HYPOTHETICAL-FRAME]` + `[TASK]` | The model answers inside the frame while producing the real content |

## Framing and breakout shapes

- JSON-role framing: a `[ROLE-OBJECT]` carrying a role key and the task, so the payload matches a templating step that renders structured messages.
- Tag framing: a `[TAG-BLOCK]` that matches the target's prompt templating, so the payload lands inside a block the model reads as system text.
- Delimiter breakout: `[CLOSE-DATA-DELIMITER]` + `[OPEN-INSTRUCTION-DELIMITER]` + `[TASK]`, which closes the application's data region and opens an instruction region.
- Completion priming: `[PREFIX-OF-EXPECTED-TEXT]`, so the model continues from an attacker-chosen prefix.
- Few-shot priming: `[EXAMPLE-TURN]` pairs that establish the behaviour before the real `[TASK]`.

## Extraction framings

- Verbatim repeat: `[REPEAT-VERBATIM-FRAME]` over the hidden text.
- Span extraction: `[SPAN-FRAME]` naming a boundary before or above which the hidden text sits.
- Encoded output: request the hidden text under a `[TRANSPORT-ENCODING]` or a `[SUBSTITUTION-ALPHABET]`, so an output filter that reads plain text misses it.
- Structured reformat: request the hidden text as a table, a list, or a poem, where the format itself carries the content.
- Schema request: `[TOOL-SCHEMA-REQUEST]`, which discloses the declared interface even without a call.
- Anchor: pair every probe with `[NON-GUESSABLE-ANCHOR]`, so confabulated text that matches no ground truth is discarded immediately.

## Exfiltration templates

- Markup image: `[IMAGE-MARKUP]` whose URL carries `[DATA-CARRIER]`, so rendering the output performs the request with no click.
- Link or redirect shape: `[LINK-MARKUP]` carrying `[DATA-CARRIER]` in the destination.
- Fetch-tool call: `[FETCH-TOOL-CALL]` with `[DATA-CARRIER]` in an argument, so a tool reaches attacker infrastructure.
- Name-resolution channel: `[DATA-CARRIER]` split into labels of a `[LOOKUP-NAME]`, which leaves the host even where fetch egress is filtered.
- Behavioural carrier: `[REDIRECT-OR-DISPLAY-DIRECTIVE]` that moves the data to a surface the attacker reads.

## Wrapper families

- Transport encodings and rotation or substitution ciphers over a blocked phrase, so a keyword matcher misses it while the model still reads it.
- Alternate alphabets, homoglyphs, and translation, which change the surface form without changing the instruction.
- Invisible codepoints: tag-plane, zero-width, and bidirectional controls, which a human reviewer cannot see and a model still consumes.
- Splitting: fragments across turns, parameters, or records, which the model reassembles and a per-fragment filter cannot.
- Paraphrase variation: the same directive restated in new wording when a verbatim pattern is blocked.

## Adjudication

- A phrase family proves nothing alone: pair it with a ground-truth anchor and a sink, and repeat it across runs before claiming a bypass.
- Treat a resisted probe as a recorded negative, and keep the refusal pattern beside the positives so the guard boundary stays mapped.
- Chase the sink: an override that reaches no tool, no corpus, and no renderer is model chatter rather than a finding.
- Promote a phrase that works repeatedly into the runtime knowledge base, never into this note.
