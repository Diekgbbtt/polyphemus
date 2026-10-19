---
name: http-request-smuggling-cross-protocol-desync
description: Framing desync at a translation hop into a binary back-end protocol, embedding a smuggled request inside the frame's own attribute encoding so the front-end's framing declaration never reaches the back-end, and reaching application-server paths the edge refuses.
metadata:
  version: 1.0.0
---

# HTTP Request Smuggling via Cross-Protocol Translation Desync

Cross-protocol desync breaks the framing agreement at a hop that translates HTTP into a binary protocol of the back-end's own design.
The hop re-encodes the request into attribute-encoded frames, so a request embedded in that encoding is never inspected by the front-end's framing checks.
The embedded request is executed by the back-end as a first-class request from the hop's network position, which reaches application-server paths the edge would refuse.

## Attack Surface

- **Applicability**: centers on a hop that terminates HTTP and re-emits a binary protocol whose frame and attribute encoding is its own.
- **Translation direction**: the front-end speaks HTTP to clients and the back-end speaks the binary protocol, and the hop maps a subset of HTTP semantics onto binary attributes.
- **Framing invisibility**: HTTP framing declarations are consumed at the translation hop, so the back-end never parses the boundary the edge validated.
- **Attribute surface**: the frame's attribute set, its length or terminator encoding, and every field the hop copies from an HTTP field into an attribute.
- **Interior paths**: application-server administrative paths reachable only from the hop's network position.
- **Out-of-scope shapes**: same-protocol framing pairs stay in the parent, and version-downgrade header injection stays in the downgrade sibling.

## Reconnaissance

### Hop and Frame Mapping

- **Hop-chain mapping**: identify the translation hop, the client-facing protocol, and the back-end protocol, and record which HTTP fields map onto binary attributes.
- **Frame-shape recording**: record the frame and attribute encoding the hop emits, including how lengths and terminators are expressed.
- **Copy-set probing**: send one HTTP field at a time with a distinguishable value and observe which attributes carry it.
- **Interior-path inventory**: enumerate the application-server paths the back-end exposes from the hop's position.
- **Connection correspondence**: record whether the hop keeps one back-end connection per client or a shared pool, because a shared pool is what carries a smuggled frame to another party.

## Detection Channels

- **Attribute-copied marker**: a marker sent in one HTTP field arrives at the back-end inside a binary attribute, which proves the copy step.
- **Framing-blindness read**: the front-end accepts a request whose declared boundary and true body disagree, because the hop re-derives the boundary from an attribute.
- **Edge-refused path reached**: an application-server path answers although the edge refuses the same path directly.
- **Response-queue anomaly**: a response answers a request that was never sent on that connection.
- **Connection-correspondence signal**: repeated client requests ride one back-end connection, which is the precondition for a smuggled frame reaching another party.

## Adversarial Capabilities

- **Binary frame composition**: build the binary frame and its attributes, including a request embedded inside the attribute encoding.
- **Translation mapping**: know which HTTP field becomes which attribute, because only mapped fields reach the back-end frame.
- **Connection observation**: hold one client connection across requests and read response pairing plus ordering against a clean baseline.
- **Interior reach testing**: request an application-server path and read whether the back-end or the edge answered.
- **Explicit authorisation**: run capture-shaped attempts only with authorisation and during low-traffic periods.

## Trust Assumptions

- **The agreement**: the translation hop trusts that the binary frame encoding carries one request per frame, and that the HTTP boundary the edge validated is the boundary the back-end honours.
- **The failing clause**: this variant breaks the translation-boundary clause because the hop re-encodes the request into binary attributes without reconciling the HTTP framing the edge validated, so a request embedded in the attribute encoding executes as a first-class back-end request.

## Key Vulnerabilities

### Attribute-Encoded Request Embedding

- **Framing re-derivation**: the hop derives the binary length or terminator from a mapped field rather than from the HTTP body it consumed, so the surplus bytes stay inside the frame.
- **Embedded prefix**: the smuggled request rides the attribute encoding rather than the HTTP framing, so the edge's framing checks never inspect it.
- **First-class execution**: the back-end treats the embedded request as an ordinary request from the hop and answers it from the hop's network position.
- **Ownership note**: the parent owns same-protocol framing pairs and the downgrade sibling owns version translation, so this variant owns only the binary-protocol hop.

### Edge-Invisible Reach

