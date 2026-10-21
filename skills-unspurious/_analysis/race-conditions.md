# race-conditions - variant decomposition analysis

## 1. Class and scope

Race conditions exploit missing atomicity, isolation, or idempotency in state-changing workflows by interleaving concurrent requests so that checks and effects separate in time.
The authority is `skills-unspurious/race-conditions/SKILL.md` (154 lines), consulted with extra methodology from `skills/race-conditions/SKILL.md` (183 lines) as non-authority background only.
The class spans single-service read-modify-write gaps, idempotency and dedup bypasses, cross-service eventual-consistency windows, quota-counter bursts, optimistic-concurrency evasion, lock and isolation flaws, single-request fan-out, storage finalize races, and one-time-token consumption races, all tested by adversarial concurrency rather than by crafted payloads.

## 2. Ontology entity ledger

STATE 1 worked here: the class carries seven methodology steps and ten pinnable entity types, so branch 1a does not trigger and no malformed-class outlier exists.

| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | The values are read-modify-write sequences without atomicity, check-reserve-commit phase gaps, saga and async-job eventual-consistency topology, edge-only rate-limit enforcement, optimistic-concurrency marker presence or absence, idempotency-key scope TTL and persistence conditions, single-node lock storage, READ COMMITTED and REPEATABLE READ isolation levels, multi-part-upload finalize windows, and one-time-token consumability. | See spurious skill lines 10-23 and 26-38 and 77-86. | This type is a discriminator candidate collapsed under the technique feature per STATE 3 branch 3a. |
| TechnologyStack | The values are HTTP/2 multiplexing, GraphQL batched mutations and persisted queries, WebSocket channels, Redis locks, relational isolation levels, CDN and edge enforcement points, file and object storage with pre-signed URLs, and password-reset and OTP flows. | See spurious skill lines 41-46 and 77-106 and live skill lines 26-34 and 106-127. | This type is a non-discriminator because transports and products parametrize execution and no step bends when they change. |
| DefensiveControl | The values are atomic DB statements, unique indexes with upserts, serializable transactions, advisory locks and queues, idempotency stores with key scope and durable persistence, ETag and If-Match enforcement, atomic rate-limit counters, Redis locks with NX EX and fencing tokens, and per-message authorization. | See spurious skill lines 26-31 and 48-52 and 71-86 and 132-137. | This type is a non-discriminator because controls are the oracle each test checks rather than the axis that bends steps. |
| VulnerabilityClass | The value is race condition as TOCTOU and concurrent state-manipulation weakness. | See spurious skill lines 6-8. | This type is a non-discriminator because it is the class definition itself. |
| AttackGoal | The values are duplicate state changes, quota and limit bypass, financial abuse through double spend and double refund, over-issuance of credits and vouchers, privilege and role errors, and audit-trail corruption. | See spurious skill lines 6-8 and 115-120 and live skill lines 161-165. | This type is a non-discriminator because goals motivate the test without changing the kind of testing action. |
| AttackerCapability | The values are parallel-request issuance, warmed-connection and last-byte timing control, multi-IP multi-session and multi-account control, timeout provocation for retry induction, and server-load degradation to widen windows. | See spurious skill lines 41-46 and 108-113 and live skill lines 168-179. | This type is a non-discriminator because concurrency ability is an applicability condition and identity rotation co-varies with technique per branch 3a. |
| AttackTechnique | The values are synchronized parallel duplicate submission, idempotency-key scope reuse with store-timing abuse, optimistic guard omission with stale versions, cross-service window exploitation with retry induction, single-request fan-out through batching and aliases, topological distribution across nodes and regions, and storage finalize interleaving. | See spurious skill lines 41-106 and 108-113 and live skill lines 52-104. | This type is the sole signature discriminator with four values that each break a distinct parent step. |
| PayloadPattern | The values are identical-input replay sets, reused idempotency keys, omitted If-Match headers, stale version fields, aliased and batched mutation documents, and concurrently reused pre-signed URLs. | See spurious skill lines 44-52 and 71-74 and 87-100. | This type is a non-discriminator because patterns instantiate a technique inside a variant without bending any step by themselves. |
| Artifact | The values are idempotency keys, ETags and version fields, one-time reset codes and magic links, pre-signed URLs, correlation IDs, ledger entries, and issued sessions. | See spurious skill lines 28-31 and 103-106 and live skill lines 124-127. | This type is a non-discriminator because handled objects are interchangeable across techniques. |
| ObservableSignal | The values are sequential-fails-but-parallel-succeeds, duplicate rows negative counters and over-issuance, simultaneous-versus-sequential response divergence, out-of-order audit logs, and multiple 2xx responses for one intent. | See spurious skill lines 33-38. | This type is a non-discriminator because success signals confirm every variant identically. |

