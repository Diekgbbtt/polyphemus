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

- **Applicability**: centers on a grant flow whose authorization entry point accepts a caller-supplied callback destination.
- **Registration patterns**: the registration holds one or more destination patterns per client, including prefix matches, subdomain wildcards, or multiple registered values.
- **Validator-consumer gap**: the validator that approves the destination and the consumer that later delivers to it may normalise input differently.
- **Mobile transports**: mobile dispatch transports such as custom schemes and universal links widen the acceptance set with a hijackable value.
- **Out-of-scope flows**: client-credentials flows with no user and no destination fall outside this variant.

## Reconnaissance

- **Destination mapping**: map the destination inventory before fuzzing it.
- **Destination catalogue**: catalogue every client with its grant types plus every registered callback destination pattern plus the matching rule each registration implies.
- **Discovery recording**: record the discovery document values for supported response shapes and grant types so later probes parametrise correctly.
- **Rejection baseline**: probe each client with a clearly unregistered destination to learn the rejection rendering that later acceptances diverge from.
- **Completion criterion**: reconnaissance is complete when every client carries its destination list plus its baseline rejection.

## Detection Channels

- **Channel scope**: freshness, verifier, binding, and approval signals belong to the sibling variants.
- **Verdict per pattern**: record an acceptance versus rejection verdict per destination pattern across the whole matrix.
- **Validator-versus-consumer parse gap**: the approving side and the delivering side disagree on the same input.
- **Duplicate-carrier precedence**: the first and the last of two supplied destinations decide differently.
- **Consumer-confirmation capture**: a grant credential arrives at the attacker listener through an accepted destination.
- **Harvest-channel arrival**: an embedded subresource leaks the credential through the ambient referrer policy.

## Adversarial Capabilities

- **Prerequisites**: validation probing presupposes destination supply plus capture operation plus registration reach, and it consumes all three.
- **Candidate supply**: supply candidate destinations that mutate one registered pattern at a time through encoding plus suffix plus query injection.
- **Capture operation**: operate a capture listener that records every grant credential arrival with its full destination.
- **Registration reach**: register attacker-controlled suffix hosts or subdomain values where wildcard acceptance invites a claim.
- **Referrer embedding**: embed an authorized destination as a subresource to test ambient referrer leakage where policy permits.
- **Dispatch-hijack confirmation**: confirm mobile dispatch hijack by holding the scheme or link the target device routes to the tester.

## Trust Assumptions

- **The agreement**: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it, and sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
- **The failing clause**: this variant breaks the destination-match clause because the validator accepts a destination the legitimate client never registered while the consumer delivers the credential there.

## Key Vulnerabilities

### Per-Pattern Normalisation Differentials

- **Per-pattern fuzzing**: fuzz each registered pattern with one mutation family at a time, using shapes like `<registered-prefix><attacker-suffix>` plus encoded separators plus case plus port plus scheme-downgrade variants.
- **Validator-consumer comparison**: compare the validator verdict against the consumer delivery for the same input, because approval without delivery is only a parse curiosity.
- **Differential ownership**: the parent matrix step covers only generic encoding fuzzing and cannot describe validator-versus-consumer confirmation, so this variant owns the differential procedure.

### Duplicate-Carrier Precedence

- **Precedence probe**: submit the destination carrier twice with the first and the last values disagreeing, then record which occurrence each side honors.
- **Precedence verdict**: treat a split verdict as a finding and treat consistent rejection of both orderings as a negative.
- **Precedence ownership**: the parent matrix step never names precedence, so this variant owns the ordering probe.

### Wildcard-Claim Chaining

- **Wildcard claim**: claim an attacker-controlled host under an accepted wildcard scope and chain the claim into a full credential delivery.
- **Chain confirmation**: confirm the chain by capturing the credential at the claimed host rather than by reading the acceptance verdict alone.
- **Transport parameter**: transport values for mobile dispatch ride inside this variant, confirmed through dispatch hijack rather than a separate procedure.

## Advanced Techniques

