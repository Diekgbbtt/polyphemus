---
name: cross-service-consistency-race
description: Cross-service consistency race through write-versus-publish ordering when visibility lags, retry-storm induction when delivery repeats, and compensation triggering when rollback cannot prevent success.
metadata:
  version: 1.0.0
---

# Cross-Service Consistency Race

Distributed workflows promise that a write becomes visible before dependents act yet a lagging publish lets a second service act on stale state.
This variant maps write-versus-publish ordering, induces retries with provoked timeouts, and triggers compensation that cannot prevent the original success.
The goal is duplicate side effects plus over-issuance plus inconsistent aggregates that persist across service ledgers.

## Attack Surface

- **Applicability**: cross-service applicability centers on multi-step sagas and asynchronous jobs with eventual consistency between services.
- **Surface composition**: the surface holds reserve plus commit plus publish plus compensate sequences where correctness depends on visibility ordering rather than on a single atomic guard.
- **Widening factors**: writes committed before publication, consumers without idempotent handling, and compensations that roll back without blocking the success path all widen the surface.
- **Out-of-scope variant**: single-service increments ride in the parent core rather than here, because this variant owns only distributed windows.

## Reconnaissance

- **Ordering mapping**: cross-service maps the ordering before triggering it, because blind bursts cannot distinguish a saga window from a single-store gap.
- **Write-versus-publish enumeration**: enumerate when state is written versus published and note what retries plus compensations exist and which service owns the authoritative ledger.
- **Retry probe**: probe retry semantics by provoking a timeout once and observing whether the consumer replays the side effect without dedup.
- **Lag recording**: record the visibility lag per dependent service, because the window lives in the lag rather than in request timing alone.

## Detection Channels

- **Channel scope**: cross-service listens for ordering-shaped divergence, so only the entries below are live here.
- **Audit-log disorder**: audit logs out of order across services with the dependent action timestamped before the authoritative write.
- **Correlation-identifier gaps**: missing or duplicate correlation identifiers across the saga trace for one intent.
- **Duplicate downstream writes**: where one worker retry produces a second persistent side effect.
- **Inconsistent aggregates**: where service ledgers disagree after the burst settles.

## Adversarial Capabilities

- **Prerequisites**: cross-service presupposes distributed reach plus retry induction plus ledger readback across services, and it consumes all three.
- **Legitimate workflow access**: operate as a legitimate authenticated user entitled to start the distributed workflow at least once.
- **Downstream timing**: act in a downstream service before the upstream write becomes visible there.
- **Retry induction**: provoke timeouts to induce retries that replay side effects through at-least-once delivery.
- **Load distribution**: distribute load across nodes and regions to widen the visibility window where routing permits.
- **Service-ledger reads**: read each service ledger after settling to confirm which writes persisted where.

## Trust Assumptions

- **The agreement**: the feature trusts that concurrent executions of one state-changing workflow interleave safely: checks precede effects atomically, dedup keys bind one intent to one effect durably, version guards validate on every path, and published state becomes visible before dependent actions proceed.
- **The exposure**: sensitive balance plus entitlement plus ledger state leaks only when an execution commits outside these clauses.
- **The failing clause**: this variant breaks the visibility-ordering clause because a dependent action proceeds before the authoritative write becomes visible.

## Key Vulnerabilities

### Write-Versus-Publish Ordering Exploitation

- **Write-site mapping**: map the write site versus the publish site and strike the dependent service inside the lag, because ordering exploitation is the first bent behavior the parent never describes.
- **Probe sequencing**: sequence the probe as commit upstream plus act downstream before visibility plus re-read both ledgers, then compare which service observed which state.
- **Ordering ownership**: the parent identify-reads-writes step locates reads by store and cannot describe publish ordering with compensation semantics, so this variant owns the ordering procedure.

### Timeout-Induced Retry Storms

