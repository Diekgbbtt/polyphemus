---
name: oauth
description: OAuth 2.0 and OIDC flow security testing covering redirect manipulation, token leakage, PKCE bypass, and client misconfiguration
metadata:
  version: 1.0.0
---

# OAuth 2.0 / OIDC

OAuth and OIDC failures often enable account takeover, token theft, and cross-client token confusion. Treat every redirect, client identifier, and token exchange as an authorization boundary, not a convenience layer.

## Attack Surface

- **Flows**: authorization code with and without a proof-of-possession challenge, implicit (legacy), hybrid, device authorization, client credentials, refresh rotation, token introspection, and revocation.
- **Endpoints**: authorization, token, userinfo, introspection, revocation, and logout endpoints, discovery documents and key sets, and dynamic client registration where enabled.
- **Token types**: authorization codes, access tokens, refresh tokens, identity assertions, and opaque versus self-contained formats.
- **Client types**: public clients (browser and mobile) versus confidential server-side clients, and several registered destinations, wildcard and pattern matching, and custom scheme handlers.

## Reconnaissance

### Discovery

- **Discovery extraction**: fetch the discovery documents and extract the authorization endpoint, token endpoint, registration endpoint, supported response types, supported challenge methods, and supported grant types.
- **Flow recording**: record which flows each registered client actually uses, by driving each one through to completion.

### Client Enumeration

- **Client-source inspection**: inspect client bundles, mobile package configuration, and public repositories for client identifiers, registered destinations, and scopes.
- **Error-text hints**: read error text for client validation hints: unregistered client, invalid destination.
- **Destination matrix**: enumerate the destination matrix per client rather than per flow.

## Detection Channels

- **Acceptance versus rejection verdict**: per destination pattern, recorded across the whole matrix.
- **Validator-versus-consumer parse gap**: the approving side and the delivering side disagree on the same input.
- **Duplicate-carrier precedence**: the first and the last of two supplied destinations decide differently.
- **Consumer-confirmation capture**: a grant credential arrives at the attacker listener through an accepted destination.
- **Harvest-channel arrival**: an embedded subresource leaks the credential through the ambient referrer policy.
- **No-carrier acceptance**: a flow started without a freshness carrier still completes.
- **Cross-session completion**: a response minted for one session is redeemed in another.
- **Reuse-oracle acceptance**: a previously consumed freshness value succeeds a second time.
- **Scope-escape verdict**: a freshness carrier binds to no session or to the wrong challenge.
- **Challenge-less issuance**: the authorization side mints a credential with no challenge attached.
- **Any-verifier acceptance**: redemption succeeds with a verifier the requester never committed to.
- **Wrong-verifier acceptance**: redemption succeeds with a mismatched verifier value.
- **Downgrade acceptance**: a replayable challenge method succeeds after a stronger one was offered.
- **Authorize-versus-redemption mismatch**: the two steps record different client identities or destinations.
- **Cross-client redemption acceptance**: a credential minted for one client succeeds under another.
- **Cross-audience acceptance**: a token minted for one audience is honored by another service.
- **Token-status oracle answer**: the status endpoint confirms validity without proper caller authentication.
- **Profile-oracle return**: the profile endpoint releases data beyond the presenting token scope.
- **Polling-status transitions**: a guessed device code moves from denied through pending to approved.
- **Approval completion on an attacker-issued code**: the victim confirmation binds to the attacker session.
- **Rate-limit shaping**: the server slows but never blocks repeated guesses.
- **Mix-up completion**: an attacker-initiated grant completes in a victim session under the wrong client.

## Adversarial Capabilities

- **Prerequisites**: flow testing presupposes two clients, an attacker-reachable destination, and a driven flow, and it consumes all three.
- **Client and destination control**: hold at least one registered client plus an attacker-controlled destination, and a second client to test mix-up.
- **Manual flow driving**: drive the authorize, callback, and token steps by hand so every parameter stays under control.
- **Listener and embedding page**: operate an endpoint that records arrivals, plus a page that can embed the authorized destination as a subresource.
- **Victim session**: hold a victim session to test cross-session completion and approval inducement.
- **Device polling**: poll the device endpoint at a chosen rate to measure the guessing window.
- **Offline artifact reading**: read token artifacts offline: decode the header and claims, then re-encode variants.

## Trust Assumptions

- **The agreement**: every artifact in the flow is bound to the client, destination, session, and audience that started it, and to the party that proved possession.
- **The agreement clauses**: the agreement holds the destination to the registered set through one canonical parse, holds the flow response to the session that began it through a freshness carrier, holds the redemption step to the same client and verifier that started the flow, holds the device approval to a verified channel, and holds every issued token to its audience and issuer.
- **The exposure**: sensitive position leaks when a clause fails: the credential reaches an unregistered destination, a replayed or absent carrier completes the flow, one client redeems another's credential, or a token is honored outside its audience.
- **The failing clause**: each variant breaks one clause: the destination clause, the freshness clause, the possession clause, the client-binding clause, or the approval-channel clause.

## Key Vulnerabilities

### Destination Validation

