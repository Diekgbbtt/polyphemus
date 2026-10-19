---
name: oauth
description: OAuth 2.0 and OIDC flow security testing covering redirect manipulation, token leakage, PKCE bypass, and client misconfiguration
metadata:
  version: 1.0.0
---

# OAuth 2.0 / OIDC

OAuth and OIDC failures often enable account takeover, token theft, and cross-client token confusion. Treat every redirect, client identifier, and token exchange as an authorization boundary, not a convenience layer.

## Attack Surface

**Flows**
- Authorization code, with and without a proof-of-possession challenge
- Implicit (legacy), hybrid, device authorization, client credentials
- Refresh rotation, token introspection, revocation

**Endpoints**
- Authorization, token, userinfo, introspection, revocation, and logout endpoints
- Discovery documents and key sets
- Dynamic client registration where enabled

**Token Types**
- Authorization codes, access tokens, refresh tokens, identity assertions
- Opaque versus self-contained formats

**Client Types**
- Public clients (browser and mobile) versus confidential server-side clients
- Several registered destinations, wildcard and pattern matching, custom scheme handlers

## Reconnaissance

### Discovery

- Fetch the discovery documents and extract: authorization endpoint, token endpoint, registration endpoint, supported response types, supported challenge methods, supported grant types
- Record which flows each registered client actually uses, by driving each one through to completion

### Client Enumeration

- Inspect client bundles, mobile package configuration, and public repositories for client identifiers, registered destinations, and scopes
- Read error text for client validation hints: unregistered client, invalid destination
- Enumerate the destination matrix per client rather than per flow

## Detection Channels

- Acceptance versus rejection verdict per destination pattern, recorded across the whole matrix.
- Validator-versus-consumer parse gap, where the approving side and the delivering side disagree on the same input.
- Duplicate-carrier precedence, where the first and the last of two supplied destinations decide differently.
- Consumer-confirmation capture, where a grant credential arrives at the attacker listener through an accepted destination.
- Harvest-channel arrival, where an embedded subresource leaks the credential through the ambient referrer policy.
- No-carrier acceptance, where a flow started without a freshness carrier still completes.
- Cross-session completion, where a response minted for one session is redeemed in another.
- Reuse-oracle acceptance, where a previously consumed freshness value succeeds a second time.
- Scope-escape verdict, where a freshness carrier binds to no session or to the wrong challenge.
- Challenge-less issuance, where the authorization side mints a credential with no challenge attached.
- Any-verifier acceptance, where redemption succeeds with a verifier the requester never committed to.
- Wrong-verifier acceptance, where redemption succeeds with a mismatched verifier value.
- Downgrade acceptance, where a replayable challenge method succeeds after a stronger one was offered.
- Authorize-versus-redemption mismatch, where the two steps record different client identities or destinations.
- Cross-client redemption acceptance, where a credential minted for one client succeeds under another.
- Cross-audience acceptance, where a token minted for one audience is honored by another service.
- Token-status oracle answer, where the status endpoint confirms validity without proper caller authentication.
- Profile-oracle return, where the profile endpoint releases data beyond the presenting token scope.
- Polling-status transitions, where a guessed device code moves from denied through pending to approved.
- Approval completion on an attacker-issued code, where the victim confirmation binds to the attacker session.
- Rate-limit shaping, where the server slows but never blocks repeated guesses.
- Mix-up completion, where an attacker-initiated grant completes in a victim session under the wrong client.

## Adversarial Capabilities

Flow testing presupposes two clients, an attacker-reachable destination, and a driven flow, and it consumes all three.
- Hold at least one registered client plus an attacker-controlled destination, and a second client to test mix-up.
- Drive the authorize, callback, and token steps by hand so every parameter stays under control.
- Operate an endpoint that records arrivals, plus a page that can embed the authorized destination as a subresource.
- Hold a victim session to test cross-session completion and approval inducement.
- Poll the device endpoint at a chosen rate to measure the guessing window.
- Read token artifacts offline: decode the header and claims, then re-encode variants.

## Trust Assumptions

The class rests on one agreement: every artifact in the flow is bound to the client, destination, session, and audience that started it, and to the party that proved possession.
The agreement holds the destination to the registered set through one canonical parse, holds the flow response to the session that began it through a freshness carrier, holds the redemption step to the same client and verifier that started the flow, holds the device approval to a verified channel, and holds every issued token to its audience and issuer.
Sensitive position leaks when a clause fails: the credential reaches an unregistered destination, a replayed or absent carrier completes the flow, one client redeems another's credential, or a token is honored outside its audience.
Each variant breaks one clause: the destination clause, the freshness clause, the possession clause, the client-binding clause, or the approval-channel clause.

## Key Vulnerabilities

### Destination Validation

- Register or guess permissive patterns: path-prefix matching, wildcard subdomains, and custom schemes
- An open redirect on a trusted domain, used as the registered destination, intercepts the credential
- Destination parameters on logout and account-linking flows are often validated less strictly
- Validator and consuming client parse the same value differently

### Credential Leakage and Replay

- Credentials in fragments, referer headers, history, logs, and analytics
- Replay before expiry where single-use is not enforced
- Delivery to the wrong destination where the binding at redemption is weak

### Freshness Carrier Gaps

