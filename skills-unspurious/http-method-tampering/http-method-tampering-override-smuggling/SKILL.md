---
name: http-method-tampering-override-smuggling
description: Smuggle overridden verbs through gate-visible safe methods to expose reinterpretation gaps where the gate authorizes one method and the backend executes another, when override headers or fields are honored, or when a two-layer method view diverges.
metadata:
  version: 1.0.0
---

# Override Smuggling Reinterpretation Bypass

This skill proves a two-layer divergence where the front gate authorizes a safe method while the backend executes the smuggled overridden method.
It pairs every override delivery with a gate-view versus executor-view comparison.

## Attack Surface

This variant applies where a backend honors method reinterpretation carriers while a front gate sees only the outer method.
The condition is an override header carrier or an override body field carrier that the executor applies after the gate has authorized the outer method.
Resources guarded on the outer method but executable under the overridden method qualify.

## Reconnaissance

Inventory guarded resources that accept body-bearing outer methods.
Record which carriers the backend stack documents as reinterpretation signals without sending exploit payloads.
Flag resources where gate documentation and executor documentation describe different effective methods.
Reconnaissance is complete when each candidate resource carries its outer method plus its candidate override carriers.

## Detection Channels

Gate-view versus executor-view divergence signals reinterpretation acceptance.
State-change effect or guarded-data return under an override carrier confirms backend execution of the smuggled verb.
Absence of effect under every carrier signals the backend ignores reinterpretation.

## Adversarial Capabilities

This variant presupposes a low-privilege session able to send an outer method carrying override headers and override body fields.
It consumes control of header carriers plus body-field carriers while holding the outer method constant.
It presupposes comparison ability between the gate-authorized view and the executor-applied view.

## Trust Assumptions

The feature executes under a method-identity agreement at request handling time.
The server contracts that the authorization decision made for the documented verb covers every verb reaching the same resource.
The server contracts that the route table maps each verb to its equally guarded handler.
The server contracts that front-gate method identity equals executed method identity and that no privileged effect leaks through a sibling verb.
The failing clause is override reinterpretation: the gate authorizes the outer method while the backend executes the smuggled overridden method.

## Key Vulnerabilities

The core weakness is a two-layer method view with the guard fixed on the outer layer.
An override carrier lets the attacker choose the executed verb after authorization has passed.
Header carriers and body-field carriers are the two delivery shapes.
Confirm execution by backend effect rather than by gate acceptance alone.

## Advanced Techniques

Deliver each override carrier through the outer method with identical session material and fixed semantics.
Compare the gate-authorized outcome against the executor-applied outcome for each carrier.
Anchor each accepted carrier on execution proof showing the overridden verb ran.

## Bypass Techniques

The defeated control is outer-method authorization at the front gate.
The bypass keeps the outer method gate-visible while the executor applies the smuggled verb.
Confirm the bypass by showing the overridden effect unattainable through the outer method alone.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

A confirmed reinterpretation gap escalates into object-level or function-level access under the smuggled verb.
A smuggled state-changing verb chains into token-free triggering where the outer method carries a benign shape.
Name the companion skill at the chaining step rather than restating its procedure.

## Testing Methodology

1. List every candidate resource with its gate-visible outer method plus candidate override carriers.
Complete when no candidate lacks a carrier inventory.
2. Send the outer method carrying each override carrier with identical session material and fixed action semantics.
Complete when every carrier has a recorded gate-view versus executor-view outcome.
3. Prove gate-versus-executor divergence by comparing front-gate authorization against backend-executed effect per carrier.
Complete when each accepted carrier shows the overridden verb executed while the gate authorized only the outer method.
4. Confirm execution against the guarded baseline through data return or state change.
Complete when each claimed bypass shows guarded data or a state effect unattainable through the outer method alone under the same session.

## False Positives

Override carriers ignored by the backend exclude this variant.
Gate acceptance without backend execution excludes this variant.
Direct verb replay without a carrier belongs to the verb-switch variant and never confirms smuggling here.

## Pro Tips

Test header carriers and body-field carriers independently so attribution stays exact.
Hold action semantics fixed across carriers so divergence proves reinterpretation rather than payload shape.
Treat gate success as non-proof until executor effect confirms the overridden verb ran.

## Summary

Override smuggling breaks method-identity trust through reinterpretation divergence.
Deliver each carrier, compare gate view against executor view, and confirm execution by backend effect.
