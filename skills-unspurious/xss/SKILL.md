---
name: xss
description: XSS testing covering reflected, stored, and DOM-based vectors with CSP bypass techniques
metadata:
  version: 1.0.0
---

# XSS

Cross-site scripting is attacker-controlled input that reaches a render or execution sink without exact-context encoding, then executes in a victim's context. Delivery differs in shape: immediate reflection, persistence with later retrieval, or a client-only flow with no server round trip. Treat every caller-influenced string as untrusted until the exact sink encodes it and a runtime policy guards it.

## Attack Surface

**Delivery Shapes**
- Immediate reflection: the input returns in the same response that carried it
- Persistence: the input is stored and rendered later, in retrieval views, exports, notifications, inline file serving, or another principal's page
- Client-only: a client-side source reaches an executing sink with no server round trip

**Contexts**
- Markup text and nodes, attribute values, URL-bearing attributes, script strings, style contexts, and structured document nodes
- Markup formats treated as active content by a renderer

**Render Paths**
- Server render, client render, and hydration or re-render paths, which apply different encoding to the same value
- Message and document bodies rendered by restricted engines (mail, print, and report pipelines)
- Uploaded files served inline under an active content type

**Defenses to Bypass**
- Context encoding, sanitizer configuration, content-type and disposition handling, runtime script policy (CSP, Trusted Types), and URL scheme allowlists

## Reconnaissance

### Source and Sink Mapping

- Enumerate sources: URL components, referrer, message channels, storage, server data, and uploaded file names or metadata
- Trace each source to every sink that renders or evaluates it, including deferred, retrieval, and re-render paths
- Instrument markup-insertion and evaluation sinks to log which values reach them

See references/source-sink-families.md for the source and sink family lists with the context-to-encoding matrix.

### Context Classification

- Classify each sink: markup node, quoted or unquoted attribute, URL slot, script string, evaluator, style, or active-content document node
- Record the encoding the application applies at that sink, and test with a marker that survives the encoder but changes meaning when the encoder is missing
- Classify structured-document and message renderers separately; their execution rules differ from the browser's

### Defense Assessment

- Inspect encoding per sink rather than globally
- Identify the sanitizer and its configuration; feed its output back through the parser and inspect the result
- Inspect the runtime script policy: nonces and hashes, allowed origins, and whether every scriptable sink is covered
- Verify content-type and disposition handling for every served upload

### Trigger and Evidence Setup

- Keep a trigger URL or navigation for each stored payload so later-view execution is attributable
- Use a unique alphanumeric marker and search the no-marker baseline for it first, because a common word echoed by a help link reads as a reflection until the baseline clears it
- Record the beacon-field family that reaches a logged or stored surface and is later rendered: error messages, return and source parameters, identity fields, agent and referrer strings, addresses, and file names
- Operate a listener to receive exfiltration callbacks, with one marker per payload
- Snapshot the victim-context state that execution changes, so the proof shows effect rather than echo

## Detection Channels

- Same-response execution of a controlled marker, which is the reflected finding.
- Execution of a stored payload on a later retrieval view, which proves persistence.
- Execution of a stored payload in a second principal's session, which proves the cross-principal path.
- An instrumented sink invocation with no server reflection, which proves the client-only flow.
- Sanitizer output that re-parses into executable markup, which proves the round-trip gap.
- A served file that executes inline under its response type, which proves active-content delivery.
- A policy-violation report from the runtime guard, which maps which sinks the policy covers and which it misses.
- A callback receipt carrying the per-payload marker, which proves execution and exfiltration reach.
- A callback whose user agent belongs to a real browser, which separates victim execution from a backend fetch that merely followed the stored value.
- A state change in the victim context attributable to the executed payload, which proves effect beyond a script alert.
- Encoded output that stays inert under the exact sink context, which reads as correct encoding rather than a finding.

## Adversarial Capabilities

