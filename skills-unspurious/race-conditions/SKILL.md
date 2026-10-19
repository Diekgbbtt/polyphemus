---
name: race-conditions
description: Race condition testing for TOCTOU bugs, double-spend, and concurrent state manipulation
metadata:
  version: 1.0.0
---

# Race Conditions

Concurrency bugs enable duplicate state changes, quota bypass, financial abuse, and privilege errors. Treat every read-modify-write and multi-step workflow as adversarially concurrent.

## Attack Surface

**Read-Modify-Write**
- Sequences without atomicity or proper locking

**Multi-Step Operations**
- Check, reserve, and commit phases with gaps between them

**Cross-Service Workflows**
- Sagas and asynchronous jobs with eventual consistency

**Rate Limits and Quotas**
- Controls implemented at the edge only

**Envelope Surfaces**
- Batched operations, aliased operations, and persisted documents that carry many effects in one request
- Persistent channels where many messages share one connection

## Reconnaissance

### Identify Race Windows

- Look for explicit sequences: check balance then deduct, verify coupon then apply, check inventory then purchase
- Watch for concurrency markers: version fields, conditional-request headers, and update timestamps
- Examine idempotency-key support: scope (path versus principal), lifetime, and persistence (cache versus authoritative store)
- Map cross-service steps: when state is written versus published, and which retries and compensation paths exist

### Signals

- Sequential request fails but parallel succeeds
- Duplicate rows, negative counters, over-issuance, or inconsistent aggregates
- Distinct response shapes or timings for simultaneous versus sequential requests
- Audit records out of order, multiple success signals for one intent, missing or duplicate correlation identifiers

### Baseline and Instrumentation

- Record the single-request baseline for each workflow before sending any concurrent pair
- Keep correlation identifiers from each delivery so a duplicated effect is attributable to its request set
- Re-read authoritative state after the burst settles to separate durable effects from transient responses

## Detection Channels

- Sequential-versus-parallel verdict where the sequential attempt fails and the concurrent attempt succeeds for the same intent.
- Duplicate rows or double issuance after a burst, which persist across a fresh read.
- Negative counters or inconsistent aggregates where the ledgers disagree after the burst settles.
- Response-shape or timing divergence between simultaneous and sequential equivalents of one request.
- Overwritten entitlements where a later stale write erased an earlier fresh write.
- Lost-update ledger imbalance where concurrent increments net to fewer effects.
- A second effect committed while the response claims deduplication for one intent.
- Foreign or replayed key material that still commits a second effect in the authoritative source.
- Multiple success signals for one intent inside a single response envelope.
- One batched call that outcommits the same operations sent singly.
- Audit records out of order across services with the dependent action timestamped before the authoritative write.
- Missing or duplicate correlation identifiers across the trace of one intent.
- Duplicate downstream writes where one worker retry produces a second persistent side effect.

## Adversarial Capabilities

Race testing presupposes synchronized concurrent delivery, a durable-effect read, and knowledge of the workflow's phases, and it consumes all three.
- Send many requests on warmed, multiplexed connections and align their arrival to a narrow window.
- Hold multiple sessions and principals when the control under test is per-entity.
- Re-read authoritative state after the burst settles to separate a durable effect from a transient response.
- Read logs and correlation identifiers to attribute an interleaving to its request set.
- Widen a window by adding load or slow dependencies when natural timing is too tight.
- Replay one intent through several code paths that reach the same state change.

## Trust Assumptions

The class rests on one agreement: each state transition reads and writes atomically enough that concurrent deliveries of one intent produce exactly one effect.
The agreement holds each read-modify-write to an atomic operation or a lock, holds idempotency keys to a scope and lifetime that cover every delivery path, holds guards to mandatory validation on every path, and holds counters and ledgers to a single authoritative writer.
Value and privilege leak when a window exists: an effect duplicates, a guard is skipped, a counter drifts, or a stale write erases a fresh one.
Each variant breaks one clause: the atomicity and ordering clause, the dedup-scope clause, the guard clause, or the single-request clause of batched and aliased deliveries.

## Key Vulnerabilities

### Atomicity Gaps

- Lost update: read-modify-write increments without an atomic statement
- Partial multi-phase workflows: success committed before validation completes
- Uniqueness checks done outside a unique index or upsert: duplicates appear under load

### Idempotency and Dedup Bypass

- Reuse the same idempotency key across different principals or paths when scope is inadequate
- Hit the endpoint before the idempotency store is written, in the cache-before-commit window
- Application-level dedup that drops only the response while side effects still occur

### Optimistic Concurrency Evasion

- Omit conditional tokens where they are optional; supply stale versions where the server ignores them
- Version markers accepted but not validated across all code paths

### Cross-Service Races

