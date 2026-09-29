---
name: oauth-redirect-uri-relay
description: OAuth relay redirect testing that abuses loose redirect URI registration, relays issued codes through a trusted redirector, and captures tokens at an attacker endpoint
metadata:
  version: 1.0.0
---

# OAuth Redirect URI Relay

OAuth relay redirect testing abuses loose redirect URI registration to route an issued code through a trusted redirector into attacker hands.
Treat every registration comparison as hostile until exact matching binds the issued code to one pre-registered destination.

## Attack Surface

Applies when an OAuth flow exposes a registration URI field plus a logout continuation field plus relay state on the authorization path.
Applies when a trusted redirector on an allowlisted domain can forward the issued code onward.
Applies when an attacker-operated endpoint can receive the relayed code.
Stays out of scope when the sink is a generic browser redirector or a server fetcher (those belong to the sibling variants).

## Reconnaissance

### Registration Probes

List the registration URI field plus the logout continuation field plus relay and state fields on every authorization and logout surface.
Probe prefix looseness where an attacker suffix nests under the trusted origin.
Probe suffix looseness where wildcard scoping admits an unintended subdomain shape.
Probe path traversal where canonicalization reshapes the registered path before comparison.
Probe logout continuation fields separately because they are commonly validated less strictly.
Complete when every field owns a looseness hypothesis with its matching rule named.

### Relay Assembly

List trusted redirectors on allowlisted domains that can carry the issued code onward.
Pair each loose registration with the redirector that forwards to the attacker endpoint.
Complete when each registration gap has a paired relay path ending at an operated endpoint.

## Detection Channels

Issued code arrives at the attacker-operated endpoint through the trusted redirector.
Location header on the relay hop points to the attacker endpoint while the first hop stays trusted.
Browser address bar traverses the trusted redirector before landing externally.

## Adversarial Capabilities

Supply registration and relay input through the authorization and logout fields.
Operate a callback endpoint that captures relayed codes.
Induce victim authorization so the identity provider issues the code to the registered path.

## Trust Assumptions

The redirect feature assumes a destination supplied in the request is constrained to an intended set after canonical parsing, the enforcing parser agrees with the navigating consumer on scheme plus host plus path, every hop of a redirect chain re-verifies the destination, and the destination delivers the victim only to an intended party.
The clause that fails here is registration binding: the verifier matches the submitted redirect URI loosely while the relay delivers the issued code through a trusted redirector to an attacker endpoint.

## Key Vulnerabilities

### Redirect URI Abuse

Trusted-domain relay fails because a loose registration admits an open redirector as the code destination.
Prefix and suffix checks fail because nested-origin shapes satisfy the textual rule while resolving externally.
Path traversal fails because canonicalization reshapes the registered path after the check.
Logout continuation fails because its verifier enforces a weaker rule than the authorization path.
Bind every issued code to one exactly pre-registered destination compared after full canonicalization.
Verify scheme plus host plus path exactly and refuse prefix or suffix or substring rules.
Apply the strict authorization rule to logout continuation fields without exception.

## Advanced Techniques

Construct the relay so the identity provider issues to the trusted redirector and the redirector forwards the code onward.
Carry post-logout looseness as a first-class probe because logout verifiers commonly lag behind authorization verifiers.
Shape traversal values that normalize across the registered path boundary after comparison.

## Bypass Techniques

Shape nested-origin values that satisfy prefix rules while resolving to an operated endpoint.
Shape wildcard-scope values that nest an attacker shape under the trusted scope.
Shape traversal values that escape the registered path after canonicalization.
Shape encoded values that decode one extra time between verifier and navigating consumer.
Shape logout continuation values that exploit the weaker logout rule with an otherwise rejected shape.

## Chaining Attacks

Relay the intercepted code into token exchange only by handing off to the OAuth token-step owner at the code-redemption step.
Relay the code through multi-hop redirector chains where each hop preserves the code parameter.
Pivot relayed access into server-side egress only by handing off to the fetcher-pivot sibling at the fetcher step.

## Testing Methodology

1. **Inventory OAuth surfaces** - List authorization plus logout plus relay-state fields with each registration rule named, and finish when no field lacks its matching rule.
2. **Build registration matrix (bent step)** - Prepare prefix plus suffix plus traversal plus logout-looseness values per field, and finish when every field owns a complete looseness set ready to send.
3. **Compare two-party relay outcome** - Submit each value and record the identity-provider verdict beside the redirector forwarding result, and finish when both sides are recorded and every relay escape is flagged.
4. **Test relay chains** - Walk identity provider through trusted redirector to operated endpoint hop by hop, and finish when every hop is validated or one code-forwarding hop is recorded.
5. **Prove impact** - Capture the issued code at the operated endpoint with the chain trace intact, and finish when the evidence shows code delivery outside the intended destination.

## False Positives

Exactly pre-registered destinations compared by a strict verifier after full canonicalization stop this variant.
Single-parser registration checks that compare exact scheme plus host plus path stop this variant.
Prompts that display the exact final code destination and wait for explicit confirmation stop this variant.

## Pro Tips

1. Prioritize logout continuation fields first because their verifiers are commonly the loosest.
2. Test traversal inside registered paths because canonicalization timing gaps hide there.
3. Pair every registration gap with its relay redirector before claiming impact.
4. Verify every relay hop because first-hop trust rarely survives forwarding.
5. Keep the registration matrix per field so looseness coverage stays checkable.

## Summary

OAuth relay succeeds exactly where loose registration meets a trusted redirector that forwards the code.
Enforce exact pre-registered destinations, verify every relay hop, and prove the outcome by capturing the code only at its intended destination.
