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
- An edge in front of an origin: cache, load balancer, or gateway
- Proxy chains, where each hop reparses and reframes the request
- API gateways forwarding to services
- Protocol translation from a modern front-end protocol to an older back-end protocol
- Tunneling and filtering layers that terminate and re-forward requests

**Protocol versions**
- Older versions carry the classic length-versus-encoding ambiguity
- Newer versions carry the downgrade-injected declarations and frame-level shapes

**Ambiguity surface**
- Duplicate length declarations with different values
- An encoding declaration present beside a length declaration
- Chunk size obfuscation through whitespace, tab, case, or invalid extensions
- Header-block and frame boundaries where reassembly order differs between hops

## Reconnaissance

### Map the Chain

- Identify each hop between the client and the application, and note which protocol version each hop speaks
- Note whether the front-end terminates the connection or reuses a back-end socket across client connections
- Record whether the front-end rejects ambiguous requests or normalizes them before forwarding

### Probe Framing Acceptance

- Send a request whose declared lengths conflict and watch which declaration each hop honours
- Compare the two directions: front-end reads length while back-end reads encoding, and the reverse
- Test with one request at a time first, then two in sequence over one connection, so the two verdicts stay separate

### Establish a Marker

- Keep a unique placeholder token in each probe body so a response that carries the token can be attributed to a specific request
- Record a clean sequential baseline, namely latency and response pairing without any ambiguity, for later differentials

## Detection Channels

- Leftover bytes from one request appended to another request, which binds the probe to disclosure across the boundary.
- A response-queue anomaly, namely a response that answers a request that was never sent.
- A timing gap between the probe and the clean baseline, which marks a hop waiting for bytes the other hop already consumed.
- A length difference between the declared framing and the true body, reflected in a delayed or truncated reply.
- A differential marker response: two rapid requests carrying a unique token, where an unexpected or token-bearing second response proves socket poisoning.
- Downgrade mapping signals: which injected framing field reaches the back-end and which value wins when both disagree.
- Passthrough survival signals: a spec-forbidden framing field arriving at the back-end intact.
- Connection correspondence signals: whether repeated header blocks ride one persistent back-end socket.

## Adversarial Capabilities

Smuggling testing presupposes raw request control, knowledge of the hop chain, and connection-level observation, and it consumes all three.
- Compose requests by hand so framing declarations and body lengths can be set independently.
- Keep one client connection open across two requests and observe the pairing of replies.
- Read response timing, length, and ordering against a clean baseline.
- Reach the front-end directly, and the back-end where a direct path exists, so the two views can be compared.
- Hold a controlled endpoint that reflects or records request content, to receive captured material.
- Drive both protocol versions the target exposes, including the downgrade path.

## Trust Assumptions

The class rests on one agreement: every hop on the path parses the message framing identically and treats the request boundary as absolute.
The agreement holds each hop to the same declaration for message length, holds an encoding declaration to the same interpretation at every hop, holds the connection to one client at a time, and holds bytes already consumed by one request out of the next request's view.
Sensitive position leaks when the hops disagree: the front-end scopes a check to bytes the back-end treats as a separate request, or the back-end parses the next user's bytes as a continuation.
The parent baseline is the framing declaration pair itself: every hop is probed for which declaration it honours.

## Key Vulnerabilities

### Length-Versus-Encoding Disagreement

- The front-end reads a declared length while the back-end reads the encoding terminator: the trailing bytes stay on the socket and become a new request
- The front-end reads the encoding to completion while the back-end reads only the declared length: the remainder stays for the next request
- Duplicate declarations with conflicting values, where each hop picks a different one

### Downgrade-Injected Declarations

- A front-end translating to the older protocol derives a length declaration from a regular header, which the attacker sets independently of the true body length
- An encoding declaration that the newer protocol forbids passes through the front-end to the older back-end, which honours it
- Pseudo-header and frame-level shapes that survive translation and that the back-end resolves differently

### Front-End Control Bypass

- A smuggled prefix reaches the back-end as a new request from the trusted proxy, so a check the front-end enforces never runs
- The bypassed check is usually authentication, address restriction, or the bound of a rate limit

### Cross-User Capture

- A poisoned socket prepends a partial request whose declared length exceeds the sent body, so the back-end consumes bytes from the next user's request
- The captured bytes land in the response of a controlled reflective endpoint, which discloses headers and body of the next request
- Proof lives in the arrival of the marker token in a response to a request that never carried it

### Response-Queue and Cache Chains

- On pipelined connections, a misaligned response can be delivered to the wrong user, which serves attacker content or captures the next response
- A smuggled prefix landing on a cacheable endpoint with an injected authority declaration poisons the stored entry for every later requester
- A smuggled upgrade request hijacks a subsequent user's socket, where the front-end performs the upgrade itself

## Advanced Techniques

### Connection Reuse Amplification

- The impact scales with back-end socket reuse: a front-end holding one back-end socket per client limits the blast radius, a shared pool widens it
- Repeated header blocks over one client connection show whether the poisoned socket is reached again

### Frame-Level Shapes

- Header-block splitting across frames, where hops differ on whether reassembly precedes filtering
- Fields that trigger a reparse of a block the front-end already validated

## Bypass Techniques

To force the declaration disagreement, vary the encoding declaration itself:
- A non-standard value some front-ends ignore while back-ends accept
- Extra whitespace or a tab before the value, or before the field-name colon
- Duplicate encoding fields, where the back-end uses the last and the front-end the first
- A line break injected into a preceding field value, so the declaration arrives only at the back-end
- Case variation and obsolete folding forms accepted by one hop and normalized by the other

## Chaining Attacks

- Smuggling plus cache poisoning: the smuggled prefix shapes a stored entry for later users
- Smuggling plus authentication bypass: the front-end check is skipped for the smuggled request
- Smuggling plus capture: session material harvested from the next request is replayed
- Smuggling plus socket hijack: the smuggled upgrade takes over a later user's connection
- Smuggling plus header injection: the injected authority declaration bends emitted links from the smuggled response

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

## False Positives

- General network latency or server processing delays unrelated to framing
- A server that closes the connection after each request, so no socket is ever shared
- End-to-end modern protocol with no downgrade, which leaves no framing disagreement
- A layer that normalizes or rejects ambiguous framing before forwarding
- Ordinary pipelining or keep-alive behaviour mistaken for a desync

## Pro Tips

1. Confirm manually before filing; automated scanners report false positives here often
2. Declaration obfuscation is the most reliable path when the plain forms are normalized
3. Keep smuggled prefixes short during detection; confirm the desync before attempting capture
4. Downgrade-injected length is the highest-impact modern shape, because the front-end derives it from a header the attacker controls
5. In capture attempts, declare a length larger than the partial body so a full header from the next request lands in the buffer
6. Test during low-traffic periods first; capture attempts touch real users and need explicit authorization
7. If timing probes stay inconsistent, pipeline two requests over one connection and look for response swapping

## Summary

Request smuggling is eliminated by consistent framing interpretation at every hop: prefer end-to-end modern protocol, never forward an encoding declaration that was not present on arrival, and treat a conflict between length and encoding declarations as a hard error.
