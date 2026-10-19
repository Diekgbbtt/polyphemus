---
name: ssti-reflected-evaluation
description: Reflected template evaluation confirmed by same-response arithmetic proof across differential probing, error-text disclosure, and reachable-global gadget chains.
metadata:
  version: 1.0.0
---

# Reflected Template Evaluation

Reflected evaluation confirms server-side template injection when request-derived input is parsed as template syntax and the computed result appears in the same response.
The differential probe is the load-bearing move because exactly one probe grammar evaluates per engine family while the rest echo literally.
Treat any same-response arithmetic proof as injection-shaped until the coincidence and escaping checks below rule it out.

## Attack Surface

- **Applicability**: request-derived input reaches template source before render rather than arriving as a bound context variable.
- **Candidate sinks**: editable text fields, message and preview panes, generated documents and emails, theme and customization flows, and file metadata consumed by report templates.
- **Second-order pipelines**: values pass through an intermediate encoding or markup stage and are evaluated as template syntax downstream.
- **Template-editor features**: the template itself is attacker-controlled there, so direct source authority exists.
- **Out-of-scope frameworks**: frameworks that bind model variables as inert values and never re-evaluate them stay outside this variant even when the same delimiters appear.

## Reconnaissance

### Injection Points

- **Injection-point sweep**: submit a benign marker string through every candidate sink and record where it reflects verbatim across bodies, documents, emails, and error pages.
- **Surface prioritisation**: prioritise surfaces that visibly template input such as preview panels and generated views because they carry the highest signal.
- **Error-page inspection**: inspect error pages for engine disclosure because stack content often names the rendering layer.

### Engine Fingerprinting

- **Delimiter-family probe**: run one arithmetic probe per delimiter family and record which single grammar evaluates while the others echo literally.
- **Second-probe confirmation**: confirm the fingerprint with a second probe in a different arithmetic shape so coincidence cannot explain the first result.
- **Knowledge-base lookup**: consult the operator knowledge base for the engine-specific gadget that follows from the confirmed family.
- **Secondary differentials**: record comment-syntax and filter-syntax differentials as secondary confirmation because each family spells them differently.

## Detection Channels

- **Same-response arithmetic proof**: fires when a probe renders as its computed value instead of its literal text.
- **Literal-reflection negative**: fires when the probe echoes unchanged and excludes evaluation for that sink and grammar.
- **Error-text disclosure**: fires when failure output names the rendering layer or its syntax.
- **Host-object rendering proof**: fires when a reachable-global probe renders runtime content and confirms execution beyond arithmetic.

## Adversarial Capabilities

- **Anonymous request ability**: supplies the baseline because unauthenticated probes reach most candidate sinks.
- **Authenticated low-privilege session**: extends coverage to editable profile fields, stored content, and preview flows.
- **Template-editor control**: supplies direct source authority wherever tenant or administrative editing exists.
- **Engine-family knowledge**: focuses the probe grammar and avoids wasted requests.

## Trust Assumptions

- **The agreement**: request-supplied values enter the renderer as inert data bound to context variables while template source stays author-controlled, evaluation exposes no host-runtime primitive to request-derived input, and rendered output reflects only intended content.
- **The failing clause**: request-derived input is parsed as template syntax and evaluated with the result reflected in the same response.

## Key Vulnerabilities

- **Differential arithmetic probing**: distinguishes evaluation from reflection because only the matching grammar computes.
- **Second-expression confirmation**: excludes coincidence because two independent computations cannot both appear by chance.
- **Literal-reflection adjudication**: separates injection from markup escaping because evaluated output differs from echoed syntax.
- **Comment-syntax and filter-syntax differentials**: corroborate family identity because each spelling is valid in exactly one family.
- **Error-text fingerprinting**: corroborates identity when failure output discloses the rendering layer.

## Advanced Techniques

