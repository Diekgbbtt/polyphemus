---
name: header-request-smuggling
description: Smuggling requests through framing disagreements between chained parsers, pairing length against encoding declarations with downgrade and split-frame shapes, and proving leftover bytes cross request boundaries.
metadata:
  version: 1.0.0
---

# Request Smuggling across Framing Boundaries

Chained parsers must agree on where one request ends and the next begins, and any disagreement is a smuggling primitive.
This variant proves that a framing pair with downgrade plus case plus frame-split shapes leaks leftover bytes across requests.
The smuggling goal is a prepended request executed under another party's connection, which later enables credential capture plus cache poisoning plus auth bypass through the smuggled bytes.

## Attack Surface

Applicability centers on a proxy-fronted deployment where the frontend and the backend can disagree on message framing.
The pair shapes span conflicting length-versus-encoding declarations plus dual-length declarations plus malformed chunked boundaries, replayed over version boundaries where downgrade handling differs.
Stored line-break responses belong to header-crlf-splitting, and delimiter-free same-response replacement belongs to header-response-value-confusion, so neither rides here.

## Reconnaissance

Inventory narrows to the parser boundary plus its framing behavior.
Identify the frontend-to-backend pair and record how each side reads length declarations versus encoding declarations versus chunked boundaries.
Replay framing probes across protocol versions and diff status plus headers plus body length to map downgrade plus casing plus reassembly differences.
Record the connection-reuse behavior, since smuggled bytes need a shared connection to reach another party's request.

## Detection Channels

Smuggling listens for cross-request leakage, so only the entries below are live here.
- Victim request data appended to another request binds the probe to leftover-bytes disclosure across the boundary.
- Response-queue anomaly, namely a response that answers a request never sent, proves the smuggled bytes executed as a request.
- Timing plus length diff between the paired replay and a clean sequential baseline isolates framing disagreement from ordinary latency.
- Cross-version behavior diff records which protocol path honors the smuggled framing and which path rejects it.
- Anomalous response to a normal request, namely a forbidden or wrong-path result for a request that carried no ambiguity of its own, because it was appended to the smuggled prefix.

## Adversarial Capabilities

Smuggling presupposes framing-pair supply plus shared-connection observation plus version replay, and it consumes all three.
- Send crafted framing pairs with controlled length-versus-encoding conflicts plus split-frame layouts.
- Hold sequential requests on the shared connection and observe whether foreign bytes surface in another party's request.
- Replay each pair across protocol versions to find the downgrade path that disagrees.
- Pace probes so ordinary pipelining plus keep-alive behavior cannot explain a queue anomaly.

## Trust Assumptions

The stack treats an attacker-influenced value that reaches a response header field as inert data at the moment the feature executes.
The agreement holds the value free of framing meaning from capture through serialization, holds one declared interpreter for the value across the proxy-to-backend-to-client path, keeps the request in its declared method plus path plus protocol shape, keeps each response observable only to its caller, and keeps link targets plus cached bodies plus session state plus token-bearing destinations out of attacker reach.
This variant breaks the framing-agreement clause because a framing pair splits the frontend read from the backend read and leaks leftover bytes across requests.

## Key Vulnerabilities

### Length-Versus-Encoding Disagreement Pairs

Send conflicting length and encoding declarations plus dual-length declarations plus malformed chunked boundaries, and confirm the two sides commit to different message ends.
The parent pair step names only conflicting declarations, so this variant owns the boundary-pair plus cross-version replay proof that turns a declaration conflict into executed smuggled bytes.
Treat single-server topologies as the boundary, because one parser cannot disagree with itself.

### Downgrade Plus Case Plus Frame-Split Shapes

Sweep downgrade mishandling across the version boundary, lowercase declarations past case-sensitive filters, and split-frame layouts where intermediaries differ on reassembly before filtering.
Carry these shapes as the pair envelope rather than standalone findings, since each shape matters only where it bends the boundary read.
Name stored-response splitting at this step rather than restating it, since header-crlf-splitting owns line-break storage without cross-request leakage.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no obfuscation changes the leftover-bytes oracle itself.
- Obfuscate the encoding declaration with whitespace before the colon plus casing plus folded-continuation edges plus an invalid value spelling, past a strict-match filter that recognizes only the canonical form.
- Split the framing payload across continuation frames so reassembly order decides which side filters first.
- Smuggle duplicate length declarations where the enforcing side reads one member while the backend reads the other.
- Layer encoded-length forms past a filter that decodes fewer times than the framing parser.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Smuggling chains forward through the prepended request because leaked bytes without a consumer are only desynchronization.
- Hand a smuggled authenticated-looking prefix to credential capture once victim bytes append to it.
- Hand a smuggled cacheable request to cache poisoning where the cache oracle fits better than the smuggling oracle.
- Hand a smuggled privileged request to auth bypass once it executes under the victim connection context.

## Testing Methodology

Smuggling runs boundary mapping before pairing and leakage proof last, because declaration conflicts without a disagreeing pair are only syntax.
1. **Map the boundary** - record the frontend-to-backend pair plus each side's framing reads plus connection-reuse behavior, and the step completes when every side carries a documented read rule.
2. **Diff across versions** - replay baseline payloads over each protocol version, and the step completes when every version carries a recorded framing behavior with its diffs.
3. **Send framing pairs** - replay length-versus-encoding plus dual-length plus malformed-chunked pairs one at a time, and the step completes when every pair carries a disagree-or-agree verdict with its samples.
4. **Prove leftover leakage** - observe sequential requests on the shared connection for foreign bytes plus queue anomalies, and the step completes when leakage is confirmed or ruled out with its evidence.
5. **Confirm shape attribution** - repeat the confirmed pair with downgrade plus case plus frame-split envelopes, and the step completes when each envelope carries a stored shape verdict.

## False Positives

Stop when the evidence shows agreement or ordinary connection behavior, because syntax without leakage is only noise.
- Request indicators that resolve to normal pipelining or keep-alive behavior, confirmed by clean-sequential baselines.
- Frontend and backend agreeing on every pair shape, confirmed by uniform reads across the sweep.
- Single-parser topology with no boundary pair, confirmed by deployment mapping rather than probing.
- Queue anomalies that reproduce without any framing pair, confirmed by clean-replay repetition.

## Pro Tips

Smuggling rewards boundary mapping over pair volume, because the disagreeing pair is the whole finding.
1. Prefer identifying the parser pair first, since pair shapes without a boundary target waste probes.
2. Favor one pair per connection sequence so each anomaly attributes to exactly one shape.
3. Confirm leftover leakage through foreign bytes in another request before claiming execution.
4. Replay across versions early, because downgrade paths hold the highest-yield disagreements.
5. Hand any stored-response result to the splitting sibling where no cross-request leakage backs it.

## Summary

Two parsers that disagree on message framing hand request execution to whoever crafts the boundary pair.
Smuggling maps the parser pair, replays framing pairs with downgrade plus case plus frame-split envelopes, and proves leftover bytes cross request boundaries before any capture or poisoning chain begins.