- **Referrer harvesting**: rides here as an exfil channel rather than a separate variant.
- **Subresource mounting**: mount the authorized destination as a subresource on an attacker page and harvest the credential where the ambient referrer policy carries it.
- **Capture verdict**: treat policy-dependent capture as confirmation of the same destination finding, not as a new probe kind.
- **Browser-messaging delivery**: rides here as a second exfil channel: a flow that returns the credential into a parent-window message reaches a listener the destination check never examined, so read the listener's origin check before closing the destination finding.
- **Response-carrier swap**: a response-carrier swap that moves the credential into a browser-readable carrier beside the registered destination rides here as the same delivery-channel value.

## Bypass Techniques

- **Bypass scope**: bypass forms are the check values this variant defeats, each confirmed through delivery rather than verdict alone.
- **Normalisation-evading mutations**: trailing-separator plus case plus port plus scheme-downgrade mutations pass a textual match that never normalises.
- **Parser-differential tricks**: encoded-separator plus backslash plus delimiter tricks pass a validator whose parser differs from the consumer.
- **Suffix-host shapes**: suffix-host plus query-injection shapes pass a prefix-only comparison.
- **Duplicate carriers**: pass a check that reads one occurrence while delivery reads the other.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: validation findings chain forward into credential capture because an acceptance without a capture is only a parser gap.
- **Accepted-destination handoff**: hand an accepted attacker destination to the capture listener and redeem the arriving credential as the takeover proof.
- **Open-relay handoff**: hand a legitimate destination with an open-relay suffix to the open-redirect companion for exfiltration through a trusted host.
- **Active-script handoff**: hand a legitimate destination carrying active script to the cross-site-scripting companion for credential theft from the trusted page.
- **Leakage amplifier**: treat analytics plus log leakage of delivered credentials as an amplifier of any confirmed acceptance.

## Testing Methodology

Validation runs the differential matrix first and everything else follows, because no later claim is meaningful without a confirmed delivery gap.
1. **Inventory destinations** - list every client with its grant types plus its registered destination patterns plus the baseline rejection, and the step completes when no unlisted client or pattern remains.
2. **Run the differential matrix** - mutate one pattern at a time through encoding plus suffix plus query plus scheme-downgrade families over parent step P2, which names generic fuzzing but never names per-pattern normalisation differentials plus consumer confirmation, and the step completes when every pattern carries an acceptance or rejection verdict per family.
3. **Probe carrier precedence** - submit duplicated carriers in both orderings and record which occurrence each side honors, and the step completes when every client shows a precedence verdict or consistent rejection.
4. **Chain wildcard claims** - claim an attacker host under each accepted wildcard and attempt full credential delivery, and the step completes when every claim shows a capture or a failed delivery.
5. **Confirm mobile transport** - replay accepted destinations through scheme plus intent plus universal-link dispatch, and the step completes when each transport shows a hijack or a dispatch refusal.
6. **Confirm capture** - redeem each captured credential to prove account impact, and the step completes when every capture carries a redemption verdict or a documented expiry.

## False Positives

- **Check-held stop**: stop when the evidence shows the destination check holds, because rejected matrices are only noise.
- **Consistent rejection**: reject across every mutation family with no delivery divergence.
- **Strict full-string match**: match strictly with unified parsing between validator and consumer.
- **Ownership-gated dispatch**: custom-scheme dispatch gated on verified ownership proof that the tester cannot supply.
- **Client-side arrivals**: captured arrivals whose source matches the tester machine rather than the server indicate a client-side fetch made the request.

## Pro Tips

- **Discipline**: validation rewards one mutation family at a time plus delivery confirmation.
- **Quiet-verdict preference**: prefer the quiet acceptance verdict first, then promote only acceptances to full capture attempts.
- **Same-input comparison**: compare validator and consumer on the same input before claiming any bypass.
- **Tiny mutations**: favor tiny destination mutations so each acceptance names exactly one failing pattern.
- **Probe logging**: log every probe behind its pattern plus family so the matrix stays exhaustive.
- **Rejection recording**: stop promoting consistent rejections and record them as rejections rather than inconclusive.

## Tooling

- **Manual chain driving**: drive the grant chain by hand so every destination value stays under tester control.
- **Local credential decoding**: decode arriving credential structure locally to confirm which pattern delivered what before redeeming anything.

## Summary

A destination check that approves what the legitimate client never registered delivers grant credentials to the attacker.
Validation matrices each pattern, confirms each acceptance through delivery, and redeems each capture into account impact.
