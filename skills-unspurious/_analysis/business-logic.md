# business-logic - variant decomposition analysis

## 1. Class and scope

Business logic flaws exploit intended application functionality to violate domain invariants such as conservation of value, uniqueness, monotonicity, and exclusivity.
The authority is `skills-unspurious/business-logic/SKILL.md` (151 lines), consulted with extra methodology from `skills/business-logic/SKILL.md` (180 lines) as non-authority background only.
The class spans financial logic, account lifecycles, authorization-by-logic, quotas and inventory, multi-tenant isolation, and event-driven flows, all tested by modelling the business rather than by injecting payloads.

## 2. Ontology entity ledger

STATE 1 worked here: the class carries five methodology steps and ten pinnable entity types, so branch 1a does not trigger and no malformed-class outlier exists.

| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | The values are multi-step stateful workflows with server-side transitions, account lifecycle states, windowed quota and counter resets, async saga queue cron and backfill topology, multi-tenant organization scoping, and currency locale timezone and tax-region rulesets. | See spurious skill lines 12-19 and 21-37. | This type is a discriminator candidate collapsed under the technique feature per STATE 3 branch 3a. |
| TechnologyStack | The values are mobile web API and GraphQL channels, JSON form and multipart content types, CDN and API management gateways, and microservice topology. | See spurious skill lines 109-114 and live skill lines 42-44 and 96-100. | This type is a non-discriminator because channels parametrize execution and S4 already varies them. |
| DefensiveControl | The values are per-transition server-side precondition checks, atomicity and idempotency guards with key scope and durable storage, per-service authorization re-enforcement, tenant-key enforcement in writes, rate usage and inventory counters, post-consumption refund checks, and edge versus core feature-gate enforcement. | See spurious skill lines 41-57 and 70-86 and live skill lines 139-147. | This type is a non-discriminator because controls are the oracle each test checks rather than the axis that bends steps. |
| VulnerabilityClass | The value is business logic flaw as domain invariant violation. | See spurious skill line 8. | This type is a non-discriminator because it is the class definition itself. |
| AttackGoal | The values are unpaid value extraction, quota and entitlement overuse, privilege retention after transition, approval and review bypass, duplicated fulfillment or refund, and cross-tenant effect. | See spurious skill lines 8 and 12-18 and 65-73. | This type is a non-discriminator because goals motivate the test without changing the kind of testing action. |
| AttackerCapability | The values are unauthenticated basic premium staff and administrator roles, parallel session control for concurrent submission, and stale token flag and key reuse across users and sessions. | See spurious skill lines 21-25 and 34-38 and live skill lines 139-141. | This type is a non-discriminator because S2 enumerates roles exhaustively and concurrency ability is an applicability condition rather than a step-bending value. |
| AttackTechnique | The values are sequential transition manipulation, concurrent duplicate execution, value-domain boundary submission, window and lifecycle slicing, and async-boundary triggering. | See spurious skill lines 41-57 and 61-87 and 94-107. | This type is the sole signature discriminator with four values that each break a distinct parent step. |
| PayloadPattern | The values are negative zero null empty and scientific-notation numerics, array-for-scalar and unexpected-key shape swaps, currency and locale selector values, client-computed totals, and content-type and method-override wrappers. | See spurious skill lines 29-31 and 53-57 and 109-114. | This type is a non-discriminator because patterns instantiate a technique inside a variant without bending any step by themselves. |
| Artifact | The values are step tokens and flags, idempotency keys, reservation holds, discount credit and voucher instruments, and metered usage reports. | See spurious skill lines 22-25 and 49-51 and 61-63. | This type is a non-discriminator because handled objects are interchangeable across techniques. |
| ObservableSignal | The values are durable invariant violation in an authoritative source, retained capability after downgrade, duplicated side effect after retry, and cross-tenant visible state. | See spurious skill lines 136-147 and live skill lines 145-150. | This type is a non-discriminator because success signals confirm every variant identically. |

## 3. RDF notion map

