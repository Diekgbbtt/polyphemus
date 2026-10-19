---
name: jwt-key-resolution
description: Seize key selection through selector injection, remote key hosting, inline key embedding, or rotation and fallback abuse. Use when key selectors reach the verifier, when remote key references are honored, when inline keys are suspected, or when rotation windows look exploitable.
metadata:
  version: 1.0.0
---

# JWT Key Resolution

Seize the key selection step so verification resolves to an attacker-chosen key.
This variant breaks the key source binding while the signature routine, the claim context, and the protocol run stay unchanged.

## Attack Surface

- Token-authenticated request paths where the verifier resolves its key from presented header material.
- Key distribution infrastructure with caching behavior, rollover windows, and fallback routines on unknown selectors.
- Verification parties that share secrets across environments or tenants or that resolve keys per tenant.

## Reconnaissance

- Inventory every verification party and record which key source each one trusts and whether that source is pinned.
- Capture tokens for at least two roles and record the key selector posture, the remote key reference posture, and the inline key posture per token.
- Map the key distribution source and observe caching lifetime, rollover behavior, and the response to an unknown selector.
- Probe whether a selector pointing outside the key store, a remote reference pointing at an observed endpoint, or an embedded inline key reaches the verifier intact.

## Detection Channels

- Acceptance of a token minted under an attacker-resolved key where the authorized response matches the legitimate token response.
- Server-side fetch evidence such as timing delay, fetch error text, or correlation between hosting a remote key document and a changed verdict.
- Fallback behavior signals where an unknown or absent selector still verifies instead of rejecting.
- Rotation window signals where a retired key verifies again during rollover but rejects outside it.

## Adversarial Capabilities

- Possession of at least one legitimate token whose key selector and key reference posture are readable.
- Ability to host an observable remote key document and correlate its fetch with the verification verdict.
- Ability to re-present selector, reference, and inline key shapes to every acceptance path.
- Ability to time requests against rollover windows and to replay retired key shapes on demand.

## Trust Assumptions

- At the moment a protected feature executes, the server assumes each presented token is bound to one issuer, one audience, one verification key, one signature algorithm, and one client context, and that only the expected issuer minted it for the expected audience under the expected key and algorithm within its validity window.
- The clause binding verification to the expected key source fails, so an attacker-selected key still verifies.

## Key Vulnerabilities

- Selector injection steers key lookup outside the intended store or into attacker-influenced lookup logic: a record-store query, a command sink, or a fetch sink, each a separate family to probe.
- Remote key reference abuse hosts the verification key material at an observed endpoint that the server fetches and trusts without pinning.
- Inline key embedding supplies the verification key inside the token header where the verifier prefers it over its configured keys.
- Cache and fallback flaws accept retired keys during rollover, accept any matching key shape without selector pinning, or succeed verification when the selector is unknown or absent.

## Advanced Techniques

- Treat the remote key document as infrastructure and observe the fetch before minting under the fetched key.
- Treat rollover as a timing oracle and replay retired key shapes across the rotation boundary to bracket the acceptance window.
- Treat unknown selector behavior as a behavioral oracle and probe absent, malformed, and unlisted selectors separately.
- Test key reuse across environments and tenants because shared secrets collapse one seized key into many acceptance paths.

## Bypass Techniques

- Defeat selector pinning by presenting directory escape shapes, injection shapes, and file reference shapes in the selector field, one family per request.
- Defeat remote reference pinning by presenting a reference to the observed endpoint and minting under the hosted key.
- Defeat inline key rejection by presenting an embedded key structure in the header and signing with its private half.
- Defeat rotation and fallback controls by replaying retired keys inside the window and by presenting unknown selectors to trigger the fallback routine.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Name token theft skills at the exfiltration step and start here once a capturable token is held.
- Name request forgery skills at the fetch step where remote key resolution reaches internal hosts.
- Hand signature-only findings to the signature forgery variant once key selection is pinned and only the algorithm binding is suspect.
- Hand cross-context findings to the claims confusion variant once the resolved key is legitimate and only the context binding is suspect.

## Testing Methodology

1. **Record the legitimate key regime** - Capture one token per kind and note the selector value posture, the reference posture, and the configured key source.
2. **Seize through selector injection** - Present selector shapes that escape the key store or steer lookup logic, one shape family per request.
3. **Seize through remote hosting** - Host an observable key document, present its reference, confirm the server-side fetch, then present a token minted under the hosted key.
4. **Seize through inline embedding** - Present a token shape carrying an embedded key structure signed with its private half.
5. **Seize through timing and fallback** - Replay retired key shapes across the rollover boundary and present unknown and absent selector shapes to map the fallback routine.
6. **Verify enforcement** - Tie each acceptance verdict to the exact key shape presented and declare the missing binding only on a reproducible acceptance proof.

## False Positives

- Rejection of every attacker-resolved key shape with a consistent unauthorized verdict signals intact key pinning.
- Remote reference fetching constrained to a pinned allowlist with validated transport signals correct distribution rather than a missed seizure.
- Short-lived keys with rotation and revocation on session end limit replay value without proving resolution resistance.
- Selector-scoped error text that rejects unknown selectors without verifying signals correct fallback rather than a bypass.

## Pro Tips

- Confirm the fetch before minting so a rejection is attributed to trust rather than to reachability.
- Isolate one key shape per request so each acceptance verdict maps to exactly one resolution path.
- Bracket rollover windows from both sides because retired keys verify only inside the window.
- Prefer minimal acceptance proofs that show a token minted under an attacker-resolved key verifying on the target path.
- Retest every acceptance path separately because key pinning commonly differs between edge, service, worker, and alternate channel handlers.

## Summary

Key resolution must pin the key source, constrain remote references, reject inline keys, and close rotation and fallback gaps on every acceptance path.
Any gap in that binding admits an attacker-selected key.
