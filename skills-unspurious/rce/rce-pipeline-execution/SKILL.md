---
name: rce-pipeline-execution
description: Pipeline files triggering converter and renderer delegates into execution. Use when uploads reach media converters, when documents reach renderers, when derived outputs carry operator side effects.
metadata:
  version: 1.0.0
---

# Pipeline Execution

Uploaded files reach an out-of-process converter or renderer whose delegate semantics execute embedded operators.
This variant owns upload-then-delegate construction with policy-gated fallback reasoning and callback or file-write proof.
The goal is confirmed delegate execution that later escalates to durable control.

## Attack Surface

Applicability centers on an upload, import, or management-interface flow whose content reaches an out-of-process conversion, rendering, metadata-parsing, document-compilation, or configuration-rendering delegate.
The pipeline triggers at least one processing job per accepted input, such as thumbnail generation, format conversion, metadata extraction, document build, or a configuration reload that evaluates the rendered file.
Derived outputs or job status return to storage or to a serving path where side effects become observable.
A second input topology rides here without an upload: a free-form field in a management interface is rendered into a configuration file that a privileged daemon later reads, so the field value becomes a delegate directive.
The administrator trust context widens that topology: operators are treated as trusted, so field values pass into the configuration file without the validation an uploaded file receives.
Converter identities and delegate spellings vary only as aspects inside the single file-craft loop.
Direct-string wrapper probing belongs to command injection, and template, deserialization, chained-service, and container-boundary sinks belong to their owning skills.

## Detection Channels

Pipeline probing listens to the entries below, and only these entries are live here.
Job-trigger signal separates a live delegate from inert storage when an upload fires a conversion or parse job.
Derived-artifact difference separates execution from rendering when converted outputs or error state carry operator results.
Callback oracle binds one minted unique marker per crafted file to one inbound arrival on operated listener infrastructure.
Job-duration delta separates operator evaluation from clean conversion when processing time shifts past its baseline.
Planted-marker surfacing proves file-read operators when unique out-of-scope content appears in derived outputs.
Policy-gate signal separates an enforcing build from a permissive one when operator families succeed or fail as a group.
Configuration-reload signal separates a rendered field from inert storage when saving or reloading the configuration fires the delegate.

## Adversarial Capabilities

Pipeline probing presupposes file upload plus job triggering plus derived-output reading, and it consumes all three.
Submit media-shaped and document-shaped files carrying embedded operator content through normal ingress flows.
Trigger conversion plus metadata-parse plus render plus build jobs by submitting the file shapes each job consumes.
Read derived artifacts plus job status plus error state for processor side effects tied to submitted content.
Operate callback infrastructure that mints one fresh unique marker per crafted file and records each inbound arrival.
Hold no direct-string wrapper position, because this variant starts from uploaded files alone.

## Trust Assumptions

The feature agrees that every input string stays inside its shell quoting or CLI argument role through concatenation and parsing and execution, that every template stays inert data, that every blob stays sender-faithful, that every uploaded file stays rendition-only, that every management-interface field stays configuration data rather than a directive, and that every internal service stays unreachable.
Sensitive server control leaks only when an execution primitive consumes input outside its agreed role.
This variant breaks the rendition-only clause because an uploaded file or a rendered configuration field exercises an out-of-process delegate that executes its embedded operators.

## Key Vulnerabilities

### Delegate Operator Execution

Live delegates evaluate embedded commands or pipe constructs during conversion, parsing, rendering, or compilation.
Craft the container that exercises the delegate by placing operator content where the evaluating parser reads it.
Probe operator acceptance with minimal shapes before asserting execution.
Payload shapes stay abstract with placeholders denoting the container header, the operator directive, the probe command, and the callback marker.
A vector-graphics shape nests the operator directive inside a drawing-context block.
A document shape nests the pipe operator inside a file-operation construct.
A metadata shape nests the operator inside an embedded property block the parser expands.
A typesetting shape nests the shell-escape directive inside a build input the compiler processes.

### Configuration-Field Delegate Execution

A management interface that renders free-form fields into a configuration file carries the same execution primitive as an uploaded file through a different entry.
Enumerate management interfaces plus their free-form configuration fields, then submit evaluation probes to learn which delegate consumes the rendered file.
The delegate families are the ones a privileged daemon reloads: log destinations, plugin execution blocks, and job-template renderers.
Payload shapes stay abstract with placeholders denoting the configuration field, the operator directive, the probe command, and the callback marker.
Inject the delegate's execution primitive into the field so the rendered configuration carries it, and confirm through the same callback or file-write oracle as the file-craft loop.
Treat the administrator trust context as the root cause, because the field was accepted on the assumption that its author was trusted rather than because the value was validated.

