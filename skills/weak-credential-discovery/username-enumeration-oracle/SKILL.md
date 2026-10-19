---
name: username-enumeration-oracle
description: Enumerate valid identities through login response deltas when error wording diverges, when timing gaps appear, and when status plus redirect behavior splits across candidates.
metadata:
  version: 1.0.0
---

# Username Enumeration Oracle

Login acceptors sometimes answer differently for a known identity than for an unknown one even when the secret is wrong in both cases.
This variant converts those differences into a valid-identity list through one same-secret compare-two-responses procedure with timing normalization.
The oracle goal is a confirmed identity set that later feeds replay without wasting attempts on nonexistent accounts.

## Attack Surface

- **Applicability**: centers on a login acceptor that emits a per-identity differential signal under a fixed wrong secret.
- **Signal dimensions**: the signal lives in message wording or response timing or status code or redirect behavior across candidate identities.
- **Delta-only verdict**: neither single response alone concludes validity, because the verdict emerges only from the delta between two responses.
- **Out-of-scope siblings**: linked source plus guessed artifacts plus direct replay success plus issued tokens ride outside this variant and belong to its siblings.

## Reconnaissance

- **Reconnaissance scope**: reconnaissance inventories the acceptor plus its observable dimensions before any comparison begins.
- **Acceptor location**: locate every login acceptor reachable without authentication and record its carrier plus its submission shape with placeholders.
- **Dimension recording**: record which response dimensions are observable per attempt, namely message wording plus timing plus status plus redirect behavior.
- **Candidate enumeration**: enumerate candidate identity values only as abstract placeholders, because concrete literals are runtime knowledge-base facts.

## Detection Channels

- **Listening scope**: the oracle listens to cross-response deltas only.
- **Delta definition**: delta in this variant means the difference between two responses submitted under one fixed secret.
- **Message-wording delta across identities**: signals a distinguishing oracle.
- **Timing gap across identities after normalization**: signals a distinguishing oracle.
- **Status-code delta across identities**: signals a distinguishing oracle.
- **Redirect-behavior delta across identities**: signals a distinguishing oracle.

## Adversarial Capabilities

- **Preconditions**: the oracle presupposes anonymous submit plus repeated measurement plus pairwise comparison, and it consumes all three.
- **Fixed-secret submission**: submit one fixed wrong secret across candidate identities using ordinary submit primitives.
- **No prior session**: hold no authenticated session, because the procedure runs entirely before authentication.
- **Dimension measurement**: measure message plus timing plus status plus redirect behavior per attempt with repeated samples for timing stability.
- **Pairwise comparison**: compare responses pairwise under the same secret so the identity value is the only varying input.

## Trust Assumptions

- **The agreement**: the application agrees that served content carries no reusable secret, deployable artifacts stay unreachable over guessable paths, published default pairs grant no access, login responses stay uniform across identities, and issued tokens disclose no authority, while the request uses only ordinary fetch plus submit primitives with unauthenticated or session-held capability, the server exposes only non-sensitive renderings plus uniform outcomes, and a reusable credential or an identity oracle or an authority claim leaks only through an explicit grant, never through side content or response shape.
- **The failing clause**: this variant fails the uniformity clause because login responses diverge across identities under one fixed secret.

## Key Vulnerabilities

### Same-Secret Compare-Two-Responses

- **Same-secret comparison**: submit one fixed wrong secret across candidate identities and decide validity only from the delta between two responses.
- **Secret constancy**: keep the secret constant while varying the identity value, because any secret change would confound the comparison.
- **Ownership**: the parent names this two-response comparison in exactly one step, and no single-response fetch step covers it, so this variant owns the oracle procedure.

### Timing Normalization

- **Sample repetition**: repeat each identity sample until timing stabilizes and normalize against network jitter before reading a timing verdict.
- **Gap reading**: treat a persistent gap as a positive signal and treat uniform randomness as inconclusive rather than negative.
- **Uniformity recording**: record uniformity plus lockout state as a secondary check inside each comparison, because throttle handling rides as an aspect rather than its own bypass procedure.

## Chaining Attacks

- **Forward chaining**: the oracle chains forward into replay because an identity list without a follow-on guess is only discovery.
- **Replay handoff**: hand each confirmed identity value to default-credential replay for pair completion.
- **Rate-aware handoff**: hand each confirmed set to rate-aware follow-on testing where throttle state shapes pacing.
- **Token-validation naming**: treat token claim validation through authentication-jwt by naming it instead of restating its steps.

## Testing Methodology

The oracle runs baseline calibration first and identity verdicts last, because deltas need a stable reference to read against.
1. **Inventory the acceptor** - list every login acceptor with its observable dimensions plus its anonymous baseline, and the step completes when every acceptor carries a recorded baseline.
2. **Calibrate timing** - submit repeated fixed-secret attempts and record the timing spread, and the step completes when every acceptor carries a stable timing baseline with its sample count.
3. **Execute same-secret comparison** - submit one fixed wrong secret across every candidate identity and record message plus timing plus status plus redirect behavior per attempt, and the step completes when every candidate carries a full observation record.
4. **Read the deltas** - compare responses pairwise and assign a valid or unknown or inconclusive verdict per identity, and the step completes when every candidate carries exactly one verdict with its supporting delta.
5. **Confirm stability** - re-probe each positive with repeated samples, and the step completes when every positive shows a persistent delta or is downgraded to inconclusive.

## False Positives

- **No identity signal**: stop when the delta shows no identity signal, because a uniform acceptor offers no oracle.
- **Generic errors**: stay identical across all candidates, confirmed by delta absence in every dimension.
- **Timing jitter**: mistaken for a signal, confirmed when gaps vanish under repeated sampling.
- **Throttle or block responses**: split by attempt order rather than identity, confirmed when ordering not identity predicts the delta.

## Pro Tips

- **Oracle economics**: the oracle rewards fixed secrets plus repeated samples plus pairwise reading.
- **Fixed secret**: prefer one fixed wrong secret across all candidates, so identity stays the only varying input.
- **Repeated sampling**: favor repeated timing samples with normalization before reading any timing verdict.
- **Inconclusive handling**: treat inconclusive identities as pending rather than negative and re-probe them after calibration.
- **Attempt recording**: record every attempt with its observable dimensions so each verdict traces to a pairwise delta.

## Summary

A login acceptor that answers differently across identities already surrendered its user list before any secret guess.
The oracle submits one fixed wrong secret everywhere, normalizes timing, and reads message plus status plus redirect deltas into one verdict per identity before any replay begins.
