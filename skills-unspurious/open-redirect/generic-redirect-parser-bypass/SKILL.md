---
name: generic-redirect-parser-bypass
description: Generic parser-differential redirect testing that evades allowlists via canonicalization gaps, proves browser navigation to external destinations, and escapes multi-hop chains
metadata:
  version: 1.0.0
---

# Generic Redirect Parser Bypass

Generic parser-differential redirect testing steers a user-controllable destination to an external endpoint for phishing navigation and allowlist bypass.
Treat the destination as hostile until one canonical parser has constrained it to an exact intended origin on every hop.

## Attack Surface

Applies when a server 3xx sink or a client navigation sink consumes a user-controllable destination.
Applies when a browser victim is the navigating consumer that resolves the final destination.
Applies when an allowlist or same-origin constraint claims to confine the destination.
Stays out of scope when the sink is a registered OAuth relay or a server fetcher follows the hops (those belong to the sibling variants).

## Reconnaissance

### Injection Points

List every destination carrier on sign-in and sign-out plus reset plus payment plus message-link surfaces.
List client sinks including script-assigned locations plus meta refresh plus router navigation plus new-window calls.
List forwarding evidence that can reshape absolute destination construction.
Complete when every redirector candidate is listed with its carrier and its sink kind.

### Parser Differentials

Assemble userinfo-shaped values where the enforcing parser and the navigating consumer disagree on the host.
Assemble separator-confusion values using mixed slashes and repeated leading slashes.
Assemble whitespace and control-character values that one side strips and the other keeps.
Assemble fragment and query smuggling values that hide the effective destination from the validator.
Assemble confusable-character and dotted-name values that resolve differently after name canonicalization.
Assemble encoded and double-encoded values plus case-varied schemes plus numeric address forms.
Complete when each carrier owns a variant set covering every family above.

## Detection Channels

Location header points to an external destination on the enforcing side.
Browser address bar reaches the external destination on the navigating side.
Validator verdict and real navigation outcome disagree for the same submitted value.

## Adversarial Capabilities

Supply destination input through the carrier the surface exposes.
Induce victim navigation so the navigating consumer resolves the submitted value.
Observe both the enforcing-side verdict and the navigating-side outcome for comparison.
Operate no callback beyond confirming the victim lands externally.

## Trust Assumptions

The redirect feature assumes a destination supplied in the request is constrained to an intended set after canonical parsing, the enforcing parser agrees with the navigating consumer on scheme plus host plus path, every hop of a redirect chain re-verifies the destination, and the destination delivers the victim only to an intended party.
The clause that fails here is parser agreement: the enforcing parser and the navigating consumer canonicalize the same value differently, so a destination confined by one resolves externally in the other.

## Key Vulnerabilities

### Allowlist Evasion

Contain-checks fail because a trusted name embedded as a substring still matches while the navigation goes elsewhere.
Wildcard scoping fails because an attacker-controlled suffix nests under the trusted scope while resolving externally.
Scheme policy fails when executable or non-navigation scheme values are accepted as destinations.
Case and name-form drift fails when the validator compares one textual form and the consumer resolves another.
Constrain destinations with one canonical parser that normalizes encoding plus case plus name form before any check.
Compare the exact scheme plus the post-canonicalization host plus an explicit allowlist with optional exact path prefixes.
Require absolute secure destinations and refuse relative-escape shapes and unknown schemes.

### Client-Side Vectors

Script-assigned destinations fail when user input flows into the navigation call without the same canonical check.
Meta refresh destinations fail when the refresh target carries an unvalidated value.
Router navigation fails when the route argument is read from attacker-influenced state.
Apply the same single-parser exact-origin check on the client before navigation.

## Advanced Techniques

Deepen multi-hop chains across distinct subdomains and paths until a hop skips re-verification.
Rewrite the comparator for router-guarded clients by comparing the client-side guard verdict against the DOM navigation outcome.
Prove navigation only for executable-scheme values and leave script execution out of scope.

## Bypass Techniques

Shape userinfo values that split the parsed host between validator and consumer.
Shape separator and slash-confusion values that change the authority boundary after normalization.
Shape whitespace and control values that survive on one side and vanish on the other.
Shape fragment and query values that mask the effective destination from prefix checks.
Shape confusable-character and trailing-dot values that equalize differently per parser.
Shape double-encoded and case-varied values that decode one extra time in the consumer.

The destination parse comparison is the proxy-techniques family's step; name it there and keep the class-specific navigation verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Escape through multi-hop chains where a trusted domain fronts a redirector that lands externally.
Relay issued codes through a trusted redirector only by handing off to the OAuth relay sibling at the registration step.
Pivot an allowlisted redirector into server-side egress only by handing off to the fetcher-pivot sibling at the fetcher step.

## Testing Methodology

1. **Inventory surfaces** - List sign-in and sign-out plus reset plus payment plus message-link redirectors with each carrier and sink kind, and finish when no redirector candidate lacks a carrier.
2. **Build test matrix** - Prepare per-carrier variant sets spanning scheme plus host plus path with encoding and confusable forms, and finish when every carrier owns a complete family set.
3. **Compare enforcing against navigating outcome (bent step)** - Submit each value and record the validator verdict beside the real browser navigation result, and finish when both outcomes are recorded for every value and every disagreement is flagged as a bypass.
4. **Test multi-hop chains** - Walk trusted-domain through redirector to external sequences hop by hop, and finish when every hop is validated or one escape hop is recorded.
5. **Prove impact** - Demonstrate victim navigation to the external destination with the captured chain trace, and finish when the evidence shows the address bar on the unintended destination.

## False Positives

Destinations constrained to relative same-origin paths with robust normalization stop this variant.
Validators using a single canonical parser that compares post-canonicalization host and scheme stop this variant.
Prompts that display the exact final destination and wait for explicit confirmation stop this variant.

## Pro Tips

1. Compare server-side canonicalization against real browser navigation first because every disagreement is a bypass.
2. Try userinfo plus separator plus confusable plus numeric shapes early because they split parsers fastest.
3. Exercise multi-hop chains across distinct subdomains and paths because first-hop checks rarely survive depth.
4. Favor allowlists of exact origins plus optional path prefixes when recommending the fix.
5. Keep a curated abstract variant set per carrier so matrix coverage stays checkable.

## Summary

Generic redirect bypass succeeds exactly where the enforcing parser and the navigating consumer disagree.
Canonicalize once with a single parser, constrain every hop to exact origins, and prove the outcome in a real navigating consumer.
