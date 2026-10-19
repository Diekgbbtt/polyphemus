---
name: ssti-blind-evaluation
description: Blind template evaluation inferred without visible reflection across stored-payload sweeps, timing oracles, out-of-band callbacks, and length-differential confirmation.
metadata:
  version: 1.0.0
---

# Blind Template Evaluation

Blind evaluation confirms server-side template injection when the payload executes but no computed output appears in the attacker's own response.
The store-then-sweep procedure is the load-bearing move because the rendering surface is usually a different endpoint, document, or message from the submission surface.
Treat every timing, callback, and length signal as an oracle to be corroborated rather than a finding on its own.

## Attack Surface

- **Applicability**: request-derived input is stored in one surface and evaluated as template syntax in another render pass.
- **Candidate pairs**: stored profile content rendered on dashboards, submitted text rendered into documents or emails, and queued values rendered by background jobs.
- **Fully hidden renders**: evaluation leaves no visible content anywhere and only timing or outbound signals remain.
- **Second-order pipelines**: stored values pass through encoding or markup stages before reaching a downstream template.
- **Submission-render pairing**: the submission surface and the rendering surface are enumerated as a pair because probing one without sweeping the other misses the finding.

## Reconnaissance

### Injection Points

- **Injection-point sweep**: submit a benign marker through every writable field and record each stored value for the sweep rather than judging the submission response alone.
- **Rendering-surface inventory**: list every rendering surface the application offers including secondary views, generated documents, message previews, and administrative listings.
- **Stored-value pairing**: pair each stored value with the full surface list because the render that evaluates it is rarely the page that accepted it.

### Oracle Selection

- **Timing-oracle selection**: select the timing oracle when the render path is reachable but its output never reaches the attacker.
- **Out-of-band-oracle selection**: select the out-of-band oracle when the target can initiate outbound requests and a listener can be operated.
- **Length-differential-oracle selection**: select the length-differential oracle when evaluation changes response shape without revealing the computed value itself.
- **Deferred-reflection sweep**: select it when stored content renders visibly somewhere the submission response does not show.
- **Oracle signal shapes**: see `references/blind-oracles.md` for the signal shapes behind each oracle choice.

## Detection Channels

- **Deferred-endpoint reflection**: fires when stored probe content renders as a computed value on a surface other than the submission surface.
- **Latency differential**: fires when an evaluation-triggering submission measurably delays the render relative to a benign baseline.
- **Callback receipt**: fires when an outbound request from the target arrives at attacker-operated infrastructure.
- **Length-or-checksum shift**: fires when evaluation changes body size or validator output without revealing the computed value.
- **File-write oracle**: fires when evaluation-planted content becomes retrievable through a separate read surface.

## Adversarial Capabilities

- **Authenticated low-privilege session**: supplies the stored-field control that blind detection depends on.
- **Anonymous request ability**: still contributes wherever unauthenticated stored content reaches a renderer.
- **Persistent-write access**: across many fields multiplies oracle chances because each field is an independent evaluation candidate.
- **Listener operation**: for outbound callbacks turns network egress into a detection channel where no response content exists.

## Trust Assumptions

- **The agreement**: request-supplied values enter the renderer as inert data bound to context variables while template source stays author-controlled, evaluation exposes no host-runtime primitive to request-derived input, and rendered output reflects only intended content.
- **The failing clause**: request-derived input is parsed as template syntax and evaluated with the result hidden from the same response and recoverable only through deferred render or side-channel oracles.

## Key Vulnerabilities

- **Store-then-sweep detection**: exposes deferred evaluation because sweeping every rendering surface finds computed output the submission surface hides.
- **Time-based inference**: exposes hidden evaluation because a triggering construct delays the render by a measurable margin over baseline.
- **Out-of-band confirmation**: exposes hidden evaluation because a network egress proves execution without any response content.
- **Length-differential confirmation**: exposes masked evaluation because computed content shifts response shape even when the value itself stays hidden.
- **File-write triggering**: converts hidden execution into retrievable evidence because planted content persists for a separate read.

## Advanced Techniques