## 3. RDF notion map

The RDF source document named in SPEC section 4 is absent from `docs/design/`, so this map uses the notion list stated inline in SPEC section 4 and records the absence as a grey point in section 11.
Vuln-specific attack surface and reconnaissance holds read-modify-write paths, multi-step workflows, cross-service sagas, and edge-only quotas plus window-identification recon, varies by target workflow, and is invariant in method.
Adversarial capabilities holds parallel issuance, timing control, multi-identity control, and retry induction, varies by variant in that V3 needs cross-service reach and V4 needs batch access, and is invariant in that the attacker always races rather than crafts.
Common trust assumptions holds trust that checks precede effects atomically, that idempotency keys are scoped and durable, that versions are validated on every path, and that one-time tokens consume once, varies per variant in which assumption is attacked, and is invariant in that every assumption concerns non-interleaving.
Testing methodology holds S1 through S7, is invariant across the class, and varies only through the variant deltas stated in section 11.
Proxy techniques holds method and content-type switching to reach the same state change, is invariant as channel tricks, and is owned by the `proxy-techniques` family per SPEC section 7 so it is named and not restated.
Defence bypass techniques holds per-entity throttle evasion and cross-path guard gaps, is named to the `defence-bypass` family per SPEC section 7, and is not restated.
Techniques anti-patterns holds assuming sequential semantics, trusting visual-only effects, and accepting non-durable evidence, and is invariant as prohibitions.
Scripted tests holds nothing because the spurious class carries no `references/` directory, and this empty notion is reported as an outlier rather than hidden.
False positives holds enforced version checks, serializable transactions, correct locks and queues, and atomic counters, and is invariant as an oracle qualifier.
Chaining holds business-logic invariant abuse, IDOR ownership races, CSRF amplification, and stale-cache re-service, varies by partner skill, and is invariant in that races magnify through partners.

## 4. Runtime parametrisation

The L0 store supplies the concrete Endpoint, Parameter, Header, BaseURL, Service-adjacent Technology, and HTTP history nodes per `src/polymerhus/recon/domain/curator.py:27-31` as cited in the domain model.
The L1 layer supplies the judged Service whose workflow is raced, the System carrying channel transport and lock mechanism properties, and the DataItem records such as balances ledgers inventories and entitlements that the invariant predicates range over.
The HTTP history supplies the recorded baseline sequence that enables identical-input replay and interleaving comparison.
The operator knowledge base supplies the business framing such as conservation rules and single-use policies that names the invariants.
Every entity above parametrizes a variant at runtime and none of them defines a variant.

## 5. Agent-with-skill walkthrough

