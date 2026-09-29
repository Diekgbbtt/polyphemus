---
name: single-request-fanout
description: Fanout testing through batched mutations when one request carries many effects, aliased and persisted queries when duplicates hide inside, and persistent-channel emits when messages race over one connection.
metadata:
  version: 1.0.0
---

# Single-Request Fanout

Per-request guards promise one state change per call yet a batched or aliased request can smuggle many changes past them at once.
This variant packs many state changes into one request, hides duplicates behind aliases and persisted queries, and races emits over a persistent channel.
The goal is duplicate fulfillment plus over-issuance plus quota bypass that counts as one request at the gate but many in the ledger.

## Attack Surface

Fanout applicability centers on interfaces that accept batched operations, aliased fields, persisted query identifiers, or rapid emits over one connection.
The surface holds batch plus alias plus persisted-query plus message-emit operations where per-mutation guards assume isolated execution.
Resolver-level atomicity gaps, per-mutation guards without batch accounting, and per-handshake checks without per-message enforcement all widen the surface.
Parallel multi-request bursts ride in the parent core rather than here, because this variant owns only intra-request multiplication.

## Reconnaissance

Fanout maps the batching contract before packing, because blind batching cannot distinguish guard absence from size limits.
Enumerate which operations accept batches plus aliases plus persisted identifiers and note whether guards run per mutation or per request.
Probe batch accounting by submitting a benign pair with distinct markers and observing whether both commit while counting as one.
Record per-message enforcement on persistent channels separately, because handshake-only checks leave every later emit unguarded.

## Detection Channels

Fanout listens for intra-request multiplication, so only the entries below are live here.
- Multiple success signals for one intent inside a single response envelope.
- Duplicate rows or over-issuance where one request produced many ledger writes.
- Simultaneous-versus-sequential divergence where one batched call outcommits the same operations sent singly.
- Missing or duplicate correlation identifiers across the fanned-out writes for one request.

## Adversarial Capabilities

Fanout presupposes batch access plus alias control plus persistent-channel use, and it consumes all three.
- Operate as a legitimate authenticated user entitled to perform the batched operation at least once.
- Pack many state-changing mutations into one request through batching plus aliasing plus persisted identifiers.
- Emit concurrent messages over one persistent connection inside the same commit window.
- Replay recorded batch envelopes through direct calls outside the scripted interface.
- Read the authoritative source after the burst to count durable effects per request.

## Trust Assumptions

The feature trusts that concurrent executions of one state-changing workflow interleave safely: checks precede effects atomically, dedup keys bind one intent to one effect durably, version guards validate on every path, and published state becomes visible before dependent actions proceed.
Sensitive balance plus entitlement plus ledger state leaks only when an execution commits outside these clauses.
This variant breaks the one-request-one-effect clause because a single request fans out into many state changes inside the commit window.

## Key Vulnerabilities

### Batched Mutation Packing

Pack many identical mutations into one envelope with placeholder shape `<batch-envelope>` holding `<state-change-payload>` repeated, because intra-request packing is the first bent behavior the parent never describes.
Treat many durable writes from one envelope as fanout evidence and treat per-mutation rejection as clean batch accounting.
The parent concurrent-requests step demands parallel requests and cannot describe one request replacing them, so this variant owns the packing procedure.

### Aliased and Persisted Query Hiding

Hide duplicates behind field aliases and persisted identifiers, because hidden multiplicity is the second bent behavior.
Submit the same mutation under distinct aliases plus a stored identifier replay and count the resulting ledger writes per envelope.
Treat alias-distinct duplicates that each commit as guard-blindness rather than as client convenience.

### Persistent-Channel Concurrent Emits

Race rapid emits over one connection, because per-message gaps are the third bent behavior.
Open one channel with placeholder shape `<channel-handshake>` then `<state-change-emit>` repeated and observe whether each emit commits without its own authorization and idempotency check.
Name the graphql skill at the schema-and-resolver discovery step rather than restating its mechanics.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no throttle difference changes the fanout step itself.
- Identity rotation across sessions widens the envelope set when per-entity throttles cap one principal.
- Slow-backend provocation widens the intra-request window so sibling mutations interleave before guards serialize them.
- Name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- Name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.

## Chaining Attacks

Fanout chains forward into impact once the multiplied writes are durable, because a batched echo alone proves nothing.
- Hand durable multiplied fulfillment to business-logic invariant checks to test limit slicing above the granted quota.
- Hand revealed envelope identifiers to identifier-substitution checks to fan out against sibling resources.
- Name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Fanout packs the envelope first and everything else counts, because no later step is meaningful without intra-request multiplication.
1. **Model the per-request invariant** - state the one-request-one-effect rule plus the per-mutation guard claim plus the authoritative source, and the step completes when every guard names its scope.
2. **Baseline single execution** - perform each mutation singly and record the sequential ledger delta, and the step completes when the single-operation behavior is fully characterized.
3. **Fire the fanout envelope** - submit batched plus aliased plus persisted mutations in one request with placeholder shape `<batch-envelope>` holding `<state-change-payload>` repeated, and the step completes when the envelope shows a recorded outcome per inner mutation.
4. **Race the persistent channel** - emit concurrent messages over one connection inside the commit window, and the step completes when each emit carries a committed or rejected verdict.
5. **Confirm durability** - re-read the authoritative source after settling and count durable effects per request, and the step completes when the multiplication factor is reproducible with a minimal repeatable envelope.

## False Positives

Stop when the evidence shows per-mutation enforcement held, because clean batch accounting is not a finding.
- Batched mutations each validated with per-mutation rejection of over-limit inner calls.
- Per-message authorization and idempotency enforced on every emit over the connection.
- Visual-only multiplicity without durable extra writes in the authoritative source.
- Rate limits that reject excess inner mutations with atomic counters.

## Pro Tips

Fanout rewards envelope discipline plus per-mutation counting plus minimal packing.
1. Prefer the smallest envelope that multiplies, then grow only to map the accounting threshold.
2. Favor direct calls over scripted interface clicks so envelope shape stays exact.
3. Log every envelope behind its inner markers and timestamps so each write is attributable.
4. Re-read the ledger after settling and report only persisting multiplication.
5. Stop promoting transient echoes and record them as inconclusive rather than positive.

## Summary

A batch-aware interface without per-mutation atomicity counts one request while committing many.
Fanout packs the envelope, hides duplicates behind aliases, races the channel emits, and confirms only multiplication that persists in the authoritative source.
