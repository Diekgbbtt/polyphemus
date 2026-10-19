---
name: rfi-remote-include
description: Fetch hosted payloads through remote-scheme inclusion with outbound proof. Use when include sinks accept scheme-qualified names, when scheme policy decides remote reachability, when outbound callbacks confirm fetcher execution.
metadata:
  version: 1.0.0
---

# RFI Remote Include

Prove that scheme-qualified names fetch attacker-hosted content into the interpreter and execute retrieved content.
Treat every scheme-qualified name as untrusted until scheme enablement with outbound fetch proof confirms the boundary.

## Attack Surface

Applies where user influence reaches an include sink that resolves scheme-qualified names through a remote fetcher.
Applies where scheme policy and fetcher behavior decide whether retrieved content executes.
Varies only in which fetcher consumes the input and which outbound oracle proves the fetch-to-execution crossing.

## Reconnaissance

Inventory inclusion carriers that accept scheme-qualified names into fetchers and interpreters.
Record scheme policy by contrasting accepted scheme shapes against rejected scheme shapes.
Enumerate fetcher behavior that retrieves remote content and routes it toward evaluation.
Prepare hosted minimal content with deterministic output and a callback beacon under operator control.
Complete the survey when every inclusion carrier has a recorded scheme verdict and hosted content stands ready for fetch proof.

## Detection Channels

Outbound fetch receipt where a hosted beacon confirms the server retrieved attacker-controlled content.
Direct deterministic output where the response carries the hosted marker as evaluation evidence.
Error echo where fetcher warnings expose resolution behavior for a crafted scheme-qualified shape.

## Adversarial Capabilities

Submit scheme-qualified input through inclusion carriers without control over server code or scheme policy.
Host minimal payload content on operator-controlled infrastructure and observe outbound callbacks.
Correlate each crafted request with its beacon receipt to attribute fetcher behavior precisely.
Confirm evaluation through deterministic output rather than heavy execution shapes.

## Trust Assumptions

When the file-operation feature executes, the server trusts that carrier-supplied names join a base location under a normalization contract.
The server trusts that resolution states settle inside one intended root before any read occurs.
The server trusts that request primitives read only what the join permits and that exposed readers stay unreachable to crafted names.
The server trusts that sensitive file content never leaks to the sender through crafted resolution.
That trust fails at the remote-scheme clause: remote-scheme names fetch hosted content and execute retrieved content.

## Key Vulnerabilities

Scheme-qualified shapes that address hosted content through transfer and stream-handler spellings, held as <remote-shape>.
Fetcher shapes that retrieve remote content and route it toward evaluation instead of inert storage.
Enablement gaps where scheme policy permits remote retrieval in one sink while appearing forbidden elsewhere.
The delta over the parent is host-then-fetch proof with scheme enablement verification and beacon confirmation, which the parent fetcher and escalation steps never name.

## Advanced Techniques

Verify scheme enablement per sink by pairing accepted scheme shapes against rejected scheme shapes.
Host minimal content that returns deterministic output so evaluation proof stays quiet and attributable.
Correlate each request with per-candidate beacons to separate true fetcher callbacks from background noise.
Escalate from fetch confirmation to evaluation proof only after the outbound oracle completes.

## Bypass Techniques

Defeat scheme allowlists by spelling remote meaning across handler and encoded scheme shapes held as <remote-shape>.
Defeat name checks by nesting scheme meaning where validation resolves before the fetcher decodes.
Defeat fetcher assumptions by routing stream-handler shapes through sinks that evaluate rather than store.
Defeat appended-extension enforcement by terminating the name with a query or fragment delimiter where the fetcher truncates at it.
Defeat beacon blocking by keeping hosted content minimal and deterministic per candidate.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Carry confirmed remote retrieval into server-side request pivots through the companion request skill.
Carry evaluation proof into configuration recovery and template overwrite for persistence.
Name the server-side request companion at the pivot step rather than restating its procedure here.

## Testing Methodology

1. Inventory scheme-accepting carriers and record scheme policy per sink.
Complete when every inclusion carrier has a recorded accepted-versus-rejected scheme verdict.
2. Verify scheme enablement with benign hosted content and record fetcher retrieval behavior.
Complete when every scheme-accepting carrier has a recorded enablement verdict with no untested sink remaining.
3. Host minimal deterministic content with per-candidate beacons under operator control.
Complete when every candidate maps to exactly one hosted beacon with readiness confirmed.
4. Bent step: verify scheme enablement and host a minimal payload and confirm outbound fetch with beacon proof.
Complete when every hosted candidate has a recorded beacon verdict paired with a recorded evaluation verdict.

## False Positives

Exclude fetchers that retrieve remote content into inert storage without evaluation.
Exclude scheme policies that reject remote shapes consistently across every sink after decoding completes.
Exclude beacon receipts that trace to background scanning rather than the crafted candidate.

## Pro Tips

Prefer minimal deterministic markers over heavy execution shapes for fetch proof.
Attribute every beacon per candidate so concurrent tests never blur the verdict.
Verify enablement per sink since policy varies across inclusion surfaces.
Record beacon receipts with request correlation as hard evidence for every confirmed fetch.

## Summary

Confirm remote inclusion with scheme enablement checks, hosted minimal content, and beacon-backed fetch proof.
Forbid remote schemes where possible and bind fetchers to inert handling with consistent decoding at the input-output boundary.