STATE 1 worked here: the parent methodology contributes exactly the seven steps below, and the realistic hunting circumstance precedes them.
The agent hunts a credits, coupon, refund, and quota product where balances, single-use codes, counters, and one-time tokens mutate across services and channels.
S1 models invariants: the agent states conservation of value, uniqueness, and maximum rules for each workflow.
S1 is complete when every workflow names its invariant and its authoritative source.
S2 identifies reads and writes: the agent locates where each read and effect occurs across service, DB, and cache.
S2 is complete when every invariant maps to its read sites and write sites.
S3 runs the baseline: the agent issues single requests to establish expected sequential behavior.
S3 is complete when the sequential accept and deny behavior is recorded with before and after state.
S4 issues concurrent requests: the agent fires parallel requests with identical inputs and observes deltas.
S4 is complete when identical parallel input either held the invariant or produced a durable violation.
S5 scales and synchronizes: the agent ramps parallelism and aligns timing with warmed HTTP/2 connections and last-byte sync.
S5 is complete when the tightest achievable interleaving either held or broke the invariant reproducibly.
S6 tests cross-channel: the agent repeats the race across web, API, GraphQL, and WebSocket paths.
S6 is complete when each channel either enforced the same guard or yielded its own finding.
S7 confirms durability: the agent verifies that state changes persist and reproduce.
S7 is complete when ledger, count, or role evidence proves durable impact with a minimal repeatable request set.

## 6. Feature-verdict table

STATE 2 worked here: every candidate feature below faced Question A for accuracy and Question B for exhaustiveness, and no state was skipped.

| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Synchronized parallel duplicate submission | No. | Yes. | Non-discriminator as parent core. | S4 plus S5 perform exactly this kind of action and their descriptions cover identical inputs with ramping timing precision. |
| Idempotency-key scope reuse with store-timing abuse | Yes. | No. | Discriminator. | S4 performs identical-input firing rather than cross-principal key reuse, and S4 never describes cache-before-commit windows or response-only dedup forensics. |
| Optimistic guard omission with stale versions | Yes. | No. | Discriminator. | S4 prescribes identical inputs while the candidate mutates concurrency tokens, and no parent step describes guard-omission or cross-path validation-gap probing. |
| Cross-service window exploitation with retry induction | Yes. | No. | Discriminator. | S2 locates reads and writes by store while the candidate maps write-versus-publish with compensation semantics, and S5 ramps timing rather than inducing retries across services. |
| Single-request fan-out through batching and aliases | Yes. | No. | Discriminator. | S4 demands parallel requests while the candidate packs many state changes into one request, so the kinds of action differ entirely. |
| Topological distribution across nodes and regions | No. | Yes. | Aspect inside V3. | Routing to other nodes varies the locus of a cross-service window probe without changing its kind of action. |
| Storage finalize interleaving | No. | Yes. | Aspect of the parent core. | Parallel finalize with identical inputs is exactly what S4 performs, with corruption versus duplication as oracle detail inside S7. |
| One-time-token concurrent consumption | No. | Yes. | Aspect of the parent core. | Identical-token parallel consume is exactly what S4 performs, with session-count enumeration as oracle detail inside S7. |
| Technology and transport choice | No. | Yes. | Non-discriminator. | S6 already varies channel as the same kind of action. |
| Payload shape and key reuse pattern | No. | Yes. | Non-discriminator. | Patterns instantiate steps without changing the kind of action any step performs. |
| Attacker role and identity count | No. | Yes. | Non-discriminator. | Identities parametrize S5 scaling and co-vary with technique per branch 3a. |
| Attack goal | No. | Yes. | Non-discriminator. | One step set serves double-spend, quota bypass, and privilege errors alike, so goals never bend a step. |
| Artifact identity | No. | Yes. | Non-discriminator. | Keys tokens and URLs are handled objects that no step description depends on. |
| Observable signal | No. | Yes. | Non-discriminator. | Every variant confirms through the same S7 durability check. |
| Defensive control presence or version | No. | Yes. | Non-discriminator. | Controls are checked by steps rather than described as step variations. |
| Parallelism degree and timing precision | No. | Yes. | Non-discriminator as continuous aspect per branch 3b. | N and sync precision scale S5 without partitioning it. |

## 7. Step-coverage falsification

