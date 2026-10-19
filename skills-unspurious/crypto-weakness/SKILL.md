---
name: crypto-weakness
description: Identifying and exploiting weak cryptographic implementations including predictable tokens, weak hashes, and insecure session management
metadata:
  version: 1.0.0
---

# Cryptographic Weakness

Weak cryptography in session management, token generation, or data storage leads to authentication bypass, account takeover, and privilege escalation. The most impactful targets are session tokens, password resets, anti-CSRF tokens, and "remember me" cookies.

## Attack Surface

- Structured tokens: session cookies, access and refresh artifacts, identity assertions
- Recovery and proof artifacts: password reset, email confirmation, invite, unlock, share links
- Keyed checksums: signed session blobs, signed state carriers, signed upload descriptors
- Machine-issued values: API keys, device codes, one-time codes, anti-forgery tokens
- At-rest material: stored digests, embedded keys, seeded secrets, static placeholders
- **Encrypted at-rest material**: stored ciphertext blocks, encrypted cookies, and encrypted columns whose confidentiality rests on the cipher and its initialisation value

## Reconnaissance

### Decode and Inspect

- Decode every issued value immediately: a structured token often carries identity, role, and lifetime in clear form
- Record structure per artifact: segment count, alphabet, length, casing, fixed versus variable fields
- Note the algorithm marker and whether a signature segment is present

### Sampling

- Collect a batch of values per artifact from repeated issuance, from several principals, and from several roles
- Capture the same artifact across channels (web, mobile, API) to compare issuance paths
- Keep one known-invalid candidate of the same shape to calibrate acceptance verdicts

## Detection Channels

- Decoded predictable fields showing embedded counters or timestamps or identifiers.
- Duplicate tokens across repeated issuance showing absent randomness.
- Short token length below the strong-randomness bound.
- Fixed-length restricted-alphabet structure showing a digest-of-known-input shape.
- Accepted predicted token confirming a valid session or recovery action.
- Rejected candidate verdict per derivation closes that derivation hypothesis.
- Signature segment present on structured tokens marking the keyed-checksum binding.
- Algorithm marker showing a symmetric scheme or an unchecked acceptance option.
- Local re-verification success confirming a recovered secret without server contact.
- Accepted minted token carrying elevated claims confirming signature trust failure.
- Rejected stripped-algorithm token closing the removal hypothesis for that flow.
- Timing baseline over known-invalid tokens showing stable reference behaviour.
- Timing differential of a correct prefix over baseline with statistical separation.
- Acceptance verdict on the fully extracted token confirming the recovered value.
- Flat timing distribution across all prefixes signalling constant-time comparison.
- Error-class stability showing timing differences are comparison-driven rather than transport-driven.
- **Block-aligned repetition**: identical ciphertext segments at different plaintext positions, which show a mode that leaks plaintext structure.
- **Initialisation reuse or drift**: one initialisation value across several samples, or one that advances with a counter or a timestamp, so equal plaintext prefixes produce equal ciphertext.

## Adversarial Capabilities

Cryptographic testing presupposes issued artifacts, sampling volume, and offline computation, and it consumes all three.
- Collect a batch of issued values from repeated flows and several principals.
- Decode and re-encode each artifact without touching the server.
- Compute candidate derivations offline from known identifiers, plaintext candidates, and candidate keys.
- Verify key guesses locally against a captured signature before spending them at the endpoint.
- Measure response timing and error classes across repeated equivalent requests.
- Replay a minted artifact at the accepting endpoint under a chosen identity.

## Trust Assumptions

The class rests on one agreement: the value of the artifact is what authorizes its holder, so the value must be unpredictable to anyone who did not receive it.
The agreement holds the artifact free of recoverable structure, holds its random space wide enough to defeat search, holds the verification secret unguessable, and holds the comparison free of side channels.
Sensitive position leaks when any clause fails: the artifact can be re-derived, the key recovered offline, or the correct value extracted byte by byte.
Each variant breaks one clause: the structure and randomness clause, the key clause, or the comparison clause.
The agreement also covers encrypted at-rest material: the class tests that the cipher and its initialisation keep stored material confidential, and a weak mode or a reused or predictable initialisation value discloses plaintext structure without any key recovery.
Recovery and session artifacts carry the same root because the same generator issues both.

