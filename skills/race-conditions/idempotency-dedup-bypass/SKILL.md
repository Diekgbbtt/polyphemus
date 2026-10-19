---
name: idempotency-dedup-bypass
description: Idempotency dedup bypass through cross-principal key reuse when scope binds narrowly, cache-before-commit window probing when stores lag, and response-versus-effect forensics when dedup drops responses only.
metadata:
  version: 1.0.0
---

# Idempotency Dedup Bypass

Idempotency controls promise one effect per intent yet a reused key can commit a second effect while returning a deduped response.
This variant reuses keys across principals and paths, probes the window before the dedup store commits, and forensically separates response suppression from effect suppression.
The goal is duplicate fulfillment plus duplicate credit that persists in the authoritative source despite the dedup layer.

## Attack Surface

- **Applicability**: centers on workflows that accept a client-supplied dedup key alongside a state-changing operation.
- **Surface composition**: create plus apply plus redeem plus transfer operations where exactly-once execution depends on the key rather than on an atomic commit guard.
- **Widening factors**: keys scoped to path rather than principal, keys held only in volatile cache, and keys with short lifetimes that re-arm after eviction all widen the surface.
- **Out-of-scope variant**: pure read-modify-write increments without any dedup layer ride in the parent core rather than here, because this variant owns only key-mediated dedup.

## Reconnaissance

- **Key-contract mapping**: idempotency maps the key contract before racing, because blind reuse cannot distinguish scope failure from durability failure.
- **Check-placement enumeration**: enumerate where the dedup check sits relative to the effect commit and note whether the check store is durable or cache-only.
- **Scope probe**: probe scope by replaying a recorded finalize request with a foreign key and with a same-principal key separately, then compare which replay the server accepts.
- **Key-property recording**: record key lifetime plus binding breadth plus backing store, because a key honored from cache but absent from durable storage re-arms after eviction.

## Detection Channels

- **Channel scope**: idempotency listens for dedup-shaped doubles.
- **Sequential-versus-parallel divergence**: a sequential request fails but parallel requests succeed with the same dedup key material.
- **Response-versus-effect split**: a second effect commits while the response claims deduplication for one intent.
- **Foreign-key acceptance**: a foreign or replayed key still commits a second effect in the authoritative source.
- **Persisting delta**: a balance or entitlement delta persists across a fresh read after the dedup response claimed suppression.

## Adversarial Capabilities

- **Prerequisites**: idempotency presupposes parallel submission plus key reuse plus ledger readback, and it consumes all three.
- **Shared-key firing**: fire identical state-changing operations with shared dedup key material inside the same commit window.
- **Legitimate operation access**: operate as a legitimate authenticated user entitled to perform the operation at least once.
- **Cross-principal key reuse**: reuse keys across principals and paths to test scope binding breadth.
- **Finalize replay**: replay recorded finalize requests through direct calls outside the scripted interface.
- **Authoritative-source reads**: read the authoritative source after the burst to separate durable doubles from suppressed responses.

## Trust Assumptions

- **The agreement**: concurrent executions of one state-changing workflow interleave safely: checks precede effects atomically, dedup keys bind one intent to one effect durably, version guards validate on every path, and published state becomes visible before dependent actions proceed, and sensitive balance plus entitlement plus ledger state leaks only when an execution commits outside these clauses.
- **The failing clause**: the variant breaks the durable dedup clause because a reused key suppresses only the response while the effect commits again.

## Key Vulnerabilities

### Cross-Principal Key Scope Reuse

- **Cross-principal reuse**: reuse one key across principals and paths with placeholder shape `<state-change-payload>` plus `<dedup-key>`, because scope failure is the first bent behavior the parent never describes.
- **Acceptance adjudication**: treat acceptance of a foreign key as scope failure and treat acceptance of a same-principal replay after success as durability failure.
- **Scope ownership**: the parent concurrent-requests step covers only identical-input firing and cannot describe cross-principal reuse, so this variant owns the scope procedure.

### Cache-Before-Commit Window Probing

