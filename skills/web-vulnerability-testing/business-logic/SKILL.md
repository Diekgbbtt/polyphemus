---
name: business-logic
description: Business logic testing for workflow bypass, state manipulation, and domain invariant violations
metadata:
  version: 1.0.0
---

# Business Logic Flaws

Business logic flaws exploit intended functionality to violate domain invariants: move money without paying, exceed limits, retain privileges, or bypass reviews. They require a model of the business, not just payloads.

## Attack Surface

- **Financial logic**: pricing, discounts, payments, refunds, credits, chargebacks.
- **Account lifecycle**: signup, upgrade/downgrade, trial, suspension, deletion, and referral or reward grants.
- **Authorization-by-logic**: feature gates, role transitions, approval workflows.
- **Quotas/limits**: rate/usage limits, inventory, entitlements, seat licensing.
- **Multi-tenant isolation**: cross-organization data or action bleed.
- **Event-driven flows**: jobs, webhooks, sagas, compensations, idempotency.

## Reconnaissance

### Workflow Mapping

- **Endpoint derivation**: derive endpoints from the UI and proxy/network logs; map hidden/undocumented API calls, especially finalize/confirm endpoints.
- **Tokens/flags**: step tokens, payment intents, order status, review state, approval identifiers; test reuse across users/sessions.
- **Invariants**: conservation of value (ledger balance), uniqueness (idempotency), monotonicity (non-decreasing counters), exclusivity (one active subscription).

### Input Surface

- **Client-computed inputs**: hidden fields and client-computed totals; the server must recompute from trusted sources.
- **Alternate encodings and shapes**: arrays instead of scalars, objects with unexpected keys, null/empty/0/negative, scientific notation.
- **Business selectors**: currency, locale, timezone, tax region; vary each to trigger rounding and ruleset changes.

### State and Time Axes

- **Replays**: resubmit stale finalize/confirm requests.
- **Out-of-order steps**: call finalize before verify; refund before capture; cancel after ship.
- **Time windows**: end-of-day/month cutovers, daylight saving, grace periods, trial expiry edges.

## Detection Channels

- **Durable double**: durable double side effect in the authoritative source, such as two fulfillments or two refunds for one intent.
- **Ledger imbalance**: ledger imbalance where debits and credits no longer conserve value after the burst.
- **Ledger gain**: durable ledger gain where the charged or credited figure differs from the independently recomputed expectation.
- **Rounding-boundary delta**: rounding-boundary delta where per-item versus per-order rounding favors the caller.
- **Cross-selector mismatch**: cross-selector mismatch where changing currency or locale or tax region alters value without a matching rate refresh.
- **Client-math acceptance**: accepted client-math signal where an altered total commits instead of being corrected or rejected.
- **Retained benefit**: retained benefit after a post-commit mutation, such as keeping a discount whose qualifying condition no longer holds.
- **Counter overuse**: counter overuse where consumed units exceed the granted quota after the reset edge.
- **Hold leak**: reservation-hold leak where reserved units never release after partial completion.
- **Seat over-consumption**: seat or entitlement over-consumption past the purchased count or the window edge.
- **Key-reuse signal**: idempotency-key reuse signal where a foreign or replayed key still commits a second effect.
- **Retry duplicate**: retry-driven duplicate where one worker retry produces a second downstream write.
- **Downstream side effect**: downstream side effect without origin success, such as a compensation executing without its original commit.
- **Mutation signal**: between-call mutation signal where the downstream record reflects the altered figure rather than the validated one.
- **Stale gate decision**: stale background-gate decision where a downgraded capability still executes inside a job that skipped re-enforcement.
- **Cross-tenant state**: cross-tenant visible state where one organization action mutates another tenant's record.
- **Persistent delta**: balance or entitlement delta that persists across a fresh read rather than fading as display drift.

## Adversarial Capabilities

- **Prerequisites**: logic testing presupposes a model of the workflow, control over sequencing and timing, and a view of authoritative state, and it consumes all three.
- **Session and role set**: hold the sessions and roles the workflow crosses, including two principals where an approval or grant separates them.
- **Intent repetition**: submit the same intent repeatedly, in parallel, and through alternating channels and encodings.
- **Timing control**: control request timing relative to window edges, retries, and worker schedules.
- **Selector variation**: vary business selectors (currency, locale, region) and submit client-computed values as-is.
- **State reads**: read authoritative state after each attempt: balances, ledgers, entitlements, and inventory counts.

