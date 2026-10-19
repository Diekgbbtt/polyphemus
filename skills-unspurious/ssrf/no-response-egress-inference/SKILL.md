---
name: no-response-egress-inference
description: Infer blind SSRF reachability from side-channel differences when responses carry no readable body, map ports through timeout search, and correlate one callback token per probe.
metadata:
  version: 1.0.0
---

# No-Response Egress Inference

Server-side fetch sinks sometimes answer with no readable body, yet each probe still leaks reachability through side channels.
This variant infers internal reachability by correlating callbacks plus timing plus size plus error-class differences into one verdict per probe.
The inference goal is internal service discovery plus port mapping that later enables a direct read or a translated command.

## Attack Surface

Applicability centers on a server-side fetch sink whose response carries no readable reflection of the fetched target.
The sink accepts attacker-influenced destination input through a direct field or an indirect source such as a preview job or an import job.
The server emits at least one observable side channel per fetch, such as arrival timing or response size or error class or presence-header value.
The internal address space stays reachable from the fetcher even while the response body stays masked or uniform.
Translated-protocol craft plus gated credential sequencing ride inside this variant only as secondary confirmation once the inference oracle is established.

## Detection Channels

Inference listens to side channels rather than bodies, so only the entries below are live here.
- Callback arrival carrying a per-probe token binds one inbound hit to one outbound probe.
- Arrival-timing gap separates a reachable internal target from an unreachable one.
- Response-size difference separates a reachable fetch from a refused one.
- Error-class difference separates timeout versus reset versus transport failure.
- Presence-header difference separates otherwise uniform responses.
- Distinct status on a link-local address, namely a gate response where every other candidate returns a uniform body, which proves reach to a non-internet-routable address.
- Timeout-derived port map records one reachability verdict per probed port.

## Adversarial Capabilities

Inference presupposes destination supply plus callback operation plus repeated measurement, and it consumes all three.
- Supply destination input that steers the server-side fetch toward one chosen candidate at a time.
- Operate callback infrastructure that mints one fresh token per probe and records each inbound hit.
- Induce the fetch through a direct field or through an indirect source such as a preview job.
- Measure per-fetch timing plus response size plus error class plus presence headers across repeated probes.
- Run timeout search with tight connect and read budgets so differences stay clean.

## Trust Assumptions

The fetcher trusts a user-supplied destination to select only locations the server is permitted to reach.
The agreement holds the destination stable from allowlist check through fetch, keeps the response observable to the caller, keeps the request in plain-fetch shape with no translated protocol grammar, and keeps the request in plain-fetch shape with no gate-passing header or method pair.
Sensitive network position leaks only when the server exposes reachability through such a fetch.
This variant breaks the observability clause because the response carries no readable body, so reachability is decided only through callback correlation plus timing plus size plus error-class differencing.

## Key Vulnerabilities

### Per-Token Callback Correlation

Mint one fresh token per probe and embed it in the destination so each inbound hit identifies exactly one outbound request.
Record the listener outcome per token rather than per batch, because batch totals cannot attribute a hit to its probe.
The parent oracle step covers only quiet callback watching and cannot describe per-token attribution, so this variant owns the correlation procedure.

### Size Plus Timing Plus Error-Class Differencing

Derive reachability from timing gaps plus response-size deltas plus transport error classes plus presence-header values.
Repeat each probe until the difference stabilises, because a single sample cannot separate a reachable host from network jitter.
Treat a consistent class change as a positive and treat uniform randomness as inconclusive rather than negative.

### Timeout Binary-Search Port Mapping

Build the port map by sweeping candidate ports under short connect and read budgets and recording one verdict per port.
Anchor the sweep with a known-open and a known-closed control point, so each candidate's verdict reads against a calibrated pair rather than an absolute timing.
Narrow each open-versus-filtered boundary by halving the timeout window around the differing samples.
Blind translated craft plus blind gated sequencing stay secondary here, reusing the same inference oracle without adding their own steps.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding or parsing difference changes the inference step itself.
- Address encoding families such as decimal plus hex plus octal plus mapped forms reach the fetcher past a naive textual allowlist.
- Parser differentials, redirect chains, and short-lived resolution carry an internal destination to the fetch side, and the proxy-techniques family owns those mechanics; record only the inference verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Inference chains forward into reads because a map without a follow-up read is only discovery.
- Hand the resulting port map to a direct internal read once a reachable candidate shows a stable positive.
- Hand a reachable raw-protocol handler to scheme-translated command execution for grammar crafting.
- Hand a reachable gated store to header-gated credential sequencing for the token-then-read flow.
- Treat a redirector that passes the allowlist as the entry into any of these follow-ups.

## Testing Methodology

Inference runs the oracle first and everything else follows, because no later step is meaningful without a calibrated difference.
1. **Inventory sinks** - list every attacker-influenced destination sink with its carrier plus its masking behavior, and the step completes when no unlisted sink remains.
2. **Calibrate the oracle** - mint one token per probe and record baseline timing plus size plus error class on a known-unreachable candidate, and the step completes when every side channel shows a stable baseline.
3. **Correlate callbacks** - send one probe per token and attribute each inbound hit to its probe, and the step completes when every hit maps to exactly one probe and every probe shows a recorded outcome.
4. **Difference reachable candidates** - repeat each candidate until timing plus size plus error class stabilise, and the step completes when every candidate carries a positive or negative or inconclusive verdict with its samples.
5. **Map ports by timeout search** - sweep candidate ports under tight budgets and halve each boundary window, and the step completes when every probed port carries one verdict.
6. **Confirm secondary craft** - replay blind translated or blind gated payloads through the same oracle, and the step completes when each replay shows a verdict from the established difference rather than a new procedure.

## False Positives

Stop when the evidence shows no server fetch, because inference without egress is only noise.
- Client-side fetch only, where no request ever leaves the server.
- Strict allowlist with resolution pinning plus no redirect following, confirmed by uniform negatives across all candidates.
- Canned simulator responses that return fixed bodies without real egress.
- Uniform differences across every candidate and every side channel, which signal measurement noise rather than reachability.
- Callback hits whose source matches the tester machine rather than the server, which indicate a client-side fetch made the request.

## Pro Tips

Inference rewards patience plus tiny probes plus tight budgets.
1. Prefer the quiet callback oracle first, then promote only stable positives to differencing.
2. Favor tiny destinations plus tight timeouts so the port map stays fast and quiet.
3. Repeat each probe until the class stabilises, and log every sample behind its token.
4. Diff presence headers alongside size because masked bodies often still vary there.
5. Stop promoting inconclusive candidates and record them as inconclusive rather than negative.

## Summary

A fetcher that answers with no readable body still answers through timing plus size plus error class plus callbacks.
Inference binds one token per probe, calibrates each side channel, and maps reachability before any direct read or translated command follows.