## Key Vulnerabilities

### Structured Token Inspection

- Decoded payloads often carry identity, role, expiry, and tenant in clear form; the signature protects integrity, not confidentiality
- Treat any signed-but-readable artifact as a claim set to target: what the verifier reads is what the attacker can rewrite once the signing clause fails
- Record which claims the verifier trusts (identity, role, scope, lifetime) and whether it re-derives any of them

### Predictable Token Patterns

- Embedded counters, timestamps, or identifiers make the next value derivable from samples
- Values that are digests of known input (identifier, email, hostname) are recomputable offline
- Fixed length with a restricted alphabet marks a hashed value rather than a random one
- Short values fall to brute force or lookup tables; repeated values across issuance show a static source

### Guessable Signing Secrets

- Placeholder, dictionary, and product-derived secrets appear in default configurations and copied deployments
- A key guess is verified locally against one captured signature before it is spent at the endpoint
- Values derived from the domain, the product name, or the environment are tried alongside wordlists
- **Key-source resolution**: where the verifier derives its key basis from artifact-carried input, the key basis is attacker-supplied rather than recovered; name the signing-key variant for the resolution step and the authentication-jwt skill for the token-header shapes

### Digest-of-Known-Input Derivation

- Recovery tokens computed as a digest of the identifier are recomputed for each candidate identifier and replayed
- Case, whitespace, and alternate-identifier normalisations produce further candidates that still verify
- Precomputed tables and lookup services answer for common plaintexts without server contact

### Token Forgery

- Recover the signing clause once the secret or the checksum source is known, then mint claims the verifier trusts
- **Claim-set targeting**: decode a genuine artifact to read the claim names that control identity, role, and tenant, then mint only those claims under the recovered or attacker-supplied key basis
- Elevation targets: identity of another principal, role or privilege flags, extended lifetime, widened scope
- Re-verify the forged artifact locally before replaying it, so a rejected replay attributes to binding rather than construction

### Comparison Weakness

- Verification that compares values byte by byte without constant time leaks prefix correctness
- The leak is amplified where tokens are long, comparison is repeated, and the endpoint tolerates many attempts
- Timing work needs a calibrated baseline over known-invalid values and statistical separation over noise

### Ciphertext Confidentiality

- **Block-aligned leakage**: a mode that encrypts equal plaintext blocks to equal ciphertext blocks exposes structure and repetition in stored material without any key recovery
- **Initialisation reuse**: a reused or predictable initialisation value makes equal plaintext prefixes produce equal ciphertext, so one sample answers for many
- **Weak random source**: a non-cryptographic generator behind key or initialisation creation turns the value into a guessable one, so the search space for the secret step above collapses

## Advanced Techniques

### Timing Oracle Refinement

- Calibrate a baseline over known-invalid candidates, then iterate candidate prefixes position by position
- Separate comparison-driven differences from transport noise by repeating each sample and watching error classes
- Stop when the extracted value verifies, or when a flat distribution across all prefixes reports constant-time comparison

### Entropy and Sampling Analysis

- Sample counts in the tens per artifact: unique-value counts, length variety, and shared prefixes reveal the generator
- Cluster samples by issuance time and by principal to separate counter-driven from time-driven and identity-driven fields
- A generator verdict of strong randomness redirects effort to key and comparison clauses

### Rotation and Retirement Windows

- Values issued under a retired key or a previous generator version stay valid inside an overlap window
- Sampling across a rotation boundary shows whether the retirement is enforced at verification or only at issuance

### Ciphertext Structure Analysis

- **Sample comparison first**: compare ciphertext samples for repeated blocks and repeated initialisation values before attempting any key work
- **Structure recovery**: recover plaintext structure from a mode that preserves block equality, and search the seed space where the initialisation value advances predictably
- **Stop signal**: a mode that randomises every block under a unique unpredictable initialisation value closes this line rather than inviting more samples

## Bypass Techniques

