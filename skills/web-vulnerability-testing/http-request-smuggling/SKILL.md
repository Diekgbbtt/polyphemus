---
name: http-request-smuggling
description: HTTP request smuggling testing covering CL.TE, TE.CL, H2.CL, H2.TE, and HTTP/2 desync techniques with practical detection and exploitation methodology
metadata:
  version: 1.0.0
---

# HTTP Request Smuggling

HTTP request smuggling exploits disagreements between a front-end proxy and a back-end server about where one request ends and the next begins. When the two sides parse the length and encoding declarations differently, an attacker can prefix a hidden request onto the back-end socket, where it is prepended to the next user's request. The impact ranges from bypassing front-end controls to cross-user session capture.

## Attack Surface

**Topologies**
- **Edge in front of an origin**: cache, load balancer, or gateway.
- **Proxy chains**: where each hop reparses and reframes the request.
- **API gateways**: forwarding to services.
- **Protocol translation**: from a modern front-end protocol to an older back-end protocol.
- **Tunneling and filtering layers**: that terminate and re-forward requests.

**Protocol versions**
- **Older versions**: carry the classic length-versus-encoding ambiguity.
- **Newer versions**: carry the downgrade-injected declarations and frame-level shapes.

**Ambiguity surface**
- **Duplicate length declarations**: with different values.
- **Encoding beside length**: an encoding declaration present beside a length declaration.
- **Chunk size obfuscation**: through whitespace, tab, case, or invalid extensions.
- **Header-block and frame boundaries**: where reassembly order differs between hops.
- **Smuggling carrier families**: see `references/smuggling-carrier-families.md` for the carriers a smuggled prefix can ride and each carrier's prerequisite.

## Reconnaissance

### Map the Chain

- **Hop identification**: identify each hop between the client and the application, and note which protocol version each hop speaks.
- **Connection termination**: note whether the front-end terminates the connection or reuses a back-end socket across client connections.
- **Ambiguity handling**: record whether the front-end rejects ambiguous requests or normalizes them before forwarding.
- **Strictness posture**: fingerprint the front-end strictness posture before any pair sweep - a front-end that rejects or normalizes ambiguous framing closes the plain forms, so record that posture as the gate for the probe set rather than spending pairs on it.

### Probe Framing Acceptance

- **Conflicting declarations**: send a request whose declared lengths conflict and watch which declaration each hop honours.
- **Direction comparison**: compare the two directions - front-end reads length while back-end reads encoding, and the reverse.
- **Sequencing discipline**: test with one request at a time first, then two in sequence over one connection, so the two verdicts stay separate.

### Establish a Marker

- **Unique placeholder token**: keep a unique placeholder token in each probe body so a response that carries the token can be attributed to a specific request.
- **Clean sequential baseline**: record a clean sequential baseline, namely latency and response pairing without any ambiguity, for later differentials.

## Detection Channels

- **Leftover bytes**: leftover bytes from one request appended to another request, which binds the probe to disclosure across the boundary.
- **Response-queue anomaly**: a response that answers a request that was never sent.
- **Timing gap**: a timing gap between the probe and the clean baseline, which marks a hop waiting for bytes the other hop already consumed.
- **Length difference**: a length difference between the declared framing and the true body, reflected in a delayed or truncated reply.
- **Differential marker response**: two rapid requests carrying a unique token, where an unexpected or token-bearing second response proves socket poisoning.
- **Downgrade mapping signals**: which injected framing field reaches the back-end and which value wins when both disagree.
- **Passthrough survival signals**: a spec-forbidden framing field arriving at the back-end intact.
- **Connection correspondence signals**: whether repeated header blocks ride one persistent back-end socket.

## Adversarial Capabilities

- **Testing prerequisites**: raw request control, knowledge of the hop chain, and connection-level observation, which the class consumes.
- **Hand-composed requests**: compose requests by hand so framing declarations and body lengths can be set independently.
- **Single-connection observation**: keep one client connection open across two requests and observe the pairing of replies.
- **Baseline reads**: read response timing, length, and ordering against a clean baseline.
- **Two-view reach**: reach the front-end directly, and the back-end where a direct path exists, so the two views can be compared.
- **Controlled endpoint**: hold a controlled endpoint that reflects or records request content, to receive captured material.
- **Protocol-version drive**: drive both protocol versions the target exposes, including the downgrade path.

