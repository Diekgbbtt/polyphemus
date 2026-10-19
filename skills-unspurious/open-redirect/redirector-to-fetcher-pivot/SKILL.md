---
name: redirector-to-fetcher-pivot
description: Fetcher-pivot redirect testing that chains an allowlisted redirector to internal targets, confirms server-side egress, and escalates open redirect into internal access
metadata:
  version: 1.0.0
---

# Redirector to Fetcher Pivot

Fetcher-pivot redirect testing chains an allowlisted redirector into a server-side fetcher that follows later hops to an internal target.
Treat first-hop approval as worthless until every hop the fetcher follows is re-verified against the same exact origin rule.

## Attack Surface

Applies when a server-side fetcher follows redirect hops issued by a redirector.
Applies when an allowlisted redirector accepts a user-controllable destination.
Applies when the fetcher can reach internal targets that the browser consumer never sees.
Stays out of scope when the consumer is a browser victim or the sink is a registered OAuth relay (those belong to the sibling variants).

## Reconnaissance

### Redirector Candidates

List redirectors on allowlisted domains whose responses a fetcher will follow.
List previewer and unfurler and link-checking behaviors that confirm fetcher participation.
Complete when every fetcher-followed redirector is listed with its carrier.

### Internal Target Selection

Assemble internal-destination shapes including loopback forms plus numeric address forms plus metadata-path shapes.
Pair each allowlisted redirector with the internal target its fetcher can plausibly reach.
Complete when each redirector owns at least one reachable internal-target hypothesis.

### Egress Observables

Establish timing baselines that distinguish internal resolution from external failure.
Identify header and size signals that confirm the fetcher retrieved the internal target.
Complete when the baseline set can separate internal egress from refused or external outcomes.

## Detection Channels

Fetcher egress reaches the internal target with retrievable response evidence.
Later-hop Location header points to the internal target while the first hop stays allowlisted.
Chain trace shows the allowlisted redirector forwarding into the internal destination.
Timing and header signals confirm server-side retrieval of the internal target.

## Adversarial Capabilities

Supply destination input through the redirector carrier the fetcher follows.
Observe fetcher egress signals including timing plus headers plus response size.
Correlate submitted values with egress evidence without inducing any victim navigation.

## Trust Assumptions

The redirect feature assumes a destination supplied in the request is constrained to an intended set after canonical parsing, the enforcing parser agrees with the navigating consumer on scheme plus host plus path, every hop of a redirect chain re-verifies the destination, and the destination delivers the victim only to an intended party.
The clause that fails here is hop re-verification: the first-hop allowlist check constrains only the redirector while the server-side fetcher follows later hops to an internal target without re-verification.

## Key Vulnerabilities

### First-Hop-Only Validation

Allowlist checks fail because they validate the redirector while the fetcher resolves the later hops freely.
Chain trust fails because approval granted to the first hop is inherited by every subsequent hop.
Fetcher behavior fails because preview and unfurl flows follow redirects the browser-oriented check never modeled.
Re-verify every hop the fetcher follows against the same exact-origin rule.
Constrain fetcher destinations to an explicit egress allowlist that names reachable internal ranges as denied.
Refuse redirect following for fetchers unless each hop carries its own approval.

## Advanced Techniques

Select internal targets by pairing the redirector domain with the fetcher network position.
Confirm egress through timing differencing plus header presence plus response-size comparison.
Carry external-exfiltration endings as a secondary proof inside this variant because the chain procedure is identical.

## Bypass Techniques

Shape first-hop values that satisfy the allowlist while encoding the internal pivot in a later hop.
Shape separator and encoding values that normalize differently between the redirector check and the fetcher resolution.
Shape numeric address forms that match textual rules while resolving to internal targets.
Shape nested-redirector values that hide the internal destination one forwarding layer deep.

The hop chain and the destination parse comparison are the proxy-techniques family's steps; name it there and keep the class-specific pivot verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Pivot the egress into internal exploitation only by handing off to the `ssrf` class at the internal-access step.
Escape through multi-hop chains where the trusted redirector fronts the internal destination.
Relay the pivot through token-bearing fetcher flows only where the fetcher attaches credentials to the followed hop.

## Testing Methodology

1. **Inventory fetcher-followed redirectors** - List allowlisted redirectors with each carrier plus the fetcher behavior that follows them, and finish when no redirector lacks its fetcher hypothesis.
2. **Build variant sets** - Prepare per-carrier values spanning parser families plus numeric address forms plus nested-redirector shapes, and finish when every carrier owns a complete pivot set.
3. **Compare validator against fetcher outcome** - Submit each value and record the first-hop verdict beside the fetcher resolution result, and finish when both outcomes are recorded for every value.
4. **Chain allowlisted redirector to internal target (bent step)** - Walk redirector through followed hops toward the internal target hop by hop, and finish when every hop is re-verified or one internal-reaching hop is recorded.
5. **Prove impact** - Confirm server-side egress to the internal target through timing plus header plus response evidence, and finish when the evidence shows fetcher retrieval of the internal destination.

## False Positives

Fetchers that refuse to follow redirect hops stop this variant.
Per-hop re-verification that binds every followed hop to the exact-origin rule stops this variant.
Redirectors constrained to relative same-origin paths with robust normalization stop this variant.

## Pro Tips

1. Target fetchers known to follow redirects first because they convert redirectors into egress.
2. Confirm egress with timing plus headers plus size together because one signal alone misleads.
3. Verify every followed hop because first-hop approval never constrains later hops.
4. Treat numeric address forms as first-class pivot shapes because textual rules miss them.
5. Keep the pivot set per redirector so internal-target coverage stays checkable.

## Summary

Fetcher pivot succeeds exactly where first-hop approval is inherited by hops nobody re-verifies.
Re-verify every hop the fetcher follows, deny internal egress explicitly, and prove the outcome with server-side retrieval evidence.
