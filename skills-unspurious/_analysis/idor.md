# idor - variant decomposition analysis

## 1. Class and scope
IDOR (BOLA) is object-level authorization failure where a request binds subject and action but not the specific object, so a caller reaches or mutates another principal's resource.
The authority is `skills-unspurious/idor/SKILL.md` (200 lines), consulted against `skills/idor/SKILL.md` only for extra methodology detail.
The class covers direct reference swaps across actions and transports, set-level collection and batch scope, deferred job and storage artifact redemption, context-carrier substitution at gateways and services, and nested or expanded sub-resource binding.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | Multi-principal object ownership with per-principal IDs; tenant isolation boundary with selector headers, subdomains, and path params; bulk or batch endpoint with per-item enforcement gap; deferred job or export execution split between creation and retrieval; gateway-injected identity headers present; cache keyed without authorization or tenant headers; GraphQL resolver tree with per-hop binding; expansion or projection knobs present | 12-16, 30-32, 62-65, 73-76, 100-110, 140-142 | Discriminator candidate (resolves to 4 discriminators in section 6) |
| TechnologyStack | REST or API; GraphQL; WebSocket; gRPC; microservices with gateways, queues, and workers; mobile and web clients; file and object storage with signed URLs | 8, 19-20, 84-122 | Non-discriminator (excluded axis, see section 6) |
| DefensiveControl | Per-request subject-action-object binding at the service; resolver-level and edge-resolver checks; per-item batch validation; per-subscription channel checks; token audience and claims validation; tenant scoping on reports and rollups | 56-60, 62-65, 84-90, 100-116 | Discriminator candidate (placement and carrier values discriminate; control presence itself does not) |
| VulnerabilityClass | Broken object-level authorization, BOLA or IDOR | 6-8 | Non-discriminator (this is the class definition itself) |
| AttackGoal | Read another principal's object; mutate another principal's object; cross-tenant access across isolation boundaries | 8, 56-60, 152-158 | Non-discriminator (goal is invariant across variants) |
| AttackerCapability | Working sessions for at least owner and non-owner plus admin or staff where applicable; ability to call endpoints directly with swapped references; ability to supply headers, selectors, and cross-service tokens | 69-70, 159-176 | Non-discriminator (capability ladder is shared setup, owned with `two-principal-authz`) |
| AttackTechnique | Single-reference ID swap with control pairing; tenant selector switching; mid-array batch injection and foreign-key import; pagination and cursor filter-skip; secondary harvest then direct fetch; deferred job result redemption; signed-URL key-prefix change and stale-signature reuse; GraphQL aliasing, batching, Relay node swap, and fragment overfetch; conflicting identity-header injection; cross-service token replay; projection-parameter expansion; differential blind confirmation | 46-48, 56-126, 130-150 | Discriminator candidate (partitions by which step they bend, see section 6) |
| PayloadPattern | Duplicate-parameter and duplicate-key pollution shapes (`id=1&id=2`, `{"id":1,"id":2}`) | 46, 130-138 | Aspect (defeat sub-step inside variants, shared with the bypass family) |
| Artifact | Per-principal object IDs and reusable ID corpus; per-role tokens and sessions; job and task IDs; share tokens and signed URLs; before-and-after state diffs with role-separated evidence | 52, 69-76, 170-173, 185-196 | Non-discriminator (runtime-produced evidence, parametrises proof) |
| ObservableSignal | Returned foreign content or metadata; status, size, ETag, and timing differentials; owned-versus-foreign error-shape difference; empty array or null as silent enforcement | 147-150, 177-183 | Non-discriminator (detection signal shared by all variants) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: reference locations, identifier forms, relationship references, expansion knobs, pagination and cursor shapes, list and search seeders, and UUID or opaque-ID sources (lines 10-52); this notion varies by carrier and depth and is the raw material of discrimination.
Adversarial capabilities: two or more principals with swappable references, tokens, tenants, headers, and transport framings (lines 168-176); this notion is invariant setup and delegates to `two-principal-authz`.
Common trust assumptions: identifier opacity implies privacy, parent authorization covers children, gateway headers carry identity, token acceptance transfers across services, and creation-time checks cover deferred retrieval (lines 8, 30-32, 84-104); each assumption varies independently and each maps to one variant.
Testing methodology: the evidence-derivation preamble plus the six steps S0 to S6 listed in section 5 (lines 159-176); this notion is the step-test substrate and is invariant as parent text.
Proxy techniques: direct-to-core reach around the edge and SSRF-reached internal references (lines 140-142, 152-158); this notion is a reached step owned by the future proxy family and invoked from the context-carrier variant, not restated here.
Defence bypass techniques: parser and transport coercion, parameter pollution, cache-key confusion, race windows, and blind channels (lines 128-150); this notion varies only as defeat detail and rides as aspects inside variants, with race windows owned by `race-conditions`.
Techniques anti-patterns: concluding not-vulnerable from a single wrong-verb or placeholder-ID request (lines 159-166); this notion is an invariant warning.
Scripted tests (`references/`): none shipped with the class skill; no invariant is stated.
False positives: public-by-design resources, soft-privatized data, metadata lookups without sensitive content, and silent-enforcement empty responses (lines 177-183); this notion is invariant across variants.
Chaining: IDOR with CSRF, stored XSS, SSRF, and race (lines 152-158); chaining targets are invariant companions, not variant axes.

