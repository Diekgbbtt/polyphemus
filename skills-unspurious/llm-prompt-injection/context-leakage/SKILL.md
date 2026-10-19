---
name: context-leakage
description: Extract hidden system text plus tool schemas plus cross-tenant data through verbatim-repeat probes, and map the refusal boundary.
metadata:
  version: 1.0.0
---

# Context Leakage

An LLM feature that holds hidden instructions and privileged context can disclose them when extraction requests are answered verbatim.
This variant proves disclosure by sending repeat-shaped probes plus schema requests plus cross-boundary reads and matching the output against ground truth.
The leakage goal is hidden text in the tester's hands rather than a mere behavior change.

## Attack Surface

Applicability centers on an LLM-backed feature whose context carries text the caller must never see.
The hidden material includes developer instructions plus tool schemas plus other tenants' data present in context.
Delivery may arrive through direct turns or planted content, since membership follows the terminal disclosure proof.
A verbatim-capable response channel is required for this variant.

## Reconnaissance

Leakage work starts by mapping the hidden material before sending any extraction probe.
- Enumerate which hidden classes the context plausibly holds, such as instructions plus schemas plus cross-tenant records.
- Record the refusal baseline plus boilerplate phrasing that marks the guardrail boundary.
- Note whether delivery runs direct or planted, since delivery is an aspect carried inside this variant.
- List the ground-truth sources available for matching disclosed text, such as seeded secrets or known instruction markers.

## Detection Channels

Leakage listens to disclosure evidence, so only the entries below are live here.
- Disclosed hidden text matching ground truth confirms an extraction positive.
- Refusal-pattern or boilerplate shift across probes maps the guardrail boundary.
- Tool-schema disclosure in the response confirms schema extraction even without a call.
- Hallucinated instruction text matching no ground truth marks a negative rather than a finding.

## Adversarial Capabilities

Leakage presupposes context access through either delivery channel, and it consumes that access.
- Submit extraction requests through direct turns or through planted ingested content.
- Shape verbatim-repeat requests that ask the model to restate hidden context.
- Request structural disclosure such as tool schemas or context layout.
- Probe across tenant boundaries where shared corpora or memory are reachable.
- Compare each response against ground truth rather than accepting plausible text.

## Trust Assumptions

The feature executes under an agreement that the model separates instructions from data, treats ingested content as untrusted data, holds tool choice plus arguments to developer intent, keeps hidden system text undisclosed, and emits only sink-safe output.
Sensitive application behavior changes only when developer instructions direct them.
This variant breaks the hidden-text non-disclosure clause because system instructions plus schemas plus cross-tenant data are returned to the caller.

## Key Vulnerabilities

### Verbatim Extraction

Send placeholder-shaped repeat requests that ask the model to restate text above the caller-visible boundary.
Vary the restatement framing across attempts because one phrasing never covers every refusal pattern.
The parent leakage-probe step names only generic extraction and cannot describe ground-truth-matched disclosure, so this variant owns the extraction procedure.

### Schema Disclosure

Request the model's available capabilities plus argument shapes plus context layout as structured disclosure.
Treat returned schema detail as a positive even when no tool is invoked, because schemas guide every follow-up steer.
Match disclosed names against seeded capability notes to separate real schemas from hallucinated ones.

### Cross-Boundary Reads

Probe for records belonging to another tenant or session that share the context or corpus.
Confirm each candidate disclosure against seeded cross-tenant markers before claiming a boundary failure.
Treat a direct-delivered repeat request as leakage rather than override, since membership follows the terminal proving step.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no wrapper changes the disclosure step itself.
- Refusal-boilerplate inference reads system shape from what the guard refuses to say.
- Paraphrase reframing asks for the same hidden text through a differently worded request.
- Multi-turn laundering builds disclosure across several individually innocent turns.
- Translation wrappers request the hidden text rendered in another language form.
- Request the hidden text in an encoded or transposed rendering so an output filter that scans for the literal never sees it.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Leakage chains forward into use because disclosed text alone is only information.
- Hand disclosed schemas to tool-abuse for argument-shaped privileged calls.
- Hand disclosed instructions to direct-injection-override for sharper follow-up steering.
- Hand disclosed cross-tenant data to output-handling where a sink forwards it onward.
- Hand disclosed schemas to the server-side request and command families where a tool argument reaches a fetch or a shell, rather than restating those procedures here.
- Treat boilerplate shifts mapped here as the guardrail intelligence each follow-up reuses.

## Testing Methodology

Leakage runs extraction first and everything else follows, because no disclosure claim stands without a ground-truth match.
1. **Inventory hidden classes** - list every hidden-text class with its ground-truth source plus the refusal baseline, and the step completes when no unlisted class remains.
2. **Send repeat probes** - submit placeholder-shaped restatement requests per framing, and the step completes when every probe shows disclosed or refused.
3. **Request schemas** - ask for capability plus argument-shape plus layout disclosure, and the step completes when every schema probe shows a matched or hallucinated verdict.
4. **Probe boundaries** - request cross-tenant records through the reachable channel, and the step completes when every boundary probe shows a matched or refused verdict.
5. **Match ground truth** - compare each candidate disclosure against its seeded marker, and the step completes when every claim carries a confirmed or hallucination verdict.

## False Positives

Stop when the evidence shows plausible text without provenance, because hallucination without a ground-truth match is not a finding.
- Refusals or invented instruction text that match no seeded marker.
- Schema-shaped output naming capabilities the run never demonstrates.
- Cross-tenant-shaped output matching no seeded boundary marker.
- Single-run disclosure that never reproduces across repeated probes.
- Properly refused probes where the refusal boundary holds across reframings.

## Pro Tips

Leakage rewards ground truth plus reframing patience plus boilerplate attention.
1. Seed recognizable markers before probing so every disclosure is matchable.
2. Vary the restatement framing per refusal pattern rather than repeating one blocked phrasing.
3. Read refusal boilerplate as signal because shifts reveal the hidden shape.
4. Separate schema disclosure from tool invocation since schemas alone already guide follow-ups.
5. Record every hallucination as a negative so later runs stop relitigating invented text.
6. Anchor each probe to a non-guessable string the run seeded, so a plausible answer separates from a real disclosure.

## Summary

Hidden context that answers repeat requests stops being hidden the moment its text matches ground truth.
Leakage proves that disclosure with verbatim plus schema plus boundary probes, matched marker by marker until only confirmed text or a mapped refusal boundary remains.
