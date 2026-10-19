---
name: async-boundary-abuse
description: Trigger async sagas and workers across service boundaries when downstream re-enforcement is missing, mutate values between calls, and confirm durable cross-boundary effects.
metadata:
  version: 1.0.0
---

# Async Boundary Abuse

Business logic assumes every downstream service plus queue plus job re-enforces the invariant, yet between-call mutation and independent triggering can commit effects no single request validates.
This variant mutates values between service calls, fires compensation without origin success, and replays worker retries without idempotent guards.
The abuse goal is durable cross-boundary effects plus cross-tenant bleed that the request-time check never sees.

## Attack Surface

- **Applicability**: an event-driven topology where one request fans out across services plus queues plus scheduled jobs plus tenant scopes.
- **Surface composition**: saga plus compensation flows, outbox plus inbox handlers, cron plus backfill jobs, and multi-tenant writes where the tenant key may be absent from the update predicate.
- **Widening factors**: cross-service total-versus-line-item splits and trusted identity headers at internal edges widen the surface further.
- **Out-of-scope variant**: single-transition value oracles ride in value-domain-manipulation rather than here, because this variant owns only cross-boundary triggering.

## Reconnaissance

- **Topology mapping**: abuse first maps the topology before triggering, because blind replay cannot separate a re-enforcing boundary from a trusting one.
- **Fan-out enumeration**: enumerate the fan-out of one request across services plus queues plus jobs and note which boundary rechecks the invariant and which trusts the caller.
- **Between-call mutation probe**: probe between-call mutation by altering values after the first service validates but before the second commits, then compare the downstream record against the validated figure.
- **Independent-trigger probe**: probe independent triggering by invoking compensation or retry paths without their origin success and record which ones execute.
- **Tenant-scope baseline**: document tenant scoping per write path so every later bleed verdict has a baseline.

## Detection Channels

- **Channel scope**: abuse listens for unvalidated downstream effects.
- **Downstream side effect**: without origin success, such as compensation executing absent its original commit.
- **Forged confirmation**: an external confirmation accepted as authoritative without origin authentication, where a forged success signal commits the effect.
- **Retried worker duplicate**: one retry produces a second durable write.
- **Between-call mutation signal**: the downstream record reflects the altered figure rather than the validated one.
- **Cross-tenant visible state**: one organization action mutates another tenant record.
- **Stale background-gate decision**: a downgraded capability still executes inside a job that skipped re-enforcement.

## Adversarial Capabilities

- **Prerequisites**: abuse presupposes legitimate workflow access plus mutation position plus trigger reach, and it consumes all three.
- **Legitimate workflow access**: operate as a legitimate authenticated user entitled to start the workflow at least once.
- **Mutation position**: alter values between two service calls through direct calls outside the scripted sequence.
- **Independent trigger reach**: invoke compensation plus retry plus scheduled-job paths independently of their origin success.
- **Worker payload replay**: replay recorded worker payloads to test idempotent guards at each boundary.
- **Authoritative-source reads**: read each downstream authoritative source separately to attribute the effect to its boundary.

## Trust Assumptions

- **The agreement**: client-supplied values stay within domain bounds, each transition runs once in order after its precondition check, windowed counters reset atomically per principal, and every downstream service queue and job re-enforces the same invariants before mutating state, and sensitive value plus entitlement plus capability state leaks only when a transition commits outside these clauses.
- **The failing clause**: the variant breaks the downstream re-enforcement clause because services, queues, and jobs mutate state without rechecking the invariant.

## Key Vulnerabilities

### Between-Call Mutation

- **Between-call alteration**: alter the validated figure in transit between the checking service and the committing service.
- **Validated-figure confirmation**: confirm the downstream record against the validated figure rather than against the request echo, because the echo reflects the first service only.
- **Multi-entry windows**: test the multi-entry case: where one logical write lands as several separate statements (a debit, a credit, and a fee written one by one), the window between the first and the last statement is the mutation window.
- **Mutation-procedure ownership**: the parent boundary step covers only verifying that boundaries re-enforce and cannot describe mutating between the check and the commit, so this variant owns the mutation procedure.

### Independent Compensation and Retry Triggering

