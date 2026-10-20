# xss - variant decomposition analysis

## 1. Class and scope
This analysis covers the `xss` class from `skills-unspurious/xss/SKILL.md`.
Cross-site scripting here means attacker-controlled input that reaches a rendering or execution sink without exact-context encoding and then executes in a victim context.
The class spans immediate reflection plus persisted rendering plus client-only DOM flows across server render and client render and URL and event and file and email and PDF paths.
The recommended set keeps the parent `xss` baseline for immediate reflection plus `xss-stored` for any persistence plus `xss-dom` for non-persistent client-only flow.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | Immediate same-response reflection without persistence | SKILL 13, 128-129 | Non-discriminator and parent baseline |
| PreconditionEnvironment | Persistence of input with later retrieval and rendering through any sink | SKILL 13, 40, 47-49, 129 | Discriminator candidate |
| PreconditionEnvironment | Non-persistent client-only source-to-sink flow without server reflection | SKILL 13, 33, 62-70, 128-129 | Discriminator candidate |
| PreconditionEnvironment | Sanitizer plus parser round trip that morphs markup | SKILL 81-84 | Secondary divergence inside nearest delivery variant |
| PreconditionEnvironment | Template expression evaluation on server or client | SKILL 89-92 | Boundary-ruled overlap with server-side template injection |
| PreconditionEnvironment | Uploaded file served inline with active content type | SKILL 47-49 | Secondary divergence inside stored variant |
| PreconditionEnvironment | Email or PDF renderer with restricted active content | SKILL 109-115 | Aspect with renderer-specific confirmation |
| TechnologyStack | Jinja, EJS, Handlebars, SSR and ISR frameworks | SKILL 19, 26 | Non-discriminator |
| TechnologyStack | React, Vue, Angular, and Svelte sinks and renderers | SKILL 19, 30-32 | Non-discriminator |
| TechnologyStack | DOMPurify, CSP, Trusted Types, Markdown and PDF renderers | SKILL 22, 54, 96-105 | Non-discriminator |
| TechnologyStack | REST, GraphQL, WebSocket, SSE, and service workers | SKILL 40, 133 | Non-discriminator |
| DefensiveControl | Output encoding, sanitizer config, CSP, Trusted Types, and safe schemes | SKILL 22, 53-58, 96-105, 137-140 | Non-discriminator and cross-reference to the `defence-bypass` family |
| VulnerabilityClass | Cross-site scripting | SKILL 6-8 | Class definition itself |
| AttackGoal | Impact demonstration through exfiltration plus chaining plus evidence-backed PoCs | SKILL 77, 194, 199-201 | Non-discriminator |
| AttackerCapability | Ability to submit input that is reflected immediately | SKILL 128 | Follows delivery condition |
| AttackerCapability | Ability to write input that another principal later views | SKILL 40, 47-49 | Follows delivery condition |
| AttackerCapability | Ability to influence a client-side source such as hash or postMessage | SKILL 33, 40, 62-65 | Follows delivery condition |
| AttackTechnique | Single-cycle reflection mapping from request to response sink | SKILL 128-129 | Parent baseline procedure without delta |
| AttackTechnique | Two-phase write-then-retrieve mapping through persistence | SKILL 128-129 plus 40, 47-49 | Discriminating procedure for stored delivery |
| AttackTechnique | Browser-instrumented source-to-sink tracing without server reflection and without persistence | SKILL 62-70, 128-129, 190-193 | Discriminating procedure for DOM delivery |
| AttackTechnique | Unclosed-tag, case, encoding, and event-handler bypass probing | SKILL 144-186 | Aspect inside payload crafting |
| PayloadPattern | Per-context polyglots for HTML, attribute, URL, JS, CSS, and SVG | SKILL 119-124 | Non-discriminating aspect |
| PayloadPattern | Unclosed-tag and event-handler variety patterns | SKILL 144-186 | Non-discriminating aspect |
| Artifact | Stored payload instance and uploaded inline file | SKILL 40, 47-49 | Runtime-produced object |
| Artifact | DOM sink log, CSP violation report, and mutated markup sample | SKILL 96-100, 190-193 | Runtime-produced object |
| ObservableSignal | Same-response reflection of controlled input | SKILL 128-129 | Parent baseline observation |
| ObservableSignal | Later-view execution after persistence through any sink | SKILL 40, 47-49 | Discriminating observation for stored delivery |
| ObservableSignal | Instrumented sink invocation without server reflection and without persistence | SKILL 62-70, 190-193 | Discriminating observation for DOM delivery |
| ObservableSignal | Sanitizer output morphing into executable markup | SKILL 81-84 | Secondary signal inside nearest delivery variant |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance covers server render plus client render plus URL and DOM plus events plus cross-context plus file and metadata plus email and PDF loci.
Adversarial capabilities cover immediate submission plus persisted submission for later viewing plus non-persistent client-source influence without server round trip.
Common trust assumptions cover the rule that every user-influenced string stays untrusted until strictly encoded for the exact sink.
Testing methodology covers the six parent steps from source identification through multi-channel testing.
Proxy techniques cover transport repetition across REST plus GraphQL plus WebSocket plus SSE plus service workers without changing the delivery procedure.
Defence bypass techniques cover encoding plus sanitizer plus CSP plus Trusted Types plus filter bypasses as a cross-referenced family rather than variant axes.
Techniques anti-patterns cover payload brute force before context classification and catalog-scale payload spraying without sink evidence.
Scripted tests in `references` cover per-context minimal payloads with encoding plus whitespace plus casing variants.
False positives cover safely encoded reflection plus strict CSP without inline handlers plus enforced Trusted Types plus strict DOMPurify plus disabled scriptable contexts.
Chaining covers exfiltration plus CSRF chaining plus phishing overlays plus service-worker persistence as post-execution impact rather than delivery discrimination.

