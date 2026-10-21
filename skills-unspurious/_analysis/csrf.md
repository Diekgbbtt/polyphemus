# csrf - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/csrf/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/csrf/SKILL.md`.
CSRF here is cross-site abuse of ambient authority (cookies, HTTP auth) to trigger state changes from an attacker origin without supplying a non-replayable proof of intent.
Scope covers state-changing endpoints reachable cross-origin, the session and defense model around them, preflightless and navigation delivery, parser and method coercion, token and origin validation defeat, login fixation sequencing, and protocol-handshake transports.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | cookie-based session with ambient authority | 13, 36-38 | non-discriminator (class definition) |
| PreconditionEnvironment | state-changing endpoint reachable via simple request | 47-51, 144-152 | collapsed into signature feature (acceptance side) |
| PreconditionEnvironment | SameSite attribute Strict/Lax/None with Lax top-level GET exception | 36-37, 104-108 | aspect (enumerated inside navigation variant) |
| PreconditionEnvironment | server-side GET state change or GET callback | 49, 61-64 | collapsed into signature feature (acceptance side) |
| PreconditionEnvironment | parser auto-coercion of text/plain or form bodies into JSON | 51, 71-74, 127-130 | collapsed into signature feature (acceptance side) |
| PreconditionEnvironment | backend honors method override (_method, X-HTTP-Method-Override) | 117-118 | collapsed into signature feature (acceptance side) |
| PreconditionEnvironment | null Origin or missing Referer accepted | 43-45, 110-116, 132-136 | aspect (enumerated inside each variant defeat step) |
| PreconditionEnvironment | WebSocket handshake carries cookies and relies on Origin check | 97-100 | collapsed into signature feature (acceptance side) |
| PreconditionEnvironment | GraphQL GET or persisted queries carrying mutations | 14, 92-96 | aspect (encoded payload inside navigation variant) |
| PreconditionEnvironment | login flow permits session fixation or account planting | 76-80 | collapsed into signature feature (acceptance side) |
| TechnologyStack | JSON/REST, GraphQL, file upload, WebSocket, OAuth/OIDC, SPA/WebView, webhook back-office | 13-30, 81-100 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | anti-CSRF token (hidden input, meta tag, custom header, double-submit) | 42-43, 121-125 | aspect (enumerated inside each variant defeat step) |
| DefensiveControl | Origin/Referer enforcement | 44, 110-116, 132-136 | aspect (enumerated inside each variant defeat step) |
| DefensiveControl | SameSite cookie attribute | 36-37, 104-108 | aspect (enumerated inside navigation variant) |
| DefensiveControl | CORS allow-origin/credentials policy | 53-57 | non-discriminator (enabler of exfiltration, not a CSRF proof-of-intent control) |
| VulnerabilityClass | cross-site request forgery | 6-8, 59-101 | non-discriminator (the class itself) |
| AttackGoal | unauthorized state change under victim session | 61-100, 138-142 | non-discriminator (shared across variants except fixation direction) |
| AttackGoal | bind victim browser to attacker account (login fixation) | 76-80 | collapsed into signature feature (goal direction side) |
| AttackerCapability | ability to lure victim to attacker-controlled cross-origin page | 61-64, 138-142 | non-discriminator (shared precondition of all variants) |
| AttackTechnique | auto-submitting cross-site form POST | 61-69 | collapsed into signature feature (delivery side) |
| AttackTechnique | top-level GET navigation trigger | 61-64, 104-108 | collapsed into signature feature (delivery side) |
| AttackTechnique | parser-coercion body reconstruction (form fields to JSON keys, duplicate keys, array shapes) | 71-74, 127-130 | collapsed into signature feature (delivery side) |
| AttackTechnique | method-override smuggling through simple POST | 117-118 | collapsed into signature feature (delivery side) |
| AttackTechnique | Origin/Referer obfuscation (null Origin, about:blank Referer strip) | 110-116, 132-136 | aspect (defeat sub-step inside each variant) |
| AttackTechnique | token lifecycle abuse (removal, cross-request reuse, cross-session reuse, binding escape, GET token) | 43, 121-125 | aspect (defeat sub-step inside each variant) |
| AttackTechnique | logout-then-login chaining sequence | 76-80 | collapsed into signature feature (delivery side) |
| AttackTechnique | cross-site WebSocket handshake then authenticated socket action | 97-100 | collapsed into signature feature (delivery side) |
| AttackTechnique | OAuth authorize/logout GET or form POST abuse with redirect chaining | 81-85 | aspect (redirect-chained payload inside navigation variant) |
| PayloadPattern | preflightless bodies (urlencoded, multipart, text/plain) | 47-51, 66-69 | aspect (encoding inside form-post and parser-differential variants) |
| PayloadPattern | data[foo]=bar JSON-key-via-form with duplicate keys and array shapes | 73-74, 127-130 | aspect (encoding inside parser-differential variant) |
| PayloadPattern | _method or X-HTTP-Method-Override parameter | 117-118 | aspect (encoding inside parser-differential variant) |
| PayloadPattern | null Origin or stripped Referer delivery context | 110-116, 132-136 | aspect (delivery context inside each variant) |
| Artifact | crafted cross-origin proof-of-concept page (auto-submit form or navigation link) | 61-64, 152-166 | non-discriminator (tester-produced per attempt, not a variant axis) |
| ObservableSignal | before/after state change without proof of intent | 152-166 | non-discriminator (shared success signal) |
| ObservableSignal | missing-token acceptance or null-Origin acceptance response | 43-45, 110-125 | aspect (per-variant defeat confirmation) |
| ObservableSignal | Set-Cookie SameSite attributes and per-endpoint CORS delta | 36-38, 53-57 | non-discriminator (recon observation feeding parametrisation) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: cookie-sessioned apps, JSON/REST, GraphQL GET/persisted queries, file endpoints, login/logout/MFA flows, OAuth authorize/token/logout, WebView deep links, staff GET tools; invariant is ambient-authority session, what varies is which endpoint shape and transport carries the state change.
Adversarial capabilities: luring the victim to an attacker page and issuing form, navigation, handshake, or chained login requests; invariant is no script execution in target origin, what varies is the delivery construction the attacker page performs.
Common trust assumptions: server assumes a cookie-authenticated cross-origin request carries user intent when token, Origin/Referer, or SameSite checks are absent or weak; invariant is the ambient-authority assumption, what varies is which proof-of-intent check is relied upon.
Testing methodology: the seven parent steps P1-P7 listed in section 6; invariant is the inventory-to-validation spine, what varies is which delivery step bends per candidate procedure.
Proxy techniques: none held by this class; cross-origin delivery uses a plain attacker page rather than a proxy relay.
Defence bypass techniques: SameSite nuance exploitation, Origin/Referer obfuscation, method override, token weaknesses, content-type switching, header manipulation; invariant is defeating the proof-of-intent check, what varies is only the check value defeated, hence an aspect.
Techniques anti-patterns: relying on CORS alone, assuming framework Origin enforcement, assuming bearer-token immunity for hybrid cookie apps; these are invariant warnings.
Scripted tests (references/): none shipped with this skill; validation is described inline at lines 152-166 of the consulted catalogue copy.
False positives: enforced token plus consistent Origin/Referer, no cookies on cross-site requests, idempotent-only impact; these are invariant exclusion predicates.
Chaining: CSRF with IDOR, clickjacking, and OAuth mix-up; chaining targets are invariant companions, not variant axes.