XSS testing presupposes an input the application reflects, stores, or reads on the client, plus a victim-context render to observe, and it consumes both.
- Submit candidate payloads through every carrier the surface accepts.
- Write a value a second principal later views, and hold that principal's session to observe execution.
- Influence client-side sources the application trusts: URL components, referrer, message channels, and storage.
- Instrument sinks to log values before they are rendered or evaluated.
- Operate a listener for exfiltration callbacks, with one marker per payload.
- Snapshot the victim-context state a successful payload changes.

## Trust Assumptions

The class rests on one agreement: every caller-influenced string stays untrusted until it is encoded for the exact sink that renders it, and whatever the application stores or reads on the client stays data on the way to that sink.
The agreement holds each render to exact-context encoding, holds sanitised output to a parser round trip that cannot morph into executable markup, holds persisted content to re-encoding on every later render, holds client-side data flow from source to sink to non-executable form, and holds the runtime script policy to enforcement across every scriptable sink.
Script execution in a victim context appears when a clause fails: an encoder misses the sink's context, sanitised output re-parses into executable markup, stored content renders where it was never encoded, or a client-side source reaches an executing sink.
Each variant breaks one clause: stored delivery breaks the persistence clause, and DOM delivery breaks the client-flow clause, while the immediate-reflection baseline rests on the exact-context encoding clause alone.

## Key Vulnerabilities

### Context Encoding Gaps

- An encoder belonging to a different context: a markup value placed into an attribute, a URL slot, or a script string
- Quoted and unquoted attribute handling, and attributes whose values become URLs or handlers
- Structured document nodes the renderer treats as active content
- Style and template contexts where a value reaches an expression rather than a literal

### Sanitizer Round Trip

- Sanitised output re-parsed by the client can repair into executable markup; feed the output back through the parser
- Parsing-ambiguity combinations where one namespace plus one foreign-content element re-parse into executable markup although each part alone is inert; enumerate the namespace-plus-element pairs the sanitizer's grammar does not model
- Markdown and diagram renderers post-process sanitized text and can reintroduce markup after the sanitizer has run, so test the renderer's own grammar as a second sanitizer
- Configuration gaps: allowed elements or attributes that form a gadget with an allowed handler
- Sanitizers that cover markup while other sinks stay live

### Stored Delivery

- Retrieval views, exports, notifications, and other principals' pages render content the writing path never encoded
- Files served inline from an upload path execute under their response type
- Content persisted across environments, caches, or exports re-renders where the original encoding assumptions no longer hold

### Client-Only Flow

- Sources: URL components, referrer, message channels, storage, server data consumed in the client, and the window-name property that survives cross-origin navigation
- Sinks: markup insertion, URL-bearing attributes, string-evaluating timers, dynamic code construction, and worker or document creation
- Re-render and hydration paths where the client renders server-encoded content under different rules

### Computed Expressions

- A sink that evaluates expressions rather than rendering text; where the computation happens on the server, the template class owns the step
- Legacy expression frameworks escape their sandbox through constructor access and evaluation helpers, and some accept an order-by form that needs no quoting; treat a client-only expression sink as escaping whenever a constructor or helper reference reaches evaluation
- Client-only expression evaluation stays here

### Restricted Renderers

- Message and document engines execute a reduced subset: markup, styles, and link actions rather than scripts
- Verify what a renderer allows before claiming execution

## Advanced Techniques

**Sink Instrumentation**
- Log every value that reaches a markup-insertion or evaluation sink, with the source that supplied it
- Instrumentation reveals flows the static source list misses

**Mutation Round Trip**
- Take sanitizer output, re-parse it, and compare the executable result with the input that was cleaned
- Parser repairs are the seam where cleaned markup regains active content

**Render-Path Parity**
- Test server render, client render, and hydration for the same value; each applies different encoding
- Re-test across transports and re-render clocks (cached, exported, and re-fetched views)

**Chained Impact**
- Prefer an impact-driven proof: a session-bound action, exfiltration to a listener, or a chain into another class

