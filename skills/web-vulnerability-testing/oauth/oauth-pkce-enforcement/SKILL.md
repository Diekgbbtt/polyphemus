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

- **Applicability**: centers on a grant flow whose authorization entry point accepts a challenge derived from a verifier the client keeps, and whose redemption entry point must recheck that verifier.
- **Client dependence**: public clients that cannot hold long-term secrets depend on this binding most, while confidential clients carry it as defense in depth.
- **Challenge-less servers**: authorization servers that still issue credentials with no challenge attached widen the surface to challenge-less redemption.
- **Out-of-scope flows**: flows with no user session fall outside this variant.

## Reconnaissance

- **Verifier-surface mapping**: map the verifier surface before breaking it.
- **Method catalogue**: catalogue every client with the challenge methods it advertises plus whether the authorization server requires a challenge per client type.
- **Baseline recording**: record the baseline behavior for a credential requested with no challenge plus a credential redeemed with no verifier.
- **Completion criterion**: reconnaissance is complete when every client carries its method inventory plus its baseline challenge-less verdict.

## Detection Channels

- **Channel scope**: destination, freshness, binding, and approval signals belong to the sibling variants.
- **Challenge-less issuance**: the authorization side mints a credential with no challenge attached.
- **Any-verifier acceptance**: redemption succeeds with a verifier the requester never committed to.
- **Downgrade acceptance**: a trivially replayable challenge method succeeds after a strong one was offered.
- **Wrong-verifier acceptance**: redemption succeeds with a mismatched verifier value.
- **Comparison-weakness signal**: near-miss verifiers succeed through loose matching.

## Adversarial Capabilities

- **Prerequisites**: verifier probing presupposes challenge control plus credential capture plus redemption access, and it consumes all three.
- **Challenge-shape requests**: initiate authorization requests with strong, replayable, mismatched, and absent challenge shapes to learn which the server mints.
- **Credential capture**: capture legitimately minted credentials for redemption with attacker-chosen verifiers.
- **Verifier-value redemption**: redeem with absent plus wrong plus near-miss verifier values to oracle the comparison behavior.
- **Downgrade fallback**: offer a strong challenge method, then fall back to a replayable one, to test downgrade handling.
- **Divergent values**: hold two verifier values at once so the committed and the redeemed values can diverge deliberately.

## Trust Assumptions

- **The agreement**: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it, and sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
- **The failing clause**: this variant breaks the verifier-binding clause because a credential minted with no committed challenge redeems against any verifier the redeemer supplies.

## Key Vulnerabilities

### Challenge-Less Issuance Plus Any-Verifier Acceptance

- **Issuance-redemption pairing**: request credentials with no challenge attached, then redeem each with an attacker-chosen verifier, using shapes like `<no-challenge-request>` followed by `<arbitrary-verifier-redemption>`.
- **Issuance verdict**: treat redemption success as the core finding and treat consistent refusal at either side as a negative.
- **Issuance ownership**: the parent probe step covers only wrong-or-missing verifier replay on challenged credentials and cannot describe challenge-less issuance combined with any-verifier acceptance, so this variant owns the issuance procedure.

### Method Downgrade

- **Downgrade sequence**: offer a strong challenge method, then submit the same credential request under a trivially replayable method, then omit the method marker while keeping the replayable shape.
- **Downgrade verdict**: treat acceptance of the weaker shape as a downgrade finding.
- **Downgrade ownership**: the parent probe step names downgrade attempts but never pairs them with issuance-shape coverage, so this variant owns the downgrade confirmation.

### Comparison-Weakness Oracles

- **Near-miss redemption**: redeem with near-miss verifiers that vary by case, truncation, or trailing bytes, recording one verdict per near-miss shape.
- **Comparison verdict**: treat any near-miss success as a comparison finding and treat uniform exact-match enforcement as a negative.
- **Comparison ownership**: the parent probe step never names comparison oracles, so this variant owns the near-miss procedure.

