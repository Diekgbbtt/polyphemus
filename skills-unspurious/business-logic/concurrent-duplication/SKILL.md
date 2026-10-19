---
name: concurrent-duplication
description: Duplicate constrained operations through parallel submission when atomic checks race, reuse idempotency keys across principals, and confirm durable double effects.
metadata:
  version: 1.0.0
---

# Concurrent Duplication

Business logic assumes each constrained operation commits once, yet parallel submissions can commit twice before any guard observes the sibling write.
This variant fires identical state-changing operations simultaneously and forensically separates cache-only idempotency from durable enforcement.
The duplication goal is double fulfillment plus double refund plus double credit that survives in the authoritative source.

## Attack Surface

- **Applicability**: centers on a multi-step stateful workflow whose constrained transition lacks an atomic commit guard.
- **Held surface**: the surface holds create plus apply plus redeem plus transfer operations where conservation of value depends on exactly-once execution.
- **Widening shapes**: idempotency keys scoped to path rather than principal, keys stored only in volatile cache, and queue workers that re-run tasks on retry all widen the surface.
- **Out-of-scope variants**: sequential under-threshold slicing rides in quota-window-slicing rather than here, because this variant owns only simultaneous execution.

## Reconnaissance

- **Guard mapping**: duplicate first maps the guard before firing, because blind parallelism wastes the race window.
- **State-machine enumeration**: enumerate the state machine around the constrained transition and note which precondition check claims atomicity and where its authoritative source lives.
- **Idempotency probing**: probe idempotency handling by replaying a recorded finalize request with the same key and with a fresh key, then compare which replay the server accepts.
- **Key-scope recording**: record whether the key binds principal plus path plus operation, or path alone, and whether the store behind it is durable or cache-only.
- **Family naming**: name the race-conditions skill at the timing-primitive step rather than restating its mechanics.

## Detection Channels

- **Channel scope**: duplication listens for double commit, so only the entries below are live here.
- **Durable double**: durable double side effect in the authoritative source, such as two fulfillments or two refunds for one intent.
- **Ledger imbalance**: ledger imbalance where debits and credits no longer conserve value after the burst.
- **Key-reuse signal**: idempotency-key reuse signal where a foreign or replayed key still commits a second effect.
- **Transaction-identifier split**: two distinct transaction identifiers returned for one identical idempotency key, which confirms the key is not binding the effect.
- **Retry duplicate**: retry-driven duplicate where one worker retry produces a second downstream write.
- **Persistent delta**: balance or entitlement delta that persists across a fresh read rather than fading as display drift.

## Adversarial Capabilities

- **Prerequisites**: duplication presupposes parallel submission plus key reuse plus repeated measurement, and it consumes all three.
- **Parallel sessions**: hold parallel sessions or connections that fire identical state-changing operations within the same commit window.
- **Workflow access**: operate as a legitimate authenticated user entitled to perform the operation at least once.
- **Key reuse**: reuse stale workflow flags and idempotency keys across sessions to test scope binding.
- **Direct replay**: replay recorded finalize requests through direct calls outside the scripted user interface.
- **Post-burst reads**: read the authoritative source after the burst to separate durable doubles from transient display echoes.

## Trust Assumptions

- **The agreement**: the workflow trusts client-supplied values to stay within domain bounds, trusts each transition to run once in order after its precondition check, trusts windowed counters to reset atomically per principal, and trusts every downstream service queue and job to re-enforce the same invariants before mutating state.
- **The exposure**: sensitive value plus entitlement plus capability state leaks only when a transition commits outside these clauses.
- **The failing clause**: this variant breaks the run-once clause because parallel submissions commit before the atomic guard observes the sibling write.

## Key Vulnerabilities

### Orchestrated Parallel Duplicate Execution

- **Simultaneous firing**: fire identical operations simultaneously rather than sequentially, because sequential repetition is parent transition testing and cannot describe a commit race.
- **Single-request multiplexing**: before escalating to parallel transport, confirm the duplication in a single request where the interface multiplexes several operations (aliased or batched submissions of one logical operation), since a duplicate that already lands in one request needs no timing primitive.
- **Burst variation**: vary burst size from pairs upward until the guard either serializes cleanly or yields a durable double.
- **Ownership boundary**: the parent variance step covers only generic concurrency as one dimension and cannot describe synchronized firing, so this variant owns the orchestration procedure.

