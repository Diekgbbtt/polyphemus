---
name: xss-dom
description: DOM XSS tracing non-persistent client-only source-to-sink flows through instrumented sinks, fragment sources, or cross-document messages.
metadata:
  version: 1.0.0
---

# DOM XSS

DOM delivery flows from a client-side source to an executable sink without server reflection and without persistence.
This variant proves execution by instrumenting the browser and observing sink invocation with the attacker-influenced value.
The impact goal is victim-context execution with sink-log evidence rather than response-body evidence.

## Attack Surface

Applicability centers on a non-persistent client-only flow from source to sink with no server reflection and no storage boundary.
The source is a client-observable value such as a fragment identifier or a query string read in the browser or a cross-document message or a client store read within one page lifetime or the window-name property that survives cross-origin navigation.
The sink is a client rendering or execution primitive such as markup insertion or attribute binding or navigation handling or string evaluation or worker creation.
The flow completes within one page lifetime without a write-then-retrieve pair.
Any technique with a persistence boundary belongs to stored even when its sink is a client sink, so this variant owns only the non-persistent remainder.

## Reconnaissance

Reconnaissance inventories client sources and their reachable sinks without touching the server body.
Enumerate client sources by exercising fragment values plus query values read in the browser plus cross-document messages plus window-name values plus client store values and recording which ones reach script.
Enumerate sinks by instrumenting markup insertion plus library pre-filters that mutate markup before insertion plus framework bindings that mark a value as safe markup plus attribute binding plus navigation handling plus evaluation primitives, and recording which sink fires per source.
Record one source-to-sink path per flow with its observation hook, and the inventory completes when every reachable client source maps to its sinks with no unmapped source left.

## Detection Channels

DOM confirmation listens to instrumented sinks, so only the entries below are live here.
- Instrumented sink invocation without server reflection confirms the client-only flow.
- Source-to-sink trace log binds one client source value to one sink call within one page lifetime.
- Policy violation report fired by the client-only render binds execution to sink invocation rather than to a response body.
- Mutated markup sample shows the client parser turning the sourced value into executable markup.

## Adversarial Capabilities

DOM testing presupposes client-source influence plus instrumented observation plus navigation control, and it consumes all three.
- Influence a client-side source such as a fragment value or a cross-document message without a server round trip.
- Drive the browser through the flow that carries the sourced value to the sink.
- Instrument sinks so each invocation logs its argument plus its stack location.
- Operate without persistence and without server reflection while keeping the full trace in one page lifetime.
- Repeat the flow across render paths such as server render plus client render plus hydration to expose path-specific sinks.

## Trust Assumptions

Every user-influenced string stays untrusted until strictly encoded for the exact sink at render time.
The agreement holds the data contract from entry through storage and retrieval to sink, keeps encoding bound to the exact sink context, keeps runtime policy enforced on executable sinks, and keeps rendering from exposing executable markup to a victim context.
Session state plus token material leaks only when executable markup reaches such a context.
This variant breaks the server-mediation clause because a client-side source reaches an executable sink without server reflection and executes without exact-context encoding at sink invocation.

## Key Vulnerabilities

### Browser-Instrumented Source-to-Sink Tracing

This variant bends S2 because the parent mapping assumes server-mediated flow while DOM confirmation needs browser sink instrumentation.
Hook the candidate sinks before driving the sourced value and record each invocation with its argument.
Treat response-body reflection as non-evidence and require a sink-log entry for a positive.
The step completes when every client source carries a trace verdict with its sink log.

### Sink-Invocation Confirmation Only

Confirm exclusively through sink invocation within one page lifetime.
Bind the sourced value to the sink argument and record the sink family plus the context label at invocation time.
Treat absence of server reflection as expected rather than as a gap, because this variant owns only flows with no server reflection.
The step completes when every claimed flow shows a sink invocation with the sourced value present.

### Client-Source Families

Cover fragment-driven plus browser-read query plus cross-document message plus window-name plus client-store flows under one tracing procedure.
Vary only the driver that sets the source value while keeping the instrumentation fixed.
Message flows need their sender and listener shapes enumerated: a partial origin check by substring, suffix, or unanchored pattern is bypassable with a look-alike host, so a weak check is still a finding.
Where several listeners exist, record which one fires per message and whether a race between two handlers lets a message reach the wrong sink.
Record the source family per trace so the matrix shows which families reach which sinks.