The RDF source document named in SPEC section 4 is absent from `docs/design/`, so this map uses the notion list stated inline in SPEC section 4 and records the absence as a grey point in section 11.
Attack surface and reconnaissance holds financial lifecycle gate quota tenant and event-driven surfaces plus workflow input and time-axis recon, varies by target business, and is invariant in method.
Adversarial capabilities holds the role ladder plus replay reorder and parallelize abilities, varies by variant in that V1 needs parallel session control, and is invariant in that the attacker is always a legitimate user abusing intended function.
Common trust assumptions holds trust in client math, prior-step completion, edge gate decisions, single-service totals, and tenant scoping, varies per variant in which assumption is attacked, and is invariant in that every assumption is server-unverified.
Testing methodology holds S1 through S5, is invariant across the class, and varies only through the variant deltas stated in section 11.
Proxy techniques holds content-type switching and method alternation, is invariant as channel tricks, and is owned by the `proxy-techniques` family per SPEC section 7 so it is named and not restated.
Defence bypass techniques holds edge versus core gate gaps and stale gateway decisions, is named to the `defence-bypass` family per SPEC section 7, and is not restated.
Techniques anti-patterns holds accepting client math, checking once then trusting, and cache-only idempotency, and is invariant as prohibitions.
Scripted tests holds nothing because the spurious class carries no `references/` directory, and this empty notion is reported as an outlier rather than hidden.
False positives holds policy-allowed promotions, visual-only drift, and audited admin operations, and is invariant as an oracle qualifier.
Chaining holds race IDOR and CSRF combinations, varies by partner skill, and is invariant in that logic flaws magnify through partners.

## 4. Runtime parametrisation

The L0 store supplies the concrete Endpoint, Parameter, Header, BaseURL, Service-adjacent Technology, and HTTP history nodes per `src/polymerhus/recon/domain/curator.py:27-31` as cited in the domain model.
The L1 layer supplies the judged Service whose contract the workflow violates, the System carrying channel and mechanism properties, and the DataItem records such as orders ledger entries and entitlements that the trust predicates range over.
The HTTP history supplies the recorded step sequence that enables replay, reorder, and late-mutation execution.
The operator knowledge base supplies the business framing such as pricing rules and trial policy that names the invariants.
Every entity above parametrizes a variant at runtime and none of them defines a variant.

## 5. Agent-with-skill walkthrough

STATE 1 worked here: the parent methodology contributes exactly the five steps below, and the realistic hunting circumstance precedes them.
The agent hunts a checkout and subscription product where pricing, discounts, trials, seats, refunds, and webhooks interact across services.
S1 enumerates the state machine: the agent lists states, transitions, and preconditions and postconditions per critical workflow and notes the invariants.
S1 is complete when every transition names its guard and every invariant names its authoritative source.
S2 builds the Actor x Action x Resource matrix: the agent maps unauthenticated, basic, premium, staff, and administrator roles against every action and resource.
S2 is complete when each cell states allowed or denied with the enforcing service named.
S3 tests transitions: the agent skips, repeats, reorders, and late-mutates steps through direct calls.
S3 is complete when each transition either enforced its precondition or yielded a durable violation.
S4 introduces variance: the agent varies time, concurrency, channel, and content type around the transitions.
S4 is complete when each variance dimension was exercised without assuming it is covered by functional repetition.
S5 validates persistence boundaries: the agent verifies that all services, queues, and jobs re-enforce the invariants.
S5 is complete when every async and downstream writer demonstrably rechecked the invariant or produced a finding.

## 6. Feature-verdict table

STATE 2 worked here: every candidate feature below faced Question A for accuracy and Question B for exhaustiveness, and no state was skipped.

| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Sequential transition manipulation | No. | Yes. | Non-discriminator as parent core. | S3 performs exactly this kind of action and its description covers skipping, repetition, reordering, and late mutation. |
| Concurrent duplicate execution | Yes. | No. | Discriminator. | S4 performs generic variance rather than orchestrated duplication, and S4 never describes key scope or store-durability forensics. |
| Value-domain boundary submission | Yes. | No. | Discriminator. | S3 performs transition testing rather than boundary-value oracle testing, and no parent step describes server-side recomputation checks. |
| Window and lifecycle slicing | Yes. | No. | Discriminator. | S3 repetition plus S4 time-variance differ in kind from reset-edge and hold-lifecycle probing, and neither step describes reserve-complete-release lifecycles. |
| Async-boundary triggering | Yes. | No. | Discriminator. | S5 performs boundary validation rather than between-call mutation or independent compensation triggering, and its description covers neither action. |
| Post-transition capability reuse in sequence | No. | Yes. | Aspect of the parent core. | S2 plus S3 perform matrix-then-repeat exactly, while only the background-task depth belongs to V4 as a secondary divergence. |
| Channel and technology choice | No. | Yes. | Non-discriminator. | S4 already varies channel and content type as the same kind of action. |
| Payload encoding and shape | No. | Yes. | Non-discriminator. | Encodings instantiate steps without changing the kind of action any step performs. |
| Attacker role | No. | Yes. | Non-discriminator. | S2 enumerates every role explicitly so no role value escapes its description. |
| Attack goal | No. | Yes. | Non-discriminator. | One step set serves several goals, so goals never bend a step. |
| Artifact identity | No. | Yes. | Non-discriminator. | Tokens keys and holds are handled objects that no step description depends on. |
| Observable signal | No. | Yes. | Non-discriminator. | Every variant confirms through the same durability check in an authoritative source. |
| Defensive control presence or version | No. | Yes. | Non-discriminator. | Controls are checked by steps rather than described as step variations. |
| Special-context domain | No. | Yes. | Non-discriminator. | E-commerce banking and SaaS instantiate the same procedures in different businesses. |

## 7. Step-coverage falsification

Concurrent duplicate execution breaks S4 (`Introduce variance`, spurious lines 124-128) because S4 describes varying concurrency as one variance dimension but never describes firing identical state-changing operations simultaneously while scoping idempotency keys to principal and path and verifying durable versus cache-only storage.
Value-domain boundary submission breaks S3 (`Test transitions`, spurious lines 122-128) because S3 describes skipping, repetition, reordering, and late mutation while rounding-boundary, cross-currency, and client-math recomputation tests are value-oracle actions rather than sequence actions.
Window and lifecycle slicing breaks S4 because S4 names time as a variance dimension but never describes probing reset edges at T-1 and T+1, splitting one constrained action into sequential under-threshold sub-actions, or walking reserve-complete-release hold lifecycles.
Async-boundary triggering breaks S5 (`Validate persistence boundaries`, spurious lines 124-128) because S5 describes verifying that boundaries re-enforce invariants while the candidate mutates values between two service calls, triggers compensation without original success, and replays worker retries without idempotent guards.
Post-transition capability reuse does not break S2 plus S3 because re-exercising matrix actions after a downgrade is repetition of a matrixed action, while stale license checks inside background tasks are assigned to V4 as a secondary divergence rather than a new variant.

## 8. Hypotheses

H1 states that AttackTechnique shape alone discriminates the class into sequential core, concurrent duplication, value-domain manipulation, window slicing, and async-boundary variants.
H1 predicts four derived variants plus the parent core, and H1 is falsified for any proposed variant that lacks its own non-coverable step.
H2 states that AttackTechnique combined with PreconditionEnvironment synchrony discriminates further into sync-concurrent and async-concurrent product variants.
H2 predicts at least one product variant with a step no single-feature variant covers, and H2 is falsified if every combination is covered by single-feature variants under branch 5a.
H3 states that AttackGoal discriminates the class into financial-gain, privilege-retention, and over-consumption variants.
H3 predicts goal-shaped variant sets, and H3 is falsified because one step set demonstrably serves several goals so goals fail Question A.

## 9. Variant sets per hypothesis

STATE 4 and STATE 5 worked here: H1 survives intact, H2 loses its product on branch 5a, and H3 is discarded on the step test.

| Hypothesis | Variant | First non-coverable step | Divergence delta |
|---|---|---|---|
| H1 | concurrent-duplication is derived. | S4 fails first because S1 through S3 cover mapping, matrix, and sequential transitions. | This variant adds orchestrated parallel duplicate execution with idempotency-key scope and store-durability forensics. |
| H1 | value-domain-manipulation is derived. | S3 fails first because boundary-oracle testing is not transition testing. | This variant adds value-domain boundary submission with a server-side recomputation oracle. |
| H1 | quota-window-slicing is derived. | S4 fails first because reset-edge and hold-lifecycle probing exceed time-variance. | This variant adds reset-edge timing and reserve-complete-release lifecycle probing. |
| H1 | async-boundary-abuse is derived. | S5 fails first because triggering differs from validating. | This variant adds between-call mutation with independent compensation and retry triggering across service queue and tenant boundaries. |
| H2 | async-concurrent-retry is proposed as a product. | No own step exists because V4 already covers retry triggering and V1 already covers duplication. | This product adds nothing non-coverable so branch 5a deletes it. |
| H3 | financial-gain is proposed. | No step fails because parallel duplication and boundary submission serve financial and non-financial goals alike. | This proposal adds no step so the step test discards it. |
| H3 | privilege-retention is proposed. | No step fails because matrix repetition serves retention and bypass alike. | This proposal adds no step so the step test discards it. |