- Saga and compensation timing gaps: execute compensation without preventing the original success path
- Eventual-consistency windows: act in one service before another service's write is visible
- Retry storms: duplicate side effects from at-least-once delivery without idempotent consumers

### Rate Limits and Quotas

- Per-entity enforcement: bypass with multiple addresses or sessions
- Counter updates that are not atomic or are sharded inconsistently; send bursts before counters propagate

### Envelope Surfaces

- Parallel operations and batched calls that bypass per-operation guards
- Aliases and persisted documents that hide multiple state changes inside one request
- Ensure resolver-level idempotency and atomicity
- Per-message authorization and idempotency must hold on persistent channels; concurrent emits duplicate effects when only the handshake is checked

### Files and Storage

- Parallel finalize on multi-part uploads can create duplicate or corrupted objects
- Concurrent reuse of pre-signed URLs

### Auth Flows

- Concurrent consumption of one-time tokens (recovery codes, magic links) to mint multiple sessions
- Verify that consumption is atomic

## Advanced Techniques

**Precision Synchronization**
- Multiplexed connections over one warmed session and last-byte synchronization: hold requests open and release the final byte simultaneously
- Connection warming: pre-establish sessions, cookies, and transport state to remove jitter

**Isolation-Level Exploitation**
- Exploit read-committed and repeatable-read anomalies: phantoms and non-serializable sequences
- Upsert races: naive existence checks lose to proper unique constraints, so target the naive shape

**Lock Granularity**
- Row versus table locks; application locks held in a single process only
- Distributed locks without exclusivity flags or fencing tokens allow multiple winners
- Locks stored in memory on one node are bypassed by hitting other nodes or regions

**Window Widening**
- Degrade the target with large payloads or slow endpoints to widen the race window
- Provoke timeouts to trigger retries that produce duplicate side effects

## Bypass Techniques

- Send bursts before counters propagate, and keep the final write in a duplicate-capable phase
- Name the proxy-techniques family at the channel-wrapping step for method, content-type, and endpoint switching, rather than restating the channel tricks here.
- Name the defence-bypass family at the throttle and edge-versus-core steps for per-entity throttles and per-path guard gaps, rather than restating those mechanics here.

## Chaining Attacks

- Race plus business logic: violate invariants such as double-refund or limit slicing
- Race plus access control: modify or read others' resources before ownership checks complete
- Race plus CSRF: trigger parallel actions from a victim to amplify effects
- Race plus caching: stale caches re-serve privileged states after concurrent changes

## Testing Methodology

1. **Model invariants** - Conservation of value, uniqueness, and maximums for each workflow
2. **Identify reads and writes** - Where each occurs: service, store, cache
3. **Baseline** - Single requests to establish expected behavior and latency
4. **Concurrent requests** - Issue parallel requests with identical inputs; observe deltas
5. **Scale and synchronize** - Ramp up parallelism, use multiplexed connections, and align timing with last-byte release
6. **Cross-channel** - Test web, API, schema-layer, and persistent-channel paths
7. **Confirm durability** - Verify state changes persist across a fresh read and are reproducible

## Variants

- idempotency-dedup-bypass - Bypass deduplication through key reuse and store-lag windows, then prove a second effect landed while the response claimed suppression.
- optimistic-guard-evasion - Evade concurrency guards by omitting tokens or replaying stale versions, then confirm an overwrite or lost update across unevenly enforcing paths.
- single-request-fanout - Multiply effects inside one request through batched operations, hidden duplicates, and persistent-channel emits.
- cross-service-consistency-race - Exploit write-versus-publish ordering across services through visibility lag, retry storms, and compensation gaps.

## False Positives

- Truly idempotent operations with enforced concurrency tokens or unique constraints
- Serializable transactions or correct advisory locks and queues
- Visual-only glitches without durable state change
- Rate limits that reject excess with atomic counters
- Parallel success whose second response is a replay of one effect rather than a second effect; confirm durability across a fresh read
- Correlation from request overlap alone, with no duplicated effect and no skipped guard

## Pro Tips

1. Use multiplexed connections with warmed sessions and last-byte synchronization for precision
2. Start small (a handful of requests), then scale; too much noise masks the window
3. Target read-modify-write paths and endpoints with idempotency keys first
4. Compare the protections across the web, API, schema-layer, and socket paths; they often differ
5. Look for cross-service gaps (queues, jobs, webhooks) and retry semantics
6. Check unique constraints and upsert usage; do not rely on pre-insert checks
7. Use correlation identifiers and logs to prove the concurrent interleaving
8. Validate on production-like latency; some races appear only under real load
9. Document a minimal, repeatable request set that demonstrates durable impact

## Summary

Concurrency safety is a property of every path that mutates state. If any path lacks atomicity, proper isolation, or idempotency, parallel requests will eventually break invariants.
