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
- Form fields, query, path, header, and cookie values, and structured body or schema variables
- Filenames and file metadata processed by document, report, and notification templates
- Message subject, body, and template-selector fields
- Theme and customisation endpoints: style generation, dashboard widgets, webhook payload templates
- Markup or rich-text content rendered through a templating layer downstream

**Patterns That Enable Injection**
- Caller input concatenated into a template string before render instead of passed as a context value to a fixed template
- Template-editor surfaces where the template source itself is caller-controllable
- Format-string chains whose output is later evaluated through a template
- Structured document values (configuration, imports, message payloads) whose strings are later evaluated

**Render Consumers**
- Preview panes, notification and email generation, document and report pipelines, dynamic dashboards, and any interface that renders caller content back to a user or a derived artifact

## Reconnaissance

### Injection Points

- Submit a benign marker and search every rendered surface (page body, structured response, generated document, message, log) for verbatim reflection
- High-signal candidates: preview panes, template editors, custom fields, and panels that claim to show the caller what their content will look like
- Error pages and derived documents that quote template syntax confirm the value reached a renderer

### Probe Grammar

- Send one arithmetic differential per delimiter family the renderer may use; the family that evaluates returns the product while the others echo the syntax
- Confirm with a second expression so a coincidental echo cannot pass as evaluation
- Secondary fingerprints: comment and filter syntax differences, error text naming the engine, and scoping forms that only evaluate inside a selection scope
- Keep the probe grammar minimal; each probe is noise in logs and a wrong-family guess costs a step

### Blind Setup

- Store the probe in every field the identity can edit, then sweep every endpoint, view, report, and document that may render those fields, not only the accepting page
- Establish a latency baseline before any delay-based probe, and gate the delay so only evaluation produces it
- Preflight callback infrastructure and mint one token per probe; a callback is the primary oracle when nothing reflects
- Record length and validator values for a control request so a masked render still yields a differential

## Detection Channels

- Same-response arithmetic evaluation, which decides the reflected finding.
- A second-expression confirmation, which excludes a coincidental echo.
- Literal template syntax where the input should have rendered, which reads as data rather than evaluation.
- Engine-identifying error text, which narrows the probe grammar to one delimiter family.
- A stored probe that evaluates on a different endpoint, view, report, or document than the one that accepted it, which proves deferred rendering.
- Response latency past a calibrated baseline for a gated delay payload, which proves evaluation when nothing reflects.
- Callback receipt carrying the per-probe token, which proves evaluation and outbound reach with no visible output.
- Body-length or validator shift between the control and the probe, which proves effect on masked content.
- Rendered output carrying values computed from the probe rather than the probe text.
- A file or stored artifact created by the evaluated expression and readable afterwards, which proves side-effect execution.
- Process-object rendering or an execution artifact instead of captured output, which proves the call ran when output capture fails.

## Adversarial Capabilities

SSTI testing presupposes an input that reaches a renderer as syntax, an observability oracle, and a reachable reflection root, and it consumes all three.
- Reach an editable field, a template-editor surface, or a parameter whose value is concatenated into a template before render.
- Hold a low-privilege session for stored probes, and a second principal when the payload renders in another identity's view.
- Operate callback infrastructure and mint one token per probe.
- Measure latency against a calibrated baseline when no output is visible.
- Enumerate the objects the renderer exposes into the template namespace.
- Write an artifact (a file or a stored value) that a follow-up request can read.

## Trust Assumptions

The class rests on one agreement: caller input is data the renderer inserts, never syntax the renderer evaluates, and the engine's sandbox keeps the host runtime out of reach of whatever the template receives.
The agreement holds the template source to application-chosen content, holds the inserted value to a data position under the engine's escaping, holds the sandbox to a policy the template cannot rescind, and holds the render output to the channel that requested it.
Host-language position leaks when a clause fails: caller content reaches the template source, a value lands where the engine parses syntax, a reflection root reaches the runtime, or a stored value renders on a channel another identity reads.
Each variant reaches evaluation through a different observability: same-response arithmetic proof, or a deferred or silent render whose effect is inferred from another channel.

## Key Vulnerabilities

### Input-as-Syntax

- Concatenating caller input into a template string before render, instead of passing it as a context value, turns the value into syntax
- Template-editor surfaces where the template source is caller-controlled are the strongest form: the payload may need to escape nothing
- Name and selector resolution: a renderer that loads a caller-supplied template name or fragment selects content the application did not choose
- Second-order pipelines: stored values later evaluated through a templating layer, including format-string output, markup rendered downstream, and structured document values

### Reflection to the Runtime

