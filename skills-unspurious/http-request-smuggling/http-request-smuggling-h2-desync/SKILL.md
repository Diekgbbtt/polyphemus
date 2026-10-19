---
name: http-request-smuggling-h2-desync
description: Downgrade desync probing through HTTP/2 header-block framing injection. Use when the path downgrades HTTP/2 to HTTP/1.1 before the back-end, when an injected content-length field disagrees with the true body length, or when a spec-forbidden transfer-encoding field survives the front-end.
metadata:
  version: 1.0.0
---

# HTTP Request Smuggling via HTTP/2 Downgrade Desync

Downgrade desync breaks the framing agreement at the protocol-translation hop.
A front-end speaks HTTP/2 to the client and re-emits HTTP/1.1 to the back-end, and attacker header fields injected in the HTTP/2 header block become the back-end framing.
The leftover prefix stays on the shared back-end socket and prepends to the next legitimate request, which yields bypass of front-end checks or capture of another user's bytes.

## Attack Surface

- **Downgrade desync**: applies where a translation hop converts HTTP/2 header blocks into HTTP/1.1 framing for the back-end.
- **Front-end hop**: accepts HTTP/2 connections from clients.
- **Back-end hop**: parses HTTP/1.1 framing derived from forwarded header fields.
- **Connection persistence**: connections persist across requests so one socket serves successive users.
- **Downgrade path**: maps at least one framing-relevant header field from the HTTP/2 block onto the re-emitted request.

## Reconnaissance

- **Hop-chain mapping**: map the hop chain and record the protocol version spoken on each hop.
- **Front-end version confirmation**: confirm the front-end negotiates HTTP/2 with clients.
- **Back-end version confirmation**: confirm the back-end receives HTTP/1.1 framing from the translation hop.
- **Surviving-field probe**: probe which header fields survive translation and in what form.
- **Connection-correspondence record**: record whether one client connection corresponds to one persistent back-end connection.
- **Reconnaissance completion**: every hop version is identified and the surviving-field set is recorded.

## Detection Channels

- **Downgrade mapping**: observe which injected framing field reaches the back-end and which value wins when both disagree.
- **Passthrough survival**: observe whether a spec-forbidden framing field arrives at the back-end intact.
- **Length divergence**: observe behaviour change when the injected declared length differs from the true body length.
- **Connection correspondence**: observe whether repeated header blocks ride one persistent back-end socket.
- **Differential marker confirmation**: send two rapid requests carrying a unique placeholder token and treat an unexpected or token-bearing second response as proof of socket poisoning.

## Adversarial Capabilities

- **Raw header-block client**: the variant presupposes a client that crafts raw HTTP/2 header blocks field by field.
- **Declared-length field injection**: the operator injects a regular declared-length field kept distinct from the reserved pseudo-header fields.
- **Framing-field injection**: the operator injects a spec-forbidden framing field that the HTTP/2 framing itself never authorises.
- **Reused-connection control**: the operator holds a reused connection open and reads mapping, timing, and differential responses.
- **Prefix shaping**: the operator shapes short smuggled prefixes and aims them at restricted or reflective endpoints once desync confirms.

## Trust Assumptions

- **The agreement**: the translation path executes under one agreement where the back-end trusts the front-end parsed framing, treats the re-emitted framing as proxy-originated, and processes any bytes beyond the declared body as the next legitimate request on the shared socket, and the agreement covers the header contract between hops, the persistent socket state, the downgrade mapping primitives, the restricted and reflective endpoints the server exposes, and the session bytes that could leak with an adversarial orientation.
- **The failing clause**: the mapping clause fails because the downgrade path derives back-end framing from an attacker-supplied header field that the HTTP/2 framing never authorised.

## Key Vulnerabilities

### Downgrade length injection

- **Length disagreement**: the header block carries a regular declared-length field whose value disagrees with the true body length.
- **Translation re-emission**: the translation hop re-emits that value as the back-end framing while the front-end already consumed the true body.
- **Socket surplus**: the back-end then waits for bytes that never arrive or leaves bytes the front-end already accounted for, and the surplus stays on the socket.
- **Injection shape**: shape the injection as a header block with a declared-length placeholder plus a smuggled-prefix placeholder, keeping pseudo-header fields valid and placing the injected field as a regular field.

### Downgrade framing-field injection

- **Forbidden-field passthrough**: the header block carries a spec-forbidden framing field that the front-end passes through instead of rejecting.
- **Boundary divergence**: the back-end receives both framing signals and prefers the injected one, so its request boundary diverges from the front-end boundary.
- **Hidden-prefix residue**: the divergence leaves a hidden prefix that the back-end prepends to the next request on the shared socket.
- **Injection shape and read-out**: shape the injection as a header block with a forbidden-field placeholder plus a smuggled-prefix placeholder, then read which signal the back-end honoured.

### Prefix weaponisation

