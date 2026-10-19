---
name: crypto-predictable-token
description: Predict recovery tokens from sequence structure when tokens embed counters, re-derive tokens from known identifiers when tokens hash guessable input, and confirm low-entropy candidates at the accepting endpoint, including a space small enough to enumerate inside the validity window.
metadata:
  version: 1.0.0
---

# Predictable Token Recovery

Token services fail when a session or recovery token can be predicted instead of guessed.
This variant proves predictability by collecting issued tokens plus re-deriving candidates from known identifiers plus testing each prediction at the accepting endpoint.
The prediction goal is a valid token that authenticates or authorises without any secret recovery or side-channel measurement.

## Attack Surface

- **Applicability**: centers on a tokenised session or recovery mechanism that issues bearer tokens for later acceptance.
- **Token minting**: mints tokens from guessable input or a weak generator or a sequential counter or an embedded timestamp or a short sub-bound value or a value whose unpredictability rests on an encoding or mixing step rather than on randomness.
- **Acceptance trust**: treats presentation of a matching token as proof of ownership of the associated account or action.
- **Validity window**: bounds how long a token is accepted, and a small enough space can be enumerated inside that window even when the token is not derivable.
- **Token kind**: selects which issuance and acceptance flow the test drives while the recovery procedure stays unchanged.

## Reconnaissance

- **Token inspection**: decode and inspect every captured token before any prediction attempt.
- **Structure recording**: record structure plus encoding plus embedded claims plus length plus alphabet per token.
- **Entropy measurement**: measure the effective entropy of the captured run and compare it against the validity window, because an encoding or mixing step never raises the effective bits.
- **Window recording**: record the validity window between issuance and acceptance, because a small space is only brute-forceable inside it.
- **Flow inventory**: inventory every issuance flow and every acceptance flow that mints or checks such a token.
- **Completion criterion**: the step completes when each captured token carries a recorded structure and each flow carries an identified issuance and acceptance pair.

## Detection Channels

- **Live channels**: prediction listens to inspection plus acceptance signals, so only the entries below are live here.
- **Decoded predictable fields**: showing embedded counters or timestamps or identifiers.
- **Duplicate tokens**: across repeated issuance showing absent randomness.
- **Short token length**: below the strong-randomness bound.
- **Fixed-length restricted-alphabet structure**: showing a digest-of-known-input shape.
- **Accepted predicted token**: confirming a valid session or recovery action.
- **Rejected candidate verdict per derivation**: closing that derivation hypothesis.
- **Effective bits below the bound**: an entropy estimate under the strong-randomness bound after decoding, which marks encoding rather than randomness.
- **Space exhausted inside the window**: an enumerated candidate accepted within the validity window, which confirms the space was small enough to search.

## Adversarial Capabilities

- **Prerequisites**: prediction presupposes multi-token collection plus known-identifier knowledge, and it consumes both.
- **Multi-token collection**: collect multiple tokens for one or more accounts through repeated issuance.
- **Known-identifier knowledge**: know victim identifiers usable as known plaintext for re-derivation.
- **Structure decoding**: decode token structure to expose embedded sequence or timestamp or identifier material.
- **Candidate submission**: submit predicted candidates at the accepting endpoint and read each acceptance verdict.
- **Lookup querying**: query lookup sources for digest-to-plaintext mappings where local re-derivation stalls.

## Trust Assumptions

- **The agreement**: the token service trusts each issued token to be unpredictable and each signature to bind claims to a strong secret under a pinned algorithm and each comparison to leak no timing. The agreement covers the issuance-to-acceptance data contract plus the token state at mint and at check plus the random-generation primitive used in the request plus the server exposing only acceptance verdicts plus the account-control sensitivity that leaks when a token is accepted.
- **The failing clause**: this variant breaks the unpredictability clause because the token derives from guessable input or a weak generator, or because its effective bits fall short of the bound and the searchable space fits inside the validity window, so re-derivation or enumeration yields a valid token.

## Key Vulnerabilities

### Entropy Collection With Sequence Analysis

- **Token-run collection**: collect a run of tokens and judge lengths plus uniqueness plus ordering before any derivation attempt.
- **Sequence evidence**: treat clustering or monotonic growth or timestamp-shaped fields as prediction evidence rather than noise.
- **Variant scope**: the parent collection step alone cannot describe deterministic re-derivation, so this variant owns the collect-plus-predict procedure.

### Deterministic Re-Derivation Over Known Identifiers

- **Recompute-and-test**: recompute the digest over each known identifier under each candidate derivation wording and test every recomputed value at the accepting endpoint.
- **Derivation wording**: vary case folding and digest choice inside the same recompute-and-test procedure rather than as separate attacks.
- **Completion criterion**: the step completes when every candidate derivation carries an acceptance or rejection verdict.

### Lookup-Assisted Recovery

- **Lookup submission**: submit unreversed digests to a digest-to-plaintext lookup source and test each returned plaintext mapping at the accepting endpoint.
- **Lookup hit**: treat a lookup hit as a hypothesis that still needs an acceptance verdict rather than as proof.
- **Completion criterion**: the step completes when each lookup-sourced candidate carries an acceptance or rejection verdict.