## Advanced Techniques

Advanced work here sharpens tracing rather than adding persistence.
Feed sanitizer output back into the client parser and compare the re-parsed tree to expose morphing that turns sanitized markup into executable markup at the sink.
Route template-expression sinks by the server-computation rule, where server-computed expression output routes elsewhere and browser-only template execution stays in this variant with sink-log confirmation.
Scope evaluation sinks by confirming argument execution rather than mere argument presence, because presence without invocation is not execution.

## Bypass Techniques

Bypass detail rides as aspects inside this variant and cross-references the defence-bypass family rather than restating it.
- Encoding plus case plus whitespace variants reach the client sink past a naive source filter.
- Unclosed-markup shape reaches the client parser past a filter that matches only balanced markup.
- Handler-variety shapes reach execution when one sink family blocks direct script shapes.
- Sanitizer configuration gaps plus policy gaps plus sink-type gaps surface through sink-log positives with negative-test controls.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

DOM execution chains forward into impact once sink invocation is recorded.
- Exfiltrate session state plus token material to an attacker-controlled destination after sink execution.
- Chain sink execution into a state-changing request that rides the victim session.
- Overlay a credential-collection interface on the affected view after confirming sink invocation.
- Register a background worker from the sink execution so later visits re-execute within the same origin, and let that worker intercept later fetches for the same origin.

## Testing Methodology

DOM testing runs instrumentation first and everything else follows, because no later step is meaningful without a trusted sink log.
1. **Inventory client sources** - exercise each fragment plus browser-read query plus cross-document message plus client store candidate with a traceable marker, and the step completes when every reachable source maps to a named entry point with no unmapped source left.
2. **Instrument and trace to sinks** - hook markup insertion plus attribute binding plus navigation handling plus evaluation primitives then drive each source, and the step completes when every source carries a stated source-to-sink path plus a sink log or a recorded negative.
3. **Classify sink context** - label the invoked sink within markup plus attribute plus navigation plus script plus event plus style plus vector-graphics families, and the step completes when every trace carries a recorded context label that selects its probe family.
4. **Assess client defenses** - inspect output encoding plus sanitizer plus content policy plus sink-type enforcement at the sink with negative tests, and the step completes when every trace carries a recorded defense model plus negative-test evidence.
5. **Craft sink probes** - build a small curated probe set per classified context using abstract shapes with placeholders plus encoding variants, and the step completes when every context owns a tied probe set with no catalog spraying.
6. **Confirm across render paths** - repeat each source-to-sink flow across server render plus client render plus hydration plus socket plus event-stream delivery, and the step completes when every exercised path carries a sink-invocation verdict in the transport matrix.

## False Positives

Stop when sink evidence shows safe handling, because source reachability without sink invocation is not DOM execution.
- Sourced value safely encoded for the exact sink with quoting intact at invocation time.
- Content policy with nonces plus hashes and no inline plus handler execution, confirmed by violation-free traces.
- Sink-type enforcement applied on instrumented sinks with strict creation policies.
- Sanitizer in strict mode with scheme allowlists, confirmed by morph-free re-parsing at the sink.
- Sinks never invoked with the sourced value across all instrumented runs, which signals non-flow rather than blocked execution.

## Pro Tips

DOM work rewards instrumentation discipline plus small probe sets plus source control.
1. Prefer context classification before any probe driving, and hook sinks before sending values.
2. Favor one traceable marker per client source so sink attribution stays exact.
3. Keep a small curated probe set per sink context and iterate with encoding variants.
4. Re-run flows across render paths because hydration plus client render expose sinks that server markup hides.
5. Record violation reports alongside sink logs so policy evidence corroborates each trace.

## Tooling

Tooling here supports client-only observation without naming concrete products.
Use browser instrumentation that logs sink invocation with arguments plus stack locations.
Use a client-source driver that sets fragment values plus messages plus store values deterministically.
Use a render-path runner that repeats each flow across server render plus client render plus hydration.
Use a violation collector that attributes each policy report to its sink trace.

## Summary

DOM delivery runs from client source to sink with no server reflection and no persistence.
Instrument the sinks first, bind each source value to its invocation log, and record one trace verdict per flow before claiming impact.
