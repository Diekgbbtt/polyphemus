---
name: oauth-pkce-enforcement
description: Verifier binding gaps let stolen codes redeem. Use when grant credentials issue without any challenge; when redemption accepts a missing or mismatched verifier; when challenge methods downgrade to replayable forms.
metadata:
  version: 1.0.0
---

# PKCE Enforcement

The single-use verifier binds a grant credential to the party that requested it.
This variant proves the binding is unenforced by running issuance-without-challenge plus verifier-oracle probing.
The theft goal is a stolen grant credential redeemed with an attacker-chosen verifier the server still honors.

## Attack Surface

Applicability centers on a grant flow whose authorization entry point accepts a challenge derived from a verifier the client keeps, and whose redemption entry point must recheck that verifier.
Public clients that cannot hold long-term secrets depend on this binding most, while confidential clients carry it as defense in depth.
Authorization servers that still issue credentials with no challenge attached widen the surface to challenge-less redemption.
Flows with no user session fall outside this variant.

## Reconnaissance

Map the verifier surface before breaking it.
Catalogue every client with the challenge methods it advertises plus whether the authorization server requires a challenge per client type.
Record the baseline behavior for a credential requested with no challenge plus a credential redeemed with no verifier.
Reconnaissance is complete when every client carries its method inventory plus its baseline challenge-less verdict.

## Detection Channels

Only the entries below fire here; destination, freshness, binding, and approval signals belong to the sibling variants.
- Challenge-less issuance, where the authorization side mints a credential with no challenge attached.
- Any-verifier acceptance, where redemption succeeds with a verifier the requester never committed to.
- Downgrade acceptance, where a trivially replayable challenge method succeeds after a strong one was offered.
- Wrong-verifier acceptance, where redemption succeeds with a mismatched verifier value.
- Comparison-weakness signal, where near-miss verifiers succeed through loose matching.

## Adversarial Capabilities

Verifier probing presupposes challenge control plus credential capture plus redemption access, and it consumes all three.
- Initiate authorization requests with strong, replayable, mismatched, and absent challenge shapes to learn which the server mints.
- Capture legitimately minted credentials for redemption with attacker-chosen verifiers.
- Redeem with absent plus wrong plus near-miss verifier values to oracle the comparison behavior.
- Offer a strong challenge method, then fall back to a replayable one, to test downgrade handling.
- Hold two verifier values at once so the committed and the redeemed values can diverge deliberately.

## Trust Assumptions

At the moment the grant chain executes, the server trusts one binding agreement: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it.
Sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
This variant breaks the verifier-binding clause because a credential minted with no committed challenge redeems against any verifier the redeemer supplies.

## Key Vulnerabilities

### Challenge-Less Issuance Plus Any-Verifier Acceptance

Request credentials with no challenge attached, then redeem each with an attacker-chosen verifier, using shapes like `<no-challenge-request>` followed by `<arbitrary-verifier-redemption>`.
Treat redemption success as the core finding and treat consistent refusal at either side as a negative.
The parent probe step covers only wrong-or-missing verifier replay on challenged credentials and cannot describe challenge-less issuance combined with any-verifier acceptance, so this variant owns the issuance procedure.

### Method Downgrade

Offer a strong challenge method, then submit the same credential request under a trivially replayable method, then omit the method marker while keeping the replayable shape.
Treat acceptance of the weaker shape as a downgrade finding.
The parent probe step names downgrade attempts but never pairs them with issuance-shape coverage, so this variant owns the downgrade confirmation.

### Comparison-Weakness Oracles

Redeem with near-miss verifiers that vary by case, truncation, or trailing bytes, recording one verdict per near-miss shape.
Treat any near-miss success as a comparison finding and treat uniform exact-match enforcement as a negative.
The parent probe step never names comparison oracles, so this variant owns the near-miss procedure.

## Advanced Techniques

No advanced divergence rides here beyond the oracle core, because downgrade plus issuance plus comparison exhaust the verifier surface.
Carry replayable-method acceptance discovered during downgrade back into the issuance probe as a parameter rather than a separate technique.

## Bypass Techniques

Bypass forms are the check values this variant defeats, each confirmed through redemption rather than request shape alone.
- Absent challenges pass an issuance side that treats the challenge as advisory.
- Arbitrary verifiers pass a redemption side that never joins the verifier to the committed challenge.
- Replayable methods pass a server that advertises strong methods but honors weak ones.
- Near-miss verifiers pass a comparison that normalises case or truncates before checking.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Verifier findings chain forward into credential theft because an unenforced check without a stolen credential is only a policy gap.
- Hand a network- or log-leaked credential to the any-verifier redemption as the takeover proof.
- Hand a destination-validation acceptance from the redirect companion to this variant so the stolen credential arrives through the weaker check.
- Treat analytics plus log leakage of credentials as the supply channel that makes any-verifier acceptance exploitable.

## Testing Methodology

Verification runs issuance-without-challenge first and everything else follows, because no oracle is meaningful before the server mints the weak shape.
1. **Inventory methods** - list every client with its advertised challenge methods plus the server requirement per client type plus the baseline challenge-less verdict, and the step completes when no unlisted client or method remains.
2. **Probe challenge-less issuance** - request credentials with no challenge over parent step P4, which names replay plus downgrade on challenged credentials but never names challenge-less issuance with any-verifier acceptance or comparison-weakness oracles, and the step completes when every client carries an issuance verdict per shape.
3. **Oracle the verifier** - redeem each minted credential with absent plus wrong plus arbitrary verifiers and record one verdict per shape, and the step completes when every credential shows refusal or a documented acceptance.
4. **Confirm downgrade** - fall back from the strong method to the replayable shape and record each verdict, and the step completes when every fallback shows refusal or a documented acceptance.
5. **Oracle the comparison** - redeem with near-miss verifiers varying by case plus truncation plus trailing bytes, and the step completes when every near-miss shows refusal or a documented acceptance.

## False Positives

Stop when the evidence shows the verifier check holds, because refused redemptions are only noise.
- Strict strong-method requirement with challenge-less issuance refused on public clients.
- Exact-match verifier validation with every absent plus wrong plus near-miss redemption refused.
- Downgrade fallback refused with the strong method enforced end to end.
- Redemption failures caused by credential expiry rather than verifier rejection, confirmed by re-minting before judging.

## Pro Tips

Verification rewards fresh credentials plus one verifier shape at a time plus exact logging.
1. Mint a fresh credential per verifier shape so expiry never poses as enforcement.
2. Test challenge-less issuance before any oracle so the weakest shape names itself first.
3. Vary exactly one verifier property per redemption and log each verdict behind its shape.
4. Confirm downgrade with the method marker omitted as well as downgraded.
5. Stop promoting refused redemptions and record them as refusals rather than inconclusive.

## Tooling

Drive the grant chain by hand so every challenge and verifier value stays under tester control.
Decode arriving credential structure locally to confirm which challenge each credential actually committed to before redeeming it.

## Summary

A verifier check that mints without a challenge or redeems against any value lets stolen credentials convert to sessions.
Verification probes issuance first, oracles each verifier shape, and confirms downgrade plus comparison before claiming impact.
