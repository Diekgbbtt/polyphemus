---
name: business-logic
description: Business logic testing for workflow bypass, state manipulation, and domain invariant violations
metadata:
  version: 1.0.0
---

# Business Logic Flaws

Business logic flaws exploit intended functionality to violate domain invariants: move money without paying, exceed limits, retain privileges, or bypass reviews. They require a model of the business, not just payloads.

## Attack Surface

- Financial logic: pricing, discounts, payments, refunds, credits, chargebacks
- Account lifecycle: signup, upgrade/downgrade, trial, suspension, deletion
- Authorization-by-logic: feature gates, role transitions, approval workflows
- Quotas/limits: rate/usage limits, inventory, entitlements, seat licensing
- Multi-tenant isolation: cross-organization data or action bleed
- Event-driven flows: jobs, webhooks, sagas, compensations, idempotency

## Reconnaissance

### Workflow Mapping

- Derive endpoints from the UI and proxy/network logs; map hidden/undocumented API calls, especially finalize/confirm endpoints
- Identify tokens/flags: step tokens, payment intents, order status, review state, approval identifiers; test reuse across users/sessions
- Document invariants: conservation of value (ledger balance), uniqueness (idempotency), monotonicity (non-decreasing counters), exclusivity (one active subscription)

### Input Surface

- Hidden fields and client-computed totals; the server must recompute from trusted sources
- Alternate encodings and shapes: arrays instead of scalars, objects with unexpected keys, null/empty/0/negative, scientific notation
- Business selectors: currency, locale, timezone, tax region; vary each to trigger rounding and ruleset changes

### State and Time Axes

- Replays: resubmit stale finalize/confirm requests
- Out-of-order: call finalize before verify; refund before capture; cancel after ship
- Time windows: end-of-day/month cutovers, daylight saving, grace periods, trial expiry edges

## Detection Channels

- Durable double side effect in the authoritative source, such as two fulfillments or two refunds for one intent.
- Ledger imbalance where debits and credits no longer conserve value after the burst.
- Durable ledger gain where the charged or credited figure differs from the independently recomputed expectation.
- Rounding-boundary delta where per-item versus per-order rounding favors the caller.
- Cross-selector mismatch where changing currency or locale or tax region alters value without a matching rate refresh.
- Accepted client-math signal where an altered total commits instead of being corrected or rejected.
- Retained benefit after a post-commit mutation, such as keeping a discount whose qualifying condition no longer holds.
- Counter overuse where consumed units exceed the granted quota after the reset edge.
- Reservation-hold leak where reserved units never release after partial completion.
- Seat or entitlement over-consumption past the purchased count or the window edge.
- Idempotency-key reuse signal where a foreign or replayed key still commits a second effect.
- Retry-driven duplicate where one worker retry produces a second downstream write.
- Downstream side effect without origin success, such as a compensation executing without its original commit.
- Between-call mutation signal where the downstream record reflects the altered figure rather than the validated one.
- Stale background-gate decision where a downgraded capability still executes inside a job that skipped re-enforcement.
- Cross-tenant visible state where one organization action mutates another tenant's record.
- Balance or entitlement delta that persists across a fresh read rather than fading as display drift.

## Adversarial Capabilities

Logic testing presupposes a model of the workflow, control over sequencing and timing, and a view of authoritative state, and it consumes all three.
- Hold the sessions and roles the workflow crosses, including two principals where an approval or grant separates them.
- Submit the same intent repeatedly, in parallel, and through alternating channels and encodings.
- Control request timing relative to window edges, retries, and worker schedules.
- Vary business selectors (currency, locale, region) and submit client-computed values as-is.
- Read authoritative state after each attempt: balances, ledgers, entitlements, and inventory counts.

## Trust Assumptions

The class rests on one agreement: every step recomputes its own constraints from authoritative state at the moment it commits, and the client or an earlier step is never the authority.
The agreement holds value figures to server-side recomputation, holds a constraint check and the effect it guards to one atomic step, holds window and quota accounting to one consistent counter, and holds downstream services to re-enforcing the same rules.
Sensitive value leaks when any step commits on trust: on client math, on a prior decision, on a window edge, or on a boundary that another service already passed.
Each variant breaks one clause: the recomputation clause, the atomicity clause, the window-accounting clause, or the cross-boundary clause.

## Key Vulnerabilities

### State Machine Abuse

- Skip or reorder steps via direct API calls; verify the server enforces preconditions on each transition
- Replay prior steps with altered parameters (swap price after approval but before capture)
- Split a single constrained action into many sub-actions under the threshold (limit slicing)

### Concurrency and Idempotency

- Parallelize identical operations to bypass atomic checks (create, apply, redeem, transfer)
- Abuse idempotency: key scoped to path but not principal → reuse other users' keys; or idempotency stored only in cache
- Message reprocessing: queue workers re-run tasks on retry without idempotent guards; cause duplicate fulfillment/refund

### Numeric and Currency

