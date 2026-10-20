---
name: lfi-include-execution
description: Include local files into the interpreter through handler and poisoning chains, and synthesise an include payload from a read-only filter primitive by chaining its transform stages. Use when dynamic names resolve into local interpreters, when wrapper schemes reach local content, when poisonable state feeds an inclusion sink.
metadata:
  version: 1.0.0
---

# LFI Include Execution

Prove that crafted names enter the local interpreter through handlers, wrappers, or poisoned state and execute included content.
A read-only filter primitive upgrades to execution when its transform stages are chained to synthesise the included payload in memory, so conversion-chain synthesis belongs beside handler invocation and poisoning.
Treat every dynamic include name as untrusted until handler invocation with execution proof confirms containment.

## Attack Surface

- **Applicability**: user influence reaches a local include sink that resolves dynamic names into the interpreter.
- **Content sources**: wrapper handlers, template resolution, or poisonable state can supply the included content.
- **Filter-stage sources**: applies where a filter-style read sink lets the caller choose its transform stages, since a chain of stages can synthesise content the sink then includes.
- **Sink variance**: the only variation is which inclusion sink consumes the input and which execution oracle proves the entry.

## Reconnaissance

- **Carrier inventory**: inventory inclusion carriers that resolve dynamic names into interpreters, templates, and rendered views.
- **Handler-surface recording**: record each handler surface that interprets local content, including filter, archive-fragment, inline-data, and command-expectation shapes.
- **Transform-stage enumeration**: enumerate the transform stages a filter-style read sink exposes, and record which stages are chainable plus what each does to content length and framing.
- **Wrapper-enablement recording**: record which wrapper families the policy enables, since each handler shape carries its own enablement precondition.
- **Plain-read baseline**: read the target plainly before poisoning or synthesising, so a failed chain is not confused with an unreadable source.
- **Poisonable-state enumeration**: enumerate poisonable state such as appendable logs, session stores, and temporary staged content.
- **Template-resolution recording**: record template-name resolution that derives rendered names from carrier input.
- **Survey completion**: complete the survey when every inclusion carrier has a recorded resolution shape and every poisonable store has a recorded write-and-read path.

## Detection Channels

- **Error echo**: inclusion warnings expose canonicalized locations for a crafted include shape.
- **Direct handler disclosure**: a filter shape returns transformed local content for a crafted include shape.
- **Outbound fetch receipt**: a wrapper shape triggers a fetch that confirms handler invocation.
- **Synthesised-content execution**: where a transform chain output rather than stored content supplies the included payload.

## Adversarial Capabilities

- **Input submission**: submit path-like and handler-shaped input through inclusion carriers without control over server code or include policy.
- **State poisoning**: poison appendable state with marker content and race temporary staged content before relocation completes.
- **Handler invocation**: invoke wrapper handlers with filter, archive-fragment, inline-data, and command-expectation shapes.
- **Chain assembly**: assemble transform chains whose output is a chosen payload, and reason about the length and framing behaviour of each stage.
- **Signal observation**: observe inclusion warnings, transformed content, and fetch receipts to confirm interpreter entry.

## Trust Assumptions

- **The agreement**: the server trusts, when the file-operation feature executes, that carrier-supplied names join a base location under a normalization contract, that resolution states settle inside one intended root before any read occurs, that request primitives read only what the join permits and exposed readers stay unreachable to crafted names, and that sensitive file content never leaks to the sender through crafted resolution.
- **The failing clause**: the local-inclusion clause: resolved names enter the local interpreter and execute included content, including content a transform chain synthesised in memory rather than stored on disk.

## Key Vulnerabilities

- **Handler invocation shapes**: route local content through filter transformation, archive fragments, inline data, and command expectation, held as <wrapper-shape>.
- **Poison-then-include shapes**: plant marker content into logs, session stores, and temporary staged content before inclusion, held as <poison-shape>.
- **Temporary-race shapes**: reference staged content in the window before relocation or scanning completes.
- **Template-resolution shapes**: derive rendered names from carrier-supplied render values, held as <render-shape>.
- **Variant delta**: the delta over the parent is poison-then-include chaining with handler-execution proof, which the parent escalation step never names.

### Conversion-Chain Payload Synthesis

