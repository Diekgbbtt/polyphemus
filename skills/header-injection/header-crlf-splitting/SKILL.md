---
name: header-crlf-splitting
description: Splitting responses when line-break payloads land as stored header fields, serving a second response to unrelated requests, and bending downstream cache or proxy storage with injected framing.
metadata:
  version: 1.0.0
---

# CRLF Response Splitting

Response framing parsers treat certain byte sequences as structural boundaries.
This variant proves that an attacker-influenced value carrying a line-break sequence becomes a stored header field that a downstream component serves to an unrelated request.
The splitting goal is protocol-level control over a cached or proxied response, which later enables fixation plus poisoning plus script execution through the injected content.

## Attack Surface

- **Applicability**: centers on a response path that permits raw line breaks to become framing.
- **Carrier path**: the path copies an attacker-influenced value from a query or body or path or cookie carrier into a response header field without line-break stripping.
- **Proxy-fronted deployment**: a proxy-fronted deployment sits behind the origin, so a stored injected field can be served to requests that never carried the payload.
- **Excluded shapes**: delimiter-free replacement without line breaks belongs to header-response-value-confusion, and framing-disagreement pairs belong to header-request-smuggling, so neither rides here.

## Reconnaissance

- **Inventory**: narrows to header fields whose values move with input and that reach a framing parser.
- **Carrier diffing**: flip each carrier value and diff the response header set, and record the source field behind every moving value.
- **Line-break family**: enumerate the line-break family per source in abstract shape, namely bare feed form plus bare return form plus the pair form plus double-encoded form plus overlong form plus separator-equivalent forms plus tab form plus truncation form.
- **Stack fingerprinting**: fingerprint the stack through banner plus cache-signal headers, and replay each shape across protocol versions to map parsing differences.

## Detection Channels

- **Splitting**: listens for stored framing.
- **Stored second field**: injected second header field stored and served downstream as a real header field binds the probe to the parser trust.
- **Second-response serving**: second response served to an unrelated clean request proves the injected framing left the attack session.
- **Header-set diff**: header-set diff between the attack replay and a clean replay isolates the injected field from ambient variation.
- **Stored-entry signal**: cache-signal values showing a stored entry behind the poisoned response confirm downstream persistence.

## Adversarial Capabilities

- **Splitting**: presupposes header-reaching input supply plus downstream observation, and it consumes both.
- **Carrier supply**: supply attacker-influenced values into every carrier that reaches a response header field.
- **Downstream observation**: observe a downstream or second-session response that never carried the payload, and compare its header set against the attack response.
- **Version replay**: replay each line-break shape across protocol versions to find the parser that accepts it.
- **Quiet probing**: hold the probe quiet enough that ambient cache churn cannot explain a stored field.

## Trust Assumptions

- **The agreement**: the stack treats an attacker-influenced value that reaches a response header field as inert data at the moment the feature executes, holds the value free of framing meaning from capture through serialization, holds one declared interpreter for the value across the proxy-to-backend-to-client path, keeps the request in its declared method plus path plus protocol shape, keeps each response observable only to its caller, and keeps link targets plus cached bodies plus session state plus token-bearing destinations out of attacker reach.
- **The failing clause**: a line-break payload becomes a stored header field that a downstream component serves to an unrelated request.

## Key Vulnerabilities

### Line-Break Termination Plus Second Response

- **Response termination**: terminate the current response with a line-break sequence placeholder, then prepend an attacker-controlled second response in abstract shape.
- **Downstream-serving proof**: the parent probe step covers only whether the second line lands, so this variant owns the downstream-serving proof that turns a landed line into stored framing.
- **State-setting example**: session-state header injection in the shape of an abstract state-setting directive rides here as the canonical stored-field example.

### Downstream Storage And Serving

- **Persistence confirmation**: confirm the injected field persists in the cache or proxy store and replays to a request that carries no payload.
- **Storage boundary**: treat storage as the vulnerability boundary, because a line the origin strips or the edge drops before any store is only a reflection.
- **Sibling boundary**: name framing-disagreement pairs at this step rather than restating them, since header-request-smuggling owns leftover-bytes proof across chained parsers.

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no encoding changes the stored-field oracle itself.
- **Line-break layering**: layer single-encoded plus double-encoded plus overlong plus separator-equivalent line-break forms past a single-decode filter.
- **Whitespace edges**: slip tab plus whitespace plus folded-continuation edges past a filter that strips only strict pair sequences.
- **Duplicate splitting**: split duplicate header fields so the enforcing side joins them while the storing side keeps the injected member.
- **Casing and truncation**: mangle field-name casing plus truncation markers where the filter keys off exact spelling.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Splitting**: chains forward through the stored response because a stored field without a consumer is only persistence.
- **Session fixation**: hand a stored state-setting field to session fixation against the next visitor of the poisoned entry.
- **Script execution**: hand a stored body plus script-capable content type to script execution in the victim session.
- **Cache-poisoning handoff**: hand a stored poisoned entry to header-cache-poisoning confirmation where the cache oracle fits better than the framing oracle.

## Testing Methodology

Splitting runs inventory before injection and storage proof last, because unstored lines are only reflections.
1. **Inventory moving fields** - list every response header field whose value moves with input plus its source carrier, and the step completes when no moving field lacks a recorded source.
2. **Probe normalization per source** - replay the line-break family against each moving source, and the step completes when every source shows a landed-or-stripped verdict with its samples.
3. **Prove downstream storage** - replay an unrelated clean request with no payload and diff its header set, and the step completes when the injected field appears as a real header field or is ruled out with its evidence.
4. **Confirm second-response serving** - check whether a full attacker-controlled second response replays to the clean request, and the step completes when serving is confirmed or bounded to a single field with its evidence.
5. **Replay across versions** - repeat the confirmed shape over the remaining protocol versions, and the step completes when every version carries a stored-or-clean verdict.

## False Positives

- **Stop condition**: stop when the evidence shows reflection without storage, because splitting without a store is only noise.
- **Origin stripping**: origin strips line breaks before serialization, confirmed by a clean downstream header set across all shapes.
- **Proxy dropping**: outer proxy drops the injected field before any store or client, confirmed by edge-versus-origin diffing.
- **Per-session keying**: moving fields stay correctly keyed per session, so no unrelated request ever sees the injected value.
- **Keep-alive artifacts**: pipelined or keep-alive artifacts mistaken for a second response, confirmed by clean-replay absence.

## Pro Tips

- **Splitting**: rewards storage proof over landing proof, because only stored framing bends other users.
- **State-setting first**: prefer the state-setting field shape first, since stores keep it and diffs show it plainly.
- **One clean request per probe**: favor one clean unrelated request per probe so attribution stays exact.
- **Cache-signal verification**: verify the stored field through the cache-signal values before claiming a second response.
- **Stripped-source rule-out**: treat a stripped source as ruled out and move the family to the next moving field.
- **Sibling naming**: name the smuggling sibling at any framing-pair finding rather than bending this oracle to fit it.

## Summary

A response parser that stores line-break payloads as real header fields hands protocol control to whoever supplies input.
Splitting inventories moving fields, replays the line-break family, and proves an unrelated request receives the injected framing before any follow-up chain begins.
