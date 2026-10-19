---
name: oauth-code-client-binding
description: Client binding gaps let codes and tokens cross clients. Use when credential redemption skips destination or identity comparison; when attacker-initiated grants complete in victim sessions; when token oracles answer without proper authentication.
metadata:
  version: 1.0.0
---

# Code and Client Binding

Client identity plus destination plus audience bind each credential to the client that earned it.
This variant proves the binding is uncompared by running authorize-versus-redemption comparison plus mix-up sequencing with credential-shape probing.
The theft goal is a credential minted for one client redeemed by another, or a victim session completing an attacker-initiated grant.

## Attack Surface

- **Applicability**: centers on a grant flow whose authorization entry point records a client identity plus a callback destination and whose redemption entry point must recheck both, plus token-issuing and token-status oracles that must authenticate their callers.
- **Secondary divergences**: dynamic client provisioning, secretless redemption calls, scope over-request, refresh reuse, and account linking all ride inside this variant.
- **No-session flows**: reduce to this variant with vacuous destination and freshness steps, keeping scope plus audience probing as the same redemption kind.
- **Token-format mutation**: stays out and is consumed from the token companion skill.

## Reconnaissance

- **Binding-surface mapping**: map the binding surface before comparing it.
- **Client catalogue**: catalogue every client with its identity, its registered destinations, its credential posture, and its advertised scope set.
- **Baseline recording**: record the baseline behavior for a redemption call with no long-term secret plus a token-status query with client-only authentication.
- **Completion criterion**: reconnaissance is complete when every client carries its identity plus destination plus posture inventory with baselines on file.

## Detection Channels

- **Channel scope**: destination, freshness, verifier, and approval signals belong to the sibling variants.
- **Authorize-versus-redemption mismatch**: the two steps record different client identities or destinations for one credential.
- **Cross-client redemption acceptance**: a credential minted for one client succeeds under another.
- **Cross-audience acceptance**: a token minted for one audience is honored by another service.
- **Token-status oracle answer**: the status endpoint confirms validity without proper caller authentication.
- **Profile-oracle return**: the profile endpoint releases data beyond the presenting token scope.
- **Mix-up completion**: an attacker-initiated grant completes in a victim session under the wrong client.

## Adversarial Capabilities

- **Prerequisites**: binding probing presupposes two-client control plus credential capture plus oracle access, and it consumes all three.
- **Two-client control**: hold two clients at once, including a provisioned attacker client where dynamic provisioning permits, so credentials can cross between them.
- **Identity-cross redemption**: initiate grants under one client identity and redeem under another to test whether either side compares.
- **Rebinding probe**: rebind the destination and the identity between the authorization and redemption steps to oracle each comparison independently.
- **Caller-authentication probes**: call redemption and token-status oracles with absent, client-only, and misplaced credentials to test caller authentication.
- **Mix-up sequencing**: sequence attacker-initiated grants through victim completion to test mix-up handling.
- **Widening probes**: over-request scope and replay refresh values to test grant-widening alongside binding.

## Trust Assumptions

- **The agreement**: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it, and sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
- **The failing clause**: this variant breaks the client-identity clause because a credential minted for one client is honored when a different client presents it.

## Key Vulnerabilities

### Authorize-Versus-Redemption Comparison Gaps

- **Altered-value redemption**: record the identity plus destination the authorization side stores, then redeem with each value altered once, using shapes like `<swapped-identity>` plus `<rebound-destination>` plus `<both-altered>`.
- **Comparison verdict**: treat acceptance of any altered shape as a comparison gap and treat consistent cross-step refusal as a negative.
- **Comparison ownership**: the parent exchange step covers only swapping whole credentials between clients and cannot describe per-field comparison oracles, so this variant owns the comparison procedure.

### Mix-Up Sequencing

- **Mix-up sequence**: initiate the grant under the attacker client, deliver the victim through login completion, and redeem the resulting credential under the attacker identity.
- **Mix-up verdict**: treat victim completion that yields attacker-usable credentials as a mix-up finding.
- **Sequencing ownership**: the parent exchange step never names attacker-initiated plus victim-completed ordering, so this variant owns the sequencing procedure.

### Oracle-Authentication Probing

- **Oracle-authentication probe**: call redemption and token-status oracles with no secret, with client-only authentication, and with credentials carried outside their proper channel.
- **Oracle verdict**: treat informative answers under these shapes as oracle-authentication gaps.
- **Secondary divergences**: scope over-request plus refresh reuse plus account-linking sequencing ride inside this variant, confirmed through the same redemption verdicts rather than separate procedures.