## 4. Runtime parametrisation
Consumed L0/L1 runtime entities are the concrete Service under test, the Endpoint and its Parameter/Header carriers, the BaseURL, the DataItem surfacing at those carriers, the System mechanism overlays (auth, CORS, GraphQL, WebSocket), and the HTTP history showing request shape and Set-Cookie attributes.
The concrete cookie names, SameSite values, token strings, content-type strings, browser versions, and payload literals are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, library version, payload literal, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding a cookie-sessioned target with an inventory of state-changing endpoints and needing to prove that a cross-origin page can trigger one without user intent beyond a visit.
Parent methodology steps with completion conditions: P1 inventory endpoints, complete when every state-changing endpoint including admin and staff is listed.
P2 note request details, complete when method, content-type, and simple-request reachability are recorded per endpoint.
P3 assess session model, complete when cookie SameSite attributes and bearer-versus-cookie usage are determined.
P4 check defenses, complete when token presence plus Origin/Referer enforcement behavior is recorded.
P5 attempt preflightless delivery, complete when a form, text/plain, or multipart cross-origin POST is delivered and the state effect observed.
P6 test navigation, complete when a top-level GET navigation is delivered and the state effect observed.
P7 cross-browser validation, complete when behavior is confirmed across at least two browsers or contexts (navigation versus XHR/fetch).

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Ambient cookie authority (PreconditionEnvironment) | No | N/A | non-discriminator | It is the class definition; no parent step changes kind when it varies. |
| TechnologyStack values (REST, GraphQL, WebSocket product, OAuth vendor, SPA/WebView) | No | N/A | non-discriminator | Parent steps perform the same kind of action across stacks; stacks are excluded axes. |
| CORS policy values (DefensiveControl) | No | N/A | non-discriminator | No parent step changes kind; permissive CORS enables exfiltration overlay, not a distinct CSRF delivery procedure. |
| Attacker lure capability (AttackerCapability) | No | N/A | non-discriminator | Shared precondition; every candidate uses the same lure-then-trigger shape at this abstraction. |
| Shared state-change goal (AttackGoal) | No | N/A | non-discriminator | Same kind of P5/P6 delivery action regardless of whether the state change is email, payment, or admin action. |
| PoC page artifact and before/after signal (Artifact, ObservableSignal) | No | N/A | non-discriminator | Tester-produced per attempt and shared success read-out; no step bends. |
| Token-control values (DefensiveControl: missing, untied, reusable, GET-carried, predictable double-submit) | Yes | Yes | aspect | P4 performs the same kind of proof-of-intent removal and reuse probing and its description enumerates every token value, so no new step is needed. |
| Origin/Referer-control values (DefensiveControl: absent, null-accepting, Referer-stripped) | Yes | Yes | aspect | P4 performs the same kind of header-manipulation probing and enumerates null, missing, and cross-origin values, so coverage is complete. |
| SameSite values Strict/Lax/None (DefensiveControl, PreconditionEnvironment) | Yes | Yes | aspect | P3 plus P6 enumerate the attribute values and the Lax GET exception, so the description covers every value. |
| GraphQL GET or persisted-query shape (PreconditionEnvironment) | Yes | Yes | aspect | P2 plus P6 record GET-allowed mutations and deliver encoded payloads by navigation, so the same kind of action with an encoded body suffices. |
| OAuth redirect-chained authorize shape (AttackTechnique) | Yes | Yes | aspect | P6 delivers the authorize GET and follows the redirect chain, so the navigation action covers it with a chained-payload parameter. |
| Simple-request acceptance (PreconditionEnvironment) with form POST delivery (AttackTechnique) | Yes | No | discriminator | P5 performs form delivery but its flat description does not cover which simple encoding succeeds per endpoint nor the multipart file-action shape, so it bends. |
| GET-state-change acceptance (PreconditionEnvironment) with navigation delivery (AttackTechnique) | Yes | No | discriminator | P6 names navigation but does not cover Lax-scoped top-level GET confirmation-step chaining nor staff-GET exploitation, so it bends. |
| Parser coercion or method-override acceptance (PreconditionEnvironment) with reconstruction delivery (AttackTechnique) | Yes | No | discriminator | P5 attempts preflightless bytes but does not describe reconstructing JSON semantics via form fields, duplicate keys, array shapes, or _method smuggling plus coercion confirmation, so it bends. |
| Fixation-capable login acceptance (PreconditionEnvironment) with plant-then-abuse goal direction (AttackGoal) | Yes | No | discriminator | P3 assumes abuse of the victim session while fixation plants the attacker session first and completes on victim-in-attacker-account, so it bends. |
| Handshake Origin reliance (PreconditionEnvironment) with handshake-then-act delivery (AttackTechnique) | Yes | No | discriminator | Neither P5 (single POST) nor P6 (single GET) describes opening an authenticated socket cross-origin and then issuing actions over it, so both fail. |

