# http-method-tampering - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/http-method-tampering/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/http-method-tampering/SKILL.md`.
HTTP method tampering here is bypassing authorization, authentication, CSRF, and CORS controls by changing the request verb, smuggling an override header or parameter, or coercing the request into a differently-gated handling path.
Scope covers per-verb route dispatch gaps, framework method-override reinterpretation, informational-verb handling gaps with transport-gap exploitation, and CORS simple-request preflight coercion.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | method-differentiated route table (auth decorator present on one verb, absent on another) | 12-20, 59-63 | collapsed into signature feature (dispatch side) |
| PreconditionEnvironment | backend honors method override via header or `_method` field while front gate sees POST | 37-55, 122 | collapsed into signature feature (reinterpretation side) |
| PreconditionEnvironment | OPTIONS served with permissive Allow disclosure | 64-66 | collapsed into signature feature (informational side) |
| PreconditionEnvironment | HEAD served without body under weaker check than GET | 67-68, 125 | collapsed into signature feature (informational side) |
| PreconditionEnvironment | TRACE enabled with request echo | 70-71 | collapsed into signature feature (informational side) |
| PreconditionEnvironment | CORS enforced only on non-simple requests with preflight | 109-118 | collapsed into signature feature (preflight side) |
| PreconditionEnvironment | legacy state-changing GET handler without token check | 126 | aspect (enumerated inside verb-switch variant) |
| TechnologyStack | Rails, Django, Spring framework override support | 122 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | per-method authorization or authentication check | 8, 12-20, 59-63, 123-125 | collapsed into signature feature (dispatch side) |
| DefensiveControl | CSRF protection tied to method or content type | 8, 109-118, 126 | collapsed into signature feature (preflight side) |
| DefensiveControl | CORS preflight policy distinguishing simple from non-simple requests | 109-118 | collapsed into signature feature (preflight side) |
| VulnerabilityClass | broken access control via method confusion | 6-8, 10, 57-63 | non-discriminator (the class itself) |
| AttackGoal | bypass authorization or authentication on a guarded resource | 8, 57-63, 78-105 | non-discriminator (shared across variants except disclosure and capture) |
| AttackGoal | disclose allowed-method surface via OPTIONS | 64-66 | aspect (disclosure drive inside informational variant) |
| AttackGoal | capture credentials via TRACE echo with replay | 70-71 | collapsed into signature feature (capture-exploitation side) |
| AttackerCapability | low-privilege or unauthenticated session able to send arbitrary verbs, headers, and content types | 27-33, 78-105 | non-discriminator (shared precondition of all variants) |
| AttackTechnique | direct verb-switch replay across application-decision verbs | 22-33, 78-105, 121 | collapsed into signature feature (dispatch side, mutex excludes OPTIONS HEAD TRACE) |
| AttackTechnique | override-header or `_method` parameter smuggling through POST | 39-55, 122 | collapsed into signature feature (reinterpretation side) |
| AttackTechnique | OPTIONS Allow read plus HEAD header-only probe plus TRACE echo probe plus echo-material replay | 64-71 | collapsed into signature feature (informational side) |
| AttackTechnique | Content-Type coercion to text/plain with JSON-shaped body | 113-118 | collapsed into signature feature (preflight side) |
| PayloadPattern | verb list GET, POST, PUT, DELETE, PATCH for dispatch plus OPTIONS, HEAD, TRACE for informational under mutex | 27, 81 | aspect (enumeration split by mutex across two variants) |
| PayloadPattern | override names X-HTTP-Method-Override, X-HTTP-Method, X-Method-Override, `_method` field | 39-44 | aspect (enumeration inside override variant) |
| PayloadPattern | Content-Type text/plain carrying a JSON body | 113-118 | aspect (encoding inside preflight variant) |
| Artifact | per-method response matrix (method, status, length, Location) | 78-105 | non-discriminator (tester-produced per attempt, not a variant axis) |
| Artifact | Allow header method list from OPTIONS | 64-66 | aspect (disclosure object inside informational variant) |
| ObservableSignal | status and length divergence across verbs (for example 200 on HEAD versus 403 on GET) | 27-33, 67-68, 78-105 | collapsed into signature feature (comparison side, split by mutex) |
| ObservableSignal | Allow list disclosure on OPTIONS | 64-66 | aspect (disclosure confirmation inside informational variant) |
| ObservableSignal | request reflection containing Cookie or Authorization material on TRACE | 70-71 | collapsed into signature feature (capture-exploitation side) |
| ObservableSignal | state-change effect or guarded-data return proving bypass | 59-63, 78-105 | non-discriminator (shared success signal) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: admin and API endpoints with per-verb routing, override-header handling, OPTIONS plus HEAD plus TRACE handlers, and CORS-gated endpoints; invariant is a reachable endpoint with method-sensitive handling, what varies is which handling layer interprets the method.
Adversarial capabilities: sending arbitrary verbs, override headers, `_method` fields, and coerced content types under a low-privilege session; invariant is full control of verb plus headers plus body shape, what varies is which smuggling construction the request carries.
Common trust assumptions: server assumes the authorization decision made for one verb covers every verb, assumes the front-gate method equals the backend-executed method, and assumes preflight gating covers simple-shaped requests; invariant is method-identity trust, what varies is which layer holds the divergent interpretation.
Testing methodology: the six parent steps P1 through P6 listed in section 6; invariant is the inventory-to-validation spine, what varies is which interpretation-divergence step bends per candidate procedure.
Proxy techniques: none held by this class because requests are sent directly rather than through a proxy relay.
Defence bypass techniques: verb switching, override-header smuggling, `_method` field smuggling, informational-verb exploitation, and Content-Type coercion to simple requests; invariant is defeating the method-tied check, what varies is the layer whose interpretation diverges, hence the signature.
Techniques anti-patterns: testing only the documented verb, assuming framework override is disabled, assuming HEAD equals GET enforcement, and assuming TRACE is disabled without probing; these are invariant warnings.
Scripted tests (references/): none shipped with this skill because validation is described inline at lines 75 through 105 as a method-matrix function.
False positives: uniform enforcement across verbs, override headers ignored by the backend, TRACE disabled, and CORS enforced on simple requests too; these are invariant exclusion predicates.
Chaining: method tampering with BOLA or function-level authorization escalation and with CSRF-token bypass on state-changing GETs; chaining targets are invariant companions, not variant axes, and principal-confusion steps belong to `two-principal-authz` per SPEC section 7.