- **Permissive patterns**: register or guess permissive patterns: path-prefix matching, wildcard subdomains, and custom schemes.
- **Open redirect as destination**: an open redirect on a trusted domain, used as the registered destination, intercepts the credential.
- **Logout and linking parameters**: destination parameters on logout and account-linking flows are often validated less strictly.
- **Parse divergence**: validator and consuming client parse the same value differently.

### Credential Leakage and Replay

- **Carriage leakage**: credentials in fragments, referer headers, history, logs, and analytics.
- **Replay before expiry**: replay before expiry where single-use is not enforced.
- **Wrong-destination delivery**: delivery to the wrong destination where the binding at redemption is weak.

### Freshness Carrier Gaps

- **Carrier weaknesses**: missing, predictable, or reusable carrier values enable login CSRF, session fixation, and account linking.
- **Unbound carrier**: a carrier not bound to the client session or the possession challenge.
- **Identity-assertion replay**: identity assertions replayed where the freshness value is injected or repeated.

### Proof-of-Possession Gaps

- **Challenge downgrade**: challenge method downgrade to a replayable form.
- **Challenge-less public clients**: no challenge required on public clients.
- **Loose verifier matching**: a credential issued with no challenge, redeemed with any or no verifier, or matched loosely.

### Client Authentication

- **Secretless requests**: token and introspection endpoints accepting requests without a secret for confidential clients.
- **Client-identifier-only authentication**: client-identifier-only authentication.
- **Dynamic registration**: dynamic registration letting an attacker choose destination and name.
- **Secret exposure**: secrets embedded in public clients, or accepted in query strings and written to logs.

### Scope and Token Binding

- **Scope escalation**: request beyond the application's need and receive every requested scope.
- **Refresh rotation gaps**: refresh not rotated, or reuse undetected, giving persistent access.
- **Cross-service honor**: access tokens honored across services where audience binding is missing.
- **Unauthenticated introspection**: introspection answering validity without authenticating the caller.

### Identity Assertion Specifics

- **Assertion-as-access-token**: identity assertions accepted as access tokens at resource servers.
- **Step-up claims**: step-up claims not validated for the required assurance level.
- **Profile over-return**: profile endpoints returning data beyond the presenting token's scope.
- **Subject collisions**: subject collisions across issuers where the issuer is not validated.

## Advanced Techniques

- **Referer-based harvesting**: embed the authorized destination as a subresource on an attacker page and read the credential from the referer where the policy allows.
- **Device flow abuse**: poll the device endpoint with guessed codes where the rate limit slows without blocking, and induce a victim to approve an attacker-initiated login.
- **Account linking**: link an attacker's identity-provider identity to a victim's local account where re-authentication is not required, and exploit matching identifier values across providers to attach to the wrong account.

## Bypass Techniques

- **Shape evasions**: trailing slash, case, port, and scheme downgrade shapes that evade exact-match checks.
- **Normalization differentials**: path normalization differentials between the approving side and the consuming application.
- **Duplicate parameters**: duplicate destination parameters, where precedence decides which value binds.
- **Wildcard plus claimable name**: wildcard acceptance combined with a claimable or dangling sibling name.
- **Separator confusion**: separator and authority-confusion shapes inside the destination value.
- **Double-encoded separators**: encoded and double-encoded forms of separators, resolved by the consumer after validation.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Open redirect plus authorization flow**: the credential arrives at an attacker listener.
- **Freshness gap plus a second login**: the victim's session ends up bound to the attacker's account.
- **Device approval plus a guessed code**: the attacker's session gains victim authorization.
- **Token leakage plus a second service**: the stolen token is honored where audience binding is absent.
- **Account linking plus an identity collision**: the attacker attaches to the victim account without re-authentication.

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

- **Consistent destination rejection**: destination rejected consistently across all bypass attempts.
- **Strong challenge on public clients**: public clients correctly requiring a strong challenge with strict verifier validation.
- **Enforced freshness values**: freshness values enforced and bound, so the cross-site test fails as expected.
- **Audience and issuer validation**: token audience and issuer validated at the resource server.
- **Ownership-proofed schemes**: custom scheme redirects requiring app ownership proof.

## Pro Tips

- **Full chain capture**: capture the full redirect chain, including intermediate hops.
- **Cross-step comparison**: compare parameter binding between the authorize step and the token step: destination, client, and challenge.
- **Web and mobile separation**: test web and mobile clients separately; validation rules often differ.
- **Logout and revocation checks**: check logout and revocation: tokens may stay valid afterwards.
- **Destination chaining**: chain with an open redirect or stored script on the legitimate destination to surface credentials.
- **Narrow scope proof**: prefer the narrower read when proving a scope break, and record the exact token expectation.

## Tooling

- **Tooling scope**: drive the flow with a command-line client so every parameter stays under control, and use a script runtime to decode and re-encode token artifacts for the variants above.
- **Command-line client**: a command-line client drives authorize, callback, and token steps by hand, which is what makes destination, client, freshness, and verifier binding testable.
- **Script runtime**: a script runtime decodes and tampers token artifacts: algorithm markers, key selectors, and claim sets, then re-encodes the variants for replay.

## Summary

OAuth security rests on strict destination binding, an unguessable and bound freshness carrier, proof of possession for public clients, and consistent token audience validation. Any gap in the authorize-to-token chain is a potential account takeover.