## Trust Assumptions

- **The trust premise**: the class rests on one agreement: every step recomputes its own constraints from authoritative state at the moment it commits, and the client or an earlier step is never the authority.
- **The agreement**: it holds value figures to server-side recomputation, holds a constraint check and the effect it guards to one atomic step, holds window and quota accounting to one consistent counter, and holds downstream services to re-enforcing the same rules.
- **The exposure**: sensitive value leaks when any step commits on trust: on client math, on a prior decision, on a window edge, or on a boundary that another service already passed.
- **The failing clause**: each variant breaks one clause: the recomputation clause, the atomicity clause, the window-accounting clause, or the cross-boundary clause.

## Key Vulnerabilities

### State Machine Abuse

- **Step skipping and reordering**: skip or reorder steps via direct API calls; verify the server enforces preconditions on each transition.
- **Parameter replay**: replay prior steps with altered parameters (swap price after approval but before capture).
- **Threshold splitting**: split a single constrained action into many sub-actions under the threshold (limit slicing).
- **Identity-domain moves**: move the identity between domains after creation (register under an allowed domain, then change the identity to a privileged one) and verify each transition re-checks the domain rules.
- **Skipped-step defaults**: drop a selection step whose absence leaves a privileged default, such as a skipped role-selection request that leaves the highest role in place.

### Concurrency and Idempotency

- **Parallel duplication**: parallelize identical operations to bypass atomic checks (create, apply, redeem, transfer).
- **Idempotency abuse**: abuse idempotency: key scoped to path but not principal → reuse other users' keys; or idempotency stored only in cache.
- **Message reprocessing**: queue workers re-run tasks on retry without idempotent guards; cause duplicate fulfillment/refund.
- **Race harness**: the synchronized burst is driven by `scripts/business-logic-race-harness`, which records each lane and re-reads the authoritative state after a settling delay, so a durable double is separated from a response echo.

### Numeric and Currency

- **Rounding boundaries**: floating point vs decimal rounding; rounding/truncation favoring the attacker at boundaries.
- **Cross-currency arbitrage**: buy in one currency, refund in another at stale rates; tax rounding per-item vs per-order.
- **Numeric edge values**: negative amounts, zero-price, free-shipping thresholds, minimum/maximum guardrails.
- **Reference pointer**: the probe set, the recomputation oracle, and the failure-mode index behind these cases are in `references/value-probe-set.md`.

### Quotas, Limits, and Inventory

- **Reset edges**: off-by-one and time-bound resets (UTC vs local); pre-warm at T-1s and post-fire at T+1s.
- **Reservation/hold leaks**: reserve multiple, complete one, release not enforced; backorder logic inconsistencies.
- **Distributed counters**: distributed counters without strong consistency enabling double-consumption.

### Refunds and Chargebacks

- **Double-refund**: refund via UI and support tool; partial refunds summing above the captured amount.
- **Post-consumption refunds**: refund after benefits consumed (downloaded digital goods, shipped items) due to missing post-consumption checks.

### Feature Gates and Roles

- **Client-side gates**: feature flags enforced client-side or at the edge but not in core services; toggle names guessed or falling back to default-enabled.
- **Stale capabilities**: role transitions leaving stale capabilities (retain premium after downgrade; retain admin endpoints after demotion).
- **Delegation abuse**: invitation and delegation abuse: an inviter grants a role above its own ceiling; the authorization-principal step is owned by `two-principal-authz` and the function-level verdict by `broken-function-level-authorization`, so record only the logic delta here.
- **Dual-use endpoints**: a dual-use endpoint whose privileged branch does not require the current credential, only an earlier step's approval; the authorization verdict belongs to the classes above.

## Advanced Techniques

### Event-Driven Sagas

- **Saga/compensation gaps**: trigger compensation without original success; or execute success twice without compensation.
- **Outbox and inbox gaps**: outbox/Inbox patterns missing idempotency → duplicate downstream side effects.
- **Scheduled jobs**: cron/backfill jobs operating outside request-time authorization; mutate state broadly.

### Microservices Boundaries

- **Cross-service assumption mismatch**: one service validates the total, another trusts line items; alter between calls.
- **Header trust**: internal services trusting identity or role headers from untrusted edges.
- **Partial failure windows**: two-phase actions where phase 1 commits without phase 2, leaving exploitable intermediate state.

### Multi-Tenant Isolation

