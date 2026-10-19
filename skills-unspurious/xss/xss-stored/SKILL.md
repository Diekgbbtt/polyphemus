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

Applicability centers on any write entry whose value persists and renders at a later retrieval through any sink.
The write entry accepts attacker-influenced input through a direct field or an indirect carrier such as a message queue item or a stored document.
The retrieval view renders the persisted value through server markup or through a client sink without requiring same-response reflection.
The viewing principal may be the writer or a different principal who later opens the persisted record.
Inline file serving with an active content type rides inside this variant as a stored specialisation with content-type plus disposition plus sniffing checks.
A blind write entry carries the value into a log, error, or metadata surface that an operator view renders later, so the retrieval path may be invisible from the writer's side.
A cache layer converts a reflected value into a stored one when an unkeyed input shapes a cached body for later callers, with the cache mechanics staying with the header-injection cache leaf.
Transport repetition across direct calls plus query APIs plus socket channels plus event streams plus background workers rides as a secondary matrix for write and retrieval.
Any persistence boundary belongs here even when the retrieval sink is a client sink.

## Reconnaissance

Reconnaissance maps the write side and the retrieval side as two separate inventories.
Inventory write entries by submitting a benign marker through each entry carrier and recording which views echo it later.
Inventory retrieval views by opening every persisted record type plus every file-serving view plus every message-rendering view and recording which one renders stored values.
Inventory inline file handling by uploading a benign markup file and recording the served content type plus disposition plus sniffing behavior.
Record one write-to-view pair per persisted record type, and the inventory completes when every write entry maps to its retrieval views with no unmapped entry left.

## Detection Channels

Stored confirmation listens at retrieval time, so only the entries below are live here.
- Later-view execution after persistence through any sink confirms the write-then-retrieve flow.
- Retrieval-response reflection shows the persisted marker rendering at a later view rather than in the write response.
- Policy violation report fired at the retrieval view binds execution to the persisted render.
- Stored artifact observation records the persisted probe instance plus any inline file served with an active content type.
- Delayed callback carrying the per-payload marker from a browser user agent, which proves victim execution of a blind stored value rather than a backend fetch of the same value.
- Sanitizer-output morph sample shows retrieval rendering turning sanitized markup into executable markup.

## Adversarial Capabilities

Stored testing presupposes write access plus retrieval access plus cross-view operation, and it consumes all three.
- Write input that another principal later views, or that the same principal views in a later session.
- Reach the retrieval view directly or induce the victim principal to open it through normal workflow.
- Supply an inline file whose served content type plus disposition govern whether it executes on navigation.
- Repeat the write plus retrieval pair across direct calls plus query APIs plus socket channels plus event streams plus background workers.
- Operate the two phases with separate observations so the write response never counts as retrieval evidence.

## Trust Assumptions

Every user-influenced string stays untrusted until strictly encoded for the exact sink at render time.
The agreement holds the data contract from entry through storage and retrieval to sink, keeps encoding bound to the exact sink context, keeps runtime policy enforced on executable sinks, and keeps rendering from exposing executable markup to a victim context.
Session state plus token material leaks only when executable markup reaches such a context.
This variant breaks the persistence clause because stored input crosses a storage boundary and renders at a later retrieval without exact-context encoding at retrieval time.

## Key Vulnerabilities

### Two-Phase Write-Then-Retrieve Mapping

This variant bends S1 plus S2 because the parent source list names storage without describing a separate write action plus a later retrieval observation.
Submit a traceable marker through the write entry and confirm it only at the retrieval view.
Treat same-response reflection of the marker as non-evidence and require a second-view render for a positive.
The step completes when every write entry carries a retrieval verdict with its witness record.

### Retrieval Confirmation by Sink Locus

Select confirmation by the sink that serves the retrieval view.
Confirm server-rendered retrieval through the retrieval response showing the persisted value in an executable context.
Confirm client-sink retrieval through instrumented sink logging showing invocation with the persisted value.
Persistent client-sink execution stays here under the mutex rule because the persistence boundary decides ownership, not the sink family.

### Inline File Stored Specialisation

Treat an uploaded file served inline as a stored write whose retrieval is navigation.
Check served content type plus disposition plus sniffing behavior before claiming executability.
Claim a positive only when navigation to the served file executes the persisted markup in a victim context.

## Advanced Techniques

