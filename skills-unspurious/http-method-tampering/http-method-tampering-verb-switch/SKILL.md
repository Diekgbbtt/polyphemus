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

This variant applies where a resource is reachable under two or more application verbs with method-differentiated routing.
The condition is a route table that binds authorization to the documented verb while a sibling verb reaches the same resource through a weaker handler.
State-changing handlers exposed under a read verb and read handlers exposed under a write verb both qualify.

## Reconnaissance

Inventory guarded resources plus administrative paths first.
Record the documented verb for each resource from normal navigation.
Flag every resource where the route table hints at per-verb handlers.
Reconnaissance is complete when each guarded resource carries its documented verb plus its candidate sibling verbs.

## Detection Channels

Status-plus-length divergence across application verbs signals a dispatch gap.
Guarded-data return or state-change effect on a sibling verb confirms execution.
Redirect-target divergence across verbs signals per-verb handler split.

## Adversarial Capabilities

This variant presupposes a low-privilege session able to replay the same resource under arbitrary application verbs.
It consumes control of the verb line plus body shape while holding session material constant.
It presupposes comparison ability across per-verb responses to confirm execution.

## Trust Assumptions

The feature executes under a method-identity agreement at request handling time.
The server contracts that the authorization decision made for the documented verb covers every verb reaching the same resource.
The server contracts that the route table maps each verb to its equally guarded handler.
The server contracts that front-gate method identity equals executed method identity and that no privileged effect leaks through a sibling verb.
The failing clause is route-dispatch mapping: an alternate application verb reaches an unguarded handler while the documented verb stays guarded.

## Key Vulnerabilities

The core weakness is authorization bound to the verb instead of the resource.
A missing guard on a sibling handler lets the same action execute without privilege.
A write-only path reached through a read verb and a read-guarded path reached through a write verb are the two shapes.
Confirm execution by guarded-data return or observable state change, never by status alone.

## Advanced Techniques

Build the dispatch map by replaying each application verb against each guarded resource with identical session material.
Map missing-guard handlers including write paths reachable through a read verb and read paths reachable through an alternate write verb.
Anchor every map entry on execution proof rather than on status text.

## Bypass Techniques

The defeated control is per-method authorization on the documented verb.
The bypass replays the sibling verb so the documented-verb check never engages.
Confirm the bypass by comparing the sibling-verb effect against the guarded baseline.

## Chaining Attacks

A confirmed dispatch gap escalates into object-level or function-level access over the exposed handler.
A state-changing read verb chains into token-free cross-origin triggering where the method carries the action.
Name the companion skill at the chaining step rather than restating its procedure.

## Testing Methodology

1. List every guarded resource with its documented verb.
Complete when no guarded path lacks a documented-verb entry.
2. Replay each sibling application verb against each resource with identical session material.
Complete when every resource carries a recorded status-plus-length entry for every application verb.
3. Reconstruct the dispatch map by marking verbs that diverge toward success or state change.
Complete when each divergent verb is mapped to its handler outcome including write paths reached through a read verb.
4. Confirm execution by comparing sibling-verb effect against the guarded baseline through data return or state change.
Complete when each claimed bypass shows guarded data or a state effect unattainable through the documented verb under the same session.

## False Positives

Uniform enforcement across verbs excludes this variant.
Status divergence without data return or state effect excludes this variant.
Informational-verb responses belong to the informational variant and never confirm a dispatch gap here.

## Pro Tips

Replay every sibling verb on every guarded resource rather than sampling obvious paths.
Treat header-only or bodyless answers as non-proof until data return or state change confirms execution.
Hold session material constant across the matrix so divergence proves dispatch rather than identity.

## Summary

Verb-switch tampering breaks verb-bound authorization through sibling-verb dispatch gaps.
Map the dispatch table, replay each verb, and confirm execution by data or state effect.
