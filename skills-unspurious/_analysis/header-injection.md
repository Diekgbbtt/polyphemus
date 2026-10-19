# header-injection - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/header-injection/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/header-injection/SKILL.md`.
Header injection here is user-controlled input reaching an HTTP header value without normalization, which yields protocol-level control that downstream components then trust.
Scope covers HTTP CRLF response splitting, Host-family spoofing, forwarding-header spoofing, cache poisoning, method-override and rewrite bypass, request smuggling, content-type and cookie-attribute confusion, header-sink XSS and open redirect, plus HTTP/2 downgrade edges.
Outbound SMTP email-header injection is explicitly out of scope and belongs to its related class, which resolves the ledger precondition contradiction noted in review.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | user-controlled value reaches an HTTP header (query, body, path, cookie, reflected request header, webhook URL) | 12-15 | non-discriminator (shared class precondition) |
| PreconditionEnvironment | email fields reaching SMTP headers (To, From, Subject) | 16, 177 | explicitly out of scope, belongs to the related email-injection class |
| PreconditionEnvironment | proxy-fronted deployment where frontend and backend can disagree on framing | 24-27, 63 | discriminator value inside the single consumer feature (framing-disagreement side) |
| PreconditionEnvironment | cache layer present with key composition distinct from response content | 48-49, 65-71 | discriminator value inside the single consumer feature (cache side) |
| PreconditionEnvironment | link-generating flow that builds absolute URLs from Host (password reset, OAuth redirect, canonical link) | 73-82 | discriminator value inside the single merged spoof value (URL-builder oracle) |
| PreconditionEnvironment | IP-restricted or scheme-restricted endpoint trusting forwarding headers except rewrite headers | 92-99 | discriminator value inside the single merged spoof value (access-decision oracle, rewrite excluded) |
| PreconditionEnvironment | backend routes on method-override plus X-Original-URL and X-Rewrite-URL before authorization (IIS, ASP.NET) | 22, 100, 142-144 | discriminator value inside the single consumer feature (routing side, sole owner of rewrite headers) |
| PreconditionEnvironment | response header value consumed in the same response by cookie jar, renderer, or navigator with delimiter-free replacement only | 84-90, 102-122 | discriminator value inside the single consumer feature (same-response side, line-break payloads excluded) |
| PreconditionEnvironment | response path permits raw line breaks to become framing (missing CR/LF stripping) with line-break payloads only | 18-19, 55-63 | discriminator value inside the single consumer feature (framing-parser side, delimiter-free payloads excluded) |
| TechnologyStack | HTTP/1.0, HTTP/1.1, HTTP/2, HTTP/3, CDN, reverse proxy, cache, framework, IIS, ASP.NET, Nginx | 24-27, 46-51, 122, 124-128 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | CR/LF stripping and header normalization | 18-19, 137-140 | aspect (enumerated inside each variant defeat sub-step) |
| DefensiveControl | WAF single-decode behavior defeated by double encoding | 40, 133 | aspect (encoding inside each variant defeat sub-step) |
| DefensiveControl | X-Content-Type-Options nosniff presence or absence | 108 | aspect (enumerated inside value-confusion variant) |
| DefensiveControl | IP allowlist and rate limit keyed on client IP | 96 | non-discriminator (victim control defeated identically by any forwarding spoof value) |
| DefensiveControl | method-based authorization ordering | 22, 142-144 | discriminator value inside the single consumer feature (routing side) |
| DefensiveControl | cache key correctness with Vary and Cache-Control eligibility | 65-71 | discriminator value inside the single consumer feature (cache side) |
| DefensiveControl | CORS preflight on non-safelisted override headers from browsers | 144 | non-discriminator (delivery-context fact, not a variant axis) |
| VulnerabilityClass | HTTP header injection as the parent weakness | 6-8, 179-181 | non-discriminator (the class itself) |
| AttackGoal | protocol-level control leading to splitting, poisoning, takeover, bypass, fixation, redirect, or smuggling | 8, 55-63, 65-71, 73-82, 92-100 | non-discriminator (shared goal family except oracle direction) |
| AttackerCapability | ability to supply header-reaching input values | 12-16, 31-35 | non-discriminator (shared precondition of all variants) |
| AttackerCapability | ability to send arbitrary request headers including Host and X-Forwarded family | 51, 73-82, 92-100 | discriminator value inside the single merged spoof value (spoof side) |
| AttackerCapability | control of an attacker host that can receive reset tokens or callbacks | 73-80 | aspect (confirmation address inside the merged spoof variant) |
| AttackTechnique | CRLF injection with line-break payloads only to split the response, including the SKILL line 60 Set-Cookie CRLF example | 55-63, 130-140 | discriminator value inside the single consumer feature (framing-parser side, sole owner of line-break payloads) |
| AttackTechnique | Host plus X-Forwarded-Host forgery in link-generating flows with precedence control | 73-82 | discriminator value inside the single merged spoof value (URL-builder oracle, sole owner of X-Forwarded-Host link building) |
| AttackTechnique | forwarding-header spoofing across non-Host aliases except X-Original-URL and X-Rewrite-URL | 92-99 | discriminator value inside the single merged spoof value (access-decision oracle, rewrite headers excluded) |
| AttackTechnique | cache-poisoning via unkeyed input with second-session confirmation and no line-break requirement | 65-71 | discriminator value inside the single consumer feature (cache side) |
| AttackTechnique | method-override plus X-Original-URL and X-Rewrite-URL abuse past auth layers as sole owner | 100, 142-144 | discriminator value inside the single consumer feature (routing side) |
| AttackTechnique | request-smuggling framing pairs with leftover-bytes oracle | 63, 157 | discriminator value inside the single consumer feature (framing-disagreement side) |
| AttackTechnique | same-response value replacement without line breaks for cookie attributes, content-type, redirect, and XSS sinks | 84-90, 102-122 | discriminator value inside the single consumer feature (same-response side, sole owner of delimiter-free replacement) |
| AttackTechnique | HTTP/2 pseudo-header and CONTINUATION frame splitting across downgrade | 124-128 | aspect (protocol replay inside smuggling and splitting variants) |
| PayloadPattern | CR/LF encoding family (bare LF, bare CR, CRLF, double encoding, overlong UTF-8, U+2028, U+2029, tab, NUL) | 37-44, 130-135 | aspect (encoding inside each variant defeat sub-step, line-break members owned by splitting only) |
| PayloadPattern | header normalization edges (whitespace, obs-fold, duplicates, case mangling, NUL in name) | 137-148 | aspect (encoding inside each variant defeat sub-step) |
| PayloadPattern | cookie attribute suffixes (Domain, Path, SameSite, Max-Age, name shadowing) | 84-90 | aspect (sink value inside value-confusion variant) |
| PayloadPattern | content-type and disposition values (text/html, charset, inline, gzip) | 102-108 | aspect (sink value inside value-confusion variant) |
| PayloadPattern | redirect and XSS sink values (Location, Refresh, Link, X-Accel-Redirect, javascript and data schemes) | 110-122 | aspect (sink value inside value-confusion variant) |
| PayloadPattern | smuggling framing pairs (Content-Length versus Transfer-Encoding, dual Content-Length, malformed chunked) | 63, 157 | aspect (pair shape inside smuggling variant) |
| Artifact | poisoned cache entry served to a second session | 57, 65-71 | non-discriminator (tester-observed confirmation object per attempt) |
| Artifact | attacker-pointing reset link or OAuth redirect carrying a victim token | 73-80 | non-discriminator (tester-observed confirmation object per attempt) |
| Artifact | injected Set-Cookie or second response stored downstream | 57, 60, 84-90 | non-discriminator (tester-observed confirmation object per attempt) |
| ObservableSignal | injected second header field stored and served downstream as a real header field | 152, 174 | discriminator value inside the single consumer feature (splitting oracle side) |
| ObservableSignal | attacker-influenced body served under a victim key on clean replay with no new header field required | 155 | discriminator value inside the single consumer feature (cache oracle side) |
| ObservableSignal | auth decision flip with and without a forged forwarding header | 154 | discriminator value inside the single merged spoof value (access oracle side) |
| ObservableSignal | victim request data appended to another request | 167 | discriminator value inside the single consumer feature (smuggling oracle side) |
| ObservableSignal | header and body diffs across protocols and inputs (status, headers, length, Age, X-Cache) | 31-35, 46-51 | non-discriminator (shared recon read-out feeding parametrisation) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: header-reaching HTTP inputs, reflected request headers, webhook URL flows, parser layers, header inventory, CR/LF whitespace matrix, and stack fingerprinting at lines 10-51.
Invariant is unnormalized input reaching an HTTP header value, what varies is which downstream consumer trusts that value.
Adversarial capabilities: supplying header-reaching values, spoofing Host-family and the forwarding family, holding an attacker host, and replaying across protocols.
Invariant is no privilege beyond chosen input and headers, what varies is which trusted header the procedure forges.
Common trust assumptions: response parser treats the value as framing, cache treats unkeyed input as safe, URL builder treats Host-family as canonical, access check treats non-rewrite forwarding headers as client truth, router treats override and rewrite headers as method and path truth, client treats same-response values as store, render, or navigation truth.
Invariant is misplaced header trust, what varies is the trusting consumer and its oracle.
Testing methodology: the eight parent steps P1-P8 listed in section 6.
Invariant is the inventory-to-cross-protocol spine, what varies is which consumer step bends per candidate procedure.
Proxy techniques: none held as a standalone proxy family by this class, since smuggling and forwarding spoofing name their own boundary procedures and the `proxy-techniques` family owns generic relay steps.
Defence bypass techniques: encoding layering, normalization edges, name games, and method-override delivery at lines 130-148.
Invariant is defeating input normalization, what varies is only the encoding value used, hence an aspect.
Techniques anti-patterns: claiming CRLF on silent server-side stripping, claiming smuggling on pipelining, claiming redirect on browser-blocked schemes, and probing Age as a freshness control.
These are invariant warnings.
Scripted tests (references/): none shipped with this skill, since validation is described inline at lines 161-167 of the analysed file.
False positives: correctly keyed personalization, logging-only reflection, blocked navigation schemes, outer-proxy stripping, and keep-alive mistaken for smuggling.
These are invariant exclusion predicates.
Chaining: cache poisoning with XSS, Host-family confusion with token theft, forwarding spoof with auth bypass, smuggling with credential capture, and email-header injection as a related out-of-scope class.
Chaining targets are invariant companions, not variant axes.

