---
name: error-verbosity-disclosure
description: Verbose failures disclose internals. Use when failure output turns verbose; when debug or profiler surfaces answer in production; when evaluation probes confirm a live execution context.
metadata:
  version: 1.0.0
---

# Error Verbosity Disclosure

Failures are a channel.
This variant reads that channel: it triggers controlled failures, enumerates debug and profiler surfaces, and converts verbose output into code, paths, versions, and trust boundaries for follow-on work.

## Attack Surface

- **Triggerability**: lives wherever the target renders a failure: error pages, exception renderers, input validators, and content negotiation handlers.
- **Verbosity**: lives in debug and development tooling left reachable in production: interactive debuggers, profilers, trace viewers, and feature flag endpoints.
- **Debug surface families**: the debug surface carries families beyond the failure path: environment and configuration dumps, memory and heap dumps, logger control endpoints, route and mapping listings, trace and error recorders, version and build-info endpoints, and diagnostic consoles.
- **Adjacency**: lives in failure-adjacent metadata: tracing headers and server timing signals emitted alongside the failure response.

## Reconnaissance

- **Failure-surface mapping**: map the failure surfaces before triggering them.
- **Surface catalogue**: catalogue every endpoint that can fail, every content shape the target negotiates, and every debug or profiler surface reachable without privilege.
- **Baseline recording**: record the baseline failure rendering per surface so later output has something to diverge from.
- **Reconnaissance completion**: reconnaissance is complete when each reachable surface has a recorded baseline failure response.

## Detection Channels

- **Failure-text internals**: expose stack traces, file paths, query fragments, and framework versions inside failure responses.
- **Evaluation probe output**: confirms a live execution context behind the error renderer.
- **Fail-open paths**: a failure path that executes the action instead of only narrating it, which reads as fail-open rather than disclosure and needs its own effect proof.
- **Adjacent timing and metadata deltas**: narrate handling the trigger did not intend to expose.
- **Channel scope**: only channels carried by triggered failure output fire here; fetched artifact content and two-response differentials belong to the sibling variants.

## Adversarial Capabilities

- **Malformed input supply**: the entry capability because the procedure presupposes the ability to send arbitrary shapes the target did not expect.
- **Unprivileged reach**: sufficient because no credential, role, or session beyond anonymous requests is consumed.
- **Response observation**: closes the loop because it records, normalizes, and compares failure renderings across trigger classes.

## Trust Assumptions

- **The agreement**: at the moment the handler renders a failure, the target trusts that what it does not intend to reveal cannot be elicited, and failure output stays generic under adversarial input because malformed shapes receive uniform renderings that carry no code, path, query, or version detail.
- **The failing clause**: this variant breaks the generic-output clause because triggered failures render verbose internals instead of the agreed uniform response.

## Key Vulnerabilities

- **Triggering**: triggering submits each malformed class the surface accepts: wrong types, malformed bodies, missing fields, oversized fields, boundary-length values, null-byte shapes, and unexpected content types, one assumption broken per attempt so the failing assumption is attributable.
- **Enumeration**: enumeration walks the debug surface families beyond the failure path: interactive debuggers, profilers, trace viewers, flag endpoints, environment and configuration dumps, memory and heap dumps, logger controls, route and mapping listings, and version and build-info endpoints, each probed for a live answer.
- **Probing**: submits evaluation markers with known answers to learn whether an execution context sits behind the renderer.
- **Reading**: captures failure-adjacent tracing and timing metadata while it stays trigger-adjacent rather than a standalone channel.

## Chaining Attacks

- **Paths to file access**: filesystem layouts from stack traces scope traversal and inclusion attempts owned by the file-access skills.
- **Versions to known flaws**: precise component versions from verbose output map to reachable flaws for minimal proof.
- **Chain stop condition**: each chain stops at a reversible proof or a stated architectural risk rather than a full exploit.

## Testing Methodology

1. **Map failure surfaces.** Catalogue endpoints, negotiated content shapes, and debug surfaces, and record one baseline failure rendering per surface. Complete when every reachable surface has a baseline on file.
2. **Trigger controlled failures.** Submit each malformed class per surface: wrong types, boundary values, missing fields, and unexpected content shapes. Complete when every class has been submitted per surface and verbose output is recorded or ruled out.
3. **Enumerate debug and profiler surfaces.** Walk interactive debuggers, profilers, trace viewers, and flag endpoints, and read evaluation-oracle probes with known-answer markers over parent step P3, which names malformed-input triggering but never names debug enumeration or evaluation oracles. Complete when every enumerated surface has answered or refused and each probe outcome is recorded.
4. **Read failure-adjacent metadata.** Capture tracing and timing signals emitted alongside failures. Complete when each signal is recorded as leaking or ruled uniform.
5. **Correlate to impact.** Map each leak to versions with reachable flaws, paths enabling file access, or keys enabling control-plane access, with a minimal reversible proof or a stated risk. Complete when every recorded leak carries a proof or a risk statement.

The signature families behind each trigger, and what each one reveals, are in `references/error-signature-families.md`, read beside the failure it came from.

## False Positives

- **Generic errors**: carry no actionable detail and are not findings.
- **Intentional public documentation**: reachable through the same surfaces and not a leak.
- **Version banners**: have no exposed vulnerable surface and no chain and carry no finding.
- **Redacted fields**: leave no triggerable delta and are not disclosure.

## Pro Tips

- **Broad triggering**: trigger broadly before enumerating deeply by covering malformed classes across all surfaces first and debug walking second.
- **Rendering normalization**: normalize failure renderings before diffing so boilerplate never poses as signal.
- **Verbose-field pivot**: treat one verbose field as a pivot because its vocabulary names the next trigger class to try.
- **Minimal reversible proof**: stop each chain at the smallest reversible proof that confirms the architectural risk.

## Summary

Error verbosity disclosure turns failures into intelligence.
Trigger each surface, enumerate the debug layer behind it, and convert every verbose byte into a scoped follow-on.