- Missing, predictable, or reusable carrier values enable login CSRF, session fixation, and account linking
- A carrier not bound to the client session or the possession challenge
- Identity assertions replayed where the freshness value is injected or repeated

### Proof-of-Possession Gaps

- Challenge method downgrade to a replayable form
- No challenge required on public clients
- A credential issued with no challenge, redeemed with any or no verifier, or matched loosely

### Client Authentication

- Token and introspection endpoints accepting requests without a secret for confidential clients
- Client-identifier-only authentication
- Dynamic registration letting an attacker choose destination and name
- Secrets embedded in public clients, or accepted in query strings and written to logs

### Scope and Token Binding

- Scope escalation: request beyond the application's need and receive every requested scope
- Refresh not rotated, or reuse undetected, giving persistent access
- Access tokens honored across services where audience binding is missing
- Introspection answering validity without authenticating the caller

### Identity Assertion Specifics

- Identity assertions accepted as access tokens at resource servers
- Step-up claims not validated for the required assurance level
- Profile endpoints returning data beyond the presenting token's scope
- Subject collisions across issuers where the issuer is not validated

## Advanced Techniques

**Referer-Based Harvesting**
- Embed the authorized destination as a subresource on an attacker page and read the credential from the referer where the policy allows

**Device Flow Abuse**
- Poll the device endpoint with guessed codes where the rate limit slows without blocking
- Induce a victim to approve an attacker-initiated login

**Account Linking**
- Link an attacker's identity-provider identity to a victim's local account where re-authentication is not required
- Exploit matching identifier values across providers to attach to the wrong account

## Bypass Techniques

- Trailing slash, case, port, and scheme downgrade shapes that evade exact-match checks
- Path normalization differentials between the approving side and the consuming application
- Duplicate destination parameters, where precedence decides which value binds
- Wildcard acceptance combined with a claimable or dangling sibling name
- Separator and authority-confusion shapes inside the destination value
- Encoded and double-encoded forms of separators, resolved by the consumer after validation

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Open redirect plus authorization flow: the credential arrives at an attacker listener
- Freshness gap plus a second login: the victim's session ends up bound to the attacker's account
- Device approval plus a guessed code: the attacker's session gains victim authorization
- Token leakage plus a second service: the stolen token is honored where audience binding is absent
- Account linking plus an identity collision: the attacker attaches to the victim account without re-authentication

## Testing Methodology

1. **Map flows** - Identify grant types, clients, and destinations in use
2. **Build the destination matrix** - For each client, fuzz the destination validation with encoding and parser tricks; the step completes when every pattern carries an acceptance verdict
3. **Test freshness** - Initiate flows without a carrier and swap sessions mid-flow; the step completes when no-carrier and cross-session completion each carry a verdict
4. **Test possession** - Replay credentials with missing, wrong, and downgraded verifiers; the step completes when each verifier case carries a verdict
5. **Test the exchange** - Swap credentials and tokens between clients and audiences; the step completes when cross-client and cross-audience acceptance each carry a verdict
6. **Test the device path** - Poll with guessed codes and measure the limit; the step completes when the guessing window and the approval binding carry verdicts
7. **Test mobile dispatch** - Custom schemes, intent filters, and universal links; the step completes when the dispatch surface carries a hijack verdict

## Variants

- oauth-redirect-uri-validation - Exploit destination validation gaps where unregistered destinations are accepted or the validator and consumer parse the same destination differently.
- oauth-state-nonce-csrf - Exploit freshness binding gaps where flows start without a carrier or a carrier replays across sessions or requests.
- oauth-pkce-enforcement - Exploit verifier binding gaps where credentials issue without a challenge, redemption accepts a missing or mismatched verifier, or methods downgrade.
- oauth-code-client-binding - Exploit client binding gaps where credential redemption skips destination or identity comparison, or an attacker-initiated grant completes in a victim session.
- oauth-device-approval - Exploit the device approval path where codes are guessable or pollable, or a victim can be induced to approve an attacker-initiated login.

## False Positives

- Destination rejected consistently across all bypass attempts
- Public clients correctly requiring a strong challenge with strict verifier validation
- Freshness values enforced and bound, so the cross-site test fails as expected
- Token audience and issuer validated at the resource server
- Custom scheme redirects requiring app ownership proof

## Pro Tips

1. Capture the full redirect chain, including intermediate hops
2. Compare parameter binding between the authorize step and the token step: destination, client, and challenge
3. Test web and mobile clients separately; validation rules often differ
4. Check logout and revocation: tokens may stay valid afterwards
5. Chain with an open redirect or stored script on the legitimate destination to surface credentials
6. Prefer the narrower read when proving a scope break, and record the exact token expectation

## Tooling

Drive the flow with a command-line client so every parameter stays under control, and use a script runtime to decode and re-encode token artifacts for the variants above.
- A command-line client drives authorize, callback, and token steps by hand, which is what makes destination, client, freshness, and verifier binding testable.
- A script runtime decodes and tampers token artifacts: algorithm markers, key selectors, and claim sets, then re-encodes the variants for replay.

## Summary

OAuth security rests on strict destination binding, an unguessable and bound freshness carrier, proof of possession for public clients, and consistent token audience validation. Any gap in the authorize-to-token chain is a potential account takeover.
