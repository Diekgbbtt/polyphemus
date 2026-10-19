---
name: http-method-tampering-preflight-coercion
description: Coerce state-changing requests into simple shapes to expose preflight-gating gaps where a preflighted shape is blocked and the simple shape executes, when cross-origin policy distinguishes shapes, or when content-type coercion bypasses checks.
metadata:
  version: 1.0.0
---

# Preflight Coercion Shape Divergence

This skill proves shape-dependent gating divergence by pairing a blocked preflighted shape against an executed simple shape with identical semantics.
It confirms every claim by execution effect rather than by delivery alone.

## Attack Surface

- **Applicability**: cross-origin or method-tied policy gates the preflighted shape but treats the simple shape as safe.
- **Qualifying condition**: a state-changing endpoint whose policy decision depends on request shape rather than on semantics.
- **Qualifying endpoints**: those enforcing checks only on shaped requests that trigger a preflight.

## Reconnaissance

- **Endpoint inventory**: inventory state-changing endpoints behind shape-dependent gating.
- **Shape recording**: record the preflighted shape that triggers the gate and the candidate simple shape with identical semantics.
- **Documentation flag**: flag endpoints where gate documentation distinguishes shapes by content-type or verb simplicity.
- **Completion criterion**: reconnaissance is complete when each candidate carries its preflighted shape plus its simple-shape counterpart.

## Detection Channels

- **Blocked-versus-executed shape pair**: signals shape-dependent divergence.
- **Simple-shape effect**: guarded-data return or state-change effect under the simple shape confirms execution.
- **Gate decisions across the shape pair**: confirm the policy split.

## Adversarial Capabilities

- **Low-privilege session**: supplies the ability to reshape a state-changing request into a simple shape with identical semantics.
- **Shape control**: controls content-type plus body encoding while holding action semantics constant.
- **Outcome comparison ability**: compares the preflighted-shape outcome against the simple-shape outcome.

## Trust Assumptions

- **The agreement**: the feature executes under a method-identity agreement at request handling time, the authorization decision made for the documented verb covers every verb reaching the same resource, the route table maps each verb to its equally guarded handler, and front-gate method identity equals executed method identity with no privileged effect leaking through a sibling verb.
- **The failing clause**: preflight gating blocks the preflighted shape while the simple shape with identical semantics executes.

## Key Vulnerabilities

- **Core weakness**: a policy decision keyed on shape instead of semantics.
- **Coercion**: preserves the state-changing meaning while adopting the gate-trusted shape.
- **Simple-shape execution**: the simple shape executes where the preflighted shape is stopped.
- **Execution confirmation**: confirm execution by state effect or guarded-data return rather than by acceptance alone.

## Advanced Techniques

- **Shape-pair construction**: construct shape pairs that differ only in gating shape while preserving identical action semantics.
- **Baseline delivery**: deliver the preflighted shape first to record the blocked baseline.
- **Divergence anchoring**: deliver the simple shape second and anchor the divergence on execution proof.

## Bypass Techniques

- **Defeated controls**: preflight gating and shape-tied token or policy checks.
- **Bypass shape**: coerces the request into the gate-trusted simple shape so the preflight check never engages.
- **Bypass confirmation**: show the simple shape executed the semantics the preflighted shape was denied.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Cross-origin state change**: a confirmed shape gap chains into cross-origin state changes where the simple shape rides a benign framing.
- **Object-level or function-level effects**: executed semantics chain into object-level or function-level effects under the coerced shape.
- **Companion-skill reference**: name the companion skill at the chaining step rather than restating its procedure.

## Testing Methodology

1. **Shape-pair inventory** - list each state-changing endpoint with its preflighted shape plus its simple-shape counterpart of identical semantics, and the step completes when no candidate lacks a semantics-matched shape pair.
2. **Blocked baseline** - deliver the preflighted shape and record the blocked baseline with its gate decision, and the step completes when every pair carries a recorded blocked outcome for the preflighted shape.
3. **Simple-shape delivery** - deliver the simple shape with identical semantics and record the gate decision plus the outcome, and the step completes when every pair carries a recorded simple-shape outcome comparable against its baseline.
4. **Divergence confirmation** - confirm shape-dependent divergence by execution effect through state change or guarded-data return, and the step completes when each claimed bypass shows the simple shape executed the semantics the preflighted shape was denied under the same session.

## False Positives

- **Simple-shape policy enforcement**: policy enforced on the simple shape too excludes this variant.
- **Acceptance without effect**: simple-shape acceptance without state effect or data return excludes execution claims.
- **Direct verb replay without shape coercion**: belongs to the verb-switch variant and never confirms preflight divergence here.

## Pro Tips

- **Identical semantics**: hold semantics identical across the pair so divergence proves shape gating rather than meaning change.
- **Gate-decision recording**: record the gate decision on both shapes before claiming execution.
- **Delivery without effect as non-proof**: treat delivery without effect as non-proof until state change or data return confirms the semantics ran.

## Summary

Preflight coercion breaks shape-keyed gating through simple-shape execution.
Pair each shape, record both gate decisions, and confirm divergence by execution effect.
