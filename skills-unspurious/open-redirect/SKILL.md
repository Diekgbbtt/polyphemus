---
name: open-redirect
description: Open redirect testing for phishing pivots, OAuth token theft, and allowlist bypass
metadata:
  version: 1.0.0
---

# Open Redirect

Open redirects enable phishing, credential theft in authorization flows, and allowlist bypass in server-side fetchers that follow redirects. Treat every redirect target as untrusted: canonicalize, then enforce exact allowlists per scheme, host, and path.

## Attack Surface

**Server-Driven Redirects**
- Redirect responses whose location is built from a request value

**Client-Driven Redirects**
- Script-driven navigation, meta refresh, and client-side routers

**Authorization Flows**
- Registered callback destinations, post-logout destinations, relay state, and return-to parameters

**Multi-Hop Chains**
- Only the first hop validated, with a later hop free to leave the trusted set

## Reconnaissance

### Injection Points

- Query and body parameters whose names suggest a destination or a continuation
- Authorization flows: callback destination, post-logout destination, relay state, continuation parameters
- Client-side dispatch: router push and replace calls, location assignment, meta refresh, window opening
- Headers: authority and forwarding families that shape absolute URLs built by the server

### Validator Behaviour

- Submit one obvious external destination and observe the verdict text, which reveals the validation family (exact match, prefix, pattern, or none)
- Vary one component at a time (scheme, authority, port, path) to map which components the validator compares
- Compare the validator verdict with the navigation outcome: the gap between the two is the attack surface

## Detection Channels

- The location header points to an external destination on the enforcing side.
- The browser address bar reaches the external destination on the navigating side.
- Validator verdict and real navigation outcome disagree for the same submitted value.
- An issued credential arrives at the attacker-operated endpoint through the trusted redirector.
- The location header on the relay hop points to the attacker endpoint while the first hop stays trusted.
- The browser address bar traverses the trusted redirector before landing externally.
- Fetcher egress reaches the internal target with retrievable response evidence.
- A later-hop location header points to the internal target while the first hop stays allowlisted.
- The chain trace shows the allowlisted redirector forwarding into the internal destination.
- Timing and header signals confirm server-side retrieval of the internal target.

## Adversarial Capabilities

Redirect testing presupposes a lever that reaches a destination value, an external endpoint to receive arrivals, and a navigation observation, and it consumes all three.
- Supply destination values through every carrier the flow exposes, including encoded forms.
- Operate an external endpoint that records arrivals and their referrer context.
- Drive both sides: the server verdict and a real client navigation.
- Hold an authorized flow position (a registered callback as attacker infrastructure) when the chain targets credential delivery.
- Reach the server-side fetcher that follows redirects, where a fetch pivot is in scope.

## Trust Assumptions

The class rests on one agreement: the destination the validator approves is the destination the client eventually reaches.
The agreement holds both sides to one canonical parse, holds the approval to the whole destination rather than a fragment of it, holds every hop of a chain to the same check, and holds the approved destination's content to the trust the user grants it.
Sensitive position leaks when the two sides disagree: the validator approves a trusted-looking value that the client resolves elsewhere, or a later hop leaves the approved set unseen.
Each variant breaks one clause: the canonicalization clause, the whole-destination clause, the per-hop clause, or the credential-relay clause.

## Key Vulnerabilities

### Allowlist Evasion

- Substring and contains-style checks that accept a trusted name appearing anywhere in the value
- Wildcard acceptance that also matches a lookalike host ending outside the trusted domain
- Missing scheme pinning, which admits script, data, and file schemes
- Case and internationalized-name drift between the validator and the client
- Prefix checks that accept a trusted domain plus an attacker-controlled suffix

### Authorization Flow Abuse

- An open redirect on a trusted domain, used as the registered destination, intercepts issued credentials
- Weak prefix and suffix validation on the callback destination
- Path canonicalization gaps that resolve outside the registered prefix
- Post-logout destinations validated less strictly than callback destinations