## 10. Well-formedness evaluation

STATE 6 worked here: each set is scored against the weighted criteria, the winner is named with its losing reasons, and branch 6a does not trigger because the winner passes coverage and disjointness.

| Criterion and weight | H1 set | H2 set | H3 set |
|---|---|---|---|
| Coverage is critical. | Pass because every genuine non-coverable step belongs to exactly one of the four variants. | Pass on coverage but only by inheriting the H1 set. | Fail because value-oracle, reset-edge, and compensation steps belong to no goal variant. |
| Disjointness is critical. | Pass because simultaneous duplication, single-transition value-oracles, sequential window slicing, and cross-boundary triggering are disjoint by execution shape and locus. | Fail because async-concurrent-retry falls in both V1 and V4. | Fail because one double-refund technique falls in two goal variants. |
| Divergence delta is high. | Pass because each variant adds its own non-coverable step. | Fail because the product adds no step of its own. | Fail because no goal variant adds any step. |
| Stability is high. | Pass because techniques survive changes of stack, payload, version, and runtime asset. | Pass on stability but irrelevantly since the set already fails. | Fail because goals shift with business policy rather than procedure. |
| Parsimony is medium. | Pass as the fewest features that still cover with one feature. | Fail because two features cover nothing more than one. | Fail because goal features multiply names without covering steps. |

The winner is the H1 set for covering every non-coverable step with disjoint stable variants from a single feature.
H2 loses on parsimony and disjointness because its environment axis adds no non-coverable step beyond the technique axis.
H3 loses on coverage and the step test because goals motivate without bending steps.

## 11. Recommended set

STATE 7 worked here: the signature is stated as one sentence, each variant carries its delta, non-discriminators are explicit, and open questions with grey points close the analysis.
A business-logic candidate is a distinct variant iff its AttackTechnique value forces a testing step of concurrent duplication, value-domain oracles, window-lifecycle slicing, or async-boundary triggering that the parent S1-S5 methodology neither performs nor describes.
Variant `concurrent-duplication` adds orchestrated parallel duplicate execution with idempotency-key scope and store-durability forensics, and it names the `race-conditions` skill for the timing primitive rather than restating it.
Variant `value-domain-manipulation` adds value-domain boundary submission with a server-side recomputation oracle for rounding, cross-currency, and client-math abuse.
Variant `quota-window-slicing` adds reset-edge timing at T-1 and T+1 with reserve-complete-release lifecycle probing for limits, inventory, seats, and trials.
Variant `async-boundary-abuse` adds between-call mutation with independent compensation and retry triggering across service, queue, cron, and tenant boundaries, carrying multi-tenant bleed and background-task gate staleness as secondary divergences.
Non-discriminators are TechnologyStack channels and content types, runtime L0 and L1 entities with HTTP history, AttackerCapability roles, PayloadPattern encodings, Artifact identities, ObservableSignal forms, DefensiveControl presence and versions, AttackGoal motives, special-context domains, and sequential transition manipulation which remains the parent core.
Cross-cutting steps name `two-principal-authz` for authorization principals, the `defence-bypass` and `proxy-techniques` families for gate and channel tricks, `graphql` for GraphQL-specific steps, and `oauth` with `authentication-jwt` for token steps.
Open questions are whether proration abuse belongs to value-domain-manipulation or quota-window-slicing by dominant divergence, and whether scripted `references/` tests should exist for each variant.
Grey points are the absent RDF source document noted in section 3, the continuous numeric thresholds documented as aspects inside value-domain-manipulation per branch 3b, the AttackTechnique and PreconditionEnvironment co-variance collapsed per branch 3a, the quota-concurrency boundary rule assigning simultaneous execution to V1 and sequential slicing to V3, and the folded post-transition staleness which an adversarial change of background-task assumptions could promote to a fifth variant.