### Idempotency-Key Scope Forensics

- **Key-scope testing**: test whether the key binds principal plus path plus operation by replaying a foreign key and a same-principal key separately.
- **Verdict rules**: treat acceptance of a foreign key as scope failure and treat acceptance of any replayed key after success as durability failure.
- **Lifetime recording**: record key lifetime and surviving store, because a key honored from cache but absent from durable storage re-arms after eviction.

### Store-Durability Separation

- **Ledger confirmation**: confirm every suspected double in the authoritative ledger rather than in the response body, because responses can echo optimistically.
- **Settling re-reads**: re-read balances plus entitlements plus fulfillment records after a settling delay and require the double to persist.
- **Transient-echo handling**: treat doubles visible only in transient responses as inconclusive rather than positive.

## Advanced Techniques

- **Burst advance**: advance the burst once the basic double lands, because guards often hold at low parallelism and fail at higher pressure.
- **Pressure ramping**: ramp burst size plus connection count while holding the operation identical, and record the threshold where serialization breaks.
- **Retry interleaving**: interleave the burst with a queue retry so the worker re-runs the task inside the same window the parallel calls occupy.
- **Cross-service divergence**: carry cross-service double consumption as a secondary divergence by firing through two channels at once, then confirming in each service ledger separately.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no channel difference changes the duplication step itself.
- **Content-type wrappers**: content-type wrappers that route the same operation to a second code path join the burst as extra parallel lanes.
- **Method alternation**: method alternation that performs the same state change through a second verb joins the burst the same way.
- **Proxy-family naming**: name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- **Defence-family naming**: name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chaining scope**: duplication chains forward into impact once the double is durable, because a transient echo alone proves nothing.
- **Refund-logic chaining**: hand a durable double fulfillment to refund logic to test double-refund summation above the captured amount.
- **Identifier chaining**: hand revealed workflow identifiers to identifier-substitution checks to operate on sibling resources with the same burst.
- **Principal naming**: name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Duplication runs the burst first and everything else confirms, because no later step is meaningful without a synchronized race.
1. **Enumerate the constrained transition** - list the operation plus its atomicity claim plus its authoritative source, and the step completes when every guard names its store.
2. **Baseline single execution** - perform the operation once and record the ledger delta plus the key behavior, and the step completes when the single-run effect is fully characterized.
3. **Fire the parallel burst** - submit identical operations simultaneously across sessions with shared and fresh keys, and the step completes when every lane shows a recorded outcome.
4. **Forensicate key scope and durability** - replay foreign keys plus same-principal keys and re-read the authoritative source after settling, and the step completes when each key carries a scope verdict and each suspected double carries a durable or transient verdict.
5. **Confirm exploitability** - demonstrate the persisting value gain with exact amounts in the ledger, and the step completes when the imbalance is reproducible and auditable.

## False Positives

- **Stop condition**: stop when the evidence shows serialization held, because a clean guard is not a finding.
- **Optimistic echoes**: optimistic response echoes with no durable second write in the authoritative source.
- **Policy-allowed issuance**: policy-allowed duplicate issuance such as documented goodwill credits with matching ledger annotations.
- **Admin-only re-execution**: admin-only re-execution with proper audit and approvals.
- **Compensated doubles**: doubles that collapse after settling because a compensating job correctly reversed the second commit.

## Pro Tips

- **Discipline**: duplication rewards synchronization plus ledger discipline plus minimal bursts.
- **Smallest burst**: prefer the smallest burst that breaks serialization, then scale only to map the threshold.
- **Direct calls**: favor direct calls over scripted interface clicks so lane timing stays tight.
- **Lane logging**: log every lane behind its key and timestamp so the double is attributable.
- **Settled re-reads**: re-read the ledger after settling and report only persisting imbalances.
- **Transient-echo caution**: stop promoting transient echoes and record them as inconclusive rather than positive.

## Summary

A run-once transition without an atomic guard commits twice under a synchronized burst.
Duplication fires the lanes together, forensicates key scope and store durability, and confirms only doubles that persist in the authoritative source.