Idempotency-key scope reuse breaks S4 (`Concurrent requests`, spurious lines 126-127) because S4 describes firing parallel requests with identical inputs but never describes reusing one key across principals or paths, probing the cache-before-commit write window, or distinguishing response-dedup from effect-dedup.
Optimistic guard omission breaks S4 because S4 prescribes identical inputs while the candidate removes If-Match headers, replays stale versions, and exercises GraphQL-versus-REST path gaps that no parent step describes.
Cross-service window exploitation breaks S2 (`Identify reads/writes`, spurious lines 124-125) because S2 describes locating reads and writes by service DB and cache while the candidate maps write-versus-publish ordering with retry and compensation semantics that S2 never mentions.
Single-request fan-out breaks S4 because S4 demands parallel requests while the candidate hides many state changes inside one batched, aliased, or persisted request plus concurrent WebSocket emits over one connection.
Topological distribution does not break S5 because hitting other nodes or regions varies the target of a window probe while the probe itself remains the kind of action V3 already describes.
Storage finalize interleaving does not break S4 because parallel finalize with identical inputs is exactly the action S4 describes.
One-time-token consumption does not break S4 because identical-token parallel consume is exactly the action S4 describes, with session enumeration belonging to S7 durability.

## 8. Hypotheses

H1 states that AttackTechnique window and guard shape alone discriminates the class into the parent core plus idempotency-dedup-bypass, optimistic-guard-evasion, cross-service-consistency-race, and single-request-fanout variants.
H1 predicts four derived variants plus the parent core, and H1 is falsified for any proposed variant that lacks its own non-coverable step.
H2 states that AttackTechnique combined with PreconditionEnvironment synchrony discriminates further into single-service-sync and distributed-async product variants.
H2 predicts at least one product variant with a step no single-feature variant covers, and H2 is falsified if every combination is covered by single-feature variants under branch 5a.
H3 states that AttackGoal discriminates the class into financial-duplication, quota-bypass, and privilege-error variants.
H3 predicts goal-shaped variant sets, and H3 is falsified because one step set demonstrably serves all three goals so goals fail Question A.

## 9. Variant sets per hypothesis

STATE 4 and STATE 5 worked here: H1 survives intact, H2 loses its products on branch 5a, and H3 is discarded on the step test.

| Hypothesis | Variant | First non-coverable step | Divergence delta |
|---|---|---|---|
| H1 | Parent core synchronized-parallel-duplication is retained. | No step fails because S1 through S7 describe identical-input racing with timing sync and durability confirmation. | This core adds nothing beyond the parent and remains the baseline that lost-update, counter-burst, finalize, and token races execute. |
| H1 | idempotency-dedup-bypass is derived. | S4 fails first because S1 through S3 cover invariants, read-write mapping, and baselines. | This variant adds cross-principal key-scope reuse with cache-before-commit window probing and response-versus-effect dedup forensics. |
| H1 | optimistic-guard-evasion is derived. | S4 fails first because S3 baselines still hold for guard-carrying singles while identical-input concurrency never describes token mutation. | This variant adds concurrency-token omission and stale-version replay with cross-path validation-gap probing. |
| H1 | cross-service-consistency-race is derived. | S2 fails first because write-versus-publish with compensation semantics exceeds store-located read-write mapping. | This variant adds write-versus-publish ordering exploitation with timeout-induced retry storms and compensation-without-prevention triggering. |
| H1 | single-request-fanout is derived. | S4 fails first because one crafted request replaces many parallel requests entirely. | This variant adds intra-request fan-out through batched and aliased mutations and persisted queries with persistent-connection concurrent emits as a secondary divergence. |
| H2 | distributed-idempotency-race is proposed as a product. | No own step exists because V1 already covers key-scope forensics and V3 already covers cross-node topology. | This product adds nothing non-coverable so branch 5a deletes it. |
| H2 | async-guard-evasion is proposed as a product. | No own step exists because V2 already covers guard omission and V3 already covers async windows. | This product adds nothing non-coverable so branch 5a deletes it. |
| H3 | financial-duplication is proposed. | No step fails because identical parallel duplication serves financial and non-financial goals alike. | This proposal adds no step so the step test discards it. |
| H3 | quota-bypass is proposed. | No step fails because counter bursts are identical-input races already covered by the parent core. | This proposal adds no step so the step test discards it. |

## 10. Well-formedness evaluation

