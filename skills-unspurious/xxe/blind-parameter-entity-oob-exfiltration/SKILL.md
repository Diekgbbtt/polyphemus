---
name: blind-parameter-entity-oob-exfiltration
description: Blind XXE exfiltration through parameter-entity OOB chains. Use when responses carry no entity content, when parser errors leak interpolated fragments, when a callback host can receive exfil requests, when external DTD fetch stays enabled while inline resolution is blocked.
metadata:
  version: 1.0.0
---

# Blind Parameter-Entity OOB Exfiltration

Blind parameter-entity exfiltration treats a silent XML parser as an oracle that still fetches attacker-hosted grammars.
Blind chains smuggle file and internal-network data out through subset delivery plus entity redefinition even when responses carry no entity content.

## Attack Surface

Blind chains apply wherever a consumer accepts a declaration block carrying an external subset reference.
Blind chains apply wherever the parser resolves parameter entities and fetches external grammar subsets over the network.
Blind chains apply wherever attacker XML reaches service endpoints, soap actions, authentication assertion consumers, upload converters, report pipelines, or background jobs.
Blind chains need no reflected output channel because the callback host itself is the channel.

## Reconnaissance

Inventory every XML consumer with its carrier and record which consumers accept a declaration block.
Probe each consumer for subset fetch by aiming its external subset reference at a callback-owned address and watching for the hit.
Record per-consumer capability answers for declaration acceptance plus parameter-entity resolution plus network egress before escalating.

## Detection Channels

### OAST Callback

Watch the callback host for grammar resolution requests and correlate each hit with the probe that caused it.
Encode exfiltrated bytes into the exfil request path so small secrets arrive inside the callback itself.

### Error Coercion

Coerce parser errors that interpolate redefined entity values and harvest path fragments from the message.
Treat error fragments as a secondary channel that sharpens callback evidence rather than replacing it.

### Timing Confirmation

Treat consistent callback latency against otherwise silent consumers as supporting confirmation only.
Confirm the verdict on a logged callback hit or a reproduced error fragment, never on latency alone.

## Adversarial Capabilities

Submit attacker-shaped XML to each inventoried consumer.
Operate a callback host that serves external grammar subsets and logs every resolution request.
Sequence multi-request chains across subset delivery plus file read plus entity redefinition plus exfil callback.
Correlate callback hits with probes through unique per-probe tokens.

## Trust Assumptions

The XML consumer executes attacker-supplied markup under a five-part agreement.
Declarations are rejected or neutered on every code path.
General-entity resolution stays disabled wherever markup is parsed.
Transclusion processors stay off unless the feature requires them.
Network access stays closed for parsers and transformers.
Parsed content never carries file or internal-network data back to the requester.
The agreement fails at the external parameter-entity fetch clause.
The parser retrieves the attacker-hosted external subset and chains parameter-entity redefinition into an exfil request.

## Key Vulnerabilities

Parameter-entity chains split exfiltration into two stages that inline resolution never performs.
The first stage delivers an external subset that reads a local file or internal URL into a parameter entity.
The second stage redefines a second entity around the captured value and resolves it into an exfil request.
General-entity sanitising in the document tree stops nothing here because the chain lives entirely in the grammar subset.
Shape the chain abstractly with placeholders before runtime values fill them.

```
[DECLARATION-BLOCK external-subset=[CALLBACK-BASE]/[SUBSET-PATH] parameter-ref=[A]]
```

```
[SUBSET-BODY read=[LOCAL-FILE-URI or INTERNAL-URL] into=[B]]
[SUBSET-BODY redefine=[C] wrapping=[B] exfil-target=[CALLBACK-BASE]/[B-VALUE]]
[SUBSET-BODY resolve=[C]]
```

## Bypass Techniques

Vary declaration encoding and newline shapes so naive declaration filters miss the external subset reference.
Vary the subset declaration between peer keyword forms and internal-versus-external placement to reach the fetch path.
Pivot between file-URI reads and internal-URL reads inside the redefinition so one blocked family still yields the other.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Hand exfiltrated internal URLs to the ssrf skill when the blind chain reaches internal control planes.
Hand disclosed file paths to path traversal follow-ups when the chain reads configuration that names further files.

## Testing Methodology

1. **Inventory consumers.**
List every XML parsing sink with its carrier and its declaration acceptance answer.
Completion holds when every sink carries a carrier label and no consumer lacks an acceptance answer.
2. **Probe subset fetch.**
Aim each accepting consumer at a callback-owned subset address with a unique per-probe token.
Completion holds when every accepting consumer shows either a logged hit or recorded silence.
3. **Fix the oracle.**
Correlate each callback hit with its probe token and record error-shape plus latency baselines per consumer.
Completion holds when every consumer has a fixed channel of callback plus error plus timing baseline.
4. **Run the two-stage chain.**
Serve the external subset from the callback host, capture the file or internal-URL value through redefinition, and exfiltrate it inside the exfil request path.
Completion holds when a controlled file path or internal URL produces a reproducible callback hit or a reproduced error fragment.
5. **Validate parity.**
Repeat the chain across service endpoints plus uploads plus background jobs and record every divergence in parser options.
Completion holds when every channel shows the same options or a recorded divergence.

## False Positives

Declaration accepted without subset fetch produces callback silence plus no error fragment.
Sandbox literal emission returns entity markup verbatim with no resolution request logged.
Mock success simulates parsing without file or network access.
Client-side-only processing parses markup where no server parser runs.

## Pro Tips

Prefer the callback channel first because blind confirmation stays quietest in production-like paths.
Mint a fresh per-probe token for every request so overlapping chains never share attribution.
Exfiltrate small secrets inside the request path and escalate to larger reads only after the channel proves reliable.
Probe background processors separately because blind chains often survive there after endpoints harden.
Pair every callback verdict with its correlated token before claiming the read.

## Summary

Blind parameter-entity exfiltration ends when parsers refuse external subsets and close network fetch on every code path.
Harden the grammar layer first because silent responses never prove a silent parser.
