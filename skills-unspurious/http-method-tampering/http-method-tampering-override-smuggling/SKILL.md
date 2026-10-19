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

- **Applicability**: a backend honors method reinterpretation carriers while a front gate sees only the outer method.
- **Qualifying condition**: an override header carrier or an override body field carrier applies after the gate has authorized the outer method.
- **Qualifying resources**: those guarded on the outer method but executable under the overridden method.

## Reconnaissance

- **Resource inventory**: inventory guarded resources that accept body-bearing outer methods.
- **Carrier documentation sweep**: record which carriers the backend stack documents as reinterpretation signals without sending exploit payloads.
- **Documentation-divergence flag**: flag resources where gate documentation and executor documentation describe different effective methods.
- **Completion criterion**: reconnaissance is complete when each candidate resource carries its outer method plus its candidate override carriers.

## Detection Channels

- **Gate-view versus executor-view divergence**: signals reinterpretation acceptance.
- **State-change effect or guarded-data return**: confirms backend execution of the smuggled verb under an override carrier.
- **Absent effect under every carrier**: signals the backend ignores reinterpretation.

## Adversarial Capabilities

- **Low-privilege session**: supplies the ability to send an outer method carrying override headers and override body fields.
- **Carrier control**: controls header carriers plus body-field carriers while holding the outer method constant.
- **View comparison ability**: compares the gate-authorized view against the executor-applied view.

## Trust Assumptions

- **The agreement**: the feature executes under a method-identity agreement at request handling time, the authorization decision made for the documented verb covers every verb reaching the same resource, the route table maps each verb to its equally guarded handler, and front-gate method identity equals executed method identity with no privileged effect leaking through a sibling verb.
- **The failing clause**: override reinterpretation lets the gate authorize the outer method while the backend executes the smuggled overridden method.

## Key Vulnerabilities

- **Core weakness**: a two-layer method view with the guard fixed on the outer layer.
- **Carrier-chosen verb**: an override carrier lets the attacker choose the executed verb after authorization has passed.
- **Delivery shapes**: header carriers and body-field carriers are the two options.
- **Execution confirmation**: confirm execution by backend effect rather than by gate acceptance alone.

## Advanced Techniques

- **Carrier delivery**: deliver each override carrier through the outer method with identical session material and fixed semantics.
- **Outcome comparison**: compare the gate-authorized outcome against the executor-applied outcome for each carrier.
- **Execution anchoring**: anchor each accepted carrier on execution proof showing the overridden verb ran.
- **Path-rewrite carrier**: send a request to an unguarded path with the guarded path carried in a path-rewrite carrier, and compare the gate verdict against the executed action, because the guard evaluated the original path; name `header-injection` at the carrier step rather than restating the header mechanics here.

## Bypass Techniques

- **Defeated control**: outer-method authorization at the front gate.
- **Bypass shape**: the outer method stays gate-visible while the executor applies the smuggled verb.
- **Bypass confirmation**: show the overridden effect unattainable through the outer method alone.
- **Path-normalisation shapes**: case, dot segments, encoded separators, semicolon parameters, and trailing characters move the request onto an unguarded path pattern while the guard evaluated the original path.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Reinterpretation escalation**: a confirmed reinterpretation gap escalates into object-level or function-level access under the smuggled verb.
- **Smuggled state-changing verb**: chains into token-free triggering where the outer method carries a benign shape.
- **Companion-skill reference**: name the companion skill at the chaining step rather than restating its procedure.

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

- **Ignored override carriers**: override carriers ignored by the backend exclude this variant.
- **Gate acceptance without execution**: gate acceptance without backend execution excludes this variant.
- **Direct verb replay without a carrier**: belongs to the verb-switch variant and never confirms smuggling here.

## Pro Tips

- **Independent carrier testing**: test header carriers and body-field carriers independently so attribution stays exact.
- **Fixed semantics**: hold action semantics fixed across carriers so divergence proves reinterpretation rather than payload shape.
- **Gate success as non-proof**: treat gate success as non-proof until executor effect confirms the overridden verb ran.

## Summary

Override smuggling breaks method-identity trust through reinterpretation divergence.
Deliver each carrier, compare gate view against executor view, and confirm execution by backend effect.