- **Sandbox-state probing**: maps the reachable gadget pool by requesting framework globals exposed into the template context.
- **Reflection walks**: enumerate host-runtime classes from any reachable object through its type hierarchy.
- **Gadget chains**: connect the enumerated pool to a shell-equivalent primitive by the shortest reachable call path.
- **Stream-consumption wrappers**: capture command output where the raw execution primitive returns an opaque handle instead of text.
- **Alias and indirection recovery**: restores reachability when direct attribute paths are denied but equivalent spellings remain.
- **Length-constrained staging**: works a capped field in stages: confirm evaluation with the shortest probe, dump the exposed object list in one response, then select the execution index in a second probe.
- **Staging order**: the staging order matters because the cap forbids a single full gadget, so each stage carries the shortest fragment that still answers.

## Bypass Techniques

- **Attribute-indirection spellings**: recover denied attribute paths through lookup helpers instead of direct references.
- **Class-walk recovery**: enumerates loaded runtime classes from a permitted object when builtins are removed from scope.
- **Token-splitting assemblies**: reconstruct denied identifiers from concatenated fragments at render time.
- **Encoding layering**: survives pre-render filters by arriving in an encoding that decodes only at the template stage.
- **Whitespace, case, and precedence variants**: defeat naive keyword denylists while preserving evaluation semantics.
- **Multi-stage pipelines**: carry payloads through markup or formatting layers that strip raw syntax but preserve fenced or encoded blocks.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **File-write primitives**: establish persistence by placing executable content where a follow-up request triggers it.
- **Second-stage definitions**: plant reusable logic that executes on the next render without a fresh injection.
- **Deserialization gadgets**: reached through template objects extend the chain into adjacent parsing layers.
- **Exfiltration through outbound requests**: moves captured output out when the response channel reflects nothing useful.
- **File-read follow-ups**: after a blind write belong to the path-traversal-lfi-rfi skill and are invoked at that step rather than restated here.

## Testing Methodology

1. Find templated input by submitting a benign marker through every candidate sink with completion when each sink is listed with its reflection behaviour recorded.
2. Fingerprint the engine by running one arithmetic probe per delimiter family with completion when exactly one grammar evaluates and the family is recorded.
3. Confirm evaluation, the first bent step, by showing computed output rather than literal echo with completion when a second independent expression also computes and the markup-escaping line is adjudicated.
4. Probe sandbox state by requesting framework globals through the confirmed grammar with completion when the reachable pool or its definitive denial is recorded.
5. Enumerate gadgets by walking reflection paths from the reachable pool with completion when at least one shell-equivalent chain or a definitive negative is recorded.
6. Reach execution by invoking the shortest gadget chain with completion when command output or an opaque execution handle is observed.
7. Validate side effects through an observable execution signal with completion when the effect is tied to the submitted probe.

## False Positives

- **Literal template-syntax reflection**: markup-shaped rather than injection-shaped and belongs to the client-side family.
- **Sandboxed evaluation**: exposes no useful reachable object, confirming confinement rather than a finding.
- **Client-side rendering**: executes template syntax in the browser and carries markup impact rather than server-side execution.
- **Build-time-only templating**: never receives request input and therefore cannot evaluate attacker syntax.
- **Escaped output**: masks evaluation as literal-looking text and resolves through a non-markup numeric probe before any verdict.

## Pro Tips

- **Second computation**: confirm every arithmetic hit with a second independent computation before advancing because single-shot matches coincide with static content.
- **Fingerprint first**: fingerprint the engine before spending requests on gadget chains because wrong-family payloads add only noise.
- **Global spray**: spray every framework global the knowledge base lists for the confirmed family before walking type hierarchies because the shortest chain starts from the richest object.
- **Error text**: treat it as corroboration rather than proof because verbose failures also follow from malformed but unevaluated input.
- **Secondary renderers**: read generated documents and email previews with the same attention as primary responses because secondary renderers often enforce weaker controls.
- **Preview loops**: drive a template-editor preview or save loop with a fresh request token per iteration, because the preview path renders the template without persisting and gives the cheapest repeated evaluation surface.

## Summary

Reflected evaluation proves injection at the moment computed output replaces literal syntax in the same response.
Differential probing narrows the engine family immediately and the second-expression rule removes coincidence from the verdict.
Sandbox mapping and reflection walks then convert a confirmed evaluation primitive into shell-equivalent execution wherever the reachable pool permits.
