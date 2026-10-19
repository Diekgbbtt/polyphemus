---
name: optimistic-guard-evasion
description: Optimistic guard evasion through concurrency-token omission when guards stay optional, stale-version replay when servers ignore versions, and cross-path validation-gap probing when channels enforce unevenly.
metadata:
  version: 1.0.0
---

# Optimistic Guard Evasion

Optimistic concurrency promises that stale writes fail yet an omitted token or a replayed version can commit over a sibling write.
This variant drops concurrency tokens, replays stale versions, and probes each channel for paths that skip validation entirely.
The goal is lost-update overwrites plus privilege or entitlement errors that persist in the authoritative source.

## Attack Surface

- **Applicability**: centers on workflows that carry a concurrency token or version field alongside a state-changing operation.
- **Surface composition**: update plus transfer plus role-change operations where correctness depends on the server rejecting mismatched versions.
- **Widening factors**: optional tokens, tokens accepted but never validated, and tokens enforced on one channel but ignored on another all widen the surface.
- **Out-of-scope variant**: dedup-key scope failures ride in idempotency-dedup-bypass rather than here, because this variant owns only token-mediated guards.

## Reconnaissance

- **Guard mapping**: optimistic maps the guard before mutating it, because blind omission cannot distinguish absent validation from tolerant parsing.
- **Token enumeration**: enumerate which operations carry a concurrency token and note which precondition check claims version enforcement and where its authoritative source lives.
- **Enforcement probe**: probe enforcement by replaying a recorded update with the token removed and with a stale version substituted, then compare which replay the server accepts.
- **Per-channel recording**: record per-channel enforcement separately, because one channel often validates while a sibling channel commits unchecked.

## Detection Channels

- **Channel scope**: optimistic listens for guard-shaped overwrites.
- **Sequential-versus-parallel divergence**: a sequential request fails but parallel requests succeed when tokens are omitted or staled.
- **Response-shape divergence**: distinct response shapes or timings for simultaneous versus sequential versioned requests.
- **Stale-write overwrites**: duplicate rows or overwritten entitlements where the later stale write erased the earlier fresh write.
- **Lost-update imbalance**: a ledger imbalance where two increments net to one or two assignments collapse to the stale value.

## Adversarial Capabilities

- **Prerequisites**: optimistic presupposes versioned-write access plus token control plus multi-channel reach, and it consumes all three.
- **Legitimate operation access**: operate as a legitimate authenticated user entitled to perform the versioned operation at least once.
- **Token mutation**: omit concurrency tokens and substitute stale versions inside otherwise valid operations.
- **Simultaneous firing**: fire identical and token-mutated operations simultaneously within the same commit window.
- **Alternate-channel reach**: reach the same state change through alternate channels to test per-path enforcement gaps.
- **Authoritative-source reads**: read the authoritative source after the burst to confirm which write won durably.

## Trust Assumptions

- **The agreement**: concurrent executions of one state-changing workflow interleave safely: checks precede effects atomically, dedup keys bind one intent to one effect durably, version guards validate on every path, and published state becomes visible before dependent actions proceed, and sensitive balance plus entitlement plus ledger state leaks only when an execution commits outside these clauses.
- **The failing clause**: the variant breaks the version-guard clause because an omitted or stale concurrency token commits without validation.

## Key Vulnerabilities

### Concurrency-Token Omission

- **Token omission**: drop the token from placeholder shape `<versioned-update-payload>` plus `<concurrency-token>` and submit concurrently, because omission success is the first bent behavior the parent never describes.
- **Acceptance adjudication**: treat acceptance of a tokenless write as enforcement absence and treat rejection as a prompt to try stale replay next.
- **Omission ownership**: the parent concurrent-requests step prescribes identical inputs and cannot describe token mutation, so this variant owns the omission procedure.

### Stale-Version Replay

- **Stale replay**: replay a previously observed version after a fresh write has advanced the record, because stale acceptance is the second bent behavior.
- **Replay sequencing**: sequence the replay as read version one plus commit version two plus replay version one, then confirm which value the authoritative source retains.
- **Lost-update adjudication**: treat retention of the stale value as a lost update rather than as display lag.

### Cross-Path Validation-Gap Probing

- **Cross-path repetition**: repeat the omission and stale probes through every channel that reaches the same state change, because per-path gaps are the third bent behavior.
- **Lane comparison**: compare channel verdicts lane by lane and treat a channel that commits unchecked while its sibling rejects as the finding locus.
- **Graphql pointer**: name the graphql skill at the schema-and-resolver discovery step rather than restating its mechanics.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no throttle difference changes the guard step itself.
- **Method-switched paths**: method-switched same-effect paths join the probe set when an alternate verb reaches the same state change.
- **Identity rotation**: rotate identities across sessions to widen the burst when per-entity throttles cap one principal.
- **Proxy-technique pointer**: name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- **Defence-bypass pointer**: name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: optimistic chains forward into impact once the stale write is durable, because a transient overwrite alone proves nothing.
- **Invariant-check handoff**: hand a durable entitlement overwrite to business-logic invariant checks to test privilege persistence above the granted role.
- **Identifier-substitution handoff**: hand revealed workflow identifiers to identifier-substitution checks to replay stale versions against sibling resources.
- **Authorization-principal pointer**: name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Optimistic mutates the token first and everything else confirms, because no later step is meaningful without a guard-evading write.
1. **Model the version invariant** - state the compare-and-commit rule plus the token source plus the authoritative record, and the step completes when every guard names its store.
2. **Baseline single execution** - perform the versioned operation once with a fresh token and record the accept behavior, and the step completes when the single-run accept and stale-reject behavior is fully characterized.
3. **Fire the guard-evasion burst** - submit tokenless plus stale-versioned operations simultaneously with placeholder shape `<versioned-update-payload>` plus `<concurrency-token>`, and the step completes when every lane shows a recorded outcome.
4. **Probe cross-path gaps** - repeat the omission and stale probes through each alternate channel, and the step completes when each channel carries an enforced or unenforced verdict.
5. **Confirm durability** - re-read the authoritative record after settling and demonstrate the persisting overwrite, and the step completes when the winning value is reproducible with a minimal repeatable request set.

## False Positives

- **Guard-held stop**: stop when the evidence shows the guard held, because enforced versioning is not a finding.
- **Rejected stale writes**: stale writes are rejected with a version-conflict signal and no ledger change.
- **Idempotent operations**: truly idempotent operations with enforced token checks or unique constraints behind them.
- **Visual-only echoes**: echoes without durable overwrite in the authoritative source.
- **Serializable transactions**: serializable transactions or correct advisory locks serialize the tokenless lanes.

## Pro Tips

- **Discipline**: optimistic rewards token discipline plus channel comparison plus minimal bursts.
- **Single omission probes**: prefer single omission probes before scaling, then scale only to map the overwrite threshold.
- **Direct calls**: favor direct calls over scripted interface clicks so token mutation stays exact.
- **Lane logging**: log every lane behind its token value and timestamp so the winning write is attributable.
- **Settled record re-read**: re-read the authoritative record after settling and report only persisting overwrites.
- **Transient-echo discipline**: stop promoting transient echoes and record them as inconclusive rather than positive.

## Summary

A version guard that stays optional or unchecked on some path lets stale writes win.
Optimistic omits the token, replays stale versions, probes every path, and confirms only overwrites that persist in the authoritative source.
