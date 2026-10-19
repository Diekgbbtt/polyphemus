---
name: jwt-signature-forgery
description: Forge token signatures through algorithm confusion, unsigned acceptance, lax verifier strictness, or recovered weak secret. Use when algorithm pinning is unclear, when unsigned tokens are suspected, when verifier strictness is unproven, or when a weak signing secret is suspected.
metadata:
  version: 1.0.0
---

# JWT Signature Forgery

Forge signature validity so a token the server never minted still verifies.
This variant breaks the signature algorithm binding while the key source, the claim context, and the protocol run stay unchanged.

## Attack Surface

- **Token-authenticated request paths**: acceptance turns only on signature validity.
- **Verification parties**: each pins its own algorithm policy, including edge handlers, internal services, background consumers, and alternate channel handlers.
- **Token kinds**: acceptance paths share one verifier configuration across signing regimes.

## Reconnaissance

- **Verification-party inventory**: inventory every verification party and record which algorithm policy each one enforces.
- **Token capture**: capture tokens for at least two roles and record the header structure, the claim set, and the signature posture per token kind.
- **Discovery and key mapping**: map the discovery metadata and the key distribution source so the legitimate signing regime is known before mutation starts.
- **Mutation-reach probe**: probe whether an unsigned token shape, a confused algorithm shape, or a non-canonical signature shape reaches the verifier intact.

## Detection Channels

- **Forged token acceptance**: the mutated or stripped signature returns the same authorized response as the legitimate token.
- **Acceptance verdict difference**: the legitimate token and the forged shape diverge under otherwise identical requests.
- **Verifier error text**: distinguishes rejected signatures from accepted ones, which orients the next mutation.

## Adversarial Capabilities

- **Legitimate token possession**: at least one legitimate token has a readable header, claim set, and signature structure.
- **Shape replay**: re-present mutated token shapes to every acceptance path, including alternate channels and background consumers.
- **Offline secret recovery**: run offline secret recovery against a captured token when a weak shared secret is suspected.
- **Verdict comparison**: compare acceptance verdicts across roles without holding any insider key material.

## Trust Assumptions

- **The agreement**: at the moment a protected feature executes, the server assumes each presented token is bound to one issuer, one audience, one verification key, one signature algorithm, and one client context, and that only the expected issuer minted it for the expected audience under the expected key and algorithm within its validity window.
- **The failing clause**: the clause binding the token to its signature algorithm and signing key fails, so a forged or stripped signature still verifies.

## Key Vulnerabilities

- **Algorithm confusion**: accepts a symmetric verification path for an asymmetrically issued token, so the public verification material doubles as the signing secret.
- **Unsigned acceptance**: admits a token shape that declares no signature and carries no signature segment.
- **Lax verifier strictness**: accepts non-canonical or malleated signature encodings that a strict verifier would reject.
- **Weak shared secrets**: let offline recovery mint arbitrarily privileged tokens once the secret is found.

## Advanced Techniques

- **Confusion-first ordering**: favor confusion shapes first where the verifier selects its verification routine from the presented algorithm identifier.
- **Two-token key recovery**: recover the asymmetric public key from two captured tokens where no key endpoint is exposed, then run the confusion shape against the recovered key, so the acquisition step never depends on a published key source.
- **Encoding variation**: vary the signature encoding shape where the verifier is strict on the algorithm but lax on canonical form.
- **Secret capability**: carry the recovered secret forward as a minting capability and re-derive authorization from each freshly minted token.
- **Path-by-path test**: test every acceptance path separately because verification strictness commonly differs between edge, service, worker, and alternate channel handlers.

## Bypass Techniques

- **Algorithm-pinning bypass**: defeat algorithm pinning by presenting each neighboring algorithm shape and recording which one the verifier executes instead of rejects.
- **Unsigned-rejection bypass**: defeat unsigned rejection by presenting the unsigned shape with the signature segment removed and the algorithm identifier declaring no signature, including case-variant algorithm identifiers and signature-segment variants beside it.
- **Strict-verification bypass**: defeat strict verification by presenting encoding edge shapes such as unencoded payload forms and nested token orderings that mishandle the verification path.
- **Secret-strength bypass**: defeat secret strength by recovering the weak secret offline and then minting under the legitimate algorithm.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Token theft handoff**: name token theft skills at the exfiltration step and start here once a capturable token is held.
- **Key resolution handoff**: hand key control findings to the key resolution variant once the verifier follows an attacker-selected key instead of a forged signature.
- **Claims confusion handoff**: hand cross-context acceptance findings to the claims confusion variant once the signature verifies and only the context binding is suspect.
- **Flow lifecycle handoff**: hand multi-step flow findings to the flow lifecycle variant once forgery fails and the protocol run itself is suspect.

## Testing Methodology

1. **Record the legitimate regime** - Capture one token per kind and note the algorithm identifier, the key selector posture, and the signature presence.
2. **Forge through confusion** - Present a token shape that swaps the asymmetric algorithm identifier for its symmetric neighbor while signing with the exposed verification material.
3. **Forge through stripping** - Present a token shape that declares no signature and drops the signature segment entirely.
4. **Forge through strictness** - Present non-canonical signature encodings and edge verification path shapes, one shape per request.
5. **Forge through recovery** - Recover a suspected weak shared secret offline, mint a privileged token under the legitimate algorithm, and present it.
6. **Verify enforcement** - Tie each acceptance verdict to the exact shape presented and declare the missing binding only on a reproducible acceptance proof.

## False Positives

- **Consistent forgery rejection**: rejection of every forged shape with a consistent unauthorized verdict signals intact algorithm pinning and unsigned rejection.
- **Genuine-key acceptance**: acceptance that depends on holding the genuine signing key signals a correct verifier rather than a forgery.
- **Short-lived tokens**: short-lived tokens with rotation and revocation on session end limit replay value without proving forgery resistance.
- **Token kind separation**: one kind is never accepted at another kind path, which signals correct scoping rather than a missed forgery.

## Pro Tips

- **Confusion-first lead**: lead with confusion and stripping shapes only while algorithm pinning is unproven, then pivot to strictness and recovery.
- **One mutation per request**: isolate one mutation per request so each acceptance verdict maps to exactly one shape.
- **Verdict diff**: log and diff the verifier verdict across every acceptance path because one lax path defeats an otherwise strict fleet.
- **Minimal proof**: prefer minimal acceptance proofs that show a never-minted privilege verifying on the target path.
- **Secret capability reuse**: treat recovered secrets as minting capabilities and retest authorization from the freshly minted token.

## Summary

Signature verification must pin the algorithm, reject unsigned shapes, enforce canonical verification, and resist weak secrets on every acceptance path.
Any gap in that binding admits a forged token.