## Trust Assumptions

- **The agreement**: every hop on the path parses the message framing identically and treats the request boundary as absolute.
- **Held conditions**: the agreement holds each hop to the same declaration for message length, holds an encoding declaration to the same interpretation at every hop, holds the connection to one client at a time, and holds bytes already consumed by one request out of the next request's view.
- **The failing clause**: sensitive position leaks when the hops disagree - the front-end scopes a check to bytes the back-end treats as a separate request, or the back-end parses the next user's bytes as a continuation.
- **Parent baseline**: the parent baseline is the framing declaration pair itself - every hop is probed for which declaration it honours.

## Key Vulnerabilities

### Length-Versus-Encoding Disagreement

- **Front-end reads length**: the front-end reads a declared length while the back-end reads the encoding terminator - the trailing bytes stay on the socket and become a new request.
- **Front-end reads encoding**: the front-end reads the encoding to completion while the back-end reads only the declared length - the remainder stays for the next request.
- **Duplicate declarations**: with conflicting values, where each hop picks a different one.

### Downgrade-Injected Declarations

- **Derived length declaration**: a front-end translating to the older protocol derives a length declaration from a regular header, which the attacker sets independently of the true body length.
- **Forbidden encoding declaration**: an encoding declaration that the newer protocol forbids passes through the front-end to the older back-end, which honours it.
- **Pseudo-header and frame-level shapes**: that survive translation and that the back-end resolves differently.

### Front-End Control Bypass

- **Smuggled prefix as proxy request**: a smuggled prefix reaches the back-end as a new request from the trusted proxy, so a check the front-end enforces never runs.
- **Bypassed check classes**: the bypassed check is usually authentication, address restriction, or the bound of a rate limit.

### Cross-User Capture

- **Partial request prefix**: a poisoned socket prepends a partial request whose declared length exceeds the sent body, so the back-end consumes bytes from the next user's request.
- **Reflective handler targeting**: aim the smuggled prefix at a handler that echoes the whole request, so the next caller's headers and body return in a readable response attributed to the smuggled request, which harvests at scale instead of one request at a time.
- **Controlled reflective endpoint**: the captured bytes land in the response of a controlled reflective endpoint, which discloses headers and body of the next request.
- **Marker arrival proof**: proof lives in the arrival of the marker token in a response to a request that never carried it.

### Response-Queue and Cache Chains

- **Misaligned responses**: on pipelined connections, a misaligned response can be delivered to the wrong user, which serves attacker content or captures the next response.
- **Cacheable-endpoint poisoning**: a smuggled prefix landing on a cacheable endpoint with an injected authority declaration poisons the stored entry for every later requester.
- **Upgrade socket hijack**: a smuggled upgrade request hijacks a subsequent user's socket, where the front-end performs the upgrade itself.

## Advanced Techniques

### Connection Reuse Amplification

- **Socket-reuse scaling**: the impact scales with back-end socket reuse - a front-end holding one back-end socket per client limits the blast radius, a shared pool widens it.
- **Repeated header blocks**: repeated header blocks over one client connection show whether the poisoned socket is reached again.

### Frame-Level Shapes

- **Header-block splitting**: across frames, where hops differ on whether reassembly precedes filtering.
- **Reparse-triggering fields**: fields that trigger a reparse of a block the front-end already validated.

### Upgrade-Based Shapes

- **Upgrade framing declaration**: an upgrade request carries a framing declaration that the front-end validates and the back-end re-reads, so smuggled bytes ride a connection the front-end believes it upgraded.
- **Tunnel-establishment request**: a smuggled tunnel-establishment request makes the back-end open a channel that the front-end attributes to its own upgrade handling.
- **Connection-reuse poisoning**: a smuggled prefix that survives on a pooled socket re-shapes the framing of every later request that lands on it.

### Translation-Hop Shapes

