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

- **Applicability**: a server-side fetcher follows redirect hops issued by a redirector.
- **Allowlisted redirector**: an allowlisted redirector accepts a user-controllable destination.
- **Internal reachability**: the fetcher can reach internal targets that the browser consumer never sees.
- **Out-of-scope variants**: a browser victim consumer or a registered OAuth relay sink belongs to the sibling variants.

## Reconnaissance

### Redirector Candidates

- **Redirector inventory**: list redirectors on allowlisted domains whose responses a fetcher will follow.
- **Fetcher-participation behaviors**: list previewer, unfurler, and link-checking behaviors that confirm fetcher participation.
- **Completion condition**: complete when every fetcher-followed redirector is listed with its carrier.

### Internal Target Selection

- **Internal-destination shapes**: assemble internal-destination shapes including loopback forms, numeric address forms, and metadata-path shapes.
- **Redirector-target pairing**: pair each allowlisted redirector with the internal target its fetcher can plausibly reach.
- **Completion condition**: complete when each redirector owns at least one reachable internal-target hypothesis.

### Egress Observables

- **Timing baselines**: establish timing baselines that distinguish internal resolution from external failure.
- **Header and size signals**: identify header and size signals that confirm the fetcher retrieved the internal target.
- **Completion condition**: complete when the baseline set can separate internal egress from refused or external outcomes.

## Detection Channels

- **Fetcher egress**: fetcher egress reaches the internal target with retrievable response evidence.
- **Later-hop location**: the later-hop location header points to the internal target while the first hop stays allowlisted.
- **Chain trace**: the chain trace shows the allowlisted redirector forwarding into the internal destination.
- **Retrieval signals**: timing and header signals confirm server-side retrieval of the internal target.

## Adversarial Capabilities

- **Destination input**: supply destination input through the redirector carrier the fetcher follows.
- **Egress observation**: observe fetcher egress signals including timing, headers, and response size.
- **Evidence correlation**: correlate submitted values with egress evidence without inducing any victim navigation.

## Trust Assumptions

- **The agreement**: a destination supplied in the request is constrained to an intended set after canonical parsing, the enforcing parser agrees with the navigating consumer on scheme, host, and path, every hop of a redirect chain re-verifies the destination, and the destination delivers the victim only to an intended party.
- **The failing clause**: hop re-verification fails because the first-hop allowlist check constrains only the redirector while the server-side fetcher follows later hops to an internal target without re-verification.

## Key Vulnerabilities

### First-Hop-Only Validation

- **Allowlist-check failure**: allowlist checks fail because they validate the redirector while the fetcher resolves the later hops freely.
- **Chain-trust failure**: chain trust fails because approval granted to the first hop is inherited by every subsequent hop.
- **Fetcher-behavior failure**: fetcher behavior fails because preview and unfurl flows follow redirects the browser-oriented check never modeled.
- **Per-hop re-verification**: re-verify every hop the fetcher follows against the same exact-origin rule.
- **Egress allowlist**: constrain fetcher destinations to an explicit egress allowlist that names reachable internal ranges as denied.
- **Per-hop approval**: refuse redirect following for fetchers unless each hop carries its own approval.

## Advanced Techniques

- **Target selection**: select internal targets by pairing the redirector domain with the fetcher network position.
- **Egress confirmation**: confirm egress through timing differencing, header presence, and response-size comparison.
- **External-exfiltration endings**: carry external-exfiltration endings as a secondary proof inside this variant because the chain procedure is identical.

## Bypass Techniques

- **First-hop values**: shape first-hop values that satisfy the allowlist while encoding the internal pivot in a later hop.
- **Separator and encoding values**: shape separator and encoding values that normalize differently between the redirector check and the fetcher resolution.
- **Numeric address forms**: shape numeric address forms that match textual rules while resolving to internal targets.
- **Nested-redirector values**: shape nested-redirector values that hide the internal destination one forwarding layer deep.

- **Proxy-techniques handoff**: the hop chain and the destination parse comparison are the proxy-techniques family's steps; name it there and keep the class-specific pivot verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Internal-exploitation handoff**: pivot the egress into internal exploitation only by handing off to the `ssrf` class at the internal-access step.
- **Multi-hop escape**: escape through multi-hop chains where the trusted redirector fronts the internal destination.
- **Token-bearing relay**: relay the pivot through token-bearing fetcher flows only where the fetcher attaches credentials to the followed hop.

## Testing Methodology

1. **Inventory fetcher-followed redirectors** - List allowlisted redirectors with each carrier plus the fetcher behavior that follows them, and finish when no redirector lacks its fetcher hypothesis.
2. **Build variant sets** - Prepare per-carrier values spanning parser families plus numeric address forms plus nested-redirector shapes, and finish when every carrier owns a complete pivot set.
3. **Compare validator against fetcher outcome** - Submit each value and record the first-hop verdict beside the fetcher resolution result, and finish when both outcomes are recorded for every value.
4. **Chain allowlisted redirector to internal target (bent step)** - Walk redirector through followed hops toward the internal target hop by hop, and finish when every hop is re-verified or one internal-reaching hop is recorded.
5. **Prove impact** - Confirm server-side egress to the internal target through timing plus header plus response evidence, and finish when the evidence shows fetcher retrieval of the internal destination.

## False Positives

- **Redirect-refusing fetchers**: fetchers that refuse to follow redirect hops stop this variant.
- **Per-hop re-verification**: per-hop re-verification that binds every followed hop to the exact-origin rule stops this variant.
- **Constrained redirectors**: redirectors constrained to relative same-origin paths with robust normalization stop this variant.

## Pro Tips

- **Redirect-following fetchers**: target fetchers known to follow redirects first because they convert redirectors into egress.
- **Combined egress confirmation**: confirm egress with timing, headers, and size together because one signal alone misleads.
- **Per-hop verification**: verify every followed hop because first-hop approval never constrains later hops.
- **Numeric pivot shapes**: treat numeric address forms as first-class pivot shapes because textual rules miss them.
- **Pivot set**: keep the pivot set per redirector so internal-target coverage stays checkable.

## Summary

Fetcher pivot succeeds exactly where first-hop approval is inherited by hops nobody re-verifies.
Re-verify every hop the fetcher follows, deny internal egress explicitly, and prove the outcome with server-side retrieval evidence.
