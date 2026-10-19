# Filter-Chain Payload Synthesis

This note details the stage-chaining workflow behind the conversion-chain synthesis block of the variant body.
It applies where a read primitive exposes caller-selected transform stages, so a chain of stages rewrites the byte stream and the chain output is attacker-chosen content.
It stays at the shape level because concrete stage names and chain spellings are runtime knowledge-base facts.

## Prerequisites

- A read sink whose transform stages the caller selects, so the caller controls the byte stream rather than only the resource.
- An inclusion sink that consumes the read output as included content, which is what upgrades a transformed read into execution.
- Stage availability by policy: enumerate the exposed stages and test each one separately, because a chain is only as long as its enabled stages.
- A length budget above the target payload size, since every stage consumes or pads length.

## The workflow

1. Confirm the plain read first, so a later failure is not mistaken for an unreadable source or a policy block.
2. Enumerate the stages and record each stage's effect on content length, framing, and byte classes.
3. Choose the shortest chain whose output is the chosen payload, and compensate for the padding each stage adds.
4. Include the chain output as if it were stored content, and confirm execution rather than a transformed read.
5. Record the chain, the observed output, and the execution oracle beside the finding.

## Length and framing budget

- Every stage consumes length, so a payload longer than the remaining budget must be split across several chained stages that each pass alone.
- Order the stages so the payload survives the last transform, and pad before the stages that strip or reshape framing.
- A stage that changes framing can carry content a later stage reads as structure, which is how a chain rebuilds a directive in memory.
- When a single stage cannot carry the payload, compose stages whose intermediate outputs are still accepted by the next stage.

## The blind-target variant

- Where the sink returns no content, prove the chain by execution: include the output and observe a marker the interpreter evaluates.
- Where execution is also blocked, prove the chain by an outbound receipt from the included content.
- A transform fault and a policy block look alike on a blind target, so read the plain target first and vary one stage per attempt.
- Keep a chain that only returns transformed content as a read finding, not an execution finding.

## Failure modes

- A stage disabled by policy, which truncates the chain rather than the payload.
- A chain longer than the sink's accepted length, which fails before the interpreter reads it.
- Output that never resolves to valid content under the interpreter, which marks a transform fault rather than synthesis.
- A name check that runs after the read, which a traversal meaning nested inside the handler arguments defeats.

## Evidence

- Execution of synthesised content is the finding; a transformed read alone proves the read and stays with the handler-invocation shapes.
- Record the chain, the output, and the oracle together, so a later reviewer can replay the synthesis exactly.
- Prefer the shortest chain that still yields the payload, so the proof stays cheap to reproduce.
