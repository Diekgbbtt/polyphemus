---
name: ssti
description: Server-side template injection across template engines with engine fingerprinting, sandbox escape, and RCE gadget chains
metadata:
  version: 1.0.0
---

# Server-Side Template Injection

Server-side template injection happens when user input reaches a template renderer as syntax instead of as data, so the renderer evaluates it in the host language with whatever objects the template exposes, and the impact is usually code execution on the rendering host. The discovery cost is low: an arithmetic differential probe decides evaluation in one response. The gadget chain afterwards differs per renderer family, so fingerprinting the renderer and mapping its exposed namespace are the load-bearing steps. Treat any value that reaches a renderer as source until the engine's sandbox proves otherwise.

## Attack Surface

**Input Shapes Reaching the Renderer**
- **Request values**: form fields, query, path, header, and cookie values, and structured body or schema variables.
- **File metadata**: filenames and file metadata processed by document, report, and notification templates.
- **Message fields**: message subject, body, and template-selector fields.
- **Theme and customisation endpoints**: style generation, dashboard widgets, webhook payload templates.
- **Markup and rich text**: markup or rich-text content rendered through a templating layer downstream.

**Patterns That Enable Injection**
- **String concatenation**: caller input concatenated into a template string before render instead of passed as a context value to a fixed template.
- **Template-editor surfaces**: where the template source itself is caller-controllable.
- **Format-string chains**: whose output is later evaluated through a template.
- **Structured document values**: configuration, imports, and message payloads whose strings are later evaluated.

**Render Consumers**
- **Render consumers**: preview panes, notification and email generation, document and report pipelines, dynamic dashboards, and any interface that renders caller content back to a user or a derived artifact.

## Reconnaissance

### Injection Points

- **Marker sweep**: submit a benign marker and search every rendered surface (page body, structured response, generated document, message, log) for verbatim reflection.
- **High-signal candidates**: preview panes, template editors, custom fields, and panels that claim to show the caller what their content will look like.
- **Error pages**: error pages and derived documents that quote template syntax confirm the value reached a renderer.

### Probe Grammar

- **Delimiter-family differential**: send one arithmetic differential per delimiter family the renderer may use; the family that evaluates returns the product while the others echo the syntax.
- **Second-expression confirmation**: confirm with a second expression so a coincidental echo cannot pass as evaluation.
- **Secondary fingerprints**: comment and filter syntax differences, error text naming the engine, and scoping forms that only evaluate inside a selection scope.
- **Look-alike discriminator**: a probe whose result differs between string repetition and numeric coercion separates two families the delimiter probe cannot tell apart.
- **Probe economy**: keep the probe grammar minimal; each probe is noise in logs and a wrong-family guess costs a step.

### Blind Setup

- **Stored-probe sweep**: store the probe in every field the identity can edit, then sweep every endpoint, view, report, and document that may render those fields, not only the accepting page.
- **Latency baseline**: establish a latency baseline before any delay-based probe, and gate the delay so only evaluation produces it.
- **Callback preflight**: preflight callback infrastructure and mint one token per probe; a callback is the primary oracle when nothing reflects.
- **Control recording**: record length and validator values for a control request so a masked render still yields a differential.

## Detection Channels

- **Same-response arithmetic**: same-response arithmetic evaluation, which decides the reflected finding.
- **Second-expression confirmation**: a second-expression confirmation, which excludes a coincidental echo.
- **Literal template syntax**: literal template syntax where the input should have rendered, which reads as data rather than evaluation.
- **Engine-identifying error text**: engine-identifying error text, which narrows the probe grammar to one delimiter family.
- **Stored-probe evaluation**: a stored probe that evaluates on a different endpoint, view, report, or document than the one that accepted it, which proves deferred rendering.
- **Calibrated latency**: response latency past a calibrated baseline for a gated delay payload, which proves evaluation when nothing reflects.
- **Token-carrying callback**: callback receipt carrying the per-probe token, which proves evaluation and outbound reach with no visible output.
- **Body-length shift**: body-length or validator shift between the control and the probe, which proves effect on masked content.
- **Computed rendered output**: rendered output carrying values computed from the probe rather than the probe text.
- **Readable artifact**: a file or stored artifact created by the evaluated expression and readable afterwards, which proves side-effect execution.
- **Execution artifact**: process-object rendering or an execution artifact instead of captured output, which proves the call ran when output capture fails.