- **Missing tenant keys**: tenant-scoped counters and credits updated without the tenant key in the where-clause; leak across organizations.
- **Aggregate views**: admin aggregate views allowing actions that impact other tenants due to missing per-tenant enforcement.

### Commerce Flows

- **Discount stacking**: stack incompatible discounts via parallel apply; remove the qualifying item after the discount applied; retain free shipping after cart changes.
- **Shipping and returns**: modify shipping tier post-quote; abuse returns to keep the product and the refund.

### Ledger and Settlement Flows

- **Transfer splitting**: split transfers to bypass per-transaction thresholds; schedule vs instant path inconsistencies.
- **Grace-period abuse**: exploit grace periods on holds/authorizations to withdraw again before settlement.

### Subscription and Metering Flows

- **Seat licensing**: race seat assignment to exceed purchased seats; stale license checks in background tasks.
- **Usage metering**: report late or duplicate usage to avoid billing or to over-consume.

## Bypass Techniques

- **Client recomputation**: totals, taxes, discounts computed on the client and accepted by the server.
- **Client-side gates**: a gate or hidden interface enforced only in the browser is bypassed by direct calls, and `proxy-techniques-dom-clobbering` covers markup that shadows a global the client trusts, so name it at the client-gate step rather than restating its mechanics.
- **Proxy-family naming**: name the proxy-techniques family at the channel-wrapping step for content-type switching and method alternation, rather than restating the channel tricks here.
- **Defence-family naming**: name the defence-bypass family at the edge-versus-core step for stale gateway decisions, rather than restating the gateway differentials here.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Business logic + race**: duplicate benefits before state updates.
- **Business logic + IDOR**: operate on others' resources once a workflow leak reveals identifiers.
- **Business logic + CSRF**: force a victim to complete a sensitive step sequence.

## Testing Methodology

1. **Enumerate state machine** - Per critical workflow (states, transitions, pre/post-conditions); note invariants
2. **Build Actor × Action × Resource matrix** - Unauth, basic user, premium, staff/admin; identify actions per role
3. **Test transitions** - Step skipping, repetition, reordering, late mutation
4. **Introduce variance** - Time, concurrency, channel (mobile/web/API/schema layer), content-types
5. **Validate persistence boundaries** - All services, queues, and jobs re-enforce invariants

Alternate transition orders are replayed by `scripts/business-logic-step-skip`, which records each order's outcome and the state read beside it, so an accepted skip is attributable to the missing guard.

## Variants

- concurrent-duplication - Duplicate constrained operations through parallel submission when the atomic check races, including foreign idempotency-key reuse.
- value-domain-manipulation - Submit boundary values through constrained transitions when server-side recomputation is missing, across currency, rounding, and tax selectors.
- quota-window-slicing - Slice windowed limits through reset-edge timing and reserve-hold-release lifecycles when counters reset non-atomically.
- async-boundary-abuse - Trigger async sagas and workers across service boundaries when downstream re-enforcement is missing, and mutate values between calls.

## False Positives

- **Policy-allowed behavior**: promotional behavior explicitly allowed by policy (documented free trials, goodwill credits).
- **Visual-only inconsistencies**: visual-only inconsistencies with no durable or exploitable state change.
- **Admin-only operations**: admin-only operations with proper audit and approvals.

## Pro Tips

- **Invariants first**: start from invariants and ledgers, not the UI: prove conservation of value breaks.
- **Time and concurrency**: test with time and concurrency; many bugs only appear under pressure.
- **Server-side recomputation**: recompute totals server-side; flag every observed acceptance of client math.
- **Idempotency first**: treat idempotency and retries as first-class: verify key scope and persistence.
- **Background workers**: probe background workers and webhooks separately; they often skip auth and rule checks.
- **Service-side gate validation**: validate role and feature gates at the service that mutates state, not only at the edge.
- **Period edges**: explore end-of-period edges (month-end, trial end, daylight saving) for rounding and window issues.
- **Auditable PoCs**: use minimal, auditable PoCs that demonstrate durable state change and exact loss.
- **Authorization chaining**: chain with authorization tests (object-level and function-level access) to magnify impact.
- **State-machine mapping**: when in doubt, map the state machine; gaps appear where transitions lack server-side guards.

## Summary

Business logic security is the enforcement of domain invariants under adversarial sequencing, timing, and inputs. If any step trusts the client or prior steps, expect abuse.
