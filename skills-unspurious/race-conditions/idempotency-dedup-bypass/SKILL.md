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

Idempotency applicability centers on workflows that accept a client-supplied dedup key alongside a state-changing operation.
The surface holds create plus apply plus redeem plus transfer operations where exactly-once execution depends on the key rather than on an atomic commit guard.
Keys scoped to path rather than principal, keys held only in volatile cache, and keys with short lifetimes that re-arm after eviction all widen the surface.
Pure read-modify-write increments without any dedup layer ride in the parent core rather than here, because this variant owns only key-mediated dedup.

## Reconnaissance

Idempotency maps the key contract before racing, because blind reuse cannot distinguish scope failure from durability failure.
Enumerate where the dedup check sits relative to the effect commit and note whether the check store is durable or cache-only.
Probe scope by replaying a recorded finalize request with a foreign key and with a same-principal key separately, then compare which replay the server accepts.
Record key lifetime plus binding breadth plus backing store, because a key honored from cache but absent from durable storage re-arms after eviction.

## Detection Channels

Idempotency listens for dedup-shaped doubles, so only the entries below are live here.
- Sequential request fails but parallel requests succeed with the same dedup key material.
- Second effect commits while the response claims deduplication for one intent.
- Foreign or replayed key still commits a second effect in the authoritative source.
- Balance or entitlement delta persists across a fresh read after the dedup response claimed suppression.

## Adversarial Capabilities

Idempotency presupposes parallel submission plus key reuse plus ledger readback, and it consumes all three.
- Fire identical state-changing operations with shared dedup key material inside the same commit window.
- Operate as a legitimate authenticated user entitled to perform the operation at least once.
- Reuse keys across principals and paths to test scope binding breadth.
- Replay recorded finalize requests through direct calls outside the scripted interface.
- Read the authoritative source after the burst to separate durable doubles from suppressed responses.

## Trust Assumptions

The feature trusts that concurrent executions of one state-changing workflow interleave safely: checks precede effects atomically, dedup keys bind one intent to one effect durably, version guards validate on every path, and published state becomes visible before dependent actions proceed.
Sensitive balance plus entitlement plus ledger state leaks only when an execution commits outside these clauses.
This variant breaks the durable dedup clause because a reused key suppresses only the response while the effect commits again.

## Key Vulnerabilities

### Cross-Principal Key Scope Reuse

Reuse one key across principals and paths with placeholder shape `<state-change-payload>` plus `<dedup-key>`, because scope failure is the first bent behavior the parent never describes.
Treat acceptance of a foreign key as scope failure and treat acceptance of a same-principal replay after success as durability failure.
The parent concurrent-requests step covers only identical-input firing and cannot describe cross-principal reuse, so this variant owns the scope procedure.

### Cache-Before-Commit Window Probing

Strike before the dedup store is written by firing the burst inside the check-to-store gap, because the window between effect start and key persistence is the second bent behavior.
Ramp tightness from loose pairs toward synchronized release until the second lane either dedups cleanly or commits through the gap.
Treat a second commit that lands only under tight synchronization as window evidence rather than as scope evidence.

### Response-Versus-Effect Dedup Forensics

Confirm every suspected double in the authoritative ledger rather than in the response body, because application dedup can drop only the response while side effects still occur.
Re-read balances plus entitlements plus fulfillment records after a settling delay and require the double to persist.
Treat doubles visible only in transient responses as inconclusive rather than positive.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no channel difference changes the dedup step itself.
- Identity rotation across sessions widens the burst when per-entity throttles cap one principal.
- Slow-backend provocation widens the check-to-store gap so the second lane lands before the key persists.
- Name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- Name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.

## Chaining Attacks

Idempotency chains forward into impact once the double is durable, because a suppressed response alone proves nothing.
- Hand a durable double fulfillment to business-logic invariant checks to test double-refund summation above the captured amount.
- Hand revealed workflow identifiers to identifier-substitution checks to replay keys against sibling resources.
- Name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Idempotency races the key first and everything else confirms, because no later step is meaningful without a key-mediated double.
1. **Model the dedup invariant** - state the one-intent-one-effect rule plus the key scope claim plus the authoritative source, and the step completes when every claim names its store.
2. **Baseline single execution** - perform the operation once with a fresh key and record the ledger delta plus the replay behavior, and the step completes when the single-run accept and deny behavior is fully characterized.
3. **Fire the key-reuse burst** - submit identical operations simultaneously with shared keys across principals and paths, and the step completes when every lane shows a recorded outcome with its key material logged.
4. **Probe the commit window** - tighten synchronization around the check-to-store gap with placeholder shape `<state-change-payload>` plus `<dedup-key>`, and the step completes when the tightest achievable interleaving either held or broke the invariant reproducibly.
5. **Forensicate response versus effect** - replay foreign keys plus same-principal keys and re-read the authoritative source after settling, and the step completes when each key carries a scope verdict and each suspected double carries a durable or transient verdict.
6. **Confirm durability** - demonstrate the persisting value gain with exact amounts in the ledger, and the step completes when the imbalance is reproducible with a minimal repeatable request set.

## False Positives

Stop when the evidence shows dedup held, because a clean key store is not a finding.
- Durable single effect with deduped responses and no second ledger write.
- Policy-allowed duplicate issuance such as documented goodwill credits with matching ledger annotations.
- Visual-only echoes without durable state change in the authoritative source.
- Doubles that collapse after settling because a compensating job correctly reversed the second commit.

## Pro Tips

Idempotency rewards key discipline plus ledger discipline plus minimal bursts.
1. Prefer the smallest burst that reaches the gap, then tighten timing only to map the window.
2. Favor direct calls over scripted interface clicks so lane timing stays tight.
3. Log every lane behind its key and timestamp so the double is attributable.
4. Re-read the ledger after settling and report only persisting imbalances.
5. Stop promoting transient echoes and record them as inconclusive rather than positive.

## Summary

A dedup key without durable broad-scoped binding suppresses responses while effects commit twice.
Idempotency reuses the key across principals, probes the commit window, and confirms only doubles that persist in the authoritative source.