- **Window strike**: strike before the dedup store is written by firing the burst inside the check-to-store gap, because the window between effect start and key persistence is the second bent behavior.
- **Tightness ramp**: ramp tightness from loose pairs toward synchronized release until the second lane either dedups cleanly or commits through the gap.
- **Window adjudication**: treat a second commit that lands only under tight synchronization as window evidence rather than as scope evidence.

### Response-Versus-Effect Dedup Forensics

- **Ledger confirmation**: confirm every suspected double in the authoritative ledger rather than in the response body, because application dedup can drop only the response while side effects still occur.
- **Partial-fulfilment reading**: treat partial fulfilment as a double too - one lane can return an error while both effects commit, so read the ledger rather than the pair of responses.
- **Settled re-read**: re-read balances plus entitlements plus fulfillment records after a settling delay and require the double to persist.
- **Transient-double adjudication**: treat doubles visible only in transient responses as inconclusive rather than positive.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no channel difference changes the dedup step itself.
- **Identity rotation**: rotate identities across sessions to widen the burst when per-entity throttles cap one principal.
- **Slow-backend provocation**: widen the check-to-store gap with slow-backend provocation so the second lane lands before the key persists.
- **Proxy-technique pointer**: name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- **Defence-bypass pointer**: name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: idempotency chains forward into impact once the double is durable, because a suppressed response alone proves nothing.
- **Invariant-check handoff**: hand a durable double fulfillment to business-logic invariant checks to test double-refund summation above the captured amount.
- **Identifier-substitution handoff**: hand revealed workflow identifiers to identifier-substitution checks to replay keys against sibling resources.
- **Authorization-principal pointer**: name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Idempotency races the key first and everything else confirms, because no later step is meaningful without a key-mediated double.
1. **Model the dedup invariant** - state the one-intent-one-effect rule plus the key scope claim plus the authoritative source, and the step completes when every claim names its store.
2. **Baseline single execution** - perform the operation once with a fresh key and record the ledger delta plus the replay behavior, and the step completes when the single-run accept and deny behavior is fully characterized.
3. **Fire the key-reuse burst** - submit identical operations simultaneously with shared keys across principals and paths, and the step completes when every lane shows a recorded outcome with its key material logged.
4. **Probe the commit window** - tighten synchronization around the check-to-store gap with placeholder shape `<state-change-payload>` plus `<dedup-key>`, and the step completes when the tightest achievable interleaving either held or broke the invariant reproducibly.
5. **Forensicate response versus effect** - replay foreign keys plus same-principal keys and re-read the authoritative source after settling, and the step completes when each key carries a scope verdict and each suspected double carries a durable or transient verdict.
6. **Confirm durability** - demonstrate the persisting value gain with exact amounts in the ledger, and the step completes when the imbalance is reproducible with a minimal repeatable request set.

## False Positives

- **Dedup-held stop**: stop when the evidence shows dedup held, because a clean key store is not a finding.
- **Durable single effect**: one durable effect with deduped responses and no second ledger write.
- **Policy-allowed issuance**: duplicate issuance such as documented goodwill credits with matching ledger annotations.
- **Visual-only echoes**: echoes without durable state change in the authoritative source.
- **Settling doubles**: doubles collapse after settling because a compensating job correctly reversed the second commit.

## Pro Tips

- **Discipline**: idempotency rewards key discipline plus ledger discipline plus minimal bursts.
- **Minimal burst**: prefer the smallest burst that reaches the gap, then tighten timing only to map the window.
- **Direct calls**: favor direct calls over scripted interface clicks so lane timing stays tight.
- **Lane logging**: log every lane behind its key and timestamp so the double is attributable.
- **Settled ledger re-read**: re-read the ledger after settling and report only persisting imbalances.
- **Transient-echo discipline**: stop promoting transient echoes and record them as inconclusive rather than positive.

## Summary

A dedup key without durable broad-scoped binding suppresses responses while effects commit twice.
Idempotency reuses the key across principals, probes the commit window, and confirms only doubles that persist in the authoritative source.