- **Sandbox-state probing**: maps the reachable gadget pool through oracle-compatible probes that avoid visible reflection.
- **Reflection walks**: enumerate host-runtime classes from any reachable object through its type hierarchy without requiring visible output.
- **Gadget chains**: connect the enumerated pool to a shell-equivalent primitive by the shortest reachable call path.
- **Stream-consumption wrappers**: capture command output where the raw execution primitive returns an opaque handle instead of text.
- **Alias and indirection recovery**: restores reachability when direct attribute paths are denied but equivalent spellings remain.

## Bypass Techniques

- **Attribute-indirection spellings**: recover denied attribute paths through lookup helpers instead of direct references.
- **Class-walk recovery**: enumerates loaded runtime classes from a permitted object when builtins are removed from scope.
- **Token-splitting assemblies**: reconstruct denied identifiers from concatenated fragments at render time.
- **Encoding layering**: survives pre-render filters by arriving in an encoding that decodes only at the template stage.
- **Multi-stage pipelines**: carry payloads through markup or formatting layers that strip raw syntax but preserve fenced or encoded blocks.
- **Timing-shape discipline**: keeps oracle payloads distinguishable from benign slow responses by using margins the baseline never reaches.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **File-write primitives**: convert blind execution into retrievable evidence by planting content for a separate read surface.
- **Second-stage definitions**: plant reusable logic that executes on the next render without a fresh injection.
- **Outbound exfiltration**: moves captured output to attacker infrastructure when no readable surface exists at all.
- **Deserialization gadgets**: reached through template objects extend the chain into adjacent parsing layers.
- **File-read follow-ups**: after a blind write belong to the path-traversal-lfi-rfi skill and are invoked at that step rather than restated here.

## Testing Methodology

1. Find templated input through store-then-sweep, the first bent step, by storing a probe in every writable field and sweeping every rendering surface with completion when each submission-to-render pair is listed with its outcome recorded.
2. Fingerprint the engine through oracle-compatible probes with completion when exactly one delimiter family produces an oracle signal and the family is recorded.
3. Confirm hidden evaluation through the selected oracle with completion when a benign baseline and a triggering submission diverge on latency, callback receipt, or length shape with coincidence excluded.
4. Probe sandbox state through the confirmed grammar with completion when the reachable pool or its definitive denial is recorded.
5. Enumerate gadgets by walking reflection paths from the reachable pool with completion when at least one shell-equivalent chain or a definitive negative is recorded.
6. Reach execution by invoking the shortest gadget chain with completion when an oracle signal ties the effect to the submitted probe.
7. Validate side effects through an independent oracle channel with completion when a second signal corroborates the first.

## False Positives

- **Literal template-syntax reflection**: on a deferred surface is markup-shaped rather than injection-shaped and belongs to the client-side family.
- **Benign slow responses**: without a stable baseline diverge from timing oracles and require re-measurement before any verdict.
- **Unrelated outbound traffic**: that predates the probe cannot corroborate a callback oracle without a unique per-probe marker.
- **Sandboxed evaluation**: exposes no useful reachable object, confirming confinement rather than a finding.
- **Client-side rendering**: of stored syntax executes in the browser and carries markup impact rather than server-side execution.

## Pro Tips

- **Surface sweep**: sweep every rendering surface after each stored submission because the evaluating render is rarely the accepting page.
- **Timing baseline**: baseline timing repeatedly before judging a latency oracle because network jitter mimics small delays.
- **Unique callback marker**: tag each callback probe with a unique marker so unrelated egress cannot be mistaken for confirmation.
- **Deferred-reflection priority**: prefer the deferred-reflection sweep before spending oracle budget because visible computed output is stronger than any side channel.
- **Oracle corroboration**: corroborate every blind signal through a second independent oracle before advancing to gadget enumeration.

## Summary

Blind evaluation proves injection at the moment a deferred render, timing shift, callback, or length change ties hidden execution to the submitted probe.
Store-then-sweep coverage comes first because the accepting surface and the evaluating surface are different places by definition.
Oracle discipline then converts hidden execution into corroborated evidence that supports the same gadget path as the reflected variant.