## Advanced Techniques

- **Divergence scope**: no advanced divergence rides here beyond the oracle core, because downgrade plus issuance plus comparison exhaust the verifier surface.
- **Replayable-method parameter**: carry replayable-method acceptance discovered during downgrade back into the issuance probe as a parameter rather than a separate technique.

## Bypass Techniques

- **Bypass scope**: bypass forms are the check values this variant defeats, each confirmed through redemption rather than request shape alone.
- **Absent challenges**: pass an issuance side that treats the challenge as advisory.
- **Arbitrary verifiers**: pass a redemption side that never joins the verifier to the committed challenge.
- **Replayable methods**: pass a server that advertises strong methods but honors weak ones.
- **Near-miss verifiers**: pass a comparison that normalises case or truncates before checking.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: verifier findings chain forward into credential theft because an unenforced check without a stolen credential is only a policy gap.
- **Leaked-credential handoff**: hand a network- or log-leaked credential to the any-verifier redemption as the takeover proof.
- **Destination-validation handoff**: hand a destination-validation acceptance from the redirect companion to this variant so the stolen credential arrives through the weaker check.
- **Supply channel**: treat analytics plus log leakage of credentials as the supply channel that makes any-verifier acceptance exploitable.

## Testing Methodology

Verification runs issuance-without-challenge first and everything else follows, because no oracle is meaningful before the server mints the weak shape.
1. **Inventory methods** - list every client with its advertised challenge methods plus the server requirement per client type plus the baseline challenge-less verdict, and the step completes when no unlisted client or method remains.
2. **Probe challenge-less issuance** - request credentials with no challenge over parent step P4, which names replay plus downgrade on challenged credentials but never names challenge-less issuance with any-verifier acceptance or comparison-weakness oracles, and the step completes when every client carries an issuance verdict per shape.
3. **Oracle the verifier** - redeem each minted credential with absent plus wrong plus arbitrary verifiers and record one verdict per shape, and the step completes when every credential shows refusal or a documented acceptance.
4. **Confirm downgrade** - fall back from the strong method to the replayable shape and record each verdict, and the step completes when every fallback shows refusal or a documented acceptance.
5. **Oracle the comparison** - redeem with near-miss verifiers varying by case plus truncation plus trailing bytes, and the step completes when every near-miss shows refusal or a documented acceptance.

## False Positives

- **Verifier-held stop**: stop when the evidence shows the verifier check holds, because refused redemptions are only noise.
- **Strict strong-method requirement**: refuse challenge-less issuance on public clients.
- **Exact-match validation**: refuse every absent plus wrong plus near-miss redemption.
- **Downgrade refusal**: refuse the fallback with the strong method enforced end to end.
- **Expiry failures**: attribute redemption failures to credential expiry rather than verifier rejection, confirmed by re-minting before judging.

## Pro Tips

- **Discipline**: verification rewards fresh credentials plus one verifier shape at a time plus exact logging.
- **Fresh credential per shape**: mint a fresh credential per verifier shape so expiry never poses as enforcement.
- **Issuance-first ordering**: test challenge-less issuance before any oracle so the weakest shape names itself first.
- **Single-property variation**: vary exactly one verifier property per redemption and log each verdict behind its shape.
- **Downgrade confirmation**: confirm downgrade with the method marker omitted as well as downgraded.
- **Refusal recording**: stop promoting refused redemptions and record them as refusals rather than inconclusive.

## Tooling

- **Manual chain driving**: drive the grant chain by hand so every challenge and verifier value stays under tester control.
- **Local credential decoding**: decode arriving credential structure locally to confirm which challenge each credential actually committed to before redeeming it.

## Summary

A verifier check that mints without a challenge or redeems against any value lets stolen credentials convert to sessions.
Verification probes issuance first, oracles each verifier shape, and confirms downgrade plus comparison before claiming impact.