**Payload Discipline**
- Keep a small curated set per context and iterate on encoding rather than spraying catalogues

**Proxy Primitives**
- A markup-only injection can define or shadow a named element so a global the application trusts resolves to attacker-controlled structure; the `proxy-techniques-dom-clobbering` leaf owns that primitive plus its downstream gadget step, so name it there rather than restating it here
- Where the clobbered value later reaches a script, style, navigation, or state-changing sink, the chain continues in the class that owns that sink

## Bypass Techniques

**Filter and Parser Bypasses**
- Unclosed constructs a matching filter leaves alone yet the parser completes
- Parser repairs and mutation shapes the filter's grammar does not anticipate
- Case, whitespace, and encoding variants that survive the filter yet still parse
- Element and handler variety where the obvious family is stripped

**Runtime Policy Bypasses**
- Policy edges: a sink family left uncovered, wildcard origins, and dynamic constructs the policy allows
- Script gadgets in allowed code that turn data into execution
- Base or relative-URL retargeting that points script loading at content the policy does not govern
- Name the defence-bypass family where the bypass is generic rather than class-specific

**Sanitizer Configuration Abuse**
- Allowed elements or attributes that combine into a gadget
- Namespace and parser-context switches the sanitizer does not model

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Execution to session-bound actions: drive a state change the victim did not intend (compose with the CSRF class)
- Execution to credential and token exfiltration through the listener
- Stored execution to a persistent foothold in the victim's client state
- Execution to authorization effects where the application trusts client-readable state; the token class owns validation steps
- Execution to overlays and interface impersonation served from the trusted origin
- A self-only sink becomes a real finding when a cross-site request can drive the mutation that carries the payload; name the CSRF class at that step and re-read the false-positive verdict rather than filing self-XSS

## Testing Methodology

1. **Identify sources** - URL components, referrer, message channels, storage, server data, and file metadata
2. **Trace to sinks** - Map each source to every rendering or evaluating sink, including deferred and retrieval paths
3. **Classify context** - Markup node, attribute, URL slot, script string, evaluator, style, or active-content document
4. **Assess defenses** - Encoding per sink, sanitizer configuration, content-type handling, and runtime policy
5. **Craft minimal payloads** - One per context, with encoding and shape variants, tested with a controlled marker
6. **Exercise delivery shapes** - Immediate reflection, stored retrieval under a second principal, then client-only flow
7. **Repeat across transports** - Every render path and transport the application exposes
8. **Confirm the effect** - Execution plus a victim-context state change or a callback; every claim carries both

## Variants

- xss-stored - Persist the payload and prove execution on a later retrieval view, including inline file serving and multi-principal reads.
- xss-dom - Trace non-persistent client-only source-to-sink flows through sink instrumentation, including fragment sources and cross-document messages.

## False Positives

- Reflected content encoded exactly for its sink context
- A runtime policy with nonces or hashes and no configurable sink escape
- Enforced typed sinks with no bypassing gadget in allowed code
- Scriptable contexts disabled: no markup pass-through and safe URL schemes enforced
- Sanitized output that morphs but never executes on the real render path
- Execution that reproduces only in the tester's own session, with no second principal and no victim path
- A renderer that allows styles or links but never executes script

## Pro Tips

1. Start with context classification, not payload catalogues
2. Use sink instrumentation; it reveals flows the static source list misses
3. Keep a small curated payload set per context and iterate on encodings
4. Validate defenses by configuration inspection plus negative tests
5. Prefer impact-driven proofs (a session-bound action, exfiltration) over alert-style markers
6. Treat active-content document formats as first-class and test them separately from markup
7. Re-run tests under different render paths and transports; encoding often differs between them
8. Treat the runtime policy as a feature to violate: attempt a violation and read the report
9. Test stored payloads under a second principal; persistence is the common cross-principal path

## Summary

Context and sink decide execution: encode for the exact context, enforce runtime policy on every scriptable sink, and verify every render path. Small payloads with strong evidence beat payload catalogues.
