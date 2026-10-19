---
name: oauth-redirect-uri-validation
description: Redirect destination validation gaps yield code theft. Use when unregistered callback destinations are accepted; when validator and consumer parse the same destination differently; when mobile dispatch transports widen the acceptance set.
metadata:
  version: 1.0.0
---

# Redirect URI Validation

Registration-time destination checks decide where grant credentials are delivered.
This variant proves the check is weaker than the delivery by running a per-pattern normalisation-differential matrix plus consumer confirmation.
The theft goal is a grant credential arriving at an attacker-controlled destination through a registered client.

## Attack Surface

Applicability centers on a grant flow whose authorization entry point accepts a caller-supplied callback destination.
The registration holds one or more destination patterns per client, including prefix matches, subdomain wildcards, or multiple registered values.
The validator that approves the destination and the consumer that later delivers to it may normalise input differently.
Mobile dispatch transports such as custom schemes and universal links widen the acceptance set with a hijackable value.
Client-credentials flows with no user and no destination fall outside this variant.

## Reconnaissance

Map the destination inventory before fuzzing it.
Catalogue every client with its grant types plus every registered callback destination pattern plus the matching rule each registration implies.
Record the discovery document values for supported response shapes and grant types so later probes parametrise correctly.
Probe each client with a clearly unregistered destination to learn the rejection rendering that later acceptances diverge from.
Reconnaissance is complete when every client carries its destination list plus its baseline rejection.

## Detection Channels

Only the entries below fire here; freshness, verifier, binding, and approval signals belong to the sibling variants.
- Acceptance versus rejection verdict per destination pattern, recorded across the whole matrix.
- Validator-versus-consumer parse gap, where the approving side and the delivering side disagree on the same input.
- Duplicate-carrier precedence, where the first and the last of two supplied destinations decide differently.
- Consumer-confirmation capture, where a grant credential arrives at the attacker listener through an accepted destination.
- Harvest-channel arrival, where an embedded subresource leaks the credential through the ambient referrer policy.

## Adversarial Capabilities

Validation probing presupposes destination supply plus capture operation plus registration reach, and it consumes all three.
- Supply candidate destinations that mutate one registered pattern at a time through encoding plus suffix plus query injection.
- Operate a capture listener that records every grant credential arrival with its full destination.
- Register attacker-controlled suffix hosts or subdomain values where wildcard acceptance invites a claim.
- Embed an authorized destination as a subresource to test ambient referrer leakage where policy permits.
- Confirm mobile dispatch hijack by holding the scheme or link the target device routes to the tester.

## Trust Assumptions

At the moment the grant chain executes, the server trusts one binding agreement: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it.
Sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
This variant breaks the destination-match clause because the validator accepts a destination the legitimate client never registered while the consumer delivers the credential there.

## Key Vulnerabilities

### Per-Pattern Normalisation Differentials

Fuzz each registered pattern with one mutation family at a time, using shapes like `<registered-prefix><attacker-suffix>` plus encoded separators plus case plus port plus scheme-downgrade variants.
Compare the validator verdict against the consumer delivery for the same input, because approval without delivery is only a parse curiosity.
The parent matrix step covers only generic encoding fuzzing and cannot describe validator-versus-consumer confirmation, so this variant owns the differential procedure.

### Duplicate-Carrier Precedence

Submit the destination carrier twice with the first and the last values disagreeing, then record which occurrence each side honors.
Treat a split verdict as a finding and treat consistent rejection of both orderings as a negative.
The parent matrix step never names precedence, so this variant owns the ordering probe.

### Wildcard-Claim Chaining

Claim an attacker-controlled host under an accepted wildcard scope and chain the claim into a full credential delivery.
Confirm the chain by capturing the credential at the claimed host rather than by reading the acceptance verdict alone.
Transport values for mobile dispatch ride inside this variant as a parameter, confirmed through dispatch hijack rather than a separate procedure.

## Advanced Techniques