### Client-Side Dispatch

- Script navigation built from a parameter, including router push and replace calls
- Meta refresh targets built from input
- Client-side routers that treat a supplied path as an external destination

### Absolute URL Construction

- Authority and forwarding headers shaping absolute URLs the server emits
- Edge link-checking and unfurling features that follow redirects and leak tokens when chained

## Advanced Techniques

### Multi-Hop Chains

- Cross several distinct trusted subdomains and paths so no single hop leaves the approved set
- Use a trusted redirector as the first hop, with the destination decided at the later hop
- Vary the hop count to find where the check is applied

### Fetch Pivot

- Server-side fetchers (previewers, unfurlers, importers) follow redirects, so an allowlisted redirector pivots fetches to internal targets
- Confirm the pivot with response evidence, timing, or an outbound callback

### Destination Harvesting

- Embedded subresources leak the destination or a credential through the referrer policy
- Fragments and query strings survive the redirect and reach the attacker endpoint

## Bypass Techniques

- Userinfo-style values, where the validator reads one authority and the client navigates to another
- Backslash and mixed-slash forms, resolved as separators by some clients
- Control characters and whitespace inside the scheme or authority, stripped by one side and not the other
- Fragment and query shapes that hide a second destination after the trusted name
- Lookalike internationalized names and trailing-dot forms
- Encoded and double-encoded separators, resolved after validation
- Full-width dots and numeric address forms that the validator treats as untrusted-looking text
- Scheme case variation and scheme-relative forms

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Open redirect plus an authorization flow: the issued credential is delivered to attacker infrastructure
- Open redirect plus a server-side fetcher: the allowlisted redirector becomes a route to internal targets
- Open redirect plus phishing: the trusted link carries the victim through a trusted origin before landing elsewhere
- Open redirect plus a subresource embed: the destination or credential leaves through the referrer

## Testing Methodology

1. **Inventory surfaces** - Login and logout, recovery, single sign-on flows, payment hand-offs, message links
2. **Build the test matrix** - Scheme × authority × path variants, plus encoding and internationalized-name forms
3. **Compare behaviours** - Server-side validation verdict against real browser navigation
4. **Multi-hop testing** - Trusted origin, then redirector, then external destination
5. **Prove impact** - Credential phishing, authorization credential interception, or internal egress
6. **Confirm the clause** - Record which component the validator failed to compare, and the step completes when each accepted value carries the clause that admitted it

## Variants

- generic-redirect-parser-bypass - Evade destination allowlists through canonicalization gaps, proving browser navigation to external destinations and escaping multi-hop chains.
- oauth-redirect-uri-relay - Relay issued credentials through a trusted redirector where callback destination registration is loose, capturing them at an attacker endpoint.
- redirector-to-fetcher-pivot - Chain an allowlisted redirector into internal targets, confirming server-side egress and escalating the redirect into internal access.

## False Positives

- Redirects constrained to relative same-origin paths with robust normalization
- Exact pre-registered callback destinations with a strict verifier
- Validators using one canonical parser and comparing the post-canonicalization host and scheme
- User prompts that show the exact final destination before navigating

## Pro Tips

1. Always compare server-side canonicalization with real browser navigation; the difference is the bypass
2. Try userinfo, protocol-relative, internationalized-name, and numeric address shapes early
3. In authorization flows, prioritize the post-logout destination and the less-discussed flows; they are often looser
4. Exercise multi-hop chains across distinct subdomains and paths
5. For fetcher pivots, target services known to follow redirects
6. Favor exact-origin allowlists with optional exact path prefixes, one canonical parser, and a hard requirement for absolute secure destinations
7. Keep a curated matrix of destination shapes rather than isolated payloads, so coverage is visible

## Summary

Redirection is safe only when the final destination is constrained after canonicalization and on every hop. Enforce exact origins, verify each hop, and treat client-provided destinations as untrusted across every stack.