- Floating point vs decimal rounding; rounding/truncation favoring the attacker at boundaries
- Cross-currency arbitrage: buy in one currency, refund in another at stale rates; tax rounding per-item vs per-order
- Negative amounts, zero-price, free-shipping thresholds, minimum/maximum guardrails

### Quotas, Limits, and Inventory

- Off-by-one and time-bound resets (UTC vs local); pre-warm at T-1s and post-fire at T+1s
- Reservation/hold leaks: reserve multiple, complete one, release not enforced; backorder logic inconsistencies
- Distributed counters without strong consistency enabling double-consumption

### Refunds and Chargebacks

- Double-refund: refund via UI and support tool; partial refunds summing above the captured amount
- Refund after benefits consumed (downloaded digital goods, shipped items) due to missing post-consumption checks

### Feature Gates and Roles

- Feature flags enforced client-side or at the edge but not in core services; toggle names guessed or falling back to default-enabled
- Role transitions leaving stale capabilities (retain premium after downgrade; retain admin endpoints after demotion)

## Advanced Techniques

### Event-Driven Sagas

- Saga/compensation gaps: trigger compensation without original success; or execute success twice without compensation
- Outbox/Inbox patterns missing idempotency → duplicate downstream side effects
- Cron/backfill jobs operating outside request-time authorization; mutate state broadly

### Microservices Boundaries

- Cross-service assumption mismatch: one service validates the total, another trusts line items; alter between calls
- Header trust: internal services trusting identity or role headers from untrusted edges
- Partial failure windows: two-phase actions where phase 1 commits without phase 2, leaving exploitable intermediate state

### Multi-Tenant Isolation

- Tenant-scoped counters and credits updated without the tenant key in the where-clause; leak across organizations
- Admin aggregate views allowing actions that impact other tenants due to missing per-tenant enforcement

### Commerce Flows

- Stack incompatible discounts via parallel apply; remove the qualifying item after the discount applied; retain free shipping after cart changes
- Modify shipping tier post-quote; abuse returns to keep the product and the refund

### Ledger and Settlement Flows

- Split transfers to bypass per-transaction thresholds; schedule vs instant path inconsistencies
- Exploit grace periods on holds/authorizations to withdraw again before settlement

### Subscription and Metering Flows

- Seat licensing: race seat assignment to exceed purchased seats; stale license checks in background tasks
- Usage metering: report late or duplicate usage to avoid billing or to over-consume

## Bypass Techniques

- Client recomputation: totals, taxes, discounts computed on the client and accepted by the server
- Name the proxy-techniques family at the channel-wrapping step for content-type switching and method alternation, rather than restating the channel tricks here.
- Name the defence-bypass family at the edge-versus-core step for stale gateway decisions, rather than restating the gateway differentials here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- Business logic + race: duplicate benefits before state updates
- Business logic + IDOR: operate on others' resources once a workflow leak reveals identifiers
- Business logic + CSRF: force a victim to complete a sensitive step sequence

## Testing Methodology

1. **Enumerate state machine** - Per critical workflow (states, transitions, pre/post-conditions); note invariants
2. **Build Actor × Action × Resource matrix** - Unauth, basic user, premium, staff/admin; identify actions per role
3. **Test transitions** - Step skipping, repetition, reordering, late mutation
4. **Introduce variance** - Time, concurrency, channel (mobile/web/API/schema layer), content-types
5. **Validate persistence boundaries** - All services, queues, and jobs re-enforce invariants

## Variants

- concurrent-duplication - Duplicate constrained operations through parallel submission when the atomic check races, including foreign idempotency-key reuse.
- value-domain-manipulation - Submit boundary values through constrained transitions when server-side recomputation is missing, across currency, rounding, and tax selectors.
- quota-window-slicing - Slice windowed limits through reset-edge timing and reserve-hold-release lifecycles when counters reset non-atomically.
- async-boundary-abuse - Trigger async sagas and workers across service boundaries when downstream re-enforcement is missing, and mutate values between calls.

## False Positives

- Promotional behavior explicitly allowed by policy (documented free trials, goodwill credits)
- Visual-only inconsistencies with no durable or exploitable state change
- Admin-only operations with proper audit and approvals

## Pro Tips

1. Start from invariants and ledgers, not the UI: prove conservation of value breaks
2. Test with time and concurrency; many bugs only appear under pressure
3. Recompute totals server-side; flag every observed acceptance of client math
4. Treat idempotency and retries as first-class: verify key scope and persistence
5. Probe background workers and webhooks separately; they often skip auth and rule checks
6. Validate role and feature gates at the service that mutates state, not only at the edge
7. Explore end-of-period edges (month-end, trial end, daylight saving) for rounding and window issues
8. Use minimal, auditable PoCs that demonstrate durable state change and exact loss
9. Chain with authorization tests (object-level and function-level access) to magnify impact
10. When in doubt, map the state machine; gaps appear where transitions lack server-side guards

## Summary

Business logic security is the enforcement of domain invariants under adversarial sequencing, timing, and inputs. If any step trusts the client or prior steps, expect abuse.