## Adversarial Capabilities

- **SSTI testing**: presupposes an input that reaches a renderer as syntax, an observability oracle, and a reachable reflection root, and it consumes all three.
- **Syntax-reaching input**: reach an editable field, a template-editor surface, or a parameter whose value is concatenated into a template before render.
- **Session and second principal**: hold a low-privilege session for stored probes, and a second principal when the payload renders in another identity's view.
- **Callback infrastructure**: operate callback infrastructure and mint one token per probe.
- **Latency measurement**: measure latency against a calibrated baseline when no output is visible.
- **Namespace enumeration**: enumerate the objects the renderer exposes into the template namespace.
- **Artifact write**: write an artifact (a file or a stored value) that a follow-up request can read.

## Trust Assumptions

- **The agreement**: caller input is data the renderer inserts, never syntax the renderer evaluates, and the engine's sandbox keeps the host runtime out of reach of whatever the template receives.
- **Held clauses**: the agreement holds the template source to application-chosen content, holds the inserted value to a data position under the engine's escaping, holds the sandbox to a policy the template cannot rescind, and holds the render output to the channel that requested it.
- **Leak condition**: host-language position leaks when a clause fails: caller content reaches the template source, a value lands where the engine parses syntax, a reflection root reaches the runtime, or a stored value renders on a channel another identity reads.
- **The failing clause**: each variant reaches evaluation through a different observability: same-response arithmetic proof, or a deferred or silent render whose effect is inferred from another channel.

## Key Vulnerabilities

### Input-as-Syntax

- **String concatenation**: concatenating caller input into a template string before render, instead of passing it as a context value, turns the value into syntax.
- **Expression-context break-out**: when the value lands inside an existing expression rather than at a syntax boundary, the payload closes the surrounding context first and opens its own expression after it.
- **Template-editor surfaces**: where the template source is caller-controlled are the strongest form: the payload may need to escape nothing.
- **Name and selector resolution**: a renderer that loads a caller-supplied template name or fragment selects content the application did not choose.
- **Second-order pipelines**: stored values later evaluated through a templating layer, including format-string output, markup rendered downstream, and structured document values.

### Reflection to the Runtime

- **Namespace exposure**: template namespaces expose application objects; each reachable object is a reflection root into the host runtime.
- **Root enumeration**: enumerate the exposed roots first; a reflection walk from any of them reaches process, filesystem, and network capability.
- **Indirection recovery**: where direct attribute access is filtered, indirection recovers it: alternate accessors, aliasing, and string assembly.
- **Framework-injected globals**: are the shortest path and the most commonly missed.

### Sandbox Boundaries

- **Sandbox restriction**: sandboxes and filters restrict the object graph and the methods reachable from it; they rarely hold once a reflection root is exposed.
- **Enforcement model**: confirm the enforcement model before recording a negative: some policies restrict names, others restrict types, and some restrict only direct access.
- **Primitive recovery**: a removed primitive is usually reachable through another object already in scope.

### Stored and Deferred Render

- **Cross-view rendering**: a payload stored in one field may render on unrelated views: reports, exports, notifications, and other identities' dashboards.
- **Deferred processors**: reuse the same renderer with less filtering, so sweep every consumer of the stored value.
- **Derived-artifact proof**: where output goes to a document or message rather than a page, the proof moves to the derived artifact.

### Evaluation to Control

- **Shortest chain**: once evaluation is proven, the shortest chain to a shell-equivalent primitive is the finding.
- **Side-channel proof**: where execution returns no output, prove the effect through a side channel: a computed file, a callback, or a gated delay.
- **File write and read**: file write plus a follow-up read through the path-traversal class converts a blind evaluation into content.

## Advanced Techniques

**Oracle Discipline**
- **Evaluation proof**: prove evaluation with the differential and a second expression before attempting any gadget.
- **Family confirmation**: confirm the renderer family once; repeating fingerprint probes adds noise without narrowing the chain.

**Reflection Order**
- **Root spray**: spray the exposed roots first, then walk reflection from whichever root answers.
- **Capability mapping**: map the gadget pool by capability (process, filesystem, network) rather than by object name.

**Deferred Trigger Discipline**
- **Store and sweep**: store, then sweep; a literal render on the accepting page proves nothing about other consumers.
- **Timing correlation**: attribute a deferred effect by timing correlation between the plant and the render.

