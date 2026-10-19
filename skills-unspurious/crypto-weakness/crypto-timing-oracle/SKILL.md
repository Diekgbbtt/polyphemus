---
name: crypto-timing-oracle
description: Extract tokens through comparison timing when verification leaks prefix correctness, iterate candidate prefixes against a calibrated baseline, and confirm each position by statistical separation.
metadata:
  version: 1.0.0
---

# Timing Oracle Extraction

Token services fail when a comparison reports mismatch speed differently per correct prefix.
This variant extracts the token by establishing a timing baseline plus iterating prefix candidates with repeated samples plus confirming each position by statistical separation.
The extraction goal is the honest token recovered character by character without predicting issuance or recovering any signing secret.

## Attack Surface

Applicability centers on a token verification flow that compares a presented token against a stored reference in non-constant time.
The comparison exits early or branches observably on the first mismatching position while the requester can measure response timing.
The accepting side exposes per-attempt timing alongside its acceptance verdict through a directly reachable verification flow.
Prefix alphabet and token length bound the search space while the measurement procedure stays unchanged.

## Reconnaissance

Decode and inspect every captured token shape before any measurement attempt.
Record token length plus alphabet plus verification flow plus measurable timing surface per flow.
Inventory every verification flow that compares presented tokens against stored references.
The step completes when each verification flow carries a recorded timing surface and each token shape carries a length and alphabet bound.

## Detection Channels

Extraction listens to timing plus verdict signals, so only the entries below are live here.
- Timing baseline over known-invalid tokens showing stable reference behaviour.
- Timing differential of a correct prefix over baseline with statistical separation.
- Acceptance verdict on the fully extracted token confirming the recovered value.
- Flat timing distribution across all prefixes signalling constant-time comparison.
- Error-class stability showing timing differences are comparison-driven rather than transport-driven.

## Adversarial Capabilities

Extraction presupposes repeated timed-request position plus statistical computation, and it consumes both.
- Issue repeated verification requests carrying chosen prefix candidates.
- Measure per-request response timing across enough samples to average transport noise.
- Hold a stable network position so sample distributions stay comparable across candidates.
- Compute baseline-relative separation per prefix hypothesis from collected samples.
- Submit the fully extracted token at the accepting endpoint and read its acceptance verdict.

## Trust Assumptions

The token service trusts each issued token to be unpredictable and each signature to bind claims to a strong secret under a pinned algorithm and each comparison to leak no timing.
The agreement covers the verification data contract plus the comparison state at check time plus the equality primitive used in the request plus the server exposing only acceptance verdicts plus the token-value sensitivity that leaks when timing varies.
This variant breaks the timing-independence clause because the comparison exits early on mismatch, so repeated measurement extracts the token prefix by prefix.

## Key Vulnerabilities

### Baseline-Calibrated Timing Measurement

Establish a timing baseline over known-invalid tokens with repeated samples before testing any candidate prefix.
Treat the baseline as the reference distribution that every prefix hypothesis must separate from.
The parent validity steps cannot describe repeated measurement with baseline statistics, so this variant owns the calibrate-plus-compare procedure.

### Iterative Prefix Extraction

Iterate prefix candidates position by position, collecting repeated timing samples per candidate and promoting only the candidate with stable separation.
Treat a consistent timing elevation as a positive and treat uniform randomness as inconclusive rather than negative.
The step completes when every position carries a confirmed prefix value with its separation evidence.

### Statistical Separation Confirmation

Confirm each prefix hypothesis by separation of its sample distribution from the baseline distribution rather than by any single fast or slow sample.
Repeat each candidate until the separation stabilises because a single sample cannot separate comparison cost from network jitter.
The step completes when each promoted prefix carries a recorded sample set and separation margin.

## Advanced Techniques

Advance extraction by hardening measurement while keeping the same calibrate-plus-extract procedure.
- Interleave baseline and candidate samples so drift cannot masquerade as separation.
- Randomise candidate order within each round so ordering effects stay out of the distributions.
- Tighten request budgets so transport variance shrinks around comparison cost.
- Treat sample depth and separation ratio as measurement aspects that never change the extraction step.

## Bypass Techniques

Extraction defeats the constant-time-comparison control by showing timing still separates prefixes.
- Demonstrate stable prefix separation against a comparison that promises position independence.
- Demonstrate repeatable elevation across interleaved rounds against a deployment that promises jitter cover.
- Demonstrate full-token recovery against a store that promises no oracle beyond accept-or-reject.
- Treat flat distributions across all prefixes and rounds as a stop signal rather than a bypass.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Extraction chains forward into use because a recovered token without presentation is only a string.
- Present the extracted token at the verification or session acceptance flow to take over the bound account.
- Feed the extracted token into prediction or forgery follow-ups where those variants own the next step.
- Hand the resulting session to authorisation consumers for boundary testing rather than restating their steps.
- Treat acceptance-verdict behaviour owned by session-management checks as the downstream consumer.

## Testing Methodology

Extraction measures before concluding, because uncalibrated timing is only noise.
1. **Map verification flows** - record token shape plus length plus alphabet plus timing surface per flow, and the step completes when no verification flow lacks a recorded surface.
2. **Extract the token through comparison timing** - establish a timing baseline plus iterate prefix candidates with repeated samples plus confirm each position by statistical separation, and the step completes when every position carries a confirmed prefix value or an inconclusive verdict with its samples.
3. **Confirm exploitability** - present the fully extracted token at the accepting endpoint, and the step completes when the extracted token carries a recorded acceptance verdict.
4. **Rule out constant-time comparison** - compare prefix distributions against the baseline flatness bound, and the step completes when the timing-independence hypothesis is confirmed or refuted with distributions.

## False Positives

Stop when the evidence shows timing independence, because further sampling is only noise.
- Flat timing distributions across every prefix candidate and every round.
- Separation that vanishes under interleaved sampling, signalling drift rather than comparison cost.
- Error-class differences tracking the timing gaps, signalling transport behaviour rather than comparison behaviour.
- Rate-limit or queueing artefacts dominating per-request timing across all candidates.

## Pro Tips

Extraction rewards sample discipline plus quiet patience.
1. Prefer interleaved baseline rounds throughout so drift shows itself before it misleads.
2. Favor tight request budgets so comparison cost stands out from transport variance.
3. Repeat each candidate until separation stabilises and log every sample behind its prefix.
4. Promote only stable separation and record the rest as inconclusive rather than negative.
5. Stop sampling once distributions stay flat across full rounds and record the negative.

## Summary

A comparison that exits early on mismatch turns verification into a prefix oracle.
Extraction calibrates a baseline, iterates each position with repeated samples, confirms by statistical separation, and stops on flat distributions.
