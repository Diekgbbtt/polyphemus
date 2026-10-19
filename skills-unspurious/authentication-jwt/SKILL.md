---
name: authentication-jwt
description: JWT and OIDC security testing covering token forgery, algorithm confusion, and claim manipulation
metadata:
  version: 1.0.0
---

# Authentication / JWT / OIDC

JWT/OIDC failures often enable token forgery, token confusion, cross-service acceptance, and durable account takeover. Do not trust headers, claims, or token opacity without strict validation bound to issuer, audience, key, and context.

## Attack Surface

- Web/mobile/API authentication using JWT (JWS/JWE) and OIDC/OAuth2
- Access vs ID tokens, refresh tokens, device/PKCE/Backchannel flows
- First-party and microservices verification, gateways, and JWKS distribution

### Mobile

- Deep-link/redirect handling bugs leak codes/tokens; insecure WebView bridges exposing tokens
- Token storage in plaintext files/SQLite/Keychain/SharedPrefs; backup/adb accessible

## Reconnaissance

### Endpoints

- Well-known: `/.well-known/openid-configuration`, `/oauth2/.well-known/openid-configuration`
- Keys: `/jwks.json`, rotating key endpoints, tenant-specific JWKS
- Auth: `/authorize`, `/token`, `/introspect`, `/revoke`, `/logout`, device code endpoints
- App: `/login`, `/callback`, `/refresh`, `/me`, `/session`, `/impersonate`

### Token Features

- Headers: `{"alg":"RS256","kid":"...","typ":"JWT","jku":"...","x5u":"...","jwk":{...}}`
- Claims: `{"iss":"...","aud":"...","azp":"...","sub":"user","scope":"...","exp":...,"nbf":...,"iat":...}`
- Formats: JWS (signed), JWE (encrypted). Note unencoded payload option (`"b64":false`) and critical headers (`"crit"`)

## Detection Channels

- Acceptance verdict difference between the legitimate token and a mutated one under otherwise identical requests.
- Cross-context acceptance where a token issued for one audience, issuer, or kind returns an authorized response in another context.
- Single-service acceptance where an edited privilege claim or an expired lifetime still returns an authorized response.
- Key-resolution evidence: the verifier follows an attacker-supplied key location, shown by fetch timing, fetch error text, or a verdict change when that location changes.
- Fallback acceptance where an absent or unknown key selector still verifies instead of rejecting.
- Rotation-window acceptance where a retired key verifies again during rollover and rejects outside it.
- Nested ordering signal where the outer token verifies while the inner claims are ignored.
- Lifecycle oracle signal where refresh reuse, post-logout replay, or a fixed session identifier still verifies.
- Cross-client acceptance where a code or token issued for one client redeems successfully at a sibling client.

## Adversarial Capabilities

Verification testing presupposes token issuance, component mutation, and reach across every acceptance path, and it consumes all three.
- Issue and capture tokens: register a principal, complete the flow, and hold access, identity, refresh, and device artifacts.
- Mutate each token component - header, claim set, signature - and replay under otherwise identical requests.
- Reach every acceptance path: edge gateway, service, worker, socket, and batch consumer.
- Hold a second client or a second principal so cross-client and cross-context replay stay testable.
- Read verifier verdicts, error text, and response timing on each path.
- Host or reference an attacker-controlled key location when key resolution is in question.

## Trust Assumptions

The class rests on one agreement: the verifier binds each token to the context that minted it - issuer, audience, key, client, and lifetime - and no other party can alter that binding.
The agreement holds the signature check to a pinned algorithm, key resolution to locations the service controls, claim enforcement to the values the token was minted with, and lifecycle state to the flow that issued it.
Sensitive position leaks when the token crosses a boundary the verifier did not consider: a second service, a second client, or a later moment in time.
Each variant breaks one clause of that agreement: the algorithm or key clause at signature time, the claim clause at validation time, or the lifecycle clause at flow time.
The parent baseline is the check itself - every acceptance path is probed for the binding it skips.

## Key Vulnerabilities

### Signature Verification

- RS256→HS256 confusion: change the algorithm to a symmetric scheme and use the public key as the shared secret when the algorithm is not pinned
- Unsigned acceptance: drop the signature and mark the token unsigned where libraries tolerate it
- Weak verification settings accepting non-canonical signatures

### Header Manipulation

- **Key selector injection**: path traversal in the selector, SQL/command/template injection in key lookup, or a selector pointing at a world-readable file
- **Remote key references**: host an attacker-controlled key document or certificate chain; where the reference is not pinned or whitelisted, the server fetches and trusts attacker keys
- **Inline key embedding**: embed an attacker key in the header; some libraries prefer the inline key over the configured key
- **SSRF via remote key fetch**: exploit key-URL fetching to reach internal hosts

### Key and Cache Issues

- Key caching TTL and rollover: accept obsolete keys; race rotation windows; missing selector pinning → accept any key matching type and algorithm
- Mixed environments: same secrets across dev/stage/prod; key reuse across tenants or services
- Fallbacks: verification succeeds when the selector is not found by trying all keys or no keys (implementation bugs)

### Claims Validation Gaps

- Issuer/audience/authorized-party not enforced: cross-service token reuse; accept tokens from any issuer or wrong audience
- Scope/roles fully trusted from the token: the server does not re-derive authorization; privilege inflation via claim edits when signature checks are weak
- Lifetime claims not enforced or a large clock-skew tolerance: accept long-expired or not-yet-valid tokens
- Token type not enforced: accept an identity token where an access token is required (token confusion)