## 7. Step-coverage falsification
Simple-request acceptance with form POST delivery: parent step P5 says attempt preflightless delivery via form, text/plain, or multipart.
The uncovered reality is per-endpoint encoding divergence plus multipart file and admin-action forgery, which needs an encode-per-endpoint plus storage-effect confirmation sub-procedure that P5 never names.
GET-state-change acceptance with navigation delivery: parent step P6 says test top-level GET navigation.
The uncovered reality is Lax-scoped confirmation-step chaining and staff-tool state-changing GETs, which need a chain-two-GETs plus back-office-context procedure that P6 never names.
Parser coercion acceptance with reconstruction delivery: parent step P5 says attempt preflightless delivery.
The uncovered reality is rebuilding JSON key structure through data[foo]=bar fields, duplicate-key and array-shape confusion, and _method override smuggling, followed by proving server-side coercion applied, which is a transform-then-confirm-coercion procedure P5 never names.
Fixation-capable login acceptance with plant-then-abuse direction: parent step P3 says assess the session model as victim ambient authority.
The uncovered reality is forcing logout to clear tokens then planting attacker credentials so later victim actions run under the attacker account, completing on account-identity comparison rather than state-effect comparison, which P3 never names.
Handshake Origin reliance with handshake-then-act delivery: parent steps P5 and P6 each describe a single HTTP request causing a state change.
The uncovered reality is a two-phase transport where the cross-site handshake opens an authenticated socket and subsequent socket messages cause actions, needing a handshake-Origin plus over-socket-action procedure that neither P5 nor P6 names.
Token-control values: no falsification holds because P4 enumerates removal, cross-request reuse, cross-session reuse, binding scope, GET carriage, and double-submit predictability.
Origin-control values: no falsification holds because P4 enumerates absent, null, missing, and cross-origin header values.
SameSite values: no falsification holds because P3 records the attribute and P6 exercises the Lax top-level GET exception.
GraphQL GET shape: no falsification holds because P6 with an encoded query payload covers persisted-query mutations.
OAuth redirect chain: no falsification holds because P6 with a chained redirect payload covers forced authorization navigations.

