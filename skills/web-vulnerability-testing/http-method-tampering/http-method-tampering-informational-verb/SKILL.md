---
name: http-method-tampering-informational-verb
description: Exploit informational verbs beyond transport reads to expose handler gaps where disclosure drives bypass selection, when header-only responses leak guarded metadata, or when echo material replays as credentials.
metadata:
  version: 1.0.0
---

# Informational Verb Exploitation

This skill exploits informational-verb handling gaps beyond recording by turning disclosure into bypass selection plus header-only extraction plus echo-material replay.
It owns the informational verbs exclusively and never counts them toward the application-verb matrix.

## Attack Surface

- **Applicability**: informational handlers answer outside the application authorization path.
- **Qualifying condition**: a disclosure handler, a header-only handler, or an echo handler is reachable without the guards of the application verbs.
- **Qualifying resources**: those exposing method lists, header-only success, or request reflection.

## Reconnaissance

- **Informational-endpoint inventory**: inventory endpoints answering informational verbs across the target surface.
- **Answer recording**: record disclosure content, header-only divergence, and echo presence per endpoint without exploiting them yet.
- **Disclosure flagging**: flag disclosure entries that name further guarded paths for targeted selection.
- **Completion criterion**: reconnaissance is complete when each endpoint carries its disclosure content plus its header-only outcome plus its echo outcome.

## Detection Channels

- **Disclosure of the allowed-method list**: confirms the disclosure channel.
- **Header-only success diverging from the guarded read**: confirms the metadata-extraction channel.
- **Reflection containing session or credential material**: confirms the echo-capture channel.

## Adversarial Capabilities

- **Low-privilege session**: supplies the ability to send informational verbs and read their transport-level answers.
- **Material consumption**: consumes disclosure content for bypass selection plus header metadata for extraction plus reflected material for replay.
- **Replay ability**: reuses reflected material as credential input.

## Trust Assumptions

- **The agreement**: the feature executes under a method-identity agreement at request handling time, the authorization decision made for the documented verb covers every verb reaching the same resource, the route table maps each verb to its equally guarded handler, and front-gate method identity equals executed method identity with no privileged effect leaking through a sibling verb.
- **The failing clause**: informational handling lets disclosure plus header-only plus echo handlers execute outside authorization and leak selectable or replayable material.

## Key Vulnerabilities

- **Core weakness**: privileged transport behavior left outside the authorization path.
- **Disclosure output**: selects the next bypass target with certainty instead of guessing.
- **Header-only handling**: returns guarded metadata without body checks.
- **Echo handling**: reflects credential material that replays as authentication input.

## Advanced Techniques

- **Disclosure-driven selection**: select bypass targets from disclosure content by matching listed methods against guarded resources.
- **Header-only extraction**: extract guarded metadata from header-only success where the guarded read stays denied.
- **Echo replay**: extract reflected material from echo answers and replay it as credential input with execution confirmation.

## Bypass Techniques

- **Defeated controls**: authorization parity across verbs and echo containment.
- **Bypass path**: reads disclosure and metadata without triggering body checks and replays reflected material past authentication.
- **Confirmation basis**: confirm each bypass by data return, metadata use, or authenticated effect rather than by transport success alone.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Disclosed method lists**: chain into targeted verb-switch or override attempts against the listed handlers.
- **Replayed echo material**: chains into session or credential abuse where the reflected input authenticates.
- **Companion-skill reference**: name the companion skill at the chaining step rather than restating its procedure.

## Testing Methodology

1. Probe each endpoint with disclosure, header-only, and echo verbs and record each answer.
Complete when every endpoint carries disclosure content plus header-only outcome plus echo outcome.
2. Select bypass targets from disclosure content by matching listed methods to guarded resources.
Complete when each selected target cites the disclosure entry that named it.
3. Extract guarded metadata from header-only success diverging from the guarded read.
Complete when each extraction shows metadata unattainable through the guarded read under the same session.
4. Extract reflected credential material from echo answers and replay it toward authentication.
Complete when each replay shows an authenticated effect or guarded-data return proving the reflected material functioned as credential input.

## False Positives

- **Public-only disclosure**: disclosure naming only public handlers excludes targeted-bypass claims.
- **Header-only parity**: parity with the guarded read excludes extraction claims.
- **Echo without credential material**: echo answers without credential material or disabled echo handling exclude capture claims.

## Pro Tips

- **Disclosure-driven targeting**: drive target selection from disclosure content rather than re-scanning blindly.
- **Header-only discipline**: treat header-only success as extraction only where the guarded read stays denied under the same session.
- **Replay proof**: treat reflected material as unproven until replay produces an authenticated effect.

## Summary

Informational-verb exploitation turns transport gaps into disclosure-driven bypass plus metadata extraction plus credential replay.
Probe each handler, exploit beyond recording, and confirm by data, metadata use, or authenticated effect.