Advanced work here extends the retrieval render rather than replacing the two-phase map.
Feed sanitizer output back into the parser and compare the re-parsed tree against the pre-sanitizer tree to expose morphing that turns sanitized markup into executable markup.
Route template-expression sinks by the server-computation rule, where server-computed expression output routes elsewhere and browser-only template execution stays in this variant with retrieval confirmation.
Scope uploaded inline files with disposition plus sniffing plus scheme checks so only inline active serving counts as executable retrieval.

## Bypass Techniques

Bypass detail rides as aspects inside this variant and cross-references the defence-bypass family rather than restating it.
- Encoding plus case plus whitespace variants reach the retrieval render past a naive write-time filter.
- Unclosed-markup shape reaches the retrieval parser past a filter that matches only balanced markup.
- Handler-variety shapes reach execution when one sink family blocks direct script shapes.
- Sanitizer configuration gaps plus policy gaps plus sink-type gaps surface through negative tests at retrieval time.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Stored execution chains forward into impact once retrieval confirmation is recorded.
- Exfiltrate session state plus token material to an attacker-controlled destination after retrieval execution.
- Chain retrieval execution into a state-changing request that rides the victim session.
- Overlay a credential-collection interface on the retrieval view after confirming script execution.
- Persist a background worker from the retrieval view so later visits re-execute without a new write.

## Testing Methodology

Stored testing runs write-then-retrieve as the spine, because no later step is meaningful without a mapped pair.
1. **Map write-to-retrieval pairs** - submit one traceable marker per write entry and open every candidate retrieval view, and the step completes when every write entry maps to its retrieval views with no unmapped entry left.
2. **Trace persistence to sink** - record the source-to-storage-to-sink path per pair with its sink context label, and the step completes when every pair carries a stated path plus a context label.
3. **Classify retrieval context** - label the retrieval sink within markup plus attribute plus navigation plus script plus event plus style plus vector-graphics families, and the step completes when every pair carries a recorded context label that selects its probe family.
4. **Assess retrieval defenses** - inspect output encoding plus sanitizer plus content policy plus sink-type enforcement at retrieval time with negative tests, and the step completes when every pair carries a recorded defense model plus negative-test evidence.
5. **Craft retrieval probes** - build a small curated probe set per classified context using abstract shapes with placeholders plus encoding variants, and the step completes when every context owns a tied probe set with no catalog spraying.
6. **Confirm across transports** - repeat the write-then-retrieve pair across direct calls plus query APIs plus socket channels plus event streams plus background workers, and the step completes when every exercised path carries a retrieval verdict in the transport matrix.

## False Positives

Stop when retrieval evidence shows safe handling, because write acceptance without retrieval execution is not stored execution.
- Retrieval reflection safely encoded in the exact context with quoting intact.
- Content policy with nonces plus hashes and no inline plus handler execution, confirmed by violation-free retrieval.
- Sink-type enforcement applied on retrieval sinks with strict creation policies.
- Sanitizer in strict mode with scheme allowlists, confirmed by morph-free re-parsing at retrieval.
- Scriptable contexts disabled at the retrieval view with safe schemes enforced and no markup pass-through.

## Pro Tips

Stored work rewards pair discipline plus small probe sets plus retrieval-side patience.
1. Prefer write-to-retrieval mapping before any probe crafting, and never count write-response reflection.
2. Favor one traceable marker per write entry so retrieval attribution stays exact.
3. Keep a small curated probe set per retrieval context and iterate with encoding variants.
4. Re-parse sanitizer output at retrieval time because morphing only shows in the second parse.
5. Record one retrieval verdict per transport path so the matrix shows which paths persist.
6. Plant blind-carrier probes early and keep the listener open across the retrieval delay, because a stored value can surface hours or days after the write.

## Tooling

Tooling here supports two-phase observation without naming concrete products.
Use a persistence-aware crawler that writes once and revisits every retrieval view in a later session.
Use retrieval-view monitoring that records response reflection plus sink invocation per pair.
Use browser instrumentation that logs sink usage during retrieval rendering.
Use a violation collector that attributes each policy report to its retrieval view.

## Summary

Stored delivery crosses a storage boundary and executes at a later retrieval.
Map each write to its retrieval views, confirm through the sink that serves the view, and record one retrieval verdict per pair before claiming impact.
