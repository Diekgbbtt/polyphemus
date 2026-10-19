---
name: bfla-deferred-execution
description: Deferred authorization testing that replays finalize, approval, and background deliveries under a different actor. Use when job creation and finalization may check different callers, when webhook or queue deliveries may skip caller checks, when retries or cached decisions may carry a stale approval.
metadata:
  version: 1.0.0
---

# BFLA Deferred Execution

Action-level authorization fails open when a later step executes under an earlier approval instead of the current actor.
The leading word is deferred: every probe separates creation from execution and replays the later step as a different caller, then reads whether the actor was re-checked.

## Attack Surface

- **Applicability**: a privileged effect happens after its authorizing moment, such as split create-versus-finalize or approve flows, webhook and queue deliveries, idempotent retries of state-changing steps, and edge-cached authorization decisions reused across sessions.
- **Deferred-step forms**: the deferred step may belong to the same actor session, another actor's object, or a machine delivery with no caller at all.
- **Synchronous boundary**: synchronous first-pass invocation stays outside this variant, while only execution separated in time or context enters it.

## Reconnaissance

- **Deferred-step map**: map every deferred step that can cause a privileged effect before replaying anything.
- **Transition coverage**: include multi-step workflows whose transitions each carry their own check, because a transition that carries none is the same missing-check family reached without waiting: record its verdict here and leave the first-pass case to the parent.
- **Chain inventory**: collect interface documents, client bundles, prior HTTP history, and approval transcripts until each job, approval, webhook, and queue endpoint owns a creation-to-execution chain.
- **Silent-step recording**: record which steps name an actor check and which stay silent, since the silent step is the candidate.
- **Baseline confirmation**: confirm the allowed-actor baseline completes the chain before judging any cross-actor replay.

## Detection Channels

- **Deferred-step effect**: a privileged effect from a deferred step replayed by an unentitled caller decides the finding.
- **Background-versus-direct differential**: success via the background step beside denial via the direct call confirms the execution-context gap.
- **Redelivery state change**: state changes applied by redelivered webhooks or retried finalizes without a fresh actor check confirm missing rebinding.
- **Session-swap reuse**: session swaps that inherit a cached edge decision confirm stale-approval reuse.

## Adversarial Capabilities

- **Two-role sessions**: this variant presupposes working sessions for at least two roles plus the ability to drive multi-step flows, and it consumes cross-context replay ability.
- **Cross-actor flow control**: it consumes the ability to create as an allowed actor and finalize or approve as another, holding each step's credential explicit.
- **Delivery replay**: it consumes the ability to replay webhook and queue deliveries and to retry idempotent steps on demand.
- **Session swap**: it consumes the ability to swap sessions against cached decisions to test reuse.
- **Principal handling**: principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

- **The agreement**: every route and handler reaching the privileged function enforces the same caller-to-action binding, edge and interface gates transfer no authority downstream, actor identity comes only from verified token claims rather than request hints, and an approval recorded in a prior step never authorizes a later execution, so no lower-privileged caller causes a privileged effect and no privileged state leaks to an unentitled observer.
- **The failing clause**: a finalize, approve, replay, retry, or cached decision executes under a prior approval instead of rebinding the current actor at execution time.

## Key Vulnerabilities

- **Cross-context finalize**: cross-context finalize plus webhook replay plus idempotent retry plus cached-decision reuse is the bent step this variant owns over the parent.
- **Split-flow cross-actor replay**: drive each split flow by creating as an allowed actor and finalizing or approving as another actor or another actor's object, and record whether the later step re-checked the caller.
- **Delivery replay**: replay each webhook and queue delivery that performs a privileged action, and record whether any delivery verifies its caller.
- **Retry and cache reuse**: retry each idempotent finalize without a fresh actor grant, and swap sessions against edge-cached decisions to test whether the stored verdict authorizes the call.
- **Parent-step boundary**: the parent background step says to confirm re-validation but never describes cross-actor finalize, delivery replay, retry without grant, or cache reuse, so this variant owns that procedure.

## Bypass Techniques

- **Stale-approval reuse**: stale-approval reuse is the control defeat live for this variant.
- **No-grant replay**: replay the finalize or approve step with no actor grant beyond the prior approval, keeping the object and payload constant.
- **Delivery redelivery**: redeliver the webhook or queue task with a different caller or none, and read whether the effect still applies.
- **Session swap**: swap sessions under an unchanged cached decision, and read whether the new actor inherits the old verdict.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. Build the actor-by-action matrix by enumerating each role against each privileged action including deferred steps, with completion when every deferred step has an expected-actor cell (procedure owned by `two-principal-authz`).
2. Establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
3. Chain the flows by driving each create-then-execute sequence as the allowed actor, with completion when every deferred step shows its baseline effect and its named actor check or silence.
4. Replay across actors by finalizing or approving as another caller and by redelivering webhooks and queue tasks under a different credential, with completion when every deferred step carries a cross-actor attempt beside its baseline.
5. Retry and swap by reissuing idempotent finalizes without fresh grants and by swapping sessions against cached edge decisions, with completion when every retry and reuse case carries a recorded verdict.
6. Confirm the effect by comparing state snapshots and audit entries across each pair, with completion when every positive shows a privileged change rather than a status artifact alone.

## False Positives

- **Read-only background reads**: discard read-only background reads with no privileged effect, since notification without state change is not an execution-binding failure.
- **Intentionally open preview flows**: discard intentionally open preview flows under a clear policy, confirming the policy before filing.
- **Stubbed job and webhook endpoints**: discard stubbed job and webhook endpoints in simulated environments that record no real effect.
- **Premature single-delivery successes**: discard single-delivery successes judged before replay, since one allowed execution proves nothing about rebinding.

## Pro Tips

- **Creation-execution separation**: separate creation from execution in every test, since the later step is always the question.
- **Cross-actor finalize**: create as the allowed actor and finalize as the other, keeping object and payload constant so only the actor varies.
- **First-class deferred actions**: treat jobs, webhooks, retries, and cached decisions as first-class privileged actions with their own matrix cells.
- **Minimal proofs**: prefer minimal proofs, such as one cross-actor finalize or one redelivery that applies a privileged change under an unentitled caller.
- **Direct-denial caution**: never conclude resistance from a direct-call denial, since the background step may still execute unchecked.

## Summary

Every deferred step must rebind the current actor at execution time, since no prior approval transfers forward.
Replay each finalize, approval, delivery, retry, and cached decision as another caller, and file every step that executes without re-checking.