STATE 6 worked here: each set is scored against the weighted criteria, the winner is named with its losing reasons, and branch 6a does not trigger because the winner passes coverage and disjointness.

| Criterion and weight | H1 set | H2 set | H3 set |
|---|---|---|---|
| Coverage is critical. | Pass because every genuine non-coverable step belongs to exactly one of the four variants with the remainder held by the parent core. | Pass on coverage but only by inheriting the H1 set. | Fail because key-scope, guard-omission, compensation, and fan-out steps belong to no goal variant. |
| Disjointness is critical. | Pass because key-scope forensics, token-mutation probing, cross-service window triggering, and intra-request fan-out are disjoint by execution shape and locus. | Fail because each product falls in two single-feature variants at once. | Fail because one double-refund technique falls in two goal variants. |
| Divergence delta is high. | Pass because each variant adds its own non-coverable step. | Fail because no product adds a step of its own. | Fail because no goal variant adds any step. |
| Stability is high. | Pass because window and guard shapes survive changes of stack, payload, version, and runtime asset. | Pass on stability but irrelevantly since the set already fails. | Fail because goals shift with business policy rather than procedure. |
| Parsimony is medium. | Pass as the fewest features that still cover with one feature. | Fail because two features cover nothing more than one. | Fail because goal features multiply names without covering steps. |

The winner is the H1 set for covering every non-coverable step with disjoint stable variants from a single feature.
H2 loses on parsimony and disjointness because its synchrony axis co-varies with technique per branch 3a and adds no non-coverable step beyond it.
H3 loses on coverage and the step test because goals motivate without bending steps.

## 11. Recommended set

STATE 7 worked here: the signature is stated as one sentence, each variant carries its delta, non-discriminators are explicit, and open questions with grey points close the analysis.
A race-conditions candidate is a distinct variant iff its AttackTechnique window and guard shape forces a testing step of key-scope forensics, token-mutation probing, cross-service window triggering, or intra-request fan-out that the parent S1-S7 methodology neither performs nor describes.
Variant `idempotency-dedup-bypass` adds cross-principal key-scope reuse with cache-before-commit window probing and response-versus-effect dedup forensics.
Variant `optimistic-guard-evasion` adds concurrency-token omission and stale-version replay with cross-path validation-gap probing, carrying method-switched same-effect paths as a named proxy-techniques secondary per SPEC section 7.
Variant `cross-service-consistency-race` adds write-versus-publish ordering exploitation with timeout-induced retry storms and compensation-without-prevention triggering, carrying node and region distribution as a secondary divergence.
Variant `single-request-fanout` adds intra-request fan-out through batched and aliased mutations and persisted queries with persistent-connection concurrent emits as a secondary divergence, naming the `graphql` skill for schema and resolver discovery rather than restating it.
Non-discriminators are TechnologyStack transports and products, runtime L0 and L1 entities with HTTP history, AttackerCapability roles and identity counts, PayloadPattern shapes, Artifact identities, ObservableSignal forms, DefensiveControl presence and versions, AttackGoal motives, parallelism degree and timing precision as continuous aspects, and synchronized parallel duplication which remains the parent core with storage finalize and one-time-token races as aspects.
Cross-cutting steps name `business-logic` for S1 invariant semantics, `two-principal-authz` for race-plus-IDOR ownership checks, and the `defence-bypass` and `proxy-techniques` families for throttle and channel tricks.
Open questions are whether identity-partitioned quota bursts deserve promotion from a core aspect to a fifth variant when per-entity enforcement forces distinct orchestration, and whether scripted `references/` tests should exist for each variant.
Grey points are the absent RDF source document noted in section 3, the continuous N and sync-precision values documented as aspects inside the parent core per branch 3b, the PreconditionEnvironment and AttackerCapability co-variance collapsed under technique per branch 3a, the quota-burst boundary rule assigning identical-input bursts to the core and window-triggered compensation to V3, and the folded token and finalize races which an adversarial change of consumption-atomicity assumptions could promote to further variants.
