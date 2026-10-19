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

- **Applicability**: an OAuth flow exposes a registration URI field, a logout continuation field, and relay state on the authorization path.
- **Trusted redirector**: a trusted redirector on an allowlisted domain can forward the issued code onward.
- **Attacker endpoint**: an attacker-operated endpoint can receive the relayed code.
- **Out-of-scope variants**: a generic browser redirector sink or a server fetcher belongs to the sibling variants.

## Reconnaissance

### Registration Probes

- **Field inventory**: list the registration URI field, the logout continuation field, and the relay and state fields on every authorization and logout surface.
- **Prefix looseness**: probe prefix looseness where an attacker suffix nests under the trusted origin.
- **Suffix looseness**: probe suffix looseness where wildcard scoping admits an unintended subdomain shape.
- **Path traversal**: probe path traversal where canonicalization reshapes the registered path before comparison.
- **Logout continuation probes**: probe logout continuation fields separately because they are commonly validated less strictly.
- **Completion condition**: complete when every field owns a looseness hypothesis with its matching rule named.

### Relay Assembly

- **Trusted redirector inventory**: list trusted redirectors on allowlisted domains that can carry the issued code onward.
- **Registration-relay pairing**: pair each loose registration with the redirector that forwards to the attacker endpoint.
- **Completion condition**: complete when each registration gap has a paired relay path ending at an operated endpoint.

## Detection Channels

- **Code arrival**: the issued code arrives at the attacker-operated endpoint through the trusted redirector.
- **Relay-hop location**: the location header on the relay hop points to the attacker endpoint while the first hop stays trusted.
- **Address-bar traversal**: the browser address bar traverses the trusted redirector before landing externally.

## Adversarial Capabilities

- **Registration and relay input**: supply registration and relay input through the authorization and logout fields.
- **Callback endpoint**: operate a callback endpoint that captures relayed codes.
- **Victim authorization**: induce victim authorization so the identity provider issues the code to the registered path.

## Trust Assumptions

- **The agreement**: a destination supplied in the request is constrained to an intended set after canonical parsing, the enforcing parser agrees with the navigating consumer on scheme, host, and path, every hop of a redirect chain re-verifies the destination, and the destination delivers the victim only to an intended party.
- **The failing clause**: registration binding fails because the verifier matches the submitted redirect URI loosely while the relay delivers the issued code through a trusted redirector to an attacker endpoint.

## Key Vulnerabilities

### Redirect URI Abuse

- **Trusted-domain relay failure**: trusted-domain relay fails because a loose registration admits an open redirector as the code destination.
- **Prefix and suffix check failure**: prefix and suffix checks fail because nested-origin shapes satisfy the textual rule while resolving externally.
- **Path-traversal failure**: path traversal fails because canonicalization reshapes the registered path after the check.
- **Logout continuation failure**: logout continuation fails because its verifier enforces a weaker rule than the authorization path.
- **Exact binding**: bind every issued code to one exactly pre-registered destination compared after full canonicalization.
- **Exact verification**: verify scheme, host, and path exactly and refuse prefix, suffix, or substring rules.
- **Logout rule parity**: apply the strict authorization rule to logout continuation fields without exception.

## Advanced Techniques

- **Relay construction**: construct the relay so the identity provider issues to the trusted redirector and the redirector forwards the code onward.
- **Post-logout looseness**: carry post-logout looseness as a first-class probe because logout verifiers commonly lag behind authorization verifiers.
- **Path-boundary traversal**: shape traversal values that normalize across the registered path boundary after comparison.

## Bypass Techniques

- **Nested-origin values**: shape nested-origin values that satisfy prefix rules while resolving to an operated endpoint.
- **Wildcard-scope values**: shape wildcard-scope values that nest an attacker shape under the trusted scope.
- **Traversal values**: shape traversal values that escape the registered path after canonicalization.
- **Encoded values**: shape encoded values that decode one extra time between verifier and navigating consumer.
- **Logout continuation values**: shape logout continuation values that exploit the weaker logout rule with an otherwise rejected shape.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Token-exchange handoff**: relay the intercepted code into token exchange only by handing off to the OAuth token-step owner at the code-redemption step.
- **Multi-hop relay**: relay the code through multi-hop redirector chains where each hop preserves the code parameter.
- **Fetcher-pivot handoff**: pivot relayed access into server-side egress only by handing off to the fetcher-pivot sibling at the fetcher step.

## Testing Methodology

1. **Inventory OAuth surfaces** - List authorization plus logout plus relay-state fields with each registration rule named, and finish when no field lacks its matching rule.
2. **Build registration matrix (bent step)** - Prepare prefix plus suffix plus traversal plus logout-looseness values per field, and finish when every field owns a complete looseness set ready to send.
3. **Compare two-party relay outcome** - Submit each value and record the identity-provider verdict beside the redirector forwarding result, and finish when both sides are recorded and every relay escape is flagged.
4. **Test relay chains** - Walk identity provider through trusted redirector to operated endpoint hop by hop, and finish when every hop is validated or one code-forwarding hop is recorded.
5. **Prove impact** - Capture the issued code at the operated endpoint with the chain trace intact, and finish when the evidence shows code delivery outside the intended destination.

## False Positives

- **Exact pre-registration**: exactly pre-registered destinations compared by a strict verifier after full canonicalization stop this variant.
- **Single-parser checks**: single-parser registration checks that compare exact scheme, host, and path stop this variant.
- **Destination prompts**: prompts that display the exact final code destination and wait for explicit confirmation stop this variant.

## Pro Tips

- **Logout continuation priority**: prioritize logout continuation fields first because their verifiers are commonly the loosest.
- **Traversal inside paths**: test traversal inside registered paths because canonicalization timing gaps hide there.
- **Registration-relay pairing**: pair every registration gap with its relay redirector before claiming impact.
- **Per-hop verification**: verify every relay hop because first-hop trust rarely survives forwarding.
- **Registration matrix**: keep the registration matrix per field so looseness coverage stays checkable.

## Summary

OAuth relay succeeds exactly where loose registration meets a trusted redirector that forwards the code.
Enforce exact pre-registered destinations, verify every relay hop, and prove the outcome by capturing the code only at its intended destination.