### Token Confusion and OIDC

- Access vs identity token swap: use an identity token against APIs that verify the signature but not audience or type
- OIDC mix-up: redirect and client mix-ups causing tokens for one client to be redeemed at another
- Verifier downgrades: missing strong-challenge requirement; accept a plain or absent verifier
- Freshness weaknesses: predictable or missing state and nonce values enable login CSRF and logical interception
- Device and back-channel flows: codes and tokens accepted by unintended clients or services

### Refresh and Session

- Refresh rotation not enforced: reuse an old refresh token indefinitely; no reuse detection
- Long-lived tokens with no revocation: persistent access after logout
- Session fixation: bind new tokens to attacker-controlled session identifiers or cookies

### Transport and Storage

- Token in browser storage: susceptible to script exfiltration; cookie vs header trade-offs with SameSite/CSRF
- Insecure CORS: wildcard origins with credentialed requests expose tokens and protected responses
- Transport and cookie flags: missing Secure/HttpOnly; absence of proof-of-possession binding permits replay from another device

## Advanced Techniques

### Microservices and Gateways

- Audience mismatch: internal services verify the signature but ignore audience, accepting tokens for other services
- Header trust: the edge or gateway injects an identity header; the backend trusts it over the token claims
- Asynchronous consumers: workers process messages carrying bearer tokens but skip verification on replay

### JWS Edge Cases

- Unencoded payload with a critical-header marker: libraries mishandle the verification path
- Nested token verification-order errors; the outer token is accepted while the inner claims are ignored

### SSO Federation

- Misconfigured trust between multiple identity providers and service providers, mixed metadata, or stale keys lead to acceptance of foreign tokens

## Bypass Techniques

Bypass shapes slip past a binding that is present, so each one is tried after the baseline check reports enforcement.
- Selector forms that resolve to no configured key let the verifier fall back to trying every key, or to skipping the check.
- A mixed key set where one key matches on type alone lets a token minted under the wrong scheme verify.
- Rotation overlap: a retired key inside its window still verifies tokens minted with it.
- Kind swapping: a token of the wrong kind passes a check that reads the signature and skips kind and audience.
- Envelope-only checks: a nested token verifies at the envelope while the inner claims stay unread.
- Cached verdicts: an edge or gateway reuses a prior verification result across a change of claims or session, where the defence-bypass family owns the edge-versus-core step.
- Transport variants: the same token replayed over a second channel or device where proof-of-possession is absent, where the proxy-techniques family owns the carrier step.

## Chaining Attacks

- XSS → token theft → replay across services with weak audience checks
- SSRF → fetch private JWKS → sign tokens accepted by internal services
- Host header poisoning → OIDC redirect_uri poisoning → code capture
- IDOR in sessions/impersonation endpoints → mint tokens for other users

## Testing Methodology

1. **Inventory issuers/consumers** - Identity providers, API gateways, services, mobile/web clients
2. **Capture tokens** - Access and ID tokens for multiple roles; note header, claims, signature
3. **Map verification endpoints** - `/.well-known`, `/jwks.json`
4. **Build matrix** - Token Type × Audience × Service; attempt cross-use
5. **Mutate components** - Headers (algorithm, selector, remote/locator references, inline keys), claims (issuer, audience, party, subject, lifetime), signatures
6. **Verify enforcement** - What is actually checked vs assumed
7. **Replay across contexts** - Second service, second client, second device; the step completes when each acceptance path carries a verdict

## Variants

- jwt-signature-forgery - Forge token signatures when algorithm pinning, unsigned acceptance, verifier strictness, or the signing secret is open.
- jwt-key-resolution - Seize key selection when selectors, remote key hosting, inline keys, or rotation and fallback widen the trusted key set.
- jwt-claims-confusion - Prove cross-context acceptance when issuer, audience, privilege, lifetime, or token-kind bindings go unenforced.
- jwt-flow-lifecycle - Drive client mix-up, flow downgrade, device misuse, refresh reuse, and revocation gaps through the protocol lifecycle.

## False Positives

- Token rejected due to strict audience/issuer enforcement
- Key pinning with JWKS whitelist and TLS validation
- Short-lived tokens with rotation and revocation on logout
- ID token not accepted by APIs that require access tokens

## Pro Tips

1. Pin verification to issuer and audience; log and diff claim sets across services
2. Attempt the symmetric-confusion and unsigned shapes first only if algorithm pinning is unclear; otherwise focus on header key control (selector, remote reference, inline key)
3. Test token reuse across all services; many backends only check the signature, not audience or type
4. Exploit key caching and rotation races; try retired keys and missing-selector fallbacks
5. Exercise OIDC flows with strong-challenge, state, and nonce variants and mixed clients; look for mix-up
6. Try proof-of-possession absence to replay tokens from different devices
7. Treat refresh as its own surface: rotation, reuse detection, and audience scoping
8. Validate every acceptance path: gateway, service, worker, WebSocket, and RPC
9. Favor minimal PoCs that clearly show cross-context acceptance and durable access
10. When in doubt, assume verification differs per stack (mobile vs web vs gateway) and test each

## Summary

Verification must bind the token to the correct issuer, audience, key, and client context on every acceptance path. Any missing binding enables forgery or confusion.
