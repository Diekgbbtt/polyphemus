---
name: upload-toolchain-execution
description: Toolchain triggering proving converters execute embedded operators. Triggers on media conversion, metadata parsing, processor side effects.
metadata:
  version: 1.0.0
---

# Upload Toolchain Execution

Trigger conversion and metadata-parse jobs and confirm processor side effects beyond stored rendering.
This variant owns trigger-job-then-read-side-effect proof with command and file-read oracles.

## Attack Surface

- **Media and document pipelines**: apply where an upload triggers thumbnail generation or format conversion.
- **Metadata parsing**: applies where embedded property blocks enter a dedicated parser after ingress.
- **Derived-output conditions**: apply where converted artifacts return to storage or to a serving path.

## Reconnaissance

- **Pipeline map**: map the pipeline from submission through storage to each converter and parser and record job triggers.
- **External-IO jobs**: record which jobs resolve external references or render embedded content, because those jobs carry the external-IO operators.
- **Job-trigger probe**: probe with benign media and document-shaped files and record which jobs fire plus which derived outputs appear.
- **Parser baseline**: record parser handling of embedded property blocks before attempting live content.
- **Job baseline**: capture baseline job duration with output shape so side effects stand out.

## Detection Channels

- **Processor output**: processor command output reflected in derived artifacts or error state proves operator execution.
- **File-read signal**: out-of-scope file content surfacing through conversion proves file-read operators.
- **Fetch receipt**: outbound fetch receipts during conversion prove the converter reached a remote resource, which the ssrf skill owns at the fetch step.
- **Render activity**: script or request activity inside a rendered document proves the renderer engine executed embedded content, which the xss skill owns at the render step.
- **Behavior deltas**: job behavior deltas across probe families separate parser flaws from rendering effects.

## Adversarial Capabilities

- **Operator-content submission**: submit media-shaped and document-shaped files carrying embedded operator content.
- **Job triggering**: trigger thumbnail with conversion and metadata-parse jobs through normal submission flows.
- **Artifact reading**: read derived artifacts with job status and error state for processor side effects.

## Trust Assumptions

- **The agreement**: the pipeline agrees that a file accepted at ingress keeps its validated type through storage and processing and serving, that serving reflects only server-set type with sniffing disabled, that extraction and conversion stay confined, and that no late control point re-opens the gate.
- **The failing clause**: converter confinement: conversion jobs execute embedded operators.

## Key Vulnerabilities

- **Operator execution**: evaluates embedded commands or pipe constructs during conversion or parsing.
- **File-read operators**: exfiltrate out-of-scope content into derived artifacts or error channels.
- **External-IO operators**: fetch remote resources or read local content during conversion, including stream demuxers that follow a manifest and a browser engine that renders a document with embedded fetches.
- **Converter-internal spellings**: name local content with no file parameter, so the reader reaches material the pipeline never intended.
- **Property-block parsing**: expands oversized embedded metadata until the parser exposes flaws.

## Advanced Techniques

- **Side-effect confirmation**: trigger conversion and metadata-parse jobs then confirm processor side effects such as command execution or file reads.
- **Placement variation**: vary operator placement across vector graphics with page-description content and embedded property blocks to find the evaluating parser.
- **Carrier variation**: vary the carrier across a stream manifest, a concatenation list, and a rendered document to find the job that resolves external references.
- **Marker confirmation**: confirm file reads by planting unique marker content out of scope and watching for it in derived outputs.

## Bypass Techniques

- **Format-gate defeat**: defeat format gates by framing operator content inside an accepted container that still reaches the evaluating parser.
- **Sandbox defeat**: defeat sandbox assumptions by reaching external IO or script engines the policy claims are disabled.
- **Size-gate defeat**: defeat size gates by distributing abusive metadata across blocks that each pass alone and combine in the parser.
- **Sandbox-claim defeat**: defeat sandbox claims by reaching external IO through a converter-internal resource spelling rather than a file parameter, and verify the claim with a live fetch receipt instead of the configuration alone.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Secret-theft chain**: chain processor file reads into secret theft by aiming file operators at credential material.
- **Server-execution chain**: chain operator execution into server execution by invoking host primitives through the converter context.

## Testing Methodology

1. **Pipeline mapping** - map the pipeline and record every conversion and metadata-parse job with its trigger and derived output, and the step completes when every job with its input family and output destination is recorded.
2. **Baseline capture** - trigger each job with benign probes and record job status with output shape as baseline, and the step completes when every job has a captured baseline covering duration plus output plus error state.
3. **Side-effect confirmation** - trigger conversion and metadata-parse jobs then confirm processor side effects such as command execution or file reads, and the step completes when side effects are demonstrated for every job family or when sandboxed confinement with no external IO is proven.
4. **External-IO confirmation** - trigger the external-IO jobs and confirm fetch receipts or rendered script with a marker resource out of scope, and the step completes when every external-IO job has a recorded fetch or render verdict or when a policy-restricted proxy proves the reach confined.

## False Positives

- **Confined converters**: exclude converters confined in locked-down sandboxes with no external IO and no script engines.
- **Proxied converters**: exclude converters that resolve external references through a policy-restricted proxy with no reachable internal address, confirmed by live probes rather than by configuration alone.
- **Active-content-stripping pipelines**: exclude pipelines that strip active content before conversion and serve only safe renderings.
- **Inert parser errors**: exclude parser errors that stay inert with no side effect beyond a failed job.

## Pro Tips

- **Minimal operator probes**: keep operator probes minimal so side effects stay unambiguous.
- **Safe-rendering guidance**: prefer transforming risky formats to safe renderings when advising the fix.
- **Sandbox verification**: verify sandbox claims with live operator probes instead of trusting configuration alone.
- **Family naming**: name the ssrf skill at the fetch step and the xss skill at the render step when a job reaches beyond the conversion, rather than restating their procedures here.

## Summary

Toolchain execution holds when a triggered job produces processor side effects tied to submitted content.
Treat every converter and parser as an execution context until sandboxed confinement is proven.