### Prerequisite-Completeness Gaps

- **Completeness probe**: issue a credential to an account that never completed a prerequisite step, such as an unverified address or an unaccepted invitation, and redeem it.
- **Completeness verdict**: treat redemption on an incomplete account as a completeness gap and treat consistent refusal as a negative, because the binding the flow assumes is the account state, not the credential alone.

### Registration-Metadata Fetch Gaps

- **Registration-metadata probe**: supply a registration metadata field the server fetches at registration time, such as a logo, key-set, or sector identifier location, and observe the server-side fetch.
- **Fetch-sink verdict**: treat a fetch of an attacker-chosen location as a registration-step sink, and hand the egress finding to `ssrf` at the fetch step rather than restating its procedure here.

## Advanced Techniques

- **Account linking**: rides here as a sequencing parameter rather than a separate variant.
- **Identity linkage**: link an attacker identity to a victim profile without re-authentication and test whether same-address identities across providers collide into one account.
- **Linkage verdict**: treat linkage success as confirmation of the same binding gap through a persistence-flavored outcome.

## Bypass Techniques

- **Bypass scope**: bypass forms are the check values this variant defeats, each confirmed through redemption rather than request shape alone.
- **Altered identities**: pass a redemption side that never compares against the authorization record.
- **Rebound destinations**: pass a redemption side that reads the destination without joining it to issuance.
- **Secretless calls**: pass a redemption side that treats long-term authentication as advisory.
- **Over-requested scope**: passes an issuance side that grants everything asked.
- **Cross-audience tokens**: pass a resource side that never validates the intended audience.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: binding findings chain forward into cross-client impact because a swap without a redemption verdict is only a record gap.
- **Leaked credential handoff**: hand a leaked credential from logs or analytics to the cross-client redemption as the takeover proof.
- **Destination-validation handoff**: hand a destination-validation acceptance from the redirect companion to this variant so the stolen credential arrives before it crosses clients.
- **Refresh-value handoff**: hand an over-scoped or non-rotated refresh value to session persistence as the long-term outcome.
- **Audience-side amplifier**: treat identity-format confusion verdicts consumed from the token companion as the audience-side amplifier.

## Testing Methodology

Binding runs the comparison matrix first and everything else follows, because no sequencing claim is meaningful without a confirmed comparison gap.
1. **Inventory clients** - list every client with its identity plus destinations plus credential posture plus scope set with baselines on file, and the step completes when no unlisted client remains.
2. **Compare authorize versus redemption** - alter identity plus destination singly and jointly over parent step P5, which names credential swapping but never names rebinding comparison plus mix-up sequencing plus oracle-authentication probing, and the step completes when every field carries an acceptance or refusal verdict.
3. **Sequence mix-up flows** - initiate under the attacker client and complete in the victim session, and the step completes when every sequence shows a documented completion or refusal.
4. **Probe oracle authentication** - call redemption and token-status oracles with absent plus client-only plus misplaced credentials, and the step completes when every call shows a guarded refusal or a documented answer.
5. **Probe widening shapes** - over-request scope plus replay refresh values plus attempt secretless linkage, and the step completes when every shape shows refusal or a documented acceptance.

## False Positives

- **Binding-held stop**: stop when the evidence shows the binding check holds, because refused swaps are only noise.
- **Cross-step comparison**: enforced with every altered identity or destination refused.
- **Caller authentication**: enforced on redemption and token-status oracles with secretless calls refused.
- **Audience and issuer validation**: enforced with cross-service tokens refused.
- **Scope grants**: trimmed to registered need with over-request refused.
- **Refresh rotation**: enforced with reuse detected and refused.

## Pro Tips

- **Discipline**: binding rewards two clients plus one altered field at a time plus cross-step diffing.
- **Attacker-client provisioning**: provision the attacker client first so every swap has a live second identity.
- **Single-field alteration**: alter exactly one binding field per redemption and log each verdict behind its shape.
- **Cross-step comparison**: compare authorization-step and redemption-step records on every attempt before claiming a gap.
- **Oracle-first ordering**: test oracle authentication before scope widening so the simpler gap names itself first.
- **Refusal recording**: stop promoting refused swaps and record them as refusals rather than inconclusive.

## Tooling

- **Manual chain driving**: drive the grant chain by hand so every identity and destination value stays under tester control.
- **Local token decoding**: decode arriving token structure locally to confirm which audience and scope each credential actually carried before replaying it across clients.

## Summary

A binding check that never compares lets one client credentials serve another.
Binding comparison gaps each field, sequences each mix-up, and probes each oracle before claiming cross-client impact.