## 8. Hypotheses
H1 (single-feature, delivery-and-acceptance mechanism): if the class is partitioned by the cross-origin delivery-and-acceptance mechanism into form-post, navigation-get, parser-differential, login-fixation, and handshake-transport, then each partition owns a distinct first non-coverable step and jointly covers all five falsifications above.
This hypothesis is falsified if any partition lacks its own non-coverable step or if two partitions claim the same falsification.
H2 (combined-feature, delivery-and-acceptance crossed with defense layer defeated): if each H1 partition is further split by token-defeat versus origin-defeat versus SameSite-reliance, then the set triples in size and each cell adds its own non-coverable defeat step.
This hypothesis is falsified if the defeat action kind is identical across cells and P4 already enumerates every defense value, leaving cells with no divergence delta.
H3 (combined-feature, delivery-and-acceptance crossed with technology stack): if each H1 partition is further split by REST versus GraphQL versus WebSocket versus OAuth versus file-upload stack, then each stack cell adds its own non-coverable step.
This hypothesis is falsified if the stack swap leaves the delivery procedure unchanged and only swaps runtime parameters, violating stability.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | csrf-form-post | Deliver per-endpoint preflightless POST (urlencoded, multipart, text/plain) and confirm storage or action effect. |
| H1 | csrf-navigation-get | Chain top-level GET navigations including Lax-scoped confirmation steps and staff GET tools. |
| H1 | csrf-parser-differential | Reconstruct target semantics in a preflightless encoding (form-to-JSON keys, duplicate keys, array shapes, _method) and confirm server-side coercion. |
| H1 | csrf-login-fixation | Force logout then plant attacker credentials and confirm victim browser now sits in attacker account. |
| H1 | csrf-handshake-transport | Open an authenticated cross-site socket handshake absent Origin enforcement then issue actions over the socket. |
| H2 | H1 five plus token-defeat versus origin-defeat versus SameSite cells per delivery (up to fifteen cells) | Same five first steps; cells add only a parametrized defeat sub-step with no new non-coverable step. |
| H3 | H1 five plus per-stack cells (REST, GraphQL, WebSocket product, OAuth vendor, file-upload) | Same five first steps; cells add only stack parameter swaps with no new non-coverable step. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage pass because every falsified acceptance value belongs to exactly one variant.
H1 scores disjointness pass because form-post replays identical semantics while parser-differential requires semantic transformation, navigation-get requires GET reachability, login-fixation completes on account identity, and handshake-transport completes over a socket.
H1 scores divergence delta pass because each variant adds the non-coverable step named in section 9 over P3/P5/P6.
H1 scores stability pass because swapping framework, browser brand, payload literal, or endpoint asset leaves each procedure intact.
H1 scores parsimony pass with one collapsed feature and five variants.
H2 fails divergence delta and parsimony because defeat cells repeat P4 enumeration with no new step and triple the set size, so H2 is discarded per STATE 4 branch 4a.
H3 fails stability and parsimony because stack cells swap runtime parameters only and multiply variants by technology, so H3 is discarded per STATE 4 branch 4a.
Winner is H1 with losing reason for H2 being zero-delta defeat cells and for H3 being technology-axis instability.
No return to STATE 3 is needed because the winner passes coverage and disjointness.
STATE 1 completed with seven parent steps and full entity inventory and no malformed-class outlier.
STATE 2 completed with six aspects and six non-discriminators recorded alongside five discriminator values collapsed per STATE 3 branch 3a into one feature.
STATE 3 branch 3b applied to SameSite continuity, token value range, and Origin value range by keeping them as aspects inside variants.