- **Bypass prefix**: a confirmed prefix becomes a bypass when it names a restricted endpoint the front-end would otherwise refuse.
- **Capture prefix**: a confirmed prefix becomes a capture when it names a reflective endpoint and declares a length modestly beyond its own partial body, so the back-end sources the remainder from the next user's bytes.
- **Shared desync channel**: both outcomes ride the same desync channel and differ only in the prefix payload choice.

### Upgrade and Tunnel Aspect Values

- **Enumerated aspect values**: the two framing injections stay the enumerated values inside one variant, because one inject-then-observe step covers both.
- **Upgrade and tunnel shapes**: cleartext-upgrade and tunnel-establishment shapes ride as aspect values - an upgrade request the front-end passes through while the back-end re-reads its framing, and a tunnel-establishment request that opens a channel the front-end attributes to its own upgrade handling.

## Advanced Techniques

- **Mapping-observation depth**: deepen the mapping observation by injecting each framing field alone and then both together, recording which value wins each conflict.
- **Pseudo-header discipline**: keep reserved fields valid while moving the injected field between regular positions to find placements the translation hop forwards.
- **Passthrough-survival probe**: probe passthrough survival across field encodings the normaliser may mishandle, recording per-value survival rather than assuming uniform handling.
- **Impact amplification**: amplify impact through connection correspondence by confirming one persistent back-end socket before attempting capture, since capture needs the victim bytes to land on the poisoned socket.

## Bypass Techniques

- **Normalisation defeat**: defeat framing normalisation at the translation hop rather than at the HTTP/1.1 layer.
- **Inspected-versus-mapped field**: shape the injection so the field the normaliser inspects differs from the field the downgrade path maps onto the re-emitted request.
- **Forbidden-field preference**: prefer the forbidden framing field where the front-end validates only HTTP/2 framing rules and forwards unknown fields untouched.
- **Declared-length preference**: prefer the regular declared-length field where the translation hop derives back-end framing from it without reconciling it against the true body.
- **Attempt completion**: each attempt is complete when the survival read-out names the exact field and value the back-end honoured.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Bypass-to-privilege chain**: chain bypass into privileged access by smuggling a request for a restricted endpoint and reading whether the back-end accepts it as proxy-originated.
- **Capture-to-session chain**: chain capture into session theft by aiming a partial prefix at a reflective endpoint and reading victim bytes in the controlled response.
- **Reflection-to-cache chain**: chain reflection into cache poisoning by smuggling a prefix that strikes a cacheable endpoint with a substituted host value, then reading whether later requests receive the poisoned response.
- **Upgrade-to-connection chain**: chain upgrade into connection theft where the path supports protocol upgrade, by smuggling the upgrade handshake over the confirmed desync channel.

## Testing Methodology

1. Map the chain and record the protocol version on each hop, complete when front-end, translation hop, and back-end versions are all identified.
2. Craft a header block carrying an injected declared-length field that disagrees with the true body length, complete when the block is sent and the downgrade read-out is recorded.
3. Craft a header block carrying a spec-forbidden framing field, complete when the block is sent and the passthrough-survival read-out is recorded.
4. Observe downgrade mapping, passthrough survival, and connection correspondence across both injections, complete when the winning field per conflict and the socket-reuse behaviour are both recorded.
5. Confirm with a differential marker response over two rapid requests, complete when the second response is classified as expected or as marker-bearing proof of poisoning.
6. Attempt bypass against a restricted endpoint over the confirmed channel, complete when the back-end acceptance or rejection is recorded.
7. Attempt capture with a partial prefix against a reflective endpoint, complete when follow-up bytes are captured or the attempt is recorded as failed.

## False Positives

- **Baseline latency**: exclude baseline latency and server-side processing delays that mimic desync timing without any framing divergence.
- **Non-reused connections**: exclude paths that close the connection after the first request, since no shared socket exists to poison.
- **End-to-end HTTP/2 paths**: exclude end-to-end HTTP/2 paths with no HTTP/1.1 downgrade, since no translation hop maps injected fields into framing.
- **Normalising proxies**: exclude proxies that strip or reconcile injected framing fields before re-emitting, since the ambiguity never reaches the back-end.

## Pro Tips

- **Minimal prefixes**: favour minimal prefixes during detection and escalate to weaponised prefixes only after differential confirmation.
- **Declared-length priority**: favour the declared-length injection first on new targets, since length mapping is the most commonly mishandled translation.
- **Capture-prefix sizing**: size capture prefixes so the declared length modestly exceeds the partial body, leaving room for a full credential header from the next user.
- **Capture authorisation**: run capture attempts only with explicit authorisation and during low-traffic periods.
- **Pipelined fallback**: fall back to pipelined request pairs on one connection when timing read-outs stay inconsistent, and read response swapping instead of delay.

## Summary

Downgrade desync turns HTTP/2 header-block injection into back-end framing disagreement at the translation hop.
Confirm the mapping, prove poisoning with a differential marker, then chain the prefix into bypass or capture.
The path is closed by reconciling or rejecting injected framing fields at translation and by refusing to derive back-end framing from fields the client framing never authorised.