- **Independent triggering**: invoke compensation flows without their origin success and replay worker retries without idempotent guards.
- **Forged confirmation**: supply a forged external confirmation where the provider signal carries no signature or origin authentication, and read whether the downstream effect commits on that signal alone.
- **Trigger adjudication**: treat an executing compensation absent origin success as a saga-gap positive and treat a second durable write per retry as a guard positive.
- **Path separation**: test outbox plus inbox plus cron plus backfill paths separately, because each path carries its own guard logic.

### Cross-Boundary Tenant and Gate Staleness

- **Tenant-key verification**: submit tenant-scoped writes and verify the update predicate carries the tenant key at every boundary, carrying multi-tenant bleed as a secondary divergence.
- **Gate-staleness exercise**: exercise role and feature-gate transitions then trigger background paths, because jobs that skip re-enforcement execute with stale capabilities.
- **Boundary adjudication**: treat cross-tenant durable state and post-downgrade job execution as boundary positives once confirmed in the authoritative source.

## Advanced Techniques

- **Boundary advancement**: advance the boundary once the basic trigger lands, because partial-failure windows often compose across services.
- **Partial-failure window**: commit phase one of a two-phase action and abandon phase two to leave the intermediate state, then operate against that state directly.
- **Fan-out attribution**: fan one request out through two channels at once and confirm each downstream ledger separately to expose assumption mismatch between services.
- **Scheduled-job breadth**: carry cron plus backfill breadth as an aspect inside the same triggering procedure by scoping each job run to its affected records.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no channel difference changes the boundary-triggering step itself.
- **Content-type wrappers**: route the same workflow to a second code path and join the trigger set as extra lanes.
- **Method alternation**: perform the same workflow step through a second verb and join the trigger set the same way.
- **Proxy-technique pointer**: name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- **Defence-bypass pointer**: name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: abuse chains forward into impact once the downstream effect is durable, because a single unvalidated write alone understates the reach.
- **Refund-logic handoff**: hand a durable downstream double to refund logic to test summation above the captured amount.
- **Identifier-substitution handoff**: hand revealed workflow identifiers to identifier-substitution checks to trigger boundaries against sibling resources.
- **Authorization-principal pointer**: name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Abuse runs the topology map first and everything else follows, because no later step is meaningful without attributed boundaries.
1. **Enumerate the fan-out** - list every service plus queue plus job plus tenant scope the workflow touches, and the step completes when each boundary names its re-enforcement claim.
2. **Baseline single pass** - run the workflow once cleanly and record each downstream record, and the step completes when the clean-run effects are fully characterized.
3. **Mutate between calls** - alter values after validation but before commit through direct calls, and the step completes when every boundary carries a rechecked or trusting verdict.
4. **Trigger independently** - fire compensation plus retry plus scheduled paths without origin success, and the step completes when every path carries an executed or refused verdict.
5. **Confirm durable cross-boundary effects** - re-read each downstream authoritative source including sibling tenants, and the step completes when every effect is reproducible and auditable.

## False Positives

- **Boundary-held stop**: stop when the evidence shows the boundary held, because a re-enforcing downstream is not a finding.
- **Policy-allowed promotion**: promotional behavior explicitly allowed by policy such as documented trials or goodwill credits with matching annotations.
- **Visual-only drift**: downstream drift with no durable record change after settling.
- **Admin-only execution**: job execution with proper audit and approvals.
- **Convergent retries**: retried writes that converge to exactly-once because idempotent guards correctly deduplicated them.

## Pro Tips

- **Discipline**: abuse rewards topology maps plus boundary attribution plus ledger patience.
- **One boundary per probe**: prefer one boundary per probe so each effect attributes cleanly to its writer.
- **Direct calls**: favor direct calls between services over scripted sequences so mutation timing stays controllable.
- **Origin-success logging**: log every trigger behind its origin-success status so independent execution is provable.
- **Source confirmation**: confirm each suspected effect in its own authoritative source, including sibling tenants.
- **Transient-state discipline**: stop promoting transient intermediate state and record it as inconclusive until it persists.

## Summary

A downstream that trusts its caller commits effects the request-time check never validates.
Abuse mutates between calls, triggers compensation and retries independently, and confirms only effects that persist across service plus queue plus tenant boundaries.
