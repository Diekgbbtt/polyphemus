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

This variant applies where cross-origin or method-tied policy gates the preflighted shape but treats the simple shape as safe.
The condition is a state-changing endpoint whose policy decision depends on request shape rather than on semantics.
Endpoints enforcing checks only on shaped requests that trigger a preflight qualify.

## Reconnaissance

Inventory state-changing endpoints behind shape-dependent gating.
Record the preflighted shape that triggers the gate and the candidate simple shape with identical semantics.
Flag endpoints where gate documentation distinguishes shapes by content-type or verb simplicity.
Reconnaissance is complete when each candidate carries its preflighted shape plus its simple-shape counterpart.

## Detection Channels

A blocked preflighted shape paired with an executed simple shape signals shape-dependent divergence.
Guarded-data return or state-change effect under the simple shape confirms execution.
Gate decisions observed across the shape pair confirm the policy split.

## Adversarial Capabilities

This variant presupposes a low-privilege session able to reshape a state-changing request into a simple shape with identical semantics.
It consumes control of content-type plus body encoding while holding action semantics constant.
It presupposes comparison ability between the preflighted-shape outcome and the simple-shape outcome.

## Trust Assumptions

The feature executes under a method-identity agreement at request handling time.
The server contracts that the authorization decision made for the documented verb covers every verb reaching the same resource.
The server contracts that the route table maps each verb to its equally guarded handler.
The server contracts that front-gate method identity equals executed method identity and that no privileged effect leaks through a sibling verb.
The failing clause is preflight gating: the gate blocks the preflighted shape while the simple shape with identical semantics executes.

## Key Vulnerabilities

The core weakness is a policy decision keyed on shape instead of semantics.
Coercion preserves the state-changing meaning while adopting the gate-trusted shape.
The simple shape therefore executes where the preflighted shape is stopped.
Confirm execution by state effect or guarded-data return rather than by acceptance alone.

## Advanced Techniques

Construct shape pairs that differ only in gating shape while preserving identical action semantics.
Deliver the preflighted shape first to record the blocked baseline.
Deliver the simple shape second and anchor the divergence on execution proof.

## Bypass Techniques

The defeated controls are preflight gating and shape-tied token or policy checks.
The bypass coerces the request into the gate-trusted simple shape so the preflight check never engages.
Confirm the bypass by showing the simple shape executed the semantics the preflighted shape was denied.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

A confirmed shape gap chains into cross-origin state changes where the simple shape rides a benign framing.
Executed semantics chain into object-level or function-level effects under the coerced shape.
Name the companion skill at the chaining step rather than restating its procedure.

## Testing Methodology

1. List each state-changing endpoint with its preflighted shape plus its simple-shape counterpart of identical semantics.
Complete when no candidate lacks a semantics-matched shape pair.
2. Deliver the preflighted shape and record the blocked baseline with its gate decision.
Complete when every pair carries a recorded blocked outcome for the preflighted shape.
3. Deliver the simple shape with identical semantics and record the gate decision plus the outcome.
Complete when every pair carries a recorded simple-shape outcome comparable against its baseline.
4. Confirm shape-dependent divergence by execution effect through state change or guarded-data return.
Complete when each claimed bypass shows the simple shape executed the semantics the preflighted shape was denied under the same session.

## False Positives

Policy enforced on the simple shape too excludes this variant.
Simple-shape acceptance without state effect or data return excludes execution claims.
Direct verb replay without shape coercion belongs to the verb-switch variant and never confirms preflight divergence here.

## Pro Tips

Hold semantics identical across the pair so divergence proves shape gating rather than meaning change.
Record the gate decision on both shapes before claiming execution.
Treat delivery without effect as non-proof until state change or data return confirms the semantics ran.

## Summary

Preflight coercion breaks shape-keyed gating through simple-shape execution.
Pair each shape, record both gate decisions, and confirm divergence by execution effect.
