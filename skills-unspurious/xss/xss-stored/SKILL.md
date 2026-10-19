---
name: xss-stored
description: Stored XSS persisting attacker input for later rendering across retrieval views, inline file serving, or delayed multi-principal reads.
metadata:
  version: 1.0.0
---

# Stored XSS

Stored delivery persists attacker-controlled input across a storage boundary and executes it when a later view renders the persisted value.
This variant proves persistence by writing once and confirming execution at retrieval through the sink appropriate to the view.
The impact goal is victim-context execution with evidence-backed retrieval proof rather than same-response reflection.

## Attack Surface

- **Applicability**: centers on any write entry whose value persists and renders at a later retrieval through any sink.
- **Write entry**: accepts attacker-influenced input through a direct field or an indirect carrier such as a message queue item or a stored document.
- **Retrieval view**: renders the persisted value through server markup or through a client sink without requiring same-response reflection.
- **Viewing principal**: may be the writer or a different principal who later opens the persisted record.
- **Inline file serving**: with an active content type rides inside this variant as a stored specialisation with content-type plus disposition plus sniffing checks.
- **Blind write entry**: a blind write entry carries the value into a log, error, or metadata surface that an operator view renders later, so the retrieval path may be invisible from the writer's side.
- **Cache-converted reflection**: a cache layer converts a reflected value into a stored one when an unkeyed input shapes a cached body for later callers, with the cache mechanics staying with the header-injection cache leaf.
- **Transport repetition**: across direct calls plus query APIs plus socket channels plus event streams plus background workers rides as a secondary matrix for write and retrieval.
- **Persistence boundary**: any persistence boundary belongs here even when the retrieval sink is a client sink.

## Reconnaissance

- **Reconnaissance scope**: reconnaissance maps the write side and the retrieval side as two separate inventories.
- **Write-entry inventory**: inventory write entries by submitting a benign marker through each entry carrier and recording which views echo it later.
- **Retrieval-view inventory**: inventory retrieval views by opening every persisted record type plus every file-serving view plus every message-rendering view and recording which one renders stored values.
- **Inline-file inventory**: inventory inline file handling by uploading a benign markup file and recording the served content type plus disposition plus sniffing behavior.
- **Pair recording**: record one write-to-view pair per persisted record type, and the inventory completes when every write entry maps to its retrieval views with no unmapped entry left.

## Detection Channels

- **Channel scope**: stored confirmation listens at retrieval time, so only the entries below are live here.
- **Later-view execution**: later-view execution after persistence through any sink confirms the write-then-retrieve flow.
- **Retrieval-response reflection**: shows the persisted marker rendering at a later view rather than in the write response.
- **Policy violation report**: policy violation report fired at the retrieval view binds execution to the persisted render.
- **Stored artifact observation**: records the persisted probe instance plus any inline file served with an active content type.
- **Delayed callback**: delayed callback carrying the per-payload marker from a browser user agent, which proves victim execution of a blind stored value rather than a backend fetch of the same value.
- **Sanitizer-output morph sample**: shows retrieval rendering turning sanitized markup into executable markup.

## Adversarial Capabilities

- **Prerequisites**: stored testing presupposes write access plus retrieval access plus cross-view operation, and it consumes all three.
- **Write input**: that another principal later views, or that the same principal views in a later session.
- **Retrieval-view reach**: reach the retrieval view directly or induce the victim principal to open it through normal workflow.
- **Inline file supply**: supply an inline file whose served content type plus disposition govern whether it executes on navigation.
- **Transport repetition**: repeat the write plus retrieval pair across direct calls plus query APIs plus socket channels plus event streams plus background workers.
- **Separate observations**: operate the two phases with separate observations so the write response never counts as retrieval evidence.

## Trust Assumptions

- **Exact-sink encoding**: every user-influenced string stays untrusted until strictly encoded for the exact sink at render time.
- **The agreement**: holds the data contract from entry through storage and retrieval to sink, keeps encoding bound to the exact sink context, keeps runtime policy enforced on executable sinks, and keeps rendering from exposing executable markup to a victim context.
- **The exposure**: session state plus token material leaks only when executable markup reaches such a context.
- **The failing clause**: this variant breaks the persistence clause because stored input crosses a storage boundary and renders at a later retrieval without exact-context encoding at retrieval time.

## Key Vulnerabilities

### Two-Phase Write-Then-Retrieve Mapping

- **Mapping rationale**: this variant bends S1 plus S2 because the parent source list names storage without describing a separate write action plus a later retrieval observation.
- **Marker submission**: submit a traceable marker through the write entry and confirm it only at the retrieval view.
- **Evidence rule**: treat same-response reflection of the marker as non-evidence and require a second-view render for a positive.
- **Retrieval completion**: the step completes when every write entry carries a retrieval verdict with its witness record.

### Retrieval Confirmation by Sink Locus

- **Sink-locus selection**: select confirmation by the sink that serves the retrieval view.
- **Server-render confirmation**: confirm server-rendered retrieval through the retrieval response showing the persisted value in an executable context.
- **Client-sink confirmation**: confirm client-sink retrieval through instrumented sink logging showing invocation with the persisted value.
- **Ownership rule**: persistent client-sink execution stays here under the mutex rule because the persistence boundary decides ownership, not the sink family.

### Inline File Stored Specialisation