## 4. Runtime parametrisation
Each variant consumes the concrete Service under test as the business-purpose owner of the surface.
Each variant consumes the concrete System that provides the rendering or execution mechanism.
Each variant consumes the concrete Endpoint and BaseURL where input enters and where rendering is observed.
Each variant consumes the concrete Parameter plus Header plus DataItem that carry attacker-controlled input into the sink.
Each variant consumes the observed HTTP history as the witness record for reflection plus retrieval plus transport repetition.
No runtime entity above defines a variant because each one only parametrises the delivery procedure already selected.

## 5. Agent-with-skill walkthrough
STATE 1 inventory is complete because the class has six explicit methodology steps and a populated ontology ledger.
The realistic hunting circumstance is an agent with the XSS skill facing a user-influenced string that may render in a victim context.
Parent step S1 identifies sources across URL plus query plus hash plus referrer plus postMessage plus storage plus WebSocket plus server JSON.
The completion condition for S1 is a named source candidate bound to a concrete entry point.
Parent step S2 traces data flow from the named source to a rendering or execution sink.
The completion condition for S2 is a stated source-to-sink path with an observation channel for confirmation.
Parent step S3 classifies the sink context within HTML plus attribute plus URL plus script plus event plus CSS plus SVG families.
The completion condition for S3 is a recorded context label that selects the payload family.
Parent step S4 assesses output encoding plus sanitizer plus CSP plus Trusted Types plus DOMPurify configuration.
The completion condition for S4 is a recorded defense model plus negative-test evidence.
Parent step S5 crafts minimal per-context payloads with encoding plus whitespace plus casing variants.
The completion condition for S5 is a small curated payload set tied to the classified context.
Parent step S6 repeats the test across REST plus GraphQL plus WebSocket plus SSE plus service-worker paths.
The completion condition for S6 is a transport matrix showing which paths were exercised.
STATE 2 feature testing below shows that output context and payload choice and immediate reflection leave every parent step intact.
STATE 2 feature testing also shows that persistence and non-persistent client-only flow change the kind of action in S1 and S2.

## 6. Feature-verdict table
| Candidate feature | Accurate | Exhaustive | Verdict | Evidence |
|---|---|---|---|---|
| Output context HTML versus attribute versus URL versus JS versus CSS versus SVG | No | Not tested | Non-discriminator | S3 already classifies context and S5 tunes payloads without changing procedure |
| Payload pattern polyglot versus unclosed tag versus encoding versus event variety | No | Not tested | Non-discriminator | S5 explicitly iterates encodings while the source-to-sink procedure stays fixed |
| Technology stack framework or template engine or renderer | No | Not tested | Non-discriminator | Procedure survives stack change and stack is a runtime knowledge-base fact |
| DefensiveControl encoding versus sanitizer versus CSP versus Trusted Types | No | Not tested | Non-discriminator and cross-reference | S4 assesses defenses and bypass detail belongs to the `defence-bypass` family |
| AttackGoal exfiltration versus chaining versus evidence-backed PoC | No | Not tested | Non-discriminator | Goal selects impact demonstration after execution is already confirmed |
| Immediate same-response reflection | No | Not tested | Non-discriminator and parent baseline | S2 already maps same-cycle request-to-response flow accurately and exhaustively |
| Persistence with later retrieval and rendering through any sink | Yes | No | Discriminator | S1 plus S2 cannot describe two-phase write-then-retrieve mapping through storage |
| Non-persistent client-only source-to-sink flow | Yes | No | Discriminator | S2 cannot describe browser-instrumented tracing when no server reflection exists |
| Sanitizer plus parser mutation round trip | Yes | No | Secondary divergence | Morphing step rides inside the nearest delivery variant without its own top-level partition |
| Template expression evaluation | Yes | No | Boundary-ruled overlap | Expression sink routes by the server-computation test in section 7 |
| Uploaded file served inline | Yes | No | Secondary divergence | Upload-then-navigate is a stored-delivery specialisation with content-type checks |
| Email or PDF renderer restriction | Yes | Yes for delivery | Aspect | Renderer changes confirmation evidence without changing the delivery procedure |

