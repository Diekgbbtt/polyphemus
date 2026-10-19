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

- **Applicability**: a server 3xx sink or a client navigation sink consumes a user-controllable destination.
- **Navigating consumer**: a browser victim resolves the final destination.
- **Constraint claim**: an allowlist or same-origin constraint claims to confine the destination.
- **Out-of-scope variants**: a registered OAuth relay or a server fetcher that follows the hops belongs to the sibling variants.

## Reconnaissance

### Injection Points

- **Carrier inventory**: list every destination carrier on sign-in, sign-out, reset, payment, and message-link surfaces.
- **Client-sink inventory**: list client sinks including script-assigned locations, meta refresh, router navigation, and new-window calls.
- **Forwarding evidence**: list forwarding evidence that can reshape absolute destination construction.
- **Completion condition**: complete when every redirector candidate is listed with its carrier and its sink kind.

### Parser Differentials

- **Userinfo-shaped values**: assemble userinfo-shaped values where the enforcing parser and the navigating consumer disagree on the host.
- **Separator-confusion values**: assemble separator-confusion values using mixed slashes and repeated leading slashes.
- **Whitespace and control values**: assemble whitespace and control-character values that one side strips and the other keeps.
- **Fragment and query smuggling values**: assemble fragment and query smuggling values that hide the effective destination from the validator.
- **Confusable-character values**: assemble confusable-character and dotted-name values that resolve differently after name canonicalization.
- **Encoded and case-varied values**: assemble encoded and double-encoded values plus case-varied schemes plus numeric address forms.
- **Completion condition**: complete when each carrier owns a variant set covering every family above.

## Detection Channels

- **Enforcing-side signal**: the location header points to an external destination on the enforcing side.
- **Navigating-side signal**: the browser address bar reaches the external destination on the navigating side.
- **Verdict disagreement**: the validator verdict and the real navigation outcome disagree for the same submitted value.

## Adversarial Capabilities

- **Destination input**: supply destination input through the carrier the surface exposes.
- **Victim navigation**: induce victim navigation so the navigating consumer resolves the submitted value.
- **Dual-side observation**: observe both the enforcing-side verdict and the navigating-side outcome for comparison.
- **Callback operation**: operate no callback beyond confirming the victim lands externally.

## Trust Assumptions

- **The agreement**: a destination supplied in the request is constrained to an intended set after canonical parsing, the enforcing parser agrees with the navigating consumer on scheme, host, and path, every hop of a redirect chain re-verifies the destination, and the destination delivers the victim only to an intended party.
- **The failing clause**: parser agreement fails because the enforcing parser and the navigating consumer canonicalize the same value differently, so a destination confined by one resolves externally in the other.

## Key Vulnerabilities

### Allowlist Evasion

- **Contain-check failure**: a contain-check fails because a trusted name embedded as a substring still matches while the navigation goes elsewhere.
- **Wildcard-scoping failure**: wildcard scoping fails because an attacker-controlled suffix nests under the trusted scope while resolving externally.
- **Scheme-policy failure**: scheme policy fails when executable or non-navigation scheme values are accepted as destinations.
- **Case and name-form drift**: case and name-form drift fails when the validator compares one textual form and the consumer resolves another.
- **Canonical-parser constraint**: constrain destinations with one canonical parser that normalizes encoding, case, and name form before any check.
- **Exact comparison**: compare the exact scheme, the post-canonicalization host, and an explicit allowlist with optional exact path prefixes.
- **Absolute-destination requirement**: require absolute secure destinations and refuse relative-escape shapes and unknown schemes.

### Client-Side Vectors

- **Script-assigned destination failure**: a script-assigned destination fails when user input flows into the navigation call without the same canonical check.
- **Meta-refresh failure**: a meta refresh destination fails when the refresh target carries an unvalidated value.
- **Router-navigation failure**: router navigation fails when the route argument is read from attacker-influenced state.
- **Client-side dispatch proof**: prove a client-side vector explicitly by tracing one parameter value into the navigation call and recording the external destination the client reaches, because no server verdict fires for a dispatch that never leaves the page.
- **Client-side exact-origin check**: apply the same single-parser exact-origin check on the client before navigation.

## Advanced Techniques

- **Multi-hop deepening**: deepen multi-hop chains across distinct subdomains and paths until a hop skips re-verification.
- **Comparator rewrite**: rewrite the comparator for router-guarded clients by comparing the client-side guard verdict against the DOM navigation outcome.
- **Executable-scheme proof**: prove navigation only for executable-scheme values and leave script execution out of scope.

## Bypass Techniques

- **Userinfo values**: shape userinfo values that split the parsed host between validator and consumer.
- **Separator and slash-confusion values**: shape separator and slash-confusion values that change the authority boundary after normalization.
- **Whitespace and control values**: shape whitespace and control values that survive on one side and vanish on the other.
- **Fragment and query values**: shape fragment and query values that mask the effective destination from prefix checks.
- **Confusable-character and trailing-dot values**: shape confusable-character and trailing-dot values that equalize differently per parser.
- **Double-encoded and case-varied values**: shape double-encoded and case-varied values that decode one extra time in the consumer.

- **Proxy-techniques handoff**: the destination parse comparison is the proxy-techniques family's step; name it there and keep the class-specific navigation verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Multi-hop escape**: escape through multi-hop chains where a trusted domain fronts a redirector that lands externally.
- **Code relay handoff**: relay issued codes through a trusted redirector only by handing off to the OAuth relay sibling at the registration step.
- **Fetcher-pivot handoff**: pivot an allowlisted redirector into server-side egress only by handing off to the fetcher-pivot sibling at the fetcher step.

## Testing Methodology

1. **Inventory surfaces** - List sign-in and sign-out plus reset plus payment plus message-link redirectors with each carrier and sink kind, and finish when no redirector candidate lacks a carrier.
2. **Build test matrix** - Prepare per-carrier variant sets spanning scheme plus host plus path with encoding and confusable forms, and finish when every carrier owns a complete family set.
3. **Compare enforcing against navigating outcome (bent step)** - Submit each value and record the validator verdict beside the real browser navigation result, and finish when both outcomes are recorded for every value and every disagreement is flagged as a bypass.
4. **Test multi-hop chains** - Walk trusted-domain through redirector to external sequences hop by hop, and finish when every hop is validated or one escape hop is recorded.
5. **Prove impact** - Demonstrate victim navigation to the external destination with the captured chain trace, and finish when the evidence shows the address bar on the unintended destination.

## False Positives

- **Constrained destinations**: destinations constrained to relative same-origin paths with robust normalization stop this variant.
- **Single-parser validators**: validators using a single canonical parser that compares post-canonicalization host and scheme stop this variant.
- **Destination prompts**: prompts that display the exact final destination and wait for explicit confirmation stop this variant.

## Pro Tips

- **Canonicalization comparison**: compare server-side canonicalization against real browser navigation first because every disagreement is a bypass.
- **Parser-splitting shapes**: try userinfo, separator, confusable, and numeric shapes early because they split parsers fastest.
- **Multi-hop exercise**: exercise multi-hop chains across distinct subdomains and paths because first-hop checks rarely survive depth.
- **Exact-origin allowlists**: favor allowlists of exact origins plus optional path prefixes when recommending the fix.
- **Curated variant set**: keep a curated abstract variant set per carrier so matrix coverage stays checkable.

## Summary

Generic redirect bypass succeeds exactly where the enforcing parser and the navigating consumer disagree.
Canonicalize once with a single parser, constrain every hop to exact origins, and prove the outcome in a real navigating consumer.