**Escape Recovery**
- **Alternate capability**: when one primitive is filtered, reach the same capability through another object, an alternate accessor, or a conversion.

## Bypass Techniques

**Filter and Parser Evasion**
- **Whitespace and case variants**: whitespace, case, and operator-spacing variants inside expressions.
- **Token splitting**: token splitting and assembly so denylisted identifiers never appear literally.
- **Encoding layering**: choose the encoding that survives every upstream decode yet is decoded before render.
- **Precedence games**: precedence and parenthesisation games that keep the expression equivalent.
- **Truncation forms**: truncation and normalisation forms that pass a pre-template filter yet parse intact.

**Sandbox Escape**
- **Attribute indirection**: where direct access is filtered.
- **Class walk**: recovery of filtered primitives through a class walk from any in-scope object.
- **Aliasing**: reach the same callable under a name the policy does not cover.
- **Implicit conversion**: an object whose string conversion triggers the dangerous call.

**Chained Evaluation**
- **Multi-stage pipelines**: where one renderer's output feeds another; a payload valid in both stages survives.
- **Markup stages**: markup and rich-text stages that carry a payload through a filter to the template stage.
- **Format-string stage**: format-string stage before the template stage: inert as a format string, live as a template.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Shell-equivalent control**: template evaluation to a shell-equivalent primitive on the rendering host, then durable control.
- **File write and read**: template evaluation plus file write, then the path-traversal class to read the artifact or reach served content.
- **Credential stores**: template evaluation to credential and configuration stores, then movement to other systems.
- **Decode path**: template evaluation to a decode path, where the host runtime exposes the deserialization entry.
- **Prototype pollution**: shared-object pollution consumed by downstream render logic as configuration, where the prototype class owns the pollution step.

## Testing Methodology

1. **Find templated input** - Preview panes, editors, notification and document generation, dashboards, and custom fields
2. **Fingerprint the renderer** - One differential per delimiter family, then a second probe that separates look-alike families
3. **Confirm evaluation** - A computed result rather than literal syntax, with a second expression excluding coincidence
4. **Probe the namespace** - Enumerate exposed roots and the sandbox policy; record the gadget pool or its denial
5. **Enumerate gadgets** - Reflection walks from each answering root to process, filesystem, and network capability
6. **Reach control** - The shortest chain to a shell-equivalent primitive, or a definitive negative
7. **Prove the effect** - Callback, gated delay, or a written artifact; every step carries a verdict

## Variants

- ssti-reflected-evaluation - Confirm same-response evaluation through the differential probe grammar and reachable-global gadget chains, with a second expression excluding coincidence.
- ssti-blind-evaluation - Infer evaluation with no visible reflection through stored-payload sweeps, timing, callbacks, and length differentials.

## False Positives

- **Literal reflection**: template syntax reflected literally; that is a markup-injection shape, not server-side evaluation.
- **Inert sandboxes**: sandboxes where reflection succeeds but expose nothing beyond inert values.
- **Client-side renderers**: whose impact is markup injection in a browser rather than host execution.
- **Build-time-only templating**: with no caller input reaching the build.
- **Escaped output**: output escaped before display, which masks evaluation as markup-shaped reflection; verify with an expression that returns a computed value.
- **Coincidental match**: a single coincidental numeric match without the second-expression confirmation.

## Pro Tips

- **Second-expression confirmation**: confirm with a second expression before celebrating; one reflected product could be coincidence.
- **Fingerprint first**: fingerprint the family first, enumerate gadgets second; wrong-family probes waste requests and add noise.
- **Global spray**: spray the framework's exposed globals before attempting a class walk; the shortest root wins.
- **Indirection**: sandbox escapes are usually one indirection away: alternate accessors, constructor traversal, string assembly.
- **Delay and callback oracles**: when nothing reflects, use delay and callback oracles exactly as in the blind-injection classes.
- **Consumer sweep**: stored payloads render in other identities' views and in generated documents; sweep every consumer.
- **Deferred generators**: document, notification, and report generation often reuses the same renderer with weaker validation.
- **File write and read**: a file write plus a read through the path-traversal class turns a blind evaluation into content.

## Summary

Server-side template injection is the difference between a value and syntax: the payload runs on the server, in the host language, with whatever objects the renderer exposes.
Confirm evaluation with an arithmetic differential, map the exposed namespace, and treat any caller input that reaches a renderer as source until the sandbox proves otherwise.