- **Binary-protocol translation**: where the hop re-encodes HTTP into a binary protocol of the back-end's own design, the framing declaration never reaches the back-end at all; that craft belongs to http-request-smuggling-cross-protocol-desync rather than to the declaration pairs here.

## Bypass Techniques

- **Declaration variation**: to force the declaration disagreement, vary the encoding declaration itself.
- **Non-standard value**: a non-standard value some front-ends ignore while back-ends accept.
- **Whitespace and tabs**: extra whitespace or a tab before the value, or before the field-name colon.
- **Duplicate encoding fields**: where the back-end uses the last and the front-end the first.
- **Injected line break**: a line break injected into a preceding field value, so the declaration arrives only at the back-end.
- **Case and folding variants**: case variation and obsolete folding forms accepted by one hop and normalized by the other.
- **Declaration pair matrix**: see `references/declaration-pair-matrix.md` for the pair cells and the leftover accounting.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Smuggling plus cache poisoning**: the smuggled prefix shapes a stored entry for later users.
- **Smuggling plus authentication bypass**: the front-end check is skipped for the smuggled request.
- **Smuggling plus capture**: session material harvested from the next request is replayed.
- **Smuggling plus socket hijack**: the smuggled upgrade takes over a later user's connection.
- **Smuggling plus header injection**: the injected authority declaration bends emitted links from the smuggled response.

## Testing Methodology

1. **Map the proxy chain** - Identify the front-end and the back-end and the protocol version each speaks; the step completes when each hop carries its version and its role
2. **Probe length-versus-encoding** - One request with a mismatched terminator, then the reverse shape; the step completes when each direction carries a wait-or-forward verdict
3. **Obfuscate the declaration** - Try each obfuscation variant in turn; the step completes when each variant carries an accepted or normalized verdict
4. **Confirm with a differential** - Two rapid identical requests carrying a unique marker; the step completes when the pairing is clean or one response is anomalous
5. **Attempt the control bypass** - Send a smuggled request for a guarded route; the step completes when the back-end verdict for the guarded action is recorded
6. **Attempt capture** - Poison with a partial request whose declared length exceeds the sent body, aimed at a reflective endpoint; the step completes when the marker arrives in a response or the wait times out cleanly
7. **Test the downgrade path** - Repeat the probes over the newer protocol where a downgrade exists; the step completes when each downgrade shape carries a verdict

## Variants

- http-request-smuggling-h2-desync - Downgrade desync probing through injected framing fields in the newer protocol's header block, where the front-end translates before the back-end.
- http-request-smuggling-cross-protocol-desync - Desync the hop that translates HTTP into a binary back-end protocol by embedding a request inside the frame's attribute encoding.

## False Positives

- **Latency and processing delays**: general network latency or server processing delays unrelated to framing.
- **Connection-per-request servers**: a server that closes the connection after each request, so no socket is ever shared.
- **End-to-end modern protocol**: with no downgrade, which leaves no framing disagreement.
- **Normalizing layers**: a layer that normalizes or rejects ambiguous framing before forwarding.
- **Ordinary pipelining**: ordinary pipelining or keep-alive behaviour mistaken for a desync.

## Pro Tips

- **Manual confirmation first**: confirm manually before filing; automated scanners report false positives here often.
- **Declaration obfuscation**: declaration obfuscation is the most reliable path when the plain forms are normalized.
- **Short prefixes**: keep smuggled prefixes short during detection; confirm the desync before attempting capture.
- **Downgrade-injected length**: downgrade-injected length is the highest-impact modern shape, because the front-end derives it from a header the attacker controls.
- **Capture-length sizing**: in capture attempts, declare a length larger than the partial body so a full header from the next request lands in the buffer.
- **Low-traffic testing**: test during low-traffic periods first; capture attempts touch real users and need explicit authorization.
- **Pipelined fallback**: if timing probes stay inconsistent, pipeline two requests over one connection and look for response swapping.

## Summary

Request smuggling is eliminated by consistent framing interpretation at every hop: prefer end-to-end modern protocol, never forward an encoding declaration that was not present on arrival, and treat a conflict between length and encoding declarations as a hard error.