### Delegate File-Read Operators

Live delegates exfiltrate out-of-scope content into derived artifacts or error channels through file-read operators.
Plant unique marker content out of scope, then watch derived outputs for its surfacing.
A read shape aims a file operator at the planted marker path and routes the result into the derived artifact.
An error-channel shape aims the operator so failures reflect marker content in job status.
Policy-gated fallbacks vary the operator family when one family is confined, and compile-flag gating narrows which shapes a given build evaluates.
Cross-referenced sinks stay out of this variant by naming their owning skill at the step that owns them.
Template and expression evaluation hands off to the template-injection skill at the evaluator step.
Deserializer blobs hand off to the deserialization skill at the unmarshal step.
Chained internal-service construction hands off to the server-side-fetch skill at the chained-sink step.
Container and cluster expansion hands off to post-exploitation at the durable-control step.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no framing difference changes the file-craft step itself.
Container framing reaches the evaluating parser through an accepted wrapper that still carries operator content past format gates.
Property-block distribution reaches the parser past size gates through blocks that each pass alone and combine during parsing.
Sandbox-claim probing reaches external IO or script engines that the declared policy claims are disabled.
Fallback variation reaches execution through a second operator family when the first family is confined.
Layered combinations hand off to the defence-bypass family at the filter step rather than restating relay mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Delegate execution chains forward into server control because a processor side effect is only the entry proof.
Chain file-read operators into secret theft by aiming file operators at credential material.
Chain operator execution into server execution by invoking host primitives through the converter context.
Chain confirmed execution into file writes plus scheduled execution plus service restart hooks once a writable path is proven.
Hand container or cluster expansion to post-exploitation at the durable-control step rather than extending this variant.

## Testing Methodology

Pipeline probing runs file-craft construction first and everything else follows, because no oracle is meaningful without a delegate-exercising file.
The first bent step is P1 file-mediated construction against delegate semantics.
The delta over the parent is the upload-then-delegate procedure with policy-gated fallback reasoning that parameter break-out language never names.
1. **Pipeline mapping records** every conversion plus parse plus render plus build plus configuration-reload job with its trigger and its derived-output destination.
The step is done when every job with its accepted input family and its output destination is recorded.
2. **Baseline capture triggers** each job with benign files and records job status plus output shape plus duration.
The step is done when every job family shows a captured baseline covering status plus output plus timing.
3. **Operator probing submits** minimal delegate-exercising files plus management-interface field values one operator family at a time through gated callback or file-write oracles.
The step is done when every operator family at every job shows execution or confinement with its oracle verdict.
4. **File-read proof plants** unique marker content out of scope and watches derived outputs plus error channels for its surfacing.
The step is done when every read shape shows marker surfacing or confirmed absence.
5. **Fallback reasoning replays** confined operator families through alternate spellings plus distributed property blocks plus policy-gate signals.
The step is done when every fallback shows acceptance or uniform enforcement across the job family.
6. **Durable-control proof demonstrates** the smallest file write or scheduled effect that proves persistence without an unnecessary shell.
The step is done when every claimed durable effect shows its artifact or is recorded as absent.

## False Positives

Stop when the evidence shows no delegate-driven side effect, because inert conversion is only a negative.
Confined delegates reject the claim when sandboxed processing runs with no external IO and no script engine.
Stripped pipelines reject the claim when active content is removed before conversion and only safe renderings are served.
Inert parser errors reject the claim when a failed job produces no side effect beyond the failure itself.
Simulated outputs reject the claim when derived text never derives from delegate evaluation.

## Pro Tips

Pipeline probing rewards minimal operators plus per-job baselines plus small claims.
Keep each operator probe minimal so the tied side effect stays unambiguous.
Baseline every job family before crafting so duration and output deltas stand out.
Verify sandbox and policy claims with live operator probes instead of trusting configuration alone.
Treat a management-interface field as an input vector wherever it is rendered into a privileged configuration file, because the trust context differs while the delegate stays the same.
Prefer transforming risky formats to safe renderings when advising the fix.
Document the smallest chain that proves durable effect and stop before an unnecessary persistent shell.

## Summary

A converter or renderer that processes uploaded files is a pipeline-execution candidate.
Craft the delegate-exercising file, gate proof on callback or file-write oracles, reason through policy fallbacks, and escalate to durable control only as far as proof requires.