## 11. Recommended set
Discrimination function in one sentence: CSRF decomposes by the cross-origin delivery-and-acceptance mechanism that bends the parent delivery steps, namely simple-request form acceptance, GET-state-change acceptance, parser or method coercion acceptance, fixation-capable login acceptance, and handshake Origin reliance.
Recommended variant csrf-form-post diverges by delivering per-endpoint preflightless POST with storage or action confirmation over parent step P5, which never names per-endpoint encoding choice or file-action forgery.
Recommended variant csrf-navigation-get diverges by chaining top-level GET navigations through Lax-scoped confirmation steps and staff GET tools over parent step P6, which never names confirmation chaining or back-office context.
Recommended variant csrf-parser-differential diverges by reconstructing target semantics in preflightless encodings with method-override smuggling and coercion confirmation over parent step P5, which never names transform-then-confirm-coercion.
Recommended variant csrf-login-fixation diverges by forcing logout then planting attacker credentials with account-identity completion over parent step P3, which assumes victim-session abuse and never names plant-then-abuse sequencing.
Recommended variant csrf-websocket-handshake diverges by opening an authenticated cross-site socket handshake and issuing over-socket actions over parent steps P5 and P6, which describe only single HTTP requests and never name two-phase socket transport.
Non-discriminators are ambient cookie authority as class definition, technology stack with versions as excluded runtime axis, CORS policy as exfiltration enabler, lure capability with PoC artifact and before/after signal as shared apparatus, and shared state-change goal direction except fixation.
Open questions: none at FAIL level; the analysis leaves no uncovered falsification and no skipped state.
Grey points: OAuth authorize and GraphQL GET ride inside navigation-get as chained or encoded payloads rather than standalone variants, which holds only while their servers accept single-navigation triggering.
Grey points: multipart file forgery rides inside form-post rather than a file variant, which holds only while upload handling needs no coercion beyond multipart encoding.
Grey points: double-submit predictability and GET-carried tokens stay inside the per-variant defeat sub-step, which holds only while token lifecycle probing needs no multi-session oracle beyond reuse comparison.