## 4. Runtime parametrisation
Each variant consumes the concrete Service under test, the System mechanism overlays it lies on, and the Endpoint plus Parameter, Header, DataItem, and BaseURL atoms that locate the object reference at runtime.
The HTTP history supplies the prior verb and body shapes, the per-principal transcripts, and the differential signals that each variant compares against.
The operator knowledge base supplies the role roster, the tenant layout, and the gateway topology that parametrise matrix rows, header names, and selector values.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding owner and non-owner sessions against a deployed application where object references appear in paths, bodies, headers, or messages and may not be bound to the caller.
S0a Gather evidence: collect client bundles, OpenAPI, prior HTTP, and recon notes, with completion when the real method, path pattern, and body field names are inferable.
S0b Infer verb and body: derive the working method, path pattern, and field names from that evidence, with completion when a same-shape baseline request succeeds for the owner.
S0c Run the two-principal chain: execute the cross-cutting owner-versus-non-owner comparison, with completion when each probe has a control response beside it (procedure owned by `two-principal-authz`, referenced not restated).
S0d Retry before verdict: resubmit failures with the inferred verb and fields, with completion when no probe is judged on a wrong-verb or placeholder-ID attempt.
S1 Build matrix: enumerate Subject by Object by Action cells, with completion when each action on each object has an expected-principal cell.
S2 Obtain principals: acquire one working credential per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`, referenced not restated).
S3 Collect IDs: capture at least one valid object ID per principal from list, search, or export endpoints, with completion when each principal has a seeded corpus.
S4 Cross-channel testing: exercise every action while swapping IDs, tokens, and tenants, with completion when every action has a swapped attempt beside its control.
S5 Transport variation: repeat across web, mobile, API, GraphQL, WebSocket, and gRPC framings, with completion when each reachable framing has a recorded decision.
S6 Consistency check: require the same rule across transport, content-type, serialization, and gateway, with completion when every divergence is either explained or filed.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Trust direction (horizontal peer versus vertical privilege versus cross-tenant) | No (all three use the same kind of action: swap reference or token and compare against the control) | Not applicable | Non-discriminator | S4 at lines 173-174 explicitly enumerates swapping IDs, tokens, and tenants, so direction labels never bend a step |
| Identifier form (integer versus UUID versus composite versus opaque token) | No (one opaque string versus another is the same kind of action) | Not applicable | Non-discriminator (`aspect` for corpus building) | Pitfall rule in SPEC section 8 excludes identifier encoding; opacity changes harvesting effort, never the probe kind |
| Attack goal or impact (read versus write versus delete versus export) | No (goal changes reporting, not the testing action) | Not applicable | Non-discriminator | S4 at line 173 enumerates R, W, D, and Export under one action |
| TechnologyStack name (REST, GraphQL, WebSocket, gRPC, storage product) | No (stack name alone changes tooling, not the authorization-testing action) | Not applicable | Non-discriminator | Stability criterion excludes TechnologyStack; framing detail is owned with transport skills including `graphql` |
| Concrete runtime values (which ID, which tenant string, which header literal, which token) | No (one value versus another is the same kind of action) | Not applicable | Non-discriminator | Values are runtime parameters consumed from the graph, KB, and history |
| Observable signal shape (status pair, size, ETag, timing, error shape) | No (signals are read the same way in every variant) | Not applicable | Non-discriminator | Signals at lines 147-150 and 177-183 detect success for all variants alike |
| AttackerCapability ladder (which roles, how many sessions) | No (setup is shared before any variant diverges) | Not applicable | Non-discriminator | S2 setup is owned with `two-principal-authz` |
| Duplicate-key pollution shape (PayloadPattern) | Yes in tooling only (precedence probing is a distinct trick) | Yes as defeat detail (enumerable inside any variant attempt) | Aspect, not variant axis | Lines 46 and 130-138 describe precedence tries shared with the bypass family |
| Authorization cardinality (singleton reference versus set-level collection: paged lists, bulk arrays, imports) | Yes (mid-array injection and cursor filter-skip perform a different kind of action than single-reference swap) | No (S3 names cooperative capture and S4 names swapping, but neither describes per-item position reasoning or adversarial pagination) | Discriminator D1 | Lines 62-65 and 67-71 versus S3 at line 172 and S4 at lines 173-174 |
| Redemption timing (immediate use versus deferred artifact: job results, exports, signed URLs, share tokens) | Yes (two-phase create-as-A redeem-as-B performs a different kind of action than live swapping) | No (S4 describes swapping on live actions but never describes scope, expiry, or retrieval-time binding of a deferred artifact) | Discriminator D2 | Lines 73-82 versus S4 at lines 173-174 |
| Identity carrier (caller-supplied reference versus context channel: gateway header, cross-service token, async context) | Yes (contradictory-header precedence probing and audience-confusion replay perform a different kind of action than reference swapping) | No (S4 describes swapping tokens and tenants but never describes which identity source wins on conflict or which audience a token is valid for) | Discriminator D3 | Lines 100-104 and 106-110 versus S4 at lines 173-174 |
| Resource depth (top-level object versus nested or expanded sub-resource: projection knobs, resolver hops, fragments) | Yes (parameter-addition escalation performs a different kind of action than reference substitution) | No (S4 describes swapping IDs, tokens, and tenants but never describes adding projection parameters or traversing resolver hops) | Discriminator D4 | Lines 30-32 and 84-98 versus S4 at lines 173-174 |

## 7. Step-coverage falsification
D1 value paged-list scope: parent S3 covers capturing IDs from cooperative listing, but the uncovered reality is manipulating cursors and page windows to skip scoping filters and pull other principals' pages.
D1 value bulk-array position: parent S4 covers swapping a reference on an action, but the uncovered reality is placing foreign IDs mid-array where only the first element is validated and each position needs its own verdict.
D1 value foreign-key import: parent S4 covers live-action swapping, but the uncovered reality is submitting CSV or JSON imports carrying foreign owner or org IDs through a create-time path that never re-checks per row.
D2 value deferred job redemption: parent S4 covers swapping on live actions, but the uncovered reality is creating an export or task as an allowed actor and retrieving, cancelling, or approving another actor's job ID through a retrieval path with no caller check.
D2 value storage-bound redemption: parent S4 covers swapping IDs, tokens, and tenants, but the uncovered reality is changing key prefixes, reusing stale cross-tenant signatures, or swapping share tokens where scope and expiry binding decide the verdict.
D3 value conflicting identity headers: parent S4 covers swapping tokens and varying routing, but the uncovered reality is supplying gateway-trusted headers that contradict token claims and observing which source the service treats as the actor.
D3 value cross-service token replay: parent S4 covers swapping tokens, but the uncovered reality is replaying a token scoped for one service against another that shares verification yet skips audience and claims checks.
D3 value async context loss: parent S4 covers live request swapping, but the uncovered reality is a queue or worker re-processing a request without re-checking authorization after the gateway already passed it.
D4 value projection expansion: parent S4 covers swapping references, but the uncovered reality is adding `fields`, `include`, `expand`, or equivalent knobs to an authorized fetch so resolvers or serializers return privileged sub-fields.
D4 value resolver-hop traversal: parent S5 names GraphQL as a framing, but the uncovered reality is walking authorized parent to unauthorized child across field and edge resolvers with per-hop binding verdicts that no transport framing step describes.
D4 value alias and batch multiplex: parent S4 covers one swap per attempt, but the uncovered reality is retrieving multiple principals' nodes in one aliased or batched request where the per-node decision is the verdict.
Trust direction values: no falsification holds because S4 enumerates swapping IDs, tokens, and tenants for every action.
Identifier opacity values: no falsification holds because S0 plus S3 harvest whatever form the target uses and S4 swaps it unchanged.
Transport framing values: no falsification holds as variant axes because S5 plus S6 enumerate framings while the binding verdicts above stay owned by D1 to D4.

## 8. Hypotheses
H1 Single-feature hypothesis on authorization cardinality: if the only discriminator is D1 (singleton versus set), then the class splits into direct-swap testing versus collection-scope testing, and it is falsified if job redemption, header precedence, or projection expansion bends any step other than S3 or the S4 swap.
H2 Single-feature hypothesis on identity carrier: if the only discriminator is D3 (reference versus context channel), then the class splits into reference testing versus carrier testing, and it is falsified if batch position reasoning, deferred redemption, or resolver-hop traversal bends any step other than S4 token handling.
H3 Combined-feature hypothesis on cardinality by timing by carrier by depth: if D1 bends S3 and the S4 swap while D2, D3, and D4 each bend the S4 swap on disjoint uncovered values, then the class yields exactly five variants, and it is falsified if any two discriminators claim the same uncovered value or any proposed variant lacks its own non-coverable step.
H4 Trust-mode split hypothesis: if horizontal, vertical, and cross-tenant access each deserve a variant, then each direction adds its own non-coverable step, and it is falsified by S4 naming all three directions in one step with one kind of action.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | idor-direct-object-swap | S4 (control-paired swap with evidence-derived verb plus differential confirmation, which S4 never names) | Trust directions; identifier forms; goals; transport framings |
| H1 | idor-collection-scope | S3 (adversarial pagination) with S4 position reasoning | Cursor shapes; array positions; import rows |
| H2 | idor-direct-object-swap | Same S4 delta as above | Trust directions; identifier forms |
| H2 | idor-context-carrier | S4 (precedence and audience reasoning) | Header names; token pairs; queue paths |
| H3 | idor-direct-object-swap | S4 (control-paired swap with evidence-derived verb plus differential confirmation) | Trust directions; identifier forms; goals; framings; blind differentials |
| H3 | idor-collection-batch-scope | S3 (cursor filter-skip and cooperative-listing distrust) | Mid-array positions; first-element-only validation; import rows; list-seeded secondary harvest |
| H3 | idor-deferred-artifact-redemption | S4 (two-phase create-then-redeem binding with scope and expiry) | Job finalize and approve; export download; key-prefix changes; stale-signature and share-token reuse |
| H3 | idor-context-carrier-substitution | S4 (identity-source precedence and audience binding) | Conflicting gateway headers; cross-service token replay; tenant selector as identity; async context loss |
| H3 | idor-nested-expansion-binding | S4 (sub-resource binding beyond the swapped reference) | Projection knobs; resolver-hop traversal; alias and batch multiplex; Relay node swaps; fragment overfetch |
| H4 | idor-horizontal; idor-vertical; idor-cross-tenant | none per variant (S4 already names all three directions with one action) | Direction labels only, no procedural delta |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage fail because deferred redemption, carrier substitution, and expansion binding belong to no variant.
H1 scores disjointness pass and delta pass for its two variants, but coverage failure alone discards it per STATE 6 branch 6a.
H2 scores coverage fail because collection scope, deferred redemption, and expansion binding belong to no variant, so H2 is discarded per STATE 6 branch 6a.
H4 scores coverage pass formally but fails divergence delta because no direction adds a step over S4, and fails stability in spirit because direction labels duplicate one procedure under three names, so H4 is discarded per STATE 4 branch 4a.
H3 scores coverage pass because every falsified value in section 7 belongs to exactly one variant.
H3 scores disjointness pass because singleton swap, set position, deferred redemption, carrier precedence, and sub-resource widening never admit the same attempt twice under the grey-point assignments of section 11.
H3 scores divergence delta pass because each of the five variants adds the non-coverable step named in section 9 over its parent step.
H3 scores stability pass because cardinality, timing, carrier, and depth survive stack, payload, library, and runtime-asset swaps.
H3 scores parsimony pass with four features and five variants as the fewest set that still covers.
Winner is H3, with losing reason for H1 and H2 being coverage failure and for H4 being zero-delta direction labels.
No return to STATE 3 was needed because the winner passes coverage and disjointness.
STATE 1 completed with the S0 preamble plus S1 to S6 and full entity inventory and no malformed-class outlier.
STATE 2 tested every ledger value with both halves and recorded five non-discriminator groups with reasons.
STATE 3 branch 3a collapsed co-varying transport framings and direction labels into aspects of their owning variants.
STATE 3 branch 3b kept identifier opacity, signal shapes, pollution encodings, and defeat detail as aspects rather than variant axes.

## 11. Recommended set
Discrimination function in one sentence: IDOR discriminates by authorization cardinality (singleton reference versus set-level collection) versus redemption timing (immediate use versus deferred artifact redemption) versus identity carrier (caller-supplied reference versus context channel) versus resource depth (top-level object versus nested or expanded sub-resource).
Recommended variant idor-direct-object-swap diverges by control-paired swapping with evidence-derived verb and body plus differential blind confirmation over parent step S4, which names swapping but never names verb derivation, control pairing, or differential confirmation.
Recommended variant idor-collection-batch-scope diverges by adversarial pagination filter-skip plus per-position batch verdicts over parent step S3, which names cooperative capture but never names listing distrust, cursor filter-skip, or mid-array position reasoning.
Recommended variant idor-deferred-artifact-redemption diverges by two-phase create-then-redeem binding with scope and expiry verdicts over parent step S4, which describes live-action swapping but never describes retrieval-time binding of jobs, exports, keys, or signatures.
Recommended variant idor-context-carrier-substitution diverges by identity-source precedence probing plus audience binding checks over parent step S4, which names swapping tokens and tenants but never names which source wins on conflict or which audience a token is valid for.
Recommended variant idor-nested-expansion-binding diverges by projection-parameter escalation plus per-hop resolver verdicts with multiplexed alias and batch decisions over parent step S4, which names reference swapping but never names parameter-addition escalation or sub-resource traversal.
Non-discriminators are trust direction labels, identifier forms and opacity, attack goals and impact, TechnologyStack names with versions and transport framings, concrete runtime ID and selector and token values, the AttackerCapability ladder with `two-principal-authz` ownership, Artifact evidence objects, ObservableSignal shapes, and duplicate-key pollution detail as a shared defeat aspect.
Open questions: none at FAIL level, and no uncertainty blocks the five-variant recommendation.
Grey points: tenant-selector cases that only route (same identity, different scope) stay as aspects inside the direct variant, and only selector-as-identity cases enter the carrier variant.
Grey points: file and storage signed-URL work rides inside the deferred variant as scope-and-expiry redemption, which holds only while storage needs no content-sniffing beyond key and signature binding.
Grey points: GraphQL aliasing and batching ride inside the expansion variant as multiplexed per-node verdicts, which holds only while multiplexing needs no scheduler beyond single-request batching.
Grey points: parser coercion, cache-key confusion, and race-window detail invoke the bypass, proxy, and race families mid-procedure, and each IDOR variant records only its authorization delta.
Grey points: blind differentials with HEAD, OPTIONS, and conditional requests serve as confirmation aspects inside every variant, never as standalone variants.
