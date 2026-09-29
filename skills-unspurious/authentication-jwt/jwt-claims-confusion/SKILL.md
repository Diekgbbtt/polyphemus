---
name: jwt-claims-confusion
description: Prove cross-context acceptance through issuer, audience, privilege, lifetime, or token type confusion. Use when cross-service reuse is suspected, when privilege derives from token claims, when expiry looks unenforced, or when token types look interchangeable.
metadata:
  version: 1.0.0
---

# JWT Claims Confusion

Prove that a validly signed token verifies in a context it was never issued for.
This variant breaks the claims and context binding while the signature routine, the key source, and the protocol run stay unchanged.

## Attack Surface

- Token-authenticated request paths where authorization derives from presented claims rather than server-side state.
- Multi-consumer topologies where one issuer serves several services, audiences, tenants, or token kinds.
- Acceptance paths that distinguish token kinds, privilege levels, lifetimes, or nested token orderings.

## Reconnaissance

- Inventory every issuer and consumer and record which audience, token kind, and privilege model each one expects.
- Capture tokens for at least two roles and across token kinds, and record the issuer, audience, privilege, lifetime, and type posture per token.
- Map the token kind by audience by service matrix so every cross-context cell is named before replay starts.
- Probe whether a single-service claim edit, a cross-service replay, or a nested ordering swap reaches the verifier intact.

## Detection Channels

- Cross-context acceptance where a token issued for one audience, issuer, service, or token kind returns an authorized response in another.
- Single-service acceptance where an edited privilege claim or an expired lifetime still returns an authorized response.
- Acceptance verdict difference between the original context and the replayed context under otherwise identical requests.
- Nested ordering signals where the outer token verifies while the inner claims are ignored.

## Adversarial Capabilities

- Possession of legitimate tokens spanning at least two roles, audiences, services, or token kinds.
- Ability to re-present edited claim sets and cross-context replays to every acceptance path.
- Ability to compare acceptance verdicts across contexts without holding any insider key material.
- Ability to hold expired, privilege-edited, and type-swapped shapes for single-service verdicts.

## Trust Assumptions

- At the moment a protected feature executes, the server assumes each presented token is bound to one issuer, one audience, one verification key, one signature algorithm, and one client context, and that only the expected issuer minted it for the expected audience under the expected key and algorithm within its validity window.
- The clause binding the token to its issuer, audience, lifetime, and token type fails, so a validly signed token for another context still verifies.

## Key Vulnerabilities

- Issuer and audience gaps accept tokens minted for a foreign issuer, a neighboring audience, or a neighboring tenant.
- Privilege trust re-derives authorization from presented scope or role claims without server-side confirmation, so edited privilege verifies.
- Lifetime gaps accept expired or premature tokens through missing enforcement or through overly tolerant clock skew.
- Token type confusion accepts one token kind where another is required, including access for identity shapes and outer for inner shapes in nested orderings.

## Advanced Techniques

- Fill the token kind by audience by service matrix cell by cell because signature-only checks pass in cells that context checks would reject.
- Test gateway-injected identity material where the backend prefers a header claim over the verified token claims.
- Test asynchronous consumers that skip context checks on replay even when the synchronous path enforces them.
- Test nested token orderings by swapping outer and inner verification priority and observing which claim set governs.

## Bypass Techniques

- Defeat issuer and audience enforcement by replaying a legitimate token from a neighboring issuer, audience, or tenant into the target path.
- Defeat privilege enforcement by presenting edited privilege claim sets against a single service and observing authorization change.
- Defeat lifetime enforcement by presenting expired and premature shapes and by bracketing the clock skew tolerance.
- Defeat token kind enforcement by swapping token kinds across paths and by swapping nested token orderings.

## Chaining Attacks

- Name token theft skills at the exfiltration step and start here once tokens for two contexts are held.
- Name session and impersonation skills at the minting step where a foreign context token is obtainable.
- Hand signature-only findings to the signature forgery variant once context is pinned and only the algorithm binding is suspect.
- Hand key control findings to the key resolution variant once context is pinned and only the key source binding is suspect.

## Testing Methodology

1. **Record the legitimate context regime** - Capture one token per kind, role, audience, and service, and note the issuer, audience, privilege, lifetime, and type posture.
2. **Prove cross-context replay** - Replay each token into every neighboring audience, service, tenant, and issuer path and record each acceptance verdict.
3. **Prove single-service claim acceptance** - Present privilege-edited and lifetime-violating shapes against one service and record each acceptance verdict.
4. **Prove token type confusion** - Swap token kinds across paths and swap nested token orderings, one swap per request.
5. **Verify enforcement** - Tie each acceptance verdict to the exact context crossed and declare the missing binding only on a reproducible acceptance proof.

## False Positives

- Rejection of every cross-context replay with a consistent unauthorized verdict signals intact issuer, audience, and type enforcement.
- Server-side re-derivation of privilege that ignores presented privilege edits signals correct authorization rather than a missed confusion.
- Short lifetimes with rotation and revocation on session end limit replay value without proving context resistance.
- Token kind separation where one kind is never accepted at another kind path signals correct scoping rather than a missed swap.

## Pro Tips

- Build the full matrix before replaying so no cross-context cell goes untested.
- Isolate one context change per request so each acceptance verdict maps to exactly one binding.
- Bracket lifetime tolerance from both sides because skew windows admit tokens just outside validity.
- Prefer minimal acceptance proofs that show one validly signed token verifying in a foreign context.
- Retest every acceptance path separately because context enforcement commonly differs between edge, service, worker, and alternate channel handlers.

## Summary

Context validation must bind each token to its issuer, audience, privilege source, lifetime, and token kind on every acceptance path.
Any gap in that binding admits cross-context acceptance.
