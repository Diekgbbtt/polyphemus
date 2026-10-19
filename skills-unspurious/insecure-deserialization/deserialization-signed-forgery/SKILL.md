---
name: deserialization-signed-forgery
description: Signed-forgery deserialization testing for signature-gated state blobs. Triggers on weakly protected state blobs, on unsigned fallback paths, on mintable claims controlling identity or role.
metadata:
  version: 1.0.0
---

# Deserialization Signed Forgery

Signature-gated state blobs deserialize privileged claims only because a binding ties each blob to a secret.
This variant breaks the binding through weak-secret recovery or signature removal and then mints a state blob the server accepts.

## Attack Surface

This variant applies where a signed state blob gates deserialization and the verifier decides acceptance from the binding.
The blob carries claims that influence identity, role, or server-side state after rehydration.
The binding rests on a shared secret, a keyed checksum, or a removable signature segment.
Unsigned graphs without any binding belong to the gadget-chain variant, and stored blobs rehydrated by later jobs belong to the deferred-trigger variant.

## Reconnaissance

Hunt state blobs that carry a signature segment alongside opaque content.
Map the verifier by tampering one byte and recording accept, reject, or silent-fallback behaviour.
Probe for unsigned fallback paths by removing the signature segment and resubmitting the blob.
Collect binding facts such as algorithm hints, key-roll indicators, and claim fields into the runtime knowledge base.
Stop hunting only when every reachable state blob has an accept, reject, or fallback observation recorded.

## Detection Channels

Tamper-rejection responses confirm a verifier evaluates the binding before rehydration.
Unsigned-fallback acceptance confirms a keyless path exists beside the signed one.
Re-signed blob acceptance confirms a recovered or guessed secret binds correctly.
Local re-verification success predicts server acceptance before the minted blob is sent.
Claim-reflecting behaviour confirms the forged state took effect after acceptance.

## Adversarial Capabilities

This variant presupposes the ability to submit state blobs at reachable request loci.
It runs offline secret search against captured blobs with local re-verification before touching the server.
It strips signature segments to test keyless acceptance paths without any secret.
It mints claim-bearing blobs that encode a chosen identity or role once the binding is broken.

## Trust Assumptions

The feature executes an object-graph rehydration step under a standing agreement.
The agreement holds that every consumed blob is sender-faithful and every signature binds its blob to a strong secret.
The runtime exposes only verified state, resolves only bound claims, and leaks at most a benign error on malformed input.
The exact failing clause is the signature-binding clause: the binding rests on a recoverable or removable secret and the server accepts a minted blob.

## Key Vulnerabilities

Weak-secret recovery searches the binding secret offline, re-verifies each candidate locally, and re-signs a minted state blob with the recovered value.
Signature stripping removes the binding segment and submits the content alone, reaching the unsigned fallback the verifier silently accepts.
Claim minting encodes a chosen identity or role into the abstract shape `[CLAIM-PLACEHOLDER, BINDING-PLACEHOLDER]` once either path breaks the layer.
The key-centric recovery and keyless-removal procedure is the delta chain-matching language cannot express.
Each path converges on the same proof: the server accepts the minted blob and reflects its claims.

## Advanced Techniques

Search the secret offline with local re-verification first, since server-side guessing burns budget and risks lockout.
Decide strip before resign on every target, since a keyless path removes the need for any secret work.
Choose claims for identity or role effect and keep the minted effect minimal and reversible.
Hand brute-force sub-steps to the crypto-weakness skill where secret search mechanics are owned instead of restating them here.

## Bypass Techniques

Confuse algorithm selection where the verifier honours a binding label inside the blob, confirming each attempt with local re-verification.
Downgrade the binding where legacy verifiers accept weaker checks beside the current one.
Shift the blob across equivalent request loci when one locus enforces verification and another feeds the same rehydration.
Name the defence-bypass family at steps that defeat hardened verifiers instead of restating its mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Forged identity or role state hands off to the authorization-principal skill for privilege-effect demonstration.
Accepted minted blobs that reach object-graph sinks hand off to gadget-chain consumers for execution proof.
Session-fixation effects from planted state hand off to session-management consumers where fixation is owned.

## Testing Methodology

1. Map signed state blobs to their verifiers; the step is complete when each reachable state blob has a tamper-response observation recorded.
2. Test the unsigned fallback by stripping the binding segment; the step is complete when the fallback verdict of accepted or rejected is recorded.
3. Recover the weak secret through offline search with local re-verification; the step is complete when a candidate re-verifies locally or the search space is exhausted with its bounds recorded.
4. Mint the state blob by re-signing chosen claims or by shaping the stripped form, breaking only the signature layer; the step is complete when exactly one minted blob exists with its construction rationale recorded.
5. Prove acceptance with the least-privilege claim that still demonstrates effect; the step is complete when the server reflects the minted claims from the forged blob.
6. Cover priority session stores first and revisit skipped loci; the step is complete when each named session locus is tested or ruled out with an observation.

## False Positives

Verified bindings with strong secrets and strict rejection of tampered blobs close this variant.
Verifiers that reject stripped blobs without any fallback close the keyless path.
Claim schemas that ignore unknown or elevated fields neutralise minting when the reflected state shows no effect.
Sandboxed rehydration without identity or state consequences limits the finding to acceptance without impact.
Error text naming state classes without attacker bytes reaching the verifier marks a dead code path rather than a finding.

## Pro Tips

Test the strip path before the search path, since removal is one request and recovery is many.
Verify every secret candidate locally before sending it, since local checks are silent and server checks are logged.
Mint the smallest claim that proves control, favouring a benign marker over a privileged role where the marker reflects.
Record the binding facts beside each attempt so a failed run still narrows the remaining search space.
Treat legacy verifiers as strip-first targets, since fallback paths cluster around older acceptance logic.

## Summary

Signature-gated state becomes attacker state when the binding is recoverable or removable.
Break the layer through offline recovery with local re-verification or through keyless removal, then prove acceptance with a minted blob.
Safe patterns verify bindings with strong secrets, reject stripped forms outright, and keep claims to the minimum the feature requires.
