---
name: http-method-tampering-verb-switch
description: Switch request verbs across application-decision methods to expose route-dispatch gaps where one verb is guarded and a sibling verb executes, when authorization behaves differently per verb, or when a path accepts an undocumented verb.
metadata:
  version: 1.0.0
---

# Verb Switch Dispatch Bypass

This skill reconstructs the per-verb dispatch map of a guarded resource and proves that an alternate application verb reaches an unguarded handler with execution effect.
It covers only application-decision verbs and never informational verbs.

## Attack Surface

- **Applicability**: a resource is reachable under two or more application verbs with method-differentiated routing.
- **Qualifying condition**: a route table binds authorization to the documented verb while a sibling verb reaches the same resource through a weaker handler.
- **Qualifying handlers**: state-changing handlers exposed under a read verb and read handlers exposed under a write verb.

## Reconnaissance

- **Resource inventory**: inventory guarded resources plus administrative paths first.
- **Documented-verb recording**: record the documented verb for each resource from normal navigation.
- **Per-verb handler flag**: flag every resource where the route table hints at per-verb handlers.
- **Completion criterion**: reconnaissance is complete when each guarded resource carries its documented verb plus its candidate sibling verbs.

## Detection Channels

- **Status-plus-length divergence**: signals a dispatch gap across application verbs.
- **Sibling-verb effect**: guarded-data return or state-change effect on a sibling verb confirms execution.
- **Redirect-target divergence**: signals per-verb handler split across verbs.

## Adversarial Capabilities

- **Low-privilege session**: supplies the ability to replay the same resource under arbitrary application verbs.
- **Request control**: controls the verb line plus body shape while holding session material constant.
- **Per-verb comparison ability**: compares per-verb responses to confirm execution.

## Trust Assumptions

- **The agreement**: the feature executes under a method-identity agreement at request handling time, the authorization decision made for the documented verb covers every verb reaching the same resource, the route table maps each verb to its equally guarded handler, and front-gate method identity equals executed method identity with no privileged effect leaking through a sibling verb.
- **The failing clause**: route-dispatch mapping lets an alternate application verb reach an unguarded handler while the documented verb stays guarded.

## Key Vulnerabilities

- **Core weakness**: authorization bound to the verb instead of the resource.
- **Missing sibling guard**: a missing guard on a sibling handler lets the same action execute without privilege.
- **Two shapes**: a write-only path reached through a read verb and a read-guarded path reached through a write verb.
- **Execution confirmation**: confirm execution by guarded-data return or observable state change, never by status alone.

## Advanced Techniques

- **Dispatch-map construction**: build the dispatch map by replaying each application verb against each guarded resource with identical session material.
- **Missing-guard mapping**: map missing-guard handlers including write paths reachable through a read verb and read paths reachable through an alternate write verb.
- **Execution anchoring**: anchor every map entry on execution proof rather than on status text.

## Bypass Techniques

- **Defeated control**: per-method authorization on the documented verb.
- **Bypass shape**: replays the sibling verb so the documented-verb check never engages.
- **Bypass confirmation**: compare the sibling-verb effect against the guarded baseline.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Dispatch escalation**: a confirmed dispatch gap escalates into object-level or function-level access over the exposed handler.
- **State-changing read verb**: chains into token-free cross-origin triggering where the method carries the action.
- **Companion-skill reference**: name the companion skill at the chaining step rather than restating its procedure.

## Testing Methodology

1. **Resource inventory** - list every guarded resource with its documented verb, and the step completes when no guarded path lacks a documented-verb entry.
2. **Sibling-verb replay** - replay each sibling application verb against each resource with identical session material, and the step completes when every resource carries a recorded status-plus-length entry for every application verb.
3. **Dispatch-map reconstruction** - reconstruct the dispatch map by marking verbs that diverge toward success or state change, and the step completes when each divergent verb is mapped to its handler outcome including write paths reached through a read verb.
4. **Execution confirmation** - confirm execution by comparing sibling-verb effect against the guarded baseline through data return or state change, and the step completes when each claimed bypass shows guarded data or a state effect unattainable through the documented verb under the same session.

## False Positives

- **Uniform enforcement**: uniform enforcement across verbs excludes this variant.
- **Status divergence without effect**: status divergence without data return or state effect excludes this variant.
- **Informational-verb responses**: belong to the informational variant and never confirm a dispatch gap here.

## Pro Tips

- **Full replay**: replay every sibling verb on every guarded resource rather than sampling obvious paths.
- **Header-only or bodyless answers as non-proof**: treat header-only or bodyless answers as non-proof until data return or state change confirms execution.
- **Constant session material**: hold session material constant across the matrix so divergence proves dispatch rather than identity.

## Summary

Verb-switch tampering breaks verb-bound authorization through sibling-verb dispatch gaps.
Map the dispatch table, replay each verb, and confirm execution by data or state effect.