## 7. Step-coverage falsification
STATE 2 plus STATE 3 signature work is recorded here as one value per row.
Immediate reflection against S2 passes because the parent phrase maps data flow from source to sink and already covers same-cycle request-to-response binding.
Immediate reflection against S1 passes because the parent source list plus entry-point binding already describe a same-response candidate without extra sequencing.
Persistence against S1 fails because the parent step names storage as a source without describing the separate write action and the later retrieval observation.
Persistence against S2 fails because the parent mapping omits the persistence boundary plus the second view plus possible principal separation.
Non-persistent client-only flow against S2 fails because the parent mapping assumes server-mediated flow while DOM confirmation needs browser sink instrumentation.
Non-persistent client-only flow against S1 fails because the parent list mixes client sources with server sources without distinct observation channels.
Persistent DOM execution against stored plus DOM fails neither parent step alone because it needs both two-phase sequencing and instrumented confirmation at once.
Branch 5a evaluation rejects a separate stored-DOM product because the instrumentation difference is a confirmation-channel aspect inside stored rather than a new kind of sequencing action.
STATE 3 keeps persistence presence and execution locus as two booleans with a mutex rule instead of collapsing them into one feature.
The mutex rule states that any technique with a persistence boundary belongs to stored even when the sink is a DOM sink.
The mutex rule states that DOM contains only non-persistent client-only flows with instrumented confirmation and no server reflection.
Stored therefore completes with retrieval sequencing plus locus-appropriate confirmation through server response or instrumented sink logging.
Sanitizer plus parser mutation against S4 plus S5 fails narrowly because the parent assessment step does not describe feeding sanitizer output back into the parser.
Template expression evaluation against S3 routes by a testable server-computation rule stated in the next line.
The server-computation rule states that server-computed expression output without browser execution routes to server-side template injection while browser-only template execution stays in the nearest XSS delivery variant.
Uploaded file served inline against S2 fails narrowly because the parent mapping omits content-type plus disposition plus sniffing checks before navigation.
Email or PDF rendering against S5 passes as an aspect because payload selection changes while delivery and tracing stay intact.
Output context values against S3 plus S5 pass as aspects because classification plus minimal payload tuning already covers every listed context.
Payload pattern values against S5 pass as aspects because the crafting step already enumerates encoding plus whitespace plus casing plus handler variety.
Technology stack values against all steps pass as non-discriminators because no step changes kind when the framework or renderer changes.
DefensiveControl values against S4 pass as assessed aspects because configuration inspection plus negative tests already cover each control.