- **Inline-file model**: treat an uploaded file served inline as a stored write whose retrieval is navigation.
- **Serving checks**: check served content type plus disposition plus sniffing behavior before claiming executability.
- **Positive condition**: claim a positive only when navigation to the served file executes the persisted markup in a victim context.

## Advanced Techniques

- **Retrieval-render focus**: advanced work here extends the retrieval render rather than replacing the two-phase map.
- **Sanitizer re-parsing**: feed sanitizer output back into the parser and compare the re-parsed tree against the pre-sanitizer tree to expose morphing that turns sanitized markup into executable markup.
- **Template-sink routing**: route template-expression sinks by the server-computation rule, where server-computed expression output routes elsewhere and browser-only template execution stays in this variant with retrieval confirmation.
- **Inline-file scoping**: scope uploaded inline files with disposition plus sniffing plus scheme checks so only inline active serving counts as executable retrieval.

## Bypass Techniques

- **Bypass scope**: bypass detail rides as aspects inside this variant and cross-references the defence-bypass family rather than restating it.
- **Encoding and case variants**: encoding plus case plus whitespace variants reach the retrieval render past a naive write-time filter.
- **Unclosed markup**: unclosed-markup shape reaches the retrieval parser past a filter that matches only balanced markup.
- **Handler variety**: handler-variety shapes reach execution when one sink family blocks direct script shapes.
- **Configuration gaps**: sanitizer configuration gaps plus policy gaps plus sink-type gaps surface through negative tests at retrieval time.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chaining basis**: stored execution chains forward into impact once retrieval confirmation is recorded.
- **Exfiltration**: exfiltrate session state plus token material to an attacker-controlled destination after retrieval execution.
- **State-changing request**: chain retrieval execution into a state-changing request that rides the victim session.
- **Interface overlay**: overlay a credential-collection interface on the retrieval view after confirming script execution.
- **Worker persistence**: persist a background worker from the retrieval view so later visits re-execute without a new write.

## Testing Methodology

Stored testing runs write-then-retrieve as the spine, because no later step is meaningful without a mapped pair.
1. **Map write-to-retrieval pairs** - submit one traceable marker per write entry and open every candidate retrieval view, and the step completes when every write entry maps to its retrieval views with no unmapped entry left.
2. **Trace persistence to sink** - record the source-to-storage-to-sink path per pair with its sink context label, and the step completes when every pair carries a stated path plus a context label.
3. **Classify retrieval context** - label the retrieval sink within markup plus attribute plus navigation plus script plus event plus style plus vector-graphics families, and the step completes when every pair carries a recorded context label that selects its probe family.
4. **Assess retrieval defenses** - inspect output encoding plus sanitizer plus content policy plus sink-type enforcement at retrieval time with negative tests, and the step completes when every pair carries a recorded defense model plus negative-test evidence.
5. **Craft retrieval probes** - build a small curated probe set per classified context using abstract shapes with placeholders plus encoding variants, and the step completes when every context owns a tied probe set with no catalog spraying.
6. **Confirm across transports** - repeat the write-then-retrieve pair across direct calls plus query APIs plus socket channels plus event streams plus background workers, and the step completes when every exercised path carries a retrieval verdict in the transport matrix.

## False Positives

- **Stop condition**: stop when retrieval evidence shows safe handling, because write acceptance without retrieval execution is not stored execution.
- **Exact-context encoding**: retrieval reflection safely encoded in the exact context with quoting intact.
- **Content policy**: content policy with nonces plus hashes and no inline plus handler execution, confirmed by violation-free retrieval.
- **Sink-type enforcement**: sink-type enforcement applied on retrieval sinks with strict creation policies.
- **Sanitizer strict mode**: sanitizer in strict mode with scheme allowlists, confirmed by morph-free re-parsing at retrieval.
- **Scriptable contexts**: disabled at the retrieval view with safe schemes enforced and no markup pass-through.

## Pro Tips

- **Pair discipline**: stored work rewards pair discipline plus small probe sets plus retrieval-side patience.
- **Map first**: prefer write-to-retrieval mapping before any probe crafting, and never count write-response reflection.
- **Traceable markers**: favor one traceable marker per write entry so retrieval attribution stays exact.
- **Curated probe sets**: keep a small curated probe set per retrieval context and iterate with encoding variants.
- **Retrieval re-parsing**: re-parse sanitizer output at retrieval time because morphing only shows in the second parse.
- **Verdict per path**: record one retrieval verdict per transport path so the matrix shows which paths persist.
- **Blind-carrier probes**: plant blind-carrier probes early and keep the listener open across the retrieval delay, because a stored value can surface hours or days after the write.

## Tooling

- **Tooling scope**: tooling here supports two-phase observation without naming concrete products.
- **Persistence crawler**: use a persistence-aware crawler that writes once and revisits every retrieval view in a later session.
- **Retrieval monitoring**: use retrieval-view monitoring that records response reflection plus sink invocation per pair.
- **Browser instrumentation**: use browser instrumentation that logs sink usage during retrieval rendering.
- **Violation collector**: use a violation collector that attributes each policy report to its retrieval view.

## Summary

Stored delivery crosses a storage boundary and executes at a later retrieval.
Map each write to its retrieval views, confirm through the sink that serves the view, and record one retrieval verdict per pair before claiming impact.