- **Control bypass**: the front-end's authentication and request-shaping checks apply to the outer HTTP request, so the embedded request skips them.
- **Interior path access**: application-server administrative and management paths become reachable because the back-end considers the hop a trusted caller.
- **Narrow weaponisation**: aim the embedded request at one interior path or one reflective handler, then stop at the narrowest durable proof.

## Advanced Techniques

**Attribute Set Enumeration**
- Move the injected field between mapped and unmapped positions to learn which positions the hop forwards.
- Record one verdict per position so the mapped set stays explicit.

**Terminator Variation**
- Vary the frame's terminator and length encoding to find the shape the back-end honours over the HTTP declaration.
- Prefer the smallest variation that still reaches the back-end unchanged.

**Shared-Pool Amplification**
- Prefer a shared back-end pool, because a per-client connection limits the smuggled frame to its own client.
- Confirm connection correspondence before attempting capture-shaped effects.

**Quiet Confirmation**
- Confirm with a marker read plus a response-pairing anomaly before attempting interior-path reach.
- Keep the embedded request short during detection and extend it only after the mapping is proven.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no spelling changes the translation-boundary oracle itself.
- **Mapped-field obfuscation**: encode or duplicate the mapped HTTP field so the hop's copy step and its validation step read different values.
- **Attribute-order variation**: reorder attributes where the back-end resolves duplicates by position rather than by name.
- **Framing-declaration conflict**: present conflicting HTTP framing declarations so the hop's re-derivation and the edge's validation diverge.
- **Layered combinations**: name the defence-bypass family at the filter step and the proxy-techniques family at the channel-wrapping step rather than restating either here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Bypass to privileged action**: hand a reached application-server path to a privileged management action.
- **Capture to session theft**: aim an embedded partial request at a reflective handler so the next caller's headers return in a readable response.
- **Reflection to cache poisoning**: land the embedded request on a cacheable path so later callers receive the stored response, where the cache oracle fits better than this one.
- **Escalation to deployment control**: use application-server management paths to reach deployment or application control, then stop at the narrowest durable effect.

## Testing Methodology

Cross-protocol desync runs hop mapping first and embedded-request proof last, because a binary frame without a mapped attribute cannot be confirmed.
1. **Map the hop chain** - record the client-facing protocol, the translation hop, the back-end protocol, and the mapped-field set, and the step completes when every hop and every mapped field is identified.
2. **Record the frame shape** - capture the frame and attribute encoding the hop emits, and the step completes when the length and terminator encoding are documented.
3. **Probe attribute copying** - send one distinguishable HTTP field at a time and read which binary attribute carries it, and the step completes when every field carries a copied-or-dropped verdict.
4. **Embed a request** - place a marked request inside the attribute encoding, and the step completes when the back-end executes it or the attempt is recorded as failed.
5. **Confirm invisibility** - repeat the embedded request against a path the edge refuses directly, and the step completes when the back-end answer is distinguished from the edge refusal.
6. **Test connection correspondence** - repeat header blocks over one client connection and read response pairing against a clean baseline, and the step completes when the socket-reuse behaviour is recorded.
7. **Weaponise narrowly** - aim the embedded request at one interior path or one reflective handler, and the step completes when the effect is recorded or ruled out with its evidence.

## False Positives

- **Stop condition**: stop when the evidence shows the hop re-frames one request per frame with no attribute-copied surplus, because a re-encoded request is not a smuggled one.
- **Single-protocol path**: no translation hop exists, so the binary framing is never reached.
- **Normalising hop**: the hop rejects or reconciles a mismatched declaration before re-encoding, confirmed by uniform refusals across the frame shapes.
- **Per-client connection**: the hop opens a fresh back-end connection per client request, so no smuggled frame survives to another party.
- **Uniform interior answers**: the interior path answers identically whether or not the embedded request rode the frame, which reads as ordinary handling rather than reach.

## Pro Tips

1. Prefer mapping the copied-field set first, since only mapped fields can carry the embedded request.
2. Favor one injected field per frame so the attribute that carries it attributes exactly.
3. Confirm with a marker plus a response-pairing anomaly before attempting interior-path reach.
4. Run capture-shaped attempts only with explicit authorisation and during low-traffic periods, because they touch real callers.
5. Hand any same-protocol framing result to the parent and any version-translation result to the downgrade sibling rather than stretching this oracle.

## Summary

A hop that re-encodes HTTP into its own binary frame hands request execution to whoever hides a request inside the frame's attributes.
Cross-protocol desync maps the hop and its copied fields, embeds a marked request, and proves the back-end executes what the edge never inspected.