## 8. Hypotheses
H1 states that delivery lifecycle alone partitions the class into reflected plus stored plus DOM variants.
H1 predicts three skills whose first non-coverable steps are S2 plus S1 plus S2 respectively.
H1 is falsified if any proposed variant lacks its own non-coverable step or if two variants share one procedure.
H2 states that delivery lifecycle crossed with parser and template edges partitions the class into five or more variants.
H2 predicts additional top-level mutation and template variants beyond the H1 set.
H2 is falsified if mutation and template divergences fit inside delivery variants without their own non-coverable partition step.
H3 states that output context partitions the class into HTML plus attribute plus URL plus JS plus CSS plus SVG variants.
H3 predicts six context skills with distinct procedures.
H3 is falsified if context selection stays inside S3 plus S5 without bending any step.
H4 states that the parent `xss` baseline covers immediate reflection while stored covers any persistence and DOM covers only non-persistent client-only flow.
H4 predicts one baseline plus two variants with stored diverging at S1 plus S2 and DOM diverging at S2.
H4 is falsified if immediate reflection needs its own step beyond S2 or if persistent DOM execution needs a step beyond stored sequencing plus confirmation choice.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable parent step | Divergence summary |
|---|---|---|---|
| H1 | xss-reflected | None proven and deleted | Same-cycle mapping already covered by parent S2 without delta |
| H1 | xss-stored | S1 identify sources plus S2 trace to sinks | Two-phase write-then-retrieve mapping through persistence with later-view confirmation |
| H1 | xss-dom | S2 trace to sinks | Browser-instrumented client-only source-to-sink tracing without server reflection |
| H2 | xss-reflected | None proven and deleted | Same as H1 plus plain-parser confirmation |
| H2 | xss-stored | S1 plus S2 | Same as H1 plus retrieval-view confirmation |
| H2 | xss-dom | S2 | Same as H1 plus instrumented sink confirmation |
| H2 | xss-mutation | None proven as top-level partition | Sanitizer-output-to-parser feedback loop as secondary divergence inside delivery |
| H2 | xss-template | None proven as top-level partition | Expression-evaluation sink routed by the server-computation rule in section 7 |
| H3 | xss-html | None proven | Context label only with no divergent step |
| H3 | xss-attribute | None proven | Context label only with no divergent step |
| H3 | xss-url | None proven | Context label only with no divergent step |
| H3 | xss-js | None proven | Context label only with no divergent step |
| H3 | xss-css | None proven | Context label only with no divergent step |
| H3 | xss-svg | None proven | Context label only with no divergent step |
| H4 | xss parent baseline | None and baseline by definition | Same-cycle request-to-response mapping with same-response confirmation |
| H4 | xss-stored | S1 identify sources plus S2 trace to sinks | Two-phase write-then-retrieve mapping with locus-appropriate confirmation for any sink |
| H4 | xss-dom | S2 trace to sinks | Non-persistent browser-instrumented tracing with sink-invocation confirmation only |
Branch 5a was evaluated for a persistent-DOM product combining two-phase sequencing with instrumentation.
The product was rejected because stored already sequences persistence and selects confirmation by sink without a new kind of action.

## 10. Well-formedness evaluation
STATE 6 applies weights in strict order across coverage plus disjointness plus divergence delta plus stability plus parsimony.
H1 fails coverage and disjointness because the old delivery-wins tie-breaker assigned persistent DOM execution without completion conditions.
H1 fails divergence delta because reflected adds only same-cycle binding which parent S2 already describes accurately and exhaustively.
H1 therefore triggers branch 6a and returns to STATE 3 for the persistence mutex repair.
H2 passes coverage but fails parsimony and overlap because mutation rides delivery and template routes by the server-computation rule.
H2 loses because its two extra variants add secondary divergences without requiring their own top-level partition.
H3 fails coverage and divergence delta because no context value bends any parent step beyond S3 plus S5 tuning.
H3 loses because it over-splits one procedure under many context names.
H4 passes coverage because parent owns no-persistence server-mediated flows plus DOM owns no-persistence client-only flows plus stored owns any persistence.
H4 passes disjointness through the persistence-presence mutex plus the server-reflection mutex for the non-persistent remainder.
H4 passes divergence delta because stored adds two-phase sequencing and DOM adds instrumentation without server reflection.
H4 passes stability because delivery lifecycle survives framework plus payload plus version plus runtime-asset changes.
H4 passes parsimony because one baseline plus two variants cover the class with two booleans and no product variant.
STATE 6 branch 6b therefore selects H4 as the well-formed winner.
The stored-DOM overlap is resolved by the mutex rule with completion conditions rather than by fiat.

## 11. Recommended set
STATE 7 recommends discrimination by persistence presence plus server mediation from source through storage and execution locus to confirmation channel.
The recommended variants are parent `xss` baseline plus `xss-stored` plus `xss-dom`.
Parent `xss` baseline covers immediate same-response reflection mapping with same-response confirmation and carries no delta by definition.
Variant `xss-stored` diverges at S1 plus S2 through two-phase write-then-retrieve mapping with separate later-view confirmation for server or DOM sinks.
Variant `xss-dom` diverges at S2 through non-persistent browser-instrumented client-only tracing with sink-invocation confirmation and no server reflection.
Non-discriminators are output context plus payload pattern plus technology stack plus defensive control plus attack goal plus all L0 and L1 runtime entities.
Defence bypass detail is a cross-reference to the `defence-bypass` and `proxy-techniques` families rather than variant content.
Transport repetition across REST plus GraphQL plus WebSocket plus SSE plus service workers is a secondary matrix inside each variant.
Sanitizer mutation plus uploaded inline files plus renderer restrictions are secondary divergences or aspects inside the nearest delivery variant.
Template expression routing follows the server-computation rule that server-computed output routes to server-side template injection and browser-only execution stays in XSS.
Grey points are the mutation placement plus the email and PDF confirmation limits plus future stored-DOM product evidence if a new sequencing kind appears.
No STATE was skipped and no malformed-class outlier occurred.
