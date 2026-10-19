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

- **Applicability**: applies where user influence reaches an include sink that resolves scheme-qualified names through a remote fetcher.
- **Policy and behavior**: applies where scheme policy and fetcher behavior decide whether retrieved content executes.
- **Fetcher variance**: varies only in which fetcher consumes the input and which outbound oracle proves the fetch-to-execution crossing.

## Reconnaissance

- **Carrier inventory**: inventory inclusion carriers that accept scheme-qualified names into fetchers and interpreters.
- **Scheme-policy recording**: record scheme policy by contrasting accepted scheme shapes against rejected scheme shapes.
- **Fetcher-behavior enumeration**: enumerate fetcher behavior that retrieves remote content and routes it toward evaluation.
- **Hosted-content preparation**: prepare hosted minimal content with deterministic output and a callback beacon under operator control.
- **Survey completion**: complete the survey when every inclusion carrier has a recorded scheme verdict and hosted content stands ready for fetch proof.

## Detection Channels

- **Outbound fetch receipt**: where a hosted beacon confirms the server retrieved attacker-controlled content.
- **Direct deterministic output**: where the response carries the hosted marker as evaluation evidence.
- **Error echo**: where fetcher warnings expose resolution behavior for a crafted scheme-qualified shape.

## Adversarial Capabilities

- **Input submission**: submit scheme-qualified input through inclusion carriers without control over server code or scheme policy.
- **Payload hosting**: host minimal payload content on operator-controlled infrastructure and observe outbound callbacks.
- **Receipt correlation**: correlate each crafted request with its beacon receipt to attribute fetcher behavior precisely.
- **Evaluation confirmation**: confirm evaluation through deterministic output rather than heavy execution shapes.

## Trust Assumptions

- **The agreement**: when the file-operation feature executes, the server trusts that carrier-supplied names join a base location under a normalization contract. The server trusts that resolution states settle inside one intended root before any read occurs. The server trusts that request primitives read only what the join permits and that exposed readers stay unreachable to crafted names. The server trusts that sensitive file content never leaks to the sender through crafted resolution.
- **The failing clause**: the remote-scheme clause: remote-scheme names fetch hosted content and execute retrieved content.

## Key Vulnerabilities

- **Scheme-qualified shapes**: that address hosted content through transfer and stream-handler spellings, held as <remote-shape>.
- **Fetcher shapes**: that retrieve remote content and route it toward evaluation instead of inert storage.
- **Enablement gaps**: where scheme policy permits remote retrieval in one sink while appearing forbidden elsewhere.
- **Variant delta**: the delta over the parent is host-then-fetch proof with scheme enablement verification and beacon confirmation, which the parent fetcher and escalation steps never name.

## Advanced Techniques

- **Enablement verification**: verify scheme enablement per sink by pairing accepted scheme shapes against rejected scheme shapes.
- **Quiet hosting**: host minimal content that returns deterministic output so evaluation proof stays quiet and attributable.
- **Beacon correlation**: correlate each request with per-candidate beacons to separate true fetcher callbacks from background noise.
- **Escalation sequencing**: escalate from fetch confirmation to evaluation proof only after the outbound oracle completes.

## Bypass Techniques

- **Scheme-allowlist bypass**: defeat scheme allowlists by spelling remote meaning across handler and encoded scheme shapes held as <remote-shape>.
- **Name-check bypass**: defeat name checks by nesting scheme meaning where validation resolves before the fetcher decodes.
- **Fetcher-assumption bypass**: defeat fetcher assumptions by routing stream-handler shapes through sinks that evaluate rather than store.
- **Extension-enforcement bypass**: defeat appended-extension enforcement by terminating the name with a query or fragment delimiter where the fetcher truncates at it.
- **Beacon-blocking bypass**: defeat beacon blocking by keeping hosted content minimal and deterministic per candidate.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Request pivots**: carry confirmed remote retrieval into server-side request pivots through the companion request skill.
- **Persistence writes**: carry evaluation proof into configuration recovery and template overwrite for persistence.
- **Companion-skill reference**: name the server-side request companion at the pivot step rather than restating its procedure here.

## Testing Methodology

1. **Carrier inventory** - inventory scheme-accepting carriers and record scheme policy per sink, and the step completes when every inclusion carrier has a recorded accepted-versus-rejected scheme verdict.
2. **Enablement verification** - verify scheme enablement with benign hosted content and record fetcher retrieval behavior, and the step completes when every scheme-accepting carrier has a recorded enablement verdict with no untested sink remaining.
3. **Hosted-content preparation** - host minimal deterministic content with per-candidate beacons under operator control, and the step completes when every candidate maps to exactly one hosted beacon with readiness confirmed.
4. **Bent step** - verify scheme enablement and host a minimal payload and confirm outbound fetch with beacon proof, and the step completes when every hosted candidate has a recorded beacon verdict paired with a recorded evaluation verdict.

## False Positives

- **Inert fetchers**: exclude fetchers that retrieve remote content into inert storage without evaluation.
- **Consistent rejection**: exclude scheme policies that reject remote shapes consistently across every sink after decoding completes.
- **Background receipts**: exclude beacon receipts that trace to background scanning rather than the crafted candidate.

## Pro Tips

- **Minimal markers**: prefer minimal deterministic markers over heavy execution shapes for fetch proof.
- **Beacon attribution**: attribute every beacon per candidate so concurrent tests never blur the verdict.
- **Per-sink verification**: verify enablement per sink since policy varies across inclusion surfaces.
- **Evidence recording**: record beacon receipts with request correlation as hard evidence for every confirmed fetch.

## Summary

Confirm remote inclusion with scheme enablement checks, hosted minimal content, and beacon-backed fetch proof.
Forbid remote schemes where possible and bind fetchers to inert handling with consistent decoding at the input-output boundary.