- Template namespaces expose application objects; each reachable object is a reflection root into the host runtime
- Enumerate the exposed roots first; a reflection walk from any of them reaches process, filesystem, and network capability
- Where direct attribute access is filtered, indirection recovers it: alternate accessors, aliasing, and string assembly
- Framework-injected globals are the shortest path and the most commonly missed

### Sandbox Boundaries

- Sandboxes and filters restrict the object graph and the methods reachable from it; they rarely hold once a reflection root is exposed
- Confirm the enforcement model before recording a negative: some policies restrict names, others restrict types, and some restrict only direct access
- A removed primitive is usually reachable through another object already in scope

### Stored and Deferred Render

- A payload stored in one field may render on unrelated views: reports, exports, notifications, and other identities' dashboards
- Deferred processors reuse the same renderer with less filtering, so sweep every consumer of the stored value
- Where output goes to a document or message rather than a page, the proof moves to the derived artifact

### Evaluation to Control

- Once evaluation is proven, the shortest chain to a shell-equivalent primitive is the finding
- Where execution returns no output, prove the effect through a side channel: a computed file, a callback, or a gated delay
- File write plus a follow-up read through the path-traversal class converts a blind evaluation into content

## Advanced Techniques

**Oracle Discipline**
- Prove evaluation with the differential and a second expression before attempting any gadget
- Confirm the renderer family once; repeating fingerprint probes adds noise without narrowing the chain

**Reflection Order**
- Spray the exposed roots first, then walk reflection from whichever root answers
- Map the gadget pool by capability (process, filesystem, network) rather than by object name

**Deferred Trigger Discipline**
- Store, then sweep; a literal render on the accepting page proves nothing about other consumers
- Attribute a deferred effect by timing correlation between the plant and the render

**Escape Recovery**
- When one primitive is filtered, reach the same capability through another object, an alternate accessor, or a conversion

## Bypass Techniques

**Filter and Parser Evasion**
- Whitespace, case, and operator-spacing variants inside expressions
- Token splitting and assembly so denylisted identifiers never appear literally
- Encoding layering: choose the encoding that survives every upstream decode yet is decoded before render
- Precedence and parenthesisation games that keep the expression equivalent
- Truncation and normalisation forms that pass a pre-template filter yet parse intact

**Sandbox Escape**
- Attribute indirection where direct access is filtered
- Recovery of filtered primitives through a class walk from any in-scope object
- Aliasing: reach the same callable under a name the policy does not cover
- Implicit conversion: an object whose string conversion triggers the dangerous call

**Chained Evaluation**
- Multi-stage pipelines where one renderer's output feeds another; a payload valid in both stages survives
- Markup and rich-text stages that carry a payload through a filter to the template stage
- Format-string stage before the template stage: inert as a format string, live as a template

## Chaining Attacks

- Template evaluation to a shell-equivalent primitive on the rendering host, then durable control
- Template evaluation plus file write, then the path-traversal class to read the artifact or reach served content
- Template evaluation to credential and configuration stores, then movement to other systems
- Template evaluation to a decode path, where the host runtime exposes the deserialization entry
- Shared-object pollution consumed by downstream render logic as configuration, where the prototype class owns the pollution step

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

- Template syntax reflected literally; that is a markup-injection shape, not server-side evaluation
- Sandboxes where reflection succeeds but expose nothing beyond inert values
- Client-side renderers, whose impact is markup injection in a browser rather than host execution
- Build-time-only templating with no caller input reaching the build
- Output escaped before display, which masks evaluation as markup-shaped reflection; verify with an expression that returns a computed value
- A single coincidental numeric match without the second-expression confirmation

## Pro Tips

1. Confirm with a second expression before celebrating; one reflected product could be coincidence
2. Fingerprint the family first, enumerate gadgets second; wrong-family probes waste requests and add noise
3. Spray the framework's exposed globals before attempting a class walk; the shortest root wins
4. Sandbox escapes are usually one indirection away: alternate accessors, constructor traversal, string assembly
5. When nothing reflects, use delay and callback oracles exactly as in the blind-injection classes
6. Stored payloads render in other identities' views and in generated documents; sweep every consumer
7. Document, notification, and report generation often reuses the same renderer with weaker validation
8. A file write plus a read through the path-traversal class turns a blind evaluation into content

## Summary

Server-side template injection is the difference between a value and syntax: the payload runs on the server, in the host language, with whatever objects the renderer exposes. Confirm evaluation with an arithmetic differential, map the exposed namespace, and treat any caller input that reaches a renderer as source until the sandbox proves otherwise.