Bypass shapes slip past a check that is present, so each one is tried after the baseline verdict reports enforcement.
- Case and encoding normalisation differences between minting and verification widen the candidate set that still verifies.
- Padding and truncation tolerated by the accepting endpoint let a shortened candidate verify.
- The same artifact presented over a second transport or endpoint whose check is weaker.
- Retired keys and previous generator versions accepted during a rotation overlap.
- Alternate identifier spellings accepted by the derivation path while the lookup stays on the canonical one.
- Name the defence-bypass family at the normalisation, tolerant-acceptance, and spelling-folding steps, and the proxy-techniques family at the second-carrier step, rather than restating those mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Predictable recovery artifact → account takeover → durable access
- Recovered signing key → forged session artifact → privilege escalation
- Weak session artifact → replay against a second service that checks only the signature
- Timing oracle → full value recovery → reuse in any downstream action the artifact authorizes
- Crypto weakness plus an authorization gap: the forged identity then reaches resources the original holder could not

## Testing Methodology

1. **Inventory artifacts** - List every issued value with its carrier, lifetime, and accepting endpoint; the step completes when each artifact carries a carrier and a lifetime.
2. **Sample and decode** - Collect a batch per artifact and decode structure and claims; the step completes when every artifact is recorded as structured or opaque with its fields.
3. **Test predictability** - Compare samples within and across principals for counters, timestamps, shared prefixes, and repeats; the step completes when each artifact carries a predictable or random verdict.
4. **Derive candidates** - For digest-shaped artifacts compute candidates from known identifiers and plaintext candidates; the step completes when every derivation carries an acceptance verdict.
5. **Test key guesses** - Verify candidate secrets locally against a captured signature, then at the endpoint; the step completes when the secret is recovered or the candidate space is exhausted with each family recorded.
6. **Forge and replay** - Mint the elevated claims and replay at the accepting endpoint; the step completes when acceptance or rejection is recorded with the receiving context.
7. **Measure comparison** - Calibrate a baseline and iterate prefixes with repeated samples; the step completes when timing separation is proven or constant-time comparison is recorded.
8. **Test ciphertext confidentiality** - Collect encrypted samples and compare them for repeated blocks and reused or predictable initialisation values; the step completes when each encrypted store carries a cipher and initialisation verdict.

## Variants

- crypto-predictable-token - Predict recovery and session artifacts from embedded counters or digest-of-known-input structure, or enumerate a space small enough for the validity window, and confirm candidates at the accepting endpoint.
- crypto-signing-key-forgery - Forge signed artifacts under a recovered key, or strip signature validation when an unchecked algorithm accepts keyless values.
- crypto-timing-oracle - Extract the value through comparison timing when verification leaks prefix correctness, iterating prefixes against a calibrated baseline.

## False Positives

- Long random values that decode to nothing meaningful and share no structure across samples
- Artifacts that verify only under a full binding of identity plus audience plus lifetime, and expire quickly
- Timing differences that vanish under repetition, or that match the endpoint's normal variance
- Candidate derivations that fail acceptance at every endpoint, which marks a strong random source rather than a weak one
- Encrypted material whose mode randomises every block under a unique unpredictable initialisation value, with no reuse across samples

## Pro Tips

1. Decode every session cookie and token immediately; claims often travel in clear form
2. Digests of known values (identifier, email, hostname) are recomputed offline before any guessing
3. Default and placeholder secrets are the fastest win; try product-derived and environment-derived values next
4. Stripped-signature acceptance belongs to the unchecked-algorithm clause; test it where pinning is unclear
5. Values shorter than the strong-randomness bound fall to brute force or tables
6. Collect 5-10 samples per artifact and look for counters, timestamps, and shared prefixes inside them
7. Mint elevated claims and confirm acceptance end to end; a local re-verification success is not yet a finding
8. Run the whole forgery suite across every mode before manual chaining; one automated pass finds the weak mode faster than a hand-built chain

## Summary

A token is only as strong as its unpredictability, its key, its comparison, and the confidentiality of the material it protects. Weak generation, guessable keys, leaky comparison, and weak at-rest encryption each convert a held artifact into account takeover or privilege escalation.