## 4. Runtime parametrisation
Consumed L0 plus L1 runtime entities are the concrete Service under test, the Endpoint and its Parameter and Header carriers, the BaseURL, the DataItem surfacing at those carriers, the System mechanism overlays, and the HTTP history showing per-verb status plus length plus Allow headers plus reflected material.
The concrete endpoint paths, cookie values, header spellings, content-type strings, framework versions, and payload literals are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, library version, payload literal, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding a low-privilege session against an inventory of guarded endpoints and needing to prove that a method-tied authorization, authentication, CSRF, or CORS check can be sidestepped without escalating credentials.
Parent methodology steps with completion conditions: P1 inventory endpoints, complete when every guarded and admin path is listed.
P2 replay verbs, complete when each endpoint has been requested with every verb in the list and the status-plus-length matrix is recorded.
P3 test override reinterpretation, complete when POST carrying each override header and the `_method` field has been sent and backend-applied versus front-gate-ignored behavior is recorded.
P4 probe informational verbs, complete when OPTIONS Allow content, HEAD header-only divergence, and TRACE echo presence have each been recorded.
P5 coerce preflight shape, complete when a state-changing request re-sent as a simple request with Content-Type text/plain has been delivered and the CORS decision observed.
P6 validate bypass, complete when low-privilege or unauthenticated response is compared against the guarded baseline and guarded-data return or state-change effect is confirmed.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| TechnologyStack values (Rails, Django, Spring, version) | No | N/A | non-discriminator | P2-P5 perform the same kind of action across frameworks; stacks are excluded axes. |
| Attacker low-privilege session capability (AttackerCapability) | No | N/A | non-discriminator | Shared precondition; every candidate sends requests under the same session shape. |
| Shared bypass goal direction (AttackGoal: guarded access) | No | N/A | non-discriminator | Same kind of P6 validation action regardless of whether the prize is data read or state change. |
| Response-matrix artifact and state-effect signal (Artifact, ObservableSignal) | No | N/A | non-discriminator | Tester-produced per attempt and shared success read-out; no step bends. |
| Legacy state-changing GET shape (PreconditionEnvironment) | Yes | Yes | aspect | P2 replays GET with state-change observation and P6 confirms the effect, so the description covers it. |
| Verb-list and override-name spellings (PayloadPattern) | Yes | Yes | aspect | P2 enumerates the dispatch verb list and P3 enumerates each override name and field under the mutex split, so coverage is complete. |
| Text/plain body encoding (PayloadPattern) | Yes | Yes | aspect | P5 names the exact coercion shape, so the encoding value needs no new step. |
| Method-differentiated dispatch with direct verb replay (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator | P2 replays verbs but never names route-table reconstruction with missing-decorator mapping plus PUT to a GET-only path plus per-verb execution confirmation, so it bends. |
| Override reinterpretation acceptance with smuggling delivery (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator | P3 sends override bytes but never names the two-layer divergence proof with front gate seeing POST while backend executes DELETE plus gate-versus-executor comparison, so it bends. |
| Informational-verb exploitation beyond transport read (PreconditionEnvironment plus AttackTechnique plus capture goal) | Yes | No | discriminator | P4 records Allow plus header-only plus echo but never names Allow-driven targeted bypass plus header-only metadata extraction plus echo-material credential replay, so it bends. |
| Simple-request preflight acceptance with coercion delivery (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator | P5 delivers coerced bytes but never names proving shape-dependent divergence with a preflighted-shape-blocked versus simple-shape-executed pair plus execution confirmation, so it bends. |

## 7. Step-coverage falsification
Method-differentiated dispatch with direct verb replay: parent step P2 says request every verb and record status plus length.
The uncovered reality is per-verb route-table reconstruction with missing-decorator identification including PUT to a GET-only path per skill lines 122 through 124 plus per-verb state-change confirmation, which needs a dispatch-map plus execute-and-confirm sub-procedure that P2 plus P6 never name.
Mutex rule: the verb-switch matrix covers only GET, POST, PUT, DELETE, and PATCH application decisions and excludes OPTIONS, HEAD, and TRACE entirely.
Override reinterpretation acceptance with smuggling delivery: parent step P3 says send POST with each override header and the `_method` field.
The uncovered reality is a two-layer divergence where the front gate authorizes POST while the backend executes the overridden DELETE or PUT, which needs a gate-view versus executor-view comparison procedure that P3 never names.
Informational-verb exploitation beyond transport read: parent step P4 says record OPTIONS Allow content plus HEAD header-only divergence plus TRACE echo presence.
The uncovered reality is exploitation beyond recording where the Allow list drives targeted bypass selection plus HEAD header-only 200 versus 403 extracts guarded metadata without body checks plus TRACE echo material is extracted and replayed as credential capture, which needs an exploit-and-replay procedure that P4 plus P6 never name.
Mutex rule: OPTIONS, HEAD, and TRACE belong exclusively to the informational variant and no single request on those verbs counts toward the verb-switch matrix.
Simple-request preflight acceptance with coercion delivery: parent step P5 says re-send the request with Content-Type text/plain.
The uncovered reality is proving shape-dependent CORS divergence by showing the preflighted JSON shape blocked while the text/plain shape with identical semantics executed, which needs a shape-pair plus execution-confirmation procedure that P5 never names.
Legacy state-changing GET: no falsification holds because P2 plus P6 enumerate GET replay with effect confirmation.
Verb-list and override-name spellings: no falsification holds because P2 and P3 enumerate every literal under the mutex split.
Text/plain encoding: no falsification holds because P5 names the coercion shape exactly.

## 8. Hypotheses
H1 (single-feature, interpreting-layer divergence): if the class is partitioned by the layer whose method interpretation diverges into route-dispatch, override-reinterpretation, informational-exploitation, and preflight-gating, then each partition owns a distinct first non-coverable step and jointly covers all four falsifications above.
This hypothesis is falsified if any partition lacks its own non-coverable step or if two partitions claim the same request under the mutex rule.
H2 (combined-feature, interpreting layer crossed with TRACE split): if the informational partition of H1 is further split into metadata-handling (OPTIONS plus HEAD) versus credential-capture (TRACE), then TRACE owns a further non-coverable echo-exploitation step beyond the shared informational exploit.
This hypothesis is falsified if TRACE capture needs no procedure beyond the shared Allow-driven plus header-only plus echo-replay exploit already named in H1.
H3 (combined-feature, interpreting layer crossed with technology stack): if each H1 partition is further split by Rails versus Django versus Spring stack, then each stack cell adds its own non-coverable step.
This hypothesis is falsified if the stack swap leaves the divergence-proof procedure unchanged and only swaps runtime header support facts, violating stability.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | http-method-tampering-verb-switch | Reconstruct the per-verb dispatch map with missing-decorator mapping including PUT to a GET-only path and confirm per-verb execution or data return. |
| H1 | http-method-tampering-override-smuggling | Prove gate-versus-executor divergence by comparing front-gate POST authorization against backend-executed overridden method. |
| H1 | http-method-tampering-informational-verb | Exploit transport gaps beyond P4 recording via Allow-driven bypass selection plus header-only metadata extraction plus TRACE echo-material replay. |
| H1 | http-method-tampering-preflight-coercion | Prove shape-dependent CORS divergence with a preflighted-shape-blocked versus simple-shape-executed pair plus execution confirmation. |
| H2 | H1 four with informational split into metadata-handling and credential-capture (five cells) | Disclosure cell keeps the H1 informational exploit; capture cell adds echo-body credential replay already contained in H1. |
| H3 | H1 four plus per-stack cells (Rails, Django, Spring) | Same four first steps; cells add only stack support-parameter swaps with no new non-coverable step. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
Prior scoring failed branch 6a because the informational variant claimed P2 as parent while true parent P4 already covered Allow plus header-only plus echo reads with no mutex against verb-switch.
STATE 6 branch 6a therefore triggered a return to STATE 3 with the failure named as wrong-parent plus missing-mutex plus thin verb-switch and preflight deltas.
STATE 3 repair reassigned informational falsification from P2 to P4, added the verb-switch versus informational mutex, and strengthened verb-switch plus preflight deltas as documented in section 7.
H1 re-scores coverage pass because every falsified divergence value belongs to exactly one variant under the mutex rule.
H1 re-scores disjointness pass because dispatch replay uses only application-decision verbs while smuggling needs a POST-plus-override pair while informational owns OPTIONS plus HEAD plus TRACE exclusively while coercion needs a shape pair.
H1 re-scores divergence delta pass because each variant adds the exploit-or-proof step named in section 9 over P2, P3, P4, or P5.
H1 re-scores stability pass because swapping framework, payload literal, header spelling, or endpoint asset leaves each divergence-proof procedure intact.
H1 re-scores parsimony pass with one collapsed feature and four variants.
H2 fails parsimony with no coverage gain because TRACE replay already lives inside the informational exploit plus P6 and adds no independent non-coverable step, so H2 is discarded per STATE 4 branch 4a.
H3 fails stability and parsimony because stack cells swap runtime support facts only and multiply variants by technology, so H3 is discarded per STATE 4 branch 4a.
Winner is H1 with losing reason for H2 being zero-delta TRACE split inside the repaired informational exploit and for H3 being technology-axis instability.
STATE 6 branch 6b now holds because the repaired winner passes coverage and disjointness, so analysis proceeds to STATE 7.
STATE 1 completed with six parent steps and full entity inventory and no malformed-class outlier.
STATE 2 completed with non-discriminators and aspects recorded alongside four discriminator values collapsed per STATE 3 branch 3a into one interpreting-layer feature.
STATE 3 branch 3b did not trigger because every signature value partitions cleanly under the mutex with no continuous or overlapping range.

## 11. Recommended set
Discrimination function in one sentence: HTTP method tampering decomposes by the handling layer whose method interpretation diverges, namely route-level verb dispatch, override-header reinterpretation, informational-verb exploitation, and preflight-gated CORS handling.
Recommended variant http-method-tampering-verb-switch diverges by reconstructing the per-verb dispatch map with missing-decorator mapping including PUT to a GET-only path plus per-verb execution confirmation over parent step P2, which never names dispatch mapping or execution proof.
Recommended variant http-method-tampering-override-smuggling diverges by proving gate-versus-executor divergence with front-gate versus backend comparison over parent step P3, which never names two-layer interpretation comparison.
Recommended variant http-method-tampering-informational-verb diverges by exploiting transport gaps with Allow-driven bypass selection plus header-only metadata extraction plus TRACE echo-material credential replay over parent step P4, which records Allow plus header-only plus echo but never names exploitation or replay.
Recommended variant http-method-tampering-preflight-coercion diverges by proving shape-dependent CORS divergence with a preflighted-shape-blocked versus simple-shape-executed pair plus execution confirmation over parent step P5, which never names divergence proof with execution confirmation.
Mutex rule states that verb-switch covers only GET, POST, PUT, DELETE, and PATCH while OPTIONS, HEAD, and TRACE belong exclusively to informational-verb, so no single request falls in two variants.
Non-discriminators are technology stack with versions as excluded runtime axis, low-privilege session capability as shared precondition, shared bypass goal direction, response-matrix artifact with state-effect signal as shared apparatus, legacy state-changing GET shape, verb-list plus override-name plus text/plain spellings, and disclosure completions that ride inside their variants without independent steps.
Open questions: none remain at FAIL level because every falsification is covered and every state through STATE 7 is worked.
Grey points: TRACE credential replay lives inside informational-verb as echo-replay exploitation rather than a standalone variant, which holds only while replay needs no session-hijack procedure beyond reflected-material reuse.
Grey points: HEAD auth-gap probing lives inside informational-verb as header-only extraction rather than inside verb-switch, which holds only while HEAD handling stays a transport-level handler gap under the mutex rather than a route-dispatch gap.
Grey points: state-changing GET exploitation rides inside verb-switch rather than a CSRF-adjacent variant, which holds only while confirmation stays a same-origin method replay rather than a cross-origin lure delivery.
