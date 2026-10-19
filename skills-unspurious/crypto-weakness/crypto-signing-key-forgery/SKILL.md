---
name: crypto-signing-key-forgery
description: Forge signed tokens under a recovered secret when keyed checksums use guessable keys, strip signature validation when unchecked algorithms accept keyless tokens, and mint elevated claims for acceptance testing.
metadata:
  version: 1.0.0
---

# Signing-Key Forgery

Token services fail when a signature can be satisfied without holding a strong secret.
This variant breaks signing trust by recovering the signing secret offline plus removing the algorithm where accepted plus minting elevated claims under the recovered or empty key.
The forgery goal is an accepted token carrying attacker-chosen claims without ever predicting the honest issuance sequence.

## Attack Surface

Applicability centers on a tokenised session or recovery mechanism whose integrity depends on a keyed checksum or a cookie-signing secret or an accepted algorithm choice.
The mechanism mints structured tokens whose claims the accepting side trusts once the signature verifies.
The accepting side treats a correctly signed or an algorithm-stripped token as proof of the claims it carries.
Token serialisation selects which minting shape the test produces while the recovery procedure stays unchanged.

## Reconnaissance

Decode and inspect every captured token before any recovery attempt.
Record structure plus encoding plus claim set plus signature segment plus algorithm marker per token.
Inventory every issuance flow and every acceptance flow that mints or checks signed tokens.
The step completes when each captured token carries a recorded structure and each flow carries an identified issuance and acceptance pair.

## Detection Channels

Forgery listens to signature plus acceptance signals, so only the entries below are live here.
- Signature segment present on structured tokens marking the keyed-checksum binding.
- Algorithm marker showing a symmetric scheme or an unchecked acceptance option.
- Local re-verification success confirming a recovered secret without server contact.
- Accepted minted token carrying elevated claims confirming signature trust failure.
- Rejected stripped-algorithm token closing the removal hypothesis for that flow.

## Adversarial Capabilities

Forgery presupposes token capture plus offline computation plus acceptance submission, and it consumes all three.
- Capture signed tokens with visible signature segments and algorithm markers.
- Run offline secret search with local re-verification that never touches the server per guess.
- Strip the signature segment and mark the token as keyless where the flow may accept it.
- Mint tokens carrying elevated claim sets under a recovered or empty key.
- Submit minted candidates at the accepting endpoint and read each acceptance verdict.

## Trust Assumptions

The token service trusts each issued token to be unpredictable and each signature to bind claims to a strong secret under a pinned algorithm and each comparison to leak no timing.
The agreement covers the issuance-to-acceptance data contract plus the token state at mint and at check plus the keyed-checksum primitive used in the request plus the server exposing only acceptance verdicts plus the privilege sensitivity that leaks when forged claims are accepted.
This variant breaks the signing-trust clause because the signature verifies under a guessable secret or an unpinned algorithm, so recovery or removal yields a minted token.

## Key Vulnerabilities

### Offline Secret Search With Local Re-Verification

Search the secret space offline and confirm each guess by recomputing the keyed checksum locally against a captured token.
Treat server contact during search as wasted signal because local verification already decides each guess.
The parent minting step alone cannot describe a recovery loop with a local verify oracle, so this variant owns the search-plus-verify procedure.

### Algorithm Removal Acceptance

Strip the signature segment and mark the token as keyless, then test whether the accepting side still honours the claims.
Treat removal as validation-layer bypass with no secret recovery rather than as a weak-secret case.
The parent recover-then-mint description cannot cover acceptance without a key, so this variant owns the removal procedure.

### Elevated Claim Minting

Mint tokens carrying elevated role or identity markers under the recovered or empty key and test each minted token at the accepting endpoint.
Vary claim choice inside the same minting procedure rather than as separate attacks.
The step completes when every minted token carries an acceptance or rejection verdict.

## Advanced Techniques

Advance forgery by widening secret and serialisation coverage while keeping the same search-plus-mint procedure.
- Seed secret guesses from deployment-default and application-derived string families.
- Swap serialisation between cookie-session shapes and structured-token shapes inside one minting loop.
- Pair each recovered secret with a stripped-algorithm probe to expose double failure.
- Treat claim choice as a payload aspect that never changes the minting step.

## Bypass Techniques

Forgery defeats the strong-secret plus algorithm-pinning control by showing either half was never enforced.
- Demonstrate offline secret recovery against a store that promises an unguessable key.
- Demonstrate deployment-default secret success against a rotation policy that promises uniqueness.
- Demonstrate keyless acceptance against a verifier that promises rejection of unpinned algorithms.
- Treat rejection of both recovered-secret and keyless tokens as a stop signal rather than a bypass.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Forgery chains forward into privilege because a minted token without a follow-up use is only evidence.
- Present the minted token at the session acceptance flow to take over the claimed account.
- Escalate through elevated role markers carried inside the minted claim set.
- Hand the resulting session to authorisation consumers for boundary testing rather than restating their steps.
- Treat acceptance-verdict behaviour owned by session-management checks as the downstream consumer.

## Testing Methodology

Forgery breaks signing trust before minting, because minting without a key basis is only guessing.
1. **Decode captured tokens** - record structure plus claims plus signature segment plus algorithm marker per token, and the step completes when no captured token lacks a recorded structure.
2. **Break signing trust** - brute-force the keyed-checksum or cookie secret offline with local re-verification plus strip the algorithm to keyless where accepted plus mint elevated claims under the recovered or empty key, and the step completes when every secret hypothesis and every removal probe and every minted token carries a confirmed or refuted verdict.
3. **Confirm exploitability** - present each accepted minted token as the claimed identity or role, and the step completes when every accepted token carries a recorded ownership outcome.
4. **Rule out strong signing** - compare secret-search failure plus keyless rejection against the strong-secret plus pinning bound, and the step completes when the signing-strength hypothesis is confirmed or refuted with verdicts.

## False Positives

Stop when the evidence shows strong signing, because further search is only noise.
- Rejected verdicts across minted tokens under every recovered-secret hypothesis.
- Rejected verdicts across keyless tokens at every acceptance flow.
- Local re-verification failure across the full secret-search space.
- Pinned algorithm enforcement with no unchecked acceptance path.

## Pro Tips

Forgery rewards offline patience plus minting discipline.
1. Prefer local re-verification for the whole search so the server sees only final minted candidates.
2. Favor keyless probes early because one acceptance ends the need for secret search.
3. Seed guesses from deployment-default families before widening the space.
4. Log each minted token behind its key basis so recovery versus removal stays separable.
5. Stop minting once both secret and removal hypotheses are refuted and record the negative.

## Summary

A signature that verifies under a guessable secret or an unpinned algorithm is a trust problem rather than a prediction problem.
Forgery recovers the secret offline or removes the algorithm, mints elevated claims under the resulting key basis, and stops on local-verify failure plus keyless rejection.