Referrer harvesting rides here as an exfil channel rather than a separate variant.
Mount the authorized destination as a subresource on an attacker page and harvest the credential where the ambient referrer policy carries it.
Treat policy-dependent capture as confirmation of the same destination finding, not as a new probe kind.
Browser-messaging delivery rides here as a second exfil channel: a flow that returns the credential into a parent-window message reaches a listener the destination check never examined, so read the listener's origin check before closing the destination finding.
A response-carrier swap that moves the credential into a browser-readable carrier beside the registered destination rides here as the same delivery-channel value.

## Bypass Techniques

Bypass forms are the check values this variant defeats, each confirmed through delivery rather than verdict alone.
- Trailing-separator plus case plus port plus scheme-downgrade mutations pass a textual match that never normalises.
- Encoded-separator plus backslash plus delimiter tricks pass a validator whose parser differs from the consumer.
- Suffix-host plus query-injection shapes pass a prefix-only comparison.
- Duplicate carriers pass a check that reads one occurrence while delivery reads the other.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Validation findings chain forward into credential capture because an acceptance without a capture is only a parser gap.
- Hand an accepted attacker destination to the capture listener and redeem the arriving credential as the takeover proof.
- Hand a legitimate destination with an open-relay suffix to the open-redirect companion for exfiltration through a trusted host.
- Hand a legitimate destination carrying active script to the cross-site-scripting companion for credential theft from the trusted page.
- Treat analytics plus log leakage of delivered credentials as an amplifier of any confirmed acceptance.

## Testing Methodology

Validation runs the differential matrix first and everything else follows, because no later claim is meaningful without a confirmed delivery gap.
1. **Inventory destinations** - list every client with its grant types plus its registered destination patterns plus the baseline rejection, and the step completes when no unlisted client or pattern remains.
2. **Run the differential matrix** - mutate one pattern at a time through encoding plus suffix plus query plus scheme-downgrade families over parent step P2, which names generic fuzzing but never names per-pattern normalisation differentials plus consumer confirmation, and the step completes when every pattern carries an acceptance or rejection verdict per family.
3. **Probe carrier precedence** - submit duplicated carriers in both orderings and record which occurrence each side honors, and the step completes when every client shows a precedence verdict or consistent rejection.
4. **Chain wildcard claims** - claim an attacker host under each accepted wildcard and attempt full credential delivery, and the step completes when every claim shows a capture or a failed delivery.
5. **Confirm mobile transport** - replay accepted destinations through scheme plus intent plus universal-link dispatch, and the step completes when each transport shows a hijack or a dispatch refusal.
6. **Confirm capture** - redeem each captured credential to prove account impact, and the step completes when every capture carries a redemption verdict or a documented expiry.

## False Positives

Stop when the evidence shows the destination check holds, because rejected matrices are only noise.
- Consistent rejection across every mutation family with no delivery divergence.
- Strict full-string match with unified parsing between validator and consumer.
- Custom-scheme dispatch gated on verified ownership proof that the tester cannot supply.
- Captured arrivals whose source matches the tester machine rather than the server, which indicate a client-side fetch made the request.

## Pro Tips

Validation rewards one mutation family at a time plus delivery confirmation.
1. Prefer the quiet acceptance verdict first, then promote only acceptances to full capture attempts.
2. Compare validator and consumer on the same input before claiming any bypass.
3. Favor tiny destination mutations so each acceptance names exactly one failing pattern.
4. Log every probe behind its pattern plus family so the matrix stays exhaustive.
5. Stop promoting consistent rejections and record them as rejections rather than inconclusive.

## Tooling

Drive the grant chain by hand so every destination value stays under tester control.
Decode arriving credential structure locally to confirm which pattern delivered what before redeeming anything.

## Summary

A destination check that approves what the legitimate client never registered delivers grant credentials to the attacker.
Validation matrices each pattern, confirms each acceptance through delivery, and redeems each capture into account impact.