## 4. Runtime parametrisation
Consumed L0/L1 runtime entities are the concrete Service under test, the Endpoint with its Parameter and Header carriers, the BaseURL, the DataItem surfacing at those carriers, the System mechanism overlays for proxy and cache and auth and rendering, and the HTTP history showing requests, responses, and cache signals.
The concrete header names, Host values, forwarding aliases, payload literals, browser brands, protocol versions, cache keys, cookie names, and target assets are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, library version, payload literal, protocol version, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding an inventory of response headers that move with input, facing a proxy-fronted cached application with link-generating and access-controlled flows, and needing to prove which downstream consumer trusts an injected header value.
Parent methodology steps with completion conditions: P1 inventory varying headers, complete when every response header whose value moves with input is listed with its source field.
P2 probe CR/LF normalization, complete when each varying source has been tested with the encoding family and second-line landing is confirmed or ruled out.
P3 test Host and X-Forwarded-Host, complete when a link-generating flow has been submitted with a forged Host and the emitted link destination is recorded.
P4 probe forwarding headers, complete when spoofed forwarding aliases have been replayed against an access-controlled endpoint and the decision delta is recorded.
P5 test cache key versus response content split, complete when an input changing the body without changing the key is confirmed by a second session seeing the poisoned response.
P6 test method override, complete when override and rewrite headers have been paired with a state-changing endpoint and the routing versus authorization order is recorded.
P7 test request smuggling pairs, complete when framing pairs have been sent over a frontend-to-backend pair and leftover-bytes disclosure is confirmed or ruled out.
P8 cross-protocol replay, complete when payloads have been replayed over HTTP/1.1 and HTTP/2 and the behavior diff is recorded.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Shared header-reachability precondition (PreconditionEnvironment) | No | N/A | non-discriminator | It is the class definition and no parent step changes kind when it varies. |
| Email-header reachability (PreconditionEnvironment) | No | N/A | explicitly out of scope | It belongs to the related SMTP class and no HTTP parent step applies to it. |
| TechnologyStack and protocol values (HTTP versions, CDN, cache product, framework, IIS, Nginx) | No | N/A | non-discriminator | Parent steps perform the same kind of action across stacks and P8 already parametrises protocol replay. |
| PayloadPattern encoding values (CRLF family, double encoding, Unicode, tab, NUL, folding, duplicates, case) | Yes | Yes | aspect | Each variant performs the same kind of injection with a swapped literal and its defeat sub-step enumerates the family. |
| Generic lure and input-supply capability (AttackerCapability) | No | N/A | non-discriminator | Shared precondition and every candidate uses the same supply-then-observe shape. |
| Shared protocol-control goal family (AttackGoal) | No | N/A | non-discriminator | Same kind of injection action regardless of whether impact reads as redirect, poisoning, bypass, or smuggling. |
| Per-attempt artifacts and generic diff signals (Artifact, ObservableSignal) | No | N/A | non-discriminator | Tester-observed confirmation objects and shared recon read-outs parametrise runs rather than bending steps. |
| CORS preflight delivery context (DefensiveControl) | No | N/A | non-discriminator | It constrains browser delivery of override headers only and no parent step changes kind when it varies. |
| Response framing parser trust with line-break payloads only (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator | P2 performs splitting but its flat description does not cover downstream storage and serving of the injected header field as a distinct oracle. |
| Host-family spoof trust covering URL-builder and access-decision oracles (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator (merged spoof value) | P3 plus P4 together describe single-value submission and single spray but neither covers controlled precedence comparison with out-of-band capture combined with per-alias decision mapping. |
| Cache key versus content split trust without line-break requirement (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator | P5 names the split but does not cover the five cache sub-shapes with Vary, Cache-Control, proto-host, and deception handling under one clean-replay oracle. |
| Routing-before-authorization trust for override plus rewrite as sole owner (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator | P6 names override pairing but does not cover rewrite-header path rewriting on IIS and ASP.NET with auth-order proof. |
| Framing-disagreement pair trust (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator | P7 names framing pairs but does not cover downgrade, lowercase, and CONTINUATION-split shapes with leftover-bytes proof. |
| Same-response header-semantics trust with delimiter-free replacement only (PreconditionEnvironment plus AttackTechnique) | No | No | discriminator | Delimiter-free replacement is a different action kind from the CRLF probe at SKILL line 153, so P2 is neither accurate nor exhaustive for it. |
| H2 pseudo-header and frame shapes (AttackTechnique) | Yes | Yes | aspect | P8 replays payloads across protocols and diffs behavior, so downgrade and case and frame splits ride as protocol parameters. |
| Per-sink header names and per-cache sub-shape names (Header runtime plus PayloadPattern) | Yes | Yes | aspect | Each variant enumerates its sink or sub-shape values inside one oracle, so names alone never add a step. |

## 7. Step-coverage falsification
Response framing parser trust with line-break payloads only: parent step P2 says probe CR/LF normalization and observe whether the second line lands as a real header.
The uncovered reality is proving the injected line break was stored downstream and is served as a real header field to an unrelated request, including the SKILL line 60 CRLF Set-Cookie example, which needs a downstream-serving oracle that P2 never names.
Host-family spoof trust with two oracles: parent steps P3 plus P4 say submit one forged Host and record one link plus spray one alias set and record one decision delta.
The uncovered reality is a controlled precedence experiment between Host and X-Forwarded-Host with swapped values plus bracketing and trailing-dot and port edges with emailed-link capture, combined with per-alias mapping of each non-Host alias to allowlist versus scheme-check outcomes with negative controls, which needs a unified spoof procedure that P3 plus P4 never names.
Forwarding rewrite exclusion: parent step P4 never owns X-Original-URL or X-Rewrite-URL in this analysis because those headers move entirely to the routing variant below.
Cache key versus content split trust: parent step P5 says find body-changing but key-ignored input and confirm a second session sees it.
The uncovered reality is unkeyed reflection, Vary fragmentation games, proto-host URL building, Cache-Control eligibility flips, and deception-suffixed public URLs proven by a clean second session replaying the victim URL with no attack headers and seeing attacker-influenced body content, which needs a sub-shape sweep plus eligibility handling that P5 never names.
Routing-before-authorization trust: parent step P6 says pair X-HTTP-Method-Override with state-changing endpoints.
The uncovered reality is X-Original-URL and X-Rewrite-URL rewriting the path after the auth check on IIS and ASP.NET as sole owner, which needs a rewrite-after-auth proof procedure that P6 never names.
Framing-disagreement pair trust: parent step P7 says test conflicting length and encoding pairs against a frontend-to-backend pair.
The uncovered reality is H2-to-H1 downgrade mishandling, lowercase bypass of case-sensitive filters, and CONTINUATION frame-split reassembly gaps with leftover-bytes disclosure, which needs a boundary-pair plus cross-version replay proof that P7 never names.
Same-response header-semantics trust: parent step P2 says inject CRLF encodings into each varying header source.
The uncovered reality is delimiter-free replacement using semicolon attributes, MIME values, disposition directives, redirect schemes, and XSS sinks with payloads containing no line break, completed on cookie-jar, sniff-render, or navigation behavior in the same response, which is a replace-then-observe-client procedure that P2 neither performs nor describes.
Encoding values: no falsification holds because each variant defeat sub-step enumerates the CRLF family and normalization edges.
H2 shapes: no falsification holds because P8 enumerates cross-protocol replay with diffing as a parameter.
Sink-name values: no falsification holds because each variant enumerates its sink or alias values inside its own oracle.

## 8. Hypotheses
H1 (single-feature, trusting consumer with seven partitions): if the class is partitioned by the downstream consumer into framing parser, URL builder, access decision, cache logic, pre-auth router, framing-disagreement pair, and same-response client semantics, then each partition owns a distinct first non-coverable step and jointly covers all seven falsifications above.
This hypothesis is falsified if any partition lacks its own non-coverable step or if two partitions claim the same technique under the disjointness exclusions.
H4 (lean merged-spoof, six partitions): if URL-builder and access-decision partitions merge into one Host-family spoof variant with two documented oracles while the other five partitions stay unchanged and all four disjointness exclusions apply, then the merged set covers every falsification with one fewer variant and a stronger unified spoof step.
This hypothesis is falsified if the merged spoof variant lacks a unified non-coverable step spanning precedence comparison and per-alias mapping or if any falsification loses its owning variant.
H2 (combined-feature, consumer crossed with defense layer defeated): if each H1 partition is further split by normalization defeat versus WAF double-decode defeat versus hardening-control absence, then each cell adds its own non-coverable defeat step.
This hypothesis is falsified if the defeat action kind is identical across cells and each variant already enumerates every encoding value, leaving cells with no divergence delta.
H3 (combined-feature, consumer crossed with technology stack): if each H1 partition is further split by HTTP version versus CDN vendor versus framework versus IIS and ASP.NET versus Nginx, then each stack cell adds its own non-coverable step.
This hypothesis is falsified if the stack swap leaves the consumer procedure unchanged and only swaps runtime parameters, violating stability.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | header-crlf-splitting | Prove a line-break payload created a stored header field served downstream to an unrelated request. |
| H1 | header-host-confusion | Map Host versus X-Forwarded-Host precedence with bracketing and dot and port edges and capture the emitted attacker link. |
| H1 | header-forwarding-spoof | Map each non-Host non-rewrite alias to allowlist and scheme-check decision deltas. |
| H1 | header-cache-poisoning | Sweep unkeyed, Vary, proto-host, Cache-Control, and deception sub-shapes under a clean-replay oracle. |
| H1 | header-method-override | Prove override plus rewrite headers reroute method or path before the authorization check. |
| H1 | header-request-smuggling | Prove a framing pair with downgrade and case and frame-split shapes leaks leftover bytes across requests. |
| H1 | header-response-value-confusion | Replace same-response header semantics without line breaks and observe client behavior. |
| H4 | header-crlf-splitting | Prove a line-break payload created a stored header field served downstream to an unrelated request. |
| H4 | header-host-forward-spoof | Prove one forged Host-family value bends the emitted link and the access decision under controlled precedence plus per-alias mapping. |
| H4 | header-cache-poisoning | Sweep unkeyed, Vary, proto-host, Cache-Control, and deception sub-shapes under a clean-replay oracle. |
| H4 | header-method-override | Prove override plus X-Original-URL and X-Rewrite-URL reroute method or path before the authorization check. |
| H4 | header-request-smuggling | Prove a framing pair with downgrade and case and frame-split shapes leaks leftover bytes across requests. |
| H4 | header-response-value-confusion | Replace same-response header semantics without line breaks and observe client behavior. |
| H2 | H1 seven plus per-defeat cells (normalization versus double-decode versus hardening absence) | Same seven first steps, since cells add only a parametrized encoding sub-step with no new non-coverable step. |
| H3 | H1 seven plus per-stack cells (HTTP version, CDN, framework, IIS, Nginx) | Same seven first steps, since cells add only stack parameter swaps with no new non-coverable step. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage pass because every falsified consumer value belongs to exactly one variant once the four exclusions below apply.
H1 scores disjointness weak pass because line-break versus delimiter-free payload exclusion separates splitting from value-confusion, rewrite-header sole ownership separates spoof from routing, and downstream-header-field versus clean-replay-body predicates separate splitting from cache, while X-Forwarded-Host still straddles its two spoof partitions.
H1 scores divergence delta weak because its split spoof partitions each restate one parent matrix without showing a cross-oracle comparison step.
H4 scores coverage pass because the merged spoof variant owns both URL-builder and access-decision falsifications and every other falsification keeps its owning variant.
H4 scores disjointness pass because splitting owns only line-break payloads with a stored-header-field oracle, value-confusion owns only delimiter-free payloads with a same-response client oracle, spoof owns all Host-family link and decision proof with rewrite headers excluded, routing solely owns X-Original-URL and X-Rewrite-URL, cache owns clean-replay body proof with no new header field required, and smuggling owns leftover-bytes proof.
H4 scores divergence delta pass because the merged spoof step adds controlled precedence comparison with out-of-band capture combined with per-alias decision mapping, which neither P3 nor P4 describes alone.
H4 scores stability pass because swapping stack, protocol version, payload literal, or runtime asset leaves each consumer procedure intact.
H4 scores parsimony pass with six variants from one consumer feature, which beats the seven-variant H1 set.
H2 fails divergence delta and parsimony because defeat cells repeat encoding enumeration with no new step and triple the set size, so H2 is discarded per STATE 4 branch 4a.
H3 fails stability and parsimony because stack cells swap runtime parameters only and multiply variants by technology, so H3 is discarded per STATE 4 branch 4a.
A merged cache-served-response hypothesis was considered and rejected because splitting requires line-break payloads while cache poisoning forbids that requirement, so a merge would hide a genuine payload precondition and lose coverage.
STATE 6 branch 6a fired honestly on H1 for the X-Forwarded-Host straddle and the weak split-spoof deltas, which forced a return to STATE 3 where the spoof values were merged and the four exclusions were written, after which H4 was re-scored as winner.
STATE 1 completed with eight parent steps and full entity inventory and no malformed-class outlier.
STATE 2 completed with aspects and non-discriminators recorded alongside discriminator values grouped per STATE 3 into one consumer feature.
STATE 3 co-variance was tested explicitly and no two consumer values always co-vary, since framing-parser trust can hold without URL-builder trust and cache trust can hold without routing trust, so the signature is seven values of one feature with non-co-variance explicit rather than a branch 3a collapse.
STATE 3 branch 3b applied to encoding continuity, sink-name ranges, and protocol replay by keeping them as aspects inside variants.

## 11. Recommended set
Discrimination function in one sentence: Header injection decomposes by the downstream consumer that trusts the injected header value, namely response framing parser with line-break payloads, Host-family spoof surface with link-builder and access-decision oracles, cache key-versus-content logic, pre-authorization router owning override and rewrite headers, request framing-disagreement pair, and same-response client semantics with delimiter-free replacement.
Recommended variant header-crlf-splitting diverges by proving a line-break payload created a stored header field served downstream to an unrelated request over parent step P2, which never names the downstream-serving oracle.
Recommended variant header-host-forward-spoof diverges by proving one forged Host-family value bends the emitted link and the access decision under controlled precedence plus per-alias mapping over parent steps P3 plus P4, which never name the unified comparison procedure.
Recommended variant header-cache-poisoning diverges by sweeping unkeyed, Vary, proto-host, Cache-Control, and deception sub-shapes under a clean-replay body oracle over parent step P5, which never names the sub-shape sweep with eligibility handling.
Recommended variant header-method-override diverges by proving override plus X-Original-URL and X-Rewrite-URL reroute method or path before the authorization check over parent step P6, which never names rewrite-after-auth proof on IIS and ASP.NET.
Recommended variant header-request-smuggling diverges by proving a framing pair with downgrade and case and frame-split shapes leaks leftover bytes across requests over parent step P7, which never names the boundary-pair plus cross-version replay proof.
Recommended variant header-response-value-confusion diverges by replacing same-response header semantics without line breaks for cookie, MIME, disposition, redirect, and XSS sinks and observing client behavior over parent step P2, which describes only line-break splitting and therefore neither performs nor describes delimiter-free replacement.
Non-discriminators are shared header-reachability as class definition, technology stack with versions and protocol replay as excluded runtime axis, payload encodings with normalization edges as per-variant aspects, generic input-supply capability with per-attempt artifacts and generic diffs as shared apparatus, CORS preflight delivery context, shared protocol-control goal family, sink or alias or sub-shape names as enumerated parameters, and SMTP email headers as explicitly out of scope.
Open questions: none at FAIL level, since the analysis leaves no uncovered falsification and no skipped state.
Grey points: X-Accel-Redirect internal-file access rides inside value-confusion rather than a standalone file-access variant, which holds only while its oracle stays client-or-proxy behavior on one header value.
Grey points: Location javascript and data-scheme navigation stays inside value-confusion despite modern browser blocking, which holds only while legacy and embedded clients keep the sink reachable.