- **Timeout provocation**: provoke a timeout to force the producer to redeliver, because retry-driven duplication is the second bent behavior.
- **Redelivery observation**: submit placeholder shape `<distributed-workflow-payload>` with a slow-dependent leg and observe whether each redelivery commits a fresh side effect.
- **Queue multiplicity**: probe queue multiplicity separately - where several workers consume one queue, one published message can be picked up more than once, so count the durable effects against the publish count.
- **Storm adjudication**: treat one retry yielding one extra durable write as storm evidence and treat deduped redelivery as a clean consumer.

### Compensation-Without-Prevention Triggering

- **Compensation execution**: execute the compensation path without preventing the original success, because non-blocking rollback is the third bent behavior.
- **Failure-branch triggering**: trigger the saga failure branch after the success path has committed and confirm whether both the success effect and the compensation effect persist.
- **Coexistence adjudication**: treat coexisting success plus compensation writes as the finding and treat true reversal as a clean saga.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no throttle difference changes the ordering step itself.
- **Identity rotation**: identity rotation across sessions widens the burst when per-entity throttles cap one principal.
- **Slow-backend provocation**: slow-backend provocation widens the visibility window so the dependent act lands before publication.
- **Proxy-technique pointer**: name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- **Defence-bypass pointer**: name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: cross-service chains forward into impact once the cross-ledger divergence is durable, because transient disagreement alone proves nothing.
- **Invariant-check handoff**: hand a durable double issuance to business-logic invariant checks to test conservation violations above the granted amount.
- **Caching-check handoff**: hand a stale downstream read to caching checks to test re-service of privileged states after concurrent changes.
- **Authorization-principal pointer**: name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Cross-service maps the ordering first and everything else triggers, because no later step is meaningful without a distributed window.
1. **Model the cross-service invariant** - state the conservation rule plus the write-versus-publish order plus each authoritative source, and the step completes when every service names its ledger.
2. **Baseline single execution** - run the workflow once and record the sequential write-plus-publish-plus-consume trace, and the step completes when the single-run ordering is fully characterized.
3. **Strike the visibility window** - act downstream before the upstream write becomes visible with placeholder shape `<distributed-workflow-payload>`, and the step completes when the interleaving either held or broke the invariant reproducibly.
4. **Induce retry storms** - provoke timeouts to force redelivery inside the window, and the step completes when each redelivery carries a deduped or duplicated verdict.
5. **Trigger compensation** - execute the failure branch after success commits and re-read every ledger, and the step completes when success-plus-compensation coexistence is confirmed or refuted.
6. **Confirm durability** - demonstrate the persisting cross-ledger divergence with exact amounts, and the step completes when the divergence is reproducible with a minimal repeatable request set.

## False Positives

- **Ordering-held stop**: stop when the evidence shows ordering held, because idempotent consumers are not a finding.
- **Clean redeliveries**: redeliveries deduped cleanly with a single durable downstream write.
- **Serializable transactions**: serializable transactions or correct queues that serialize the dependent act behind the publish.
- **Visual-only divergence**: visual-only divergence without durable disagreement across service ledgers.
- **True compensations**: compensations that truly reversed the success path with matching ledger annotations.

## Pro Tips

- **Ordering discipline**: cross-service rewards ordering discipline plus trace discipline plus minimal bursts.
- **Timed downstream act**: prefer one carefully timed downstream act before scaling, then scale only to map the lag.
- **Direct calls**: favor direct calls over scripted interface clicks so timeout provocation stays controlled.
- **Leg logging**: log every leg behind correlation identifiers and timestamps so the interleaving is provable.
- **Settled ledger re-read**: re-read each service ledger after settling and report only persisting divergence.
- **Transient-disagreement discipline**: stop promoting transient disagreement and record it as inconclusive rather than positive.

## Summary

A saga that publishes after committing lets dependents act on stale state and retries replay effects.
Cross-service maps the ordering, storms the retries, triggers the compensation, and confirms only divergence that persists across service ledgers.