- **Caller-selected stages**: where the read primitive lets the caller choose its transform stages, a chain of stages rewrites the byte stream step by step, so the chain output is attacker-chosen content.
- **In-memory synthesis**: the synthesised payload never touches disk, so no upload, no log write, and no writable path is required, and stored-content inspection never sees it.
- **Execution proof**: include the chain output as if it were stored content and confirm execution, since a transformed read alone only proves the read.
- **Disjointness**: transformed content that is only read stays with the handler-invocation shapes above; this variant owns the case where the chain output is executed.
- **Synthesis reference**: see `references/filter-chain-synthesis.md` for the stage-chaining workflow, its length budget, and the blind-target variant.

## Advanced Techniques

- **Poisoning chain**: chain poisoning before inclusion by planting a marker, then invoking the poisoned store through the inclusion sink.
- **Staged-content race**: race staged content by referencing its transient name promptly and confirming interpreter entry on the response.
- **Template-resolution rendering**: render template resolution by supplying render-name values and confirming engine evaluation of the resolved name.
- **Shortest-stage chain**: chain the shortest stage sequence that still yields the payload, since every stage consumes length budget.
- **Stage ordering**: order the stages so the payload survives the last transform, and compensate for stage padding before including the output.
- **Execution corroboration**: corroborate execution with transformed output or fetch receipts rather than raw disclosure alone.

## Bypass Techniques

- **Handler-policy bypass**: defeat handler-policy checks by spelling wrapper meaning across filter, fragment, and inline-data shapes held as <wrapper-shape>.
- **Name-allowlist bypass**: defeat name allowlists by nesting traversal meaning inside handler arguments that resolve after the check.
- **Relocation-timing bypass**: defeat relocation timing by addressing transient staged names before the move or scan completes.
- **Constant-template bypass**: defeat constant-template expectations by routing render-name values into dynamic resolution with <render-shape>.
- **Stage-limit bypass**: defeat stage-count and length limits by splitting the synthesis across several chained stages that each pass alone.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Persistence writes**: carry included execution into configuration recovery and template overwrite for persistence.
- **Repeatable inclusion**: carry poisoned logs and session stores into repeatable inclusion primitives across requests.
- **Companion-skill reference**: name the archive companion at the extract-then-locate step rather than restating its procedure here.

## Testing Methodology

1. Inventory inclusion carriers and record each dynamic resolution shape into the interpreter.
Complete when every inclusion carrier has a recorded resolution shape with no unvisited include surface remaining.
2. Invoke handlers with filter, archive-fragment, inline-data, and command-expectation shapes and record execution signals.
Complete when every handler shape has a recorded invocation verdict across all inventoried carriers.
3. Poison appendable state and staged content with marker values and record write-and-read paths.
Complete when every poisonable store has a recorded planted marker with a recorded retrieval path.
4. Bent step: invoke handlers and wrappers and poison-then-include logs and sessions and staged files with execution proof.
Complete when every poisoned store and handler shape has a recorded inclusion verdict with execution evidence or a recorded negative.
5. Synthesise through the chain: chain caller-selected transform stages on the read sink and include the chain output with execution proof.
Complete when every chainable stage sequence has a recorded synthesis verdict with an execution oracle or a recorded transform fault.

## False Positives

- **Virtual names**: exclude virtual names that resolve into safe stores without entering the interpreter.
- **Disabled handlers**: exclude handlers disabled by policy with includes bound to constant names only.
- **Atomic relocation**: exclude staged content that relocates atomically before any inclusion sink can address it.
- **Transform faults**: exclude chains whose output never resolves to valid content under the interpreter, which marks a transform fault rather than synthesis.

## Pro Tips

- **Transforming handlers**: prefer transforming handlers that return encoded content over destructive execution shapes.
- **Store enumeration**: enumerate readable logs and session stores before attempting poisoning chains.
- **Transient-name isolation**: isolate transient staged names quickly since relocation windows close fast.
- **Evidence recording**: record handler output and warning text as hard evidence for every confirmed inclusion.
- **Shortest chain**: prefer the shortest chain that still yields the payload, and confirm the plain read first so a transform fault is not mistaken for a policy block.

## Summary

Confirm local interpreter entry with handler invocation and poison-then-include chains backed by execution proof.
Where the read sink exposes caller-selected transform stages, chain them to synthesise the payload in memory and include the chain output.
Hold dynamic names constant, disable unneeded handlers, and bind resolution to allowlisted locations at the input-output boundary.