### Window-Bounded Brute Force

- **Searchable space**: where the effective bits fall short of the bound, enumerate the candidate space instead of deriving it, and stop at the first acceptance.
- **Window discipline**: measure the validity window before spending attempts, because an enumeration that outlives the window proves nothing, and start with the smallest candidate family.
- **Source rotation**: where a per-source limit throttles the enumeration, name the defence-bypass family at its throttle-evasion step rather than restating the rotation mechanics here.

## Advanced Techniques

- **Advancement scope**: advance prediction by widening derivation wording while keeping the same recompute-and-test procedure.
- **Candidate matrix**: fold identifier case and swap digest choice across fast unsalted digests inside one candidate matrix.
- **Issuance-order correlation**: correlate issuance order with acceptance order to expose counter-driven minting.
- **Sequence separation**: separate per-account sequences from global sequences by collecting under two identities.
- **Short-value searching**: treat short sub-bound values as exhaustively searchable only inside the acceptance verdict loop.
- **Entropy adjudication**: compute the effective bits from the captured run and compare them against the strong-randomness bound, because encoding and mixing are presentation rather than entropy.
- **Window estimate**: correlate token structure with issuance order and time to estimate the searchable space, then compare it against the validity window before spending attempts.

## Bypass Techniques

- **Defeated control**: prediction defeats the strong-random-generation control by showing its output was never random.
- **Duplicate issuance**: demonstrate duplicate or sequential issuance against a generator that promises uniqueness.
- **Identifier-derived digests**: demonstrate identifier-derived digests against a store that promises unguessability.
- **Short-value acceptance**: demonstrate short-value acceptance against a policy that promises a sufficient entropy bound.
- **Encoding versus randomness**: demonstrate that a mixing step adds no effective bits, so an encoded token falls to enumeration where a random one does not.
- **Stop signal**: treat full uniqueness at sufficient length as a stop signal rather than a bypass.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chain**: prediction chains forward into ownership because a predicted token without a follow-up use is only evidence.
- **Predicted-token presentation**: present the predicted token at the session or recovery acceptance flow to take over the bound account.
- **Claim escalation**: escalate through elevated claims carried inside a predicted structured token.
- **Session-management handoff**: hand a recovered account to session-management consumers for persistence rather than restating their steps.
- **Downstream consumer**: treat acceptance-verdict behaviour owned by authorisation checks as the downstream consumer.

## Testing Methodology

Prediction proves re-derivation plus acceptance, because inspection without a validity verdict is only suspicion.
1. **Decode captured tokens** - record structure plus claims plus encoding plus length plus alphabet per token, and the step completes when no captured token lacks a recorded structure.
2. **Prove token predictability** - collect a token run plus judge uniqueness and embedded sequence or timestamp plus recompute digests over known identifiers plus query lookup sources plus enumerate the candidate space inside the validity window where the effective bits fall short plus test each predicted token at the accepting endpoint, and the step completes when every token-pattern hypothesis and every derivation candidate carries an acceptance or rejection verdict.
3. **Confirm exploitability** - present each accepted prediction as the bound account or action, and the step completes when every accepted token carries a recorded ownership outcome.
4. **Rule out randomness** - compare the effective bits of the observed run against the strong-randomness bound, since encoding and mixing never raise them, and the step completes when the randomness hypothesis is confirmed or refuted with samples.

## False Positives

- **Stop condition**: stop when the evidence shows genuine randomness, because further prediction is only brute force.
- **Full uniqueness**: full uniqueness across a sufficient token run at or above the entropy bound.
- **No embedded structure**: no embedded sequence or timestamp or identifier structure after decoding.
- **Rejected verdicts**: rejected verdicts across the full derivation matrix plus lookup-sourced candidates.
- **Per-account isolation**: per-account isolation with no cross-account derivation success.
- **Window-bounded space**: a searchable space too large to exhaust inside the validity window, which closes the enumeration path even when the effective bits fall short of the bound.

## Pro Tips

- **Working posture**: prediction rewards collection breadth plus derivation discipline.
- **Two-identity run**: prefer a two-identity token run first so global versus per-account sequences separate early.
- **Decode-first discipline**: favor decoding every token before recomputing so derivation targets real structure.
- **Stabilised issuance**: repeat issuance until uniqueness plus ordering stabilise before judging predictability.
- **Verdict logging**: log each derivation candidate behind its acceptance verdict so gaps stay visible.
- **Exhaustion stop**: stop widening derivation wording once the matrix is exhausted and record the negative.
- **Entropy framing**: treat encoding and mixing as presentation rather than entropy; estimate the searchable space from the decoded structure and measure the validity window before spending attempts.

## Summary

A token that derives from guessable input or a weak generator is a re-derivation problem rather than a guessing problem.
Prediction collects a token run, recomputes each derivation, confirms each candidate at the accepting endpoint, and stops on full uniqueness at sufficient length or on a space too large for the validity window.
