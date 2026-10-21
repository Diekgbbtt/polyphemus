# http-request-smuggling - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/http-request-smuggling/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/http-request-smuggling/SKILL.md`.
HTTP request smuggling here is exploitation of front-end and back-end HTTP parser disagreement about request framing (`Content-Length` versus `Transfer-Encoding`, including HTTP/2 downgrade injection) to leave a hidden prefix on the back-end socket that prepends to the next legitimate request.
Scope covers proxy-chain mapping, CL.TE and TE.CL timing probes, Transfer-Encoding obfuscation, differential-response confirmation, front-end bypass and cross-user capture exploitation, and H2.CL/H2.TE downgrade variants.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | front-end CL with back-end TE parser disagreement topology | 31-33, 153-165 | aspect (one direction of the base-skill probe pair P2) |
| PreconditionEnvironment | front-end TE with back-end CL parser disagreement topology | 47-49, 167 | aspect (one direction of the base-skill probe pair P3) |
| PreconditionEnvironment | HTTP/2 front-end downgrading to HTTP/1.1 back-end with injected framing headers | 64-66, 77-79, 193-198 | discriminator (channel side, bends P8) |
| PreconditionEnvironment | persistent connection reuse with shared back-end socket | 45, 139, 198, 213-214 | non-discriminator (applicability precondition shared by all procedures) |
| PreconditionEnvironment | reflective endpoint for capture (search, comment, logging) | 115-135, 207 | aspect (exploitation target enumerated inside each skill) |
| PreconditionEnvironment | restricted endpoint behind front-end check (admin, internal) | 93-113, 206 | aspect (exploitation target enumerated inside each skill) |
| PreconditionEnvironment | cacheable endpoint with URL-keyed cache for poisoning chain | 142-143 | aspect (chained payload documented inside each skill) |
| PreconditionEnvironment | WebSocket upgrade support for handshake hijacking | 145-147 | aspect (chained payload documented inside each skill) |
| TechnologyStack | CDN, load balancer, reverse proxy, API gateway, WAF products; origin app servers; HTTP/1.1, HTTP/2, HTTP/3 research-stage | 12-22 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | normalize or reject ambiguous CL plus TE; refuse TE obfuscations; close connection after first request; end-to-end HTTP/2 with no downgrade | 213-216, 230 | non-discriminator (false-positive exclusion predicates, no step bends) |
| DefensiveControl | front-end authentication, IP restriction, and access-control check | 93-95, 104-113 | non-discriminator (exploitation target, not a variant axis) |
| VulnerabilityClass | HTTP request smuggling | 8 | non-discriminator (the class itself) |
| AttackGoal | bypass front-end security control | 93-113, 206 | non-discriminator (shared exploitation menu already covered by parent P6) |
| AttackGoal | capture next-user request bytes | 115-135, 207 | non-discriminator (shared exploitation menu already covered by parent P7) |
| AttackGoal | response queue poisoning, cache poisoning chain, WebSocket handshake hijacking | 137-147 | aspect (chained payloads documented inside each skill) |
| AttackerCapability | send crafted raw HTTP/1.1 requests on a reused connection and observe timing plus differential responses | 150-171, 205 | non-discriminator (shared precondition of all procedures) |
| AttackerCapability | inject HTTP/2 headers including spec-forbidden transfer-encoding and conflicting content-length | 64-89, 193-198, 209 | discriminator (channel side, bends P8) |
| AttackTechnique | CL.TE timing probe with missing chunk terminator | 153-165, 202 | aspect (fully procedured by parent P2 inside the base skill) |
| AttackTechnique | TE.CL timing probe with oversized Content-Length over a complete chunked body | 167, 203 | aspect (fully procedured by parent P3 inside the base skill) |
| AttackTechnique | Transfer-Encoding obfuscation (tab, leading space, space-before-colon, duplicate headers, non-standard value, CRLF header injection) | 173-191, 204, 219-222 | aspect (enumerated inside each skill probe step) |
| AttackTechnique | differential-response confirmation over two rapid requests | 169-171, 205 | non-discriminator (shared confirmation procedure) |
| AttackTechnique | smuggled bypass craft against a restricted endpoint | 97-113, 206 | aspect (exploitation sub-step inside each skill) |
| AttackTechnique | partial-prefix capture poison against a reflective endpoint | 119-135, 207 | aspect (exploitation sub-step inside each skill) |
| AttackTechnique | H2.CL content-length injection on downgrade | 64-75, 193-195, 209 | aspect (enumerated injection value inside the H2 variant) |
| AttackTechnique | H2.TE transfer-encoding injection through HTTP/2 | 77-89, 196, 209 | aspect (enumerated injection value inside the H2 variant) |
| PayloadPattern | conflicting CL plus TE header block with smuggled prefix and unique marker string | 35-62, 97-135, 171 | aspect (encoding inside each skill) |
| PayloadPattern | obfuscated TE header values | 173-191 | aspect (encoding inside each skill probe step) |
| PayloadPattern | oversized-CL partial capture prefix (50-100 bytes over partial body) | 128-135, 224 | aspect (sizing parameter inside capture sub-step) |
| PayloadPattern | HTTP/2 injected content-length and transfer-encoding header fields | 67-89 | aspect (enumerated encodings inside the H2 variant) |
| Artifact | poisoned back-end socket state | 45, 135, 171 | non-discriminator (transient per-attempt state, not a variant axis) |
| Artifact | captured victim request bytes (cookies, tokens, body) | 117, 135 | non-discriminator (exploitation yield, not a variant axis) |
| Artifact | exact raw smuggler bytes with unique marker | 171 | non-discriminator (tester-produced per attempt) |
| ObservableSignal | 10-30 second timeout on CL.TE or TE.CL probe | 153-167 | non-discriminator (shared confirmation read-out with per-direction sense) |
| ObservableSignal | unexpected second response proving socket poisoning | 169-171, 205 | non-discriminator (shared confirmation read-out) |
| ObservableSignal | 403-to-200 bypass delta on restricted endpoint | 97-113 | aspect (per-skill exploitation confirmation) |
| ObservableSignal | victim Cookie or Authorization header reflected in controlled endpoint response | 117, 135 | aspect (per-skill exploitation confirmation) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: proxy-chain topologies, HTTP versions in play, and parser differentials at lines 10-27; invariant is a two-hop parse path, what varies is whether the desync is reachable over raw HTTP/1.1 framing or only through HTTP/2 header injection with downgrade.
Adversarial capabilities: crafted raw framing requests on reused connections plus HTTP/2 header injection at lines 150-198; invariant is single-connection desync delivery, what varies is whether the attacker must construct HTTP/2 header blocks or raw HTTP/1.1 framing.
Common trust assumptions: back-end trusts the front-end parsed framing and treats the smuggled prefix as a proxy-originated request; invariant is the trusted-proxy framing assumption, what varies is nothing across channels.
Testing methodology: the eight parent steps P1-P8 listed in section 6; invariant is the map-to-probe-to-confirm-to-exploit spine, what varies is whether the probe step needs header-block construction that P8 never describes.
Proxy techniques: none held by this class as attacker technique; the proxy chain is the target topology, not an attacker relay.
Defence bypass techniques: Transfer-Encoding obfuscation and HTTP/2 header injection at lines 173-198; invariant is defeating framing normalisation, what varies is only the header encoding defeated, hence an aspect.
Techniques anti-patterns: scanner-only confirmation, oversized prefixes during detection, capture attempts without authorization or during peak traffic; these are invariant warnings.
Scripted tests (references/): none shipped with this skill; validation criteria are described inline and the Burp extension is tester tooling, not a scripted test.
False positives: latency noise, connection-close behaviour, end-to-end HTTP/2, normalising proxies at lines 211-216; these are invariant exclusion predicates.
Chaining: bypass to admin, capture to session hijack, reflection to cache poisoning, upgrade to WebSocket hijack at lines 93-147; chaining targets are invariant companions applied after any channel confirms, not variant axes.

## 4. Runtime parametrisation
Consumed L0/L1 runtime entities are the concrete Service under test, the Endpoint and its Parameter/Header carriers, the BaseURL, the Header nodes carrying Content-Length and Transfer-Encoding, the DataItem surfacing at reflective or restricted carriers, the System mechanism overlays (CDN, reverse proxy, WAF, HTTP version), and the HTTP history showing timings and response pairings.
The concrete proxy product, app-server version, header literal, chunk-extension bytes, marker string, Content-Length delta, endpoint path, and victim header bytes are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever skill runs and never define a variant.
Technology stack, library version, payload literal, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent facing a proxied target with an HTTP request path shared across users and needing to prove that a framing disagreement lets one request bleed into the next.
Parent methodology steps with completion conditions: P1 map the proxy chain, complete when front-end, back-end, and HTTP versions on each hop are identified.
P2 probe CL.TE, complete when a missing-terminator timing probe is sent and the delay read-out recorded.
P3 probe TE.CL, complete when a complete-chunked-body with oversized Content-Length probe is sent and the back-end timeout recorded.
P4 obfuscate the TE header, complete when each obfuscation value (tab, extra space, space-before-colon, duplicate, non-standard, CRLF injection) is tried and the differential recorded.
P5 confirm with differential response, complete when two rapid requests show the second receiving an unexpected or marker-bearing response.
P6 attempt bypass exploit, complete when a smuggled restricted-endpoint request is accepted or rejected by the back-end.
P7 attempt capture, complete when a partial-prefix poison against a reflective endpoint captures or fails to capture follow-up bytes.
P8 test H2.CL/H2.TE, complete when the same probes are repeated over HTTP/2, with no header-block construction or downgrade-mapping observation described.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| TechnologyStack values (proxy product, app server, HTTP/3 research stage) | No | N/A | non-discriminator | Parent steps perform the same kind of probe across products; stacks are excluded axes under stability. |
| Connection reuse precondition (PreconditionEnvironment) | No | N/A | non-discriminator | Shared applicability condition; no parent step changes kind when it varies. |
| DefensiveControl values (normalise, reject, close, end-to-end H2) | No | N/A | non-discriminator | They negate the class as false positives at lines 211-216; no step bends. |
| Front-end access check as control (DefensiveControl) | No | N/A | non-discriminator | It is the exploitation target of P6, not a procedure axis. |
| VulnerabilityClass itself (HRS) | No | N/A | non-discriminator | It is the class definition; no step changes kind. |
| Raw-send and observe capability (AttackerCapability) | No | N/A | non-discriminator | Shared precondition of P2-P5 across all candidates. |
| Differential-response confirmation (AttackTechnique) | No | N/A | non-discriminator | P5 performs the same two-request comparison regardless of channel. |
| Poisoned-socket, captured-bytes, raw-bytes artifacts (Artifact) | No | N/A | non-discriminator | Transient per-attempt state or tester-produced bytes; no step bends. |
| Timeout and second-response anomaly signals (ObservableSignal) | No | N/A | non-discriminator | Shared confirmation read-out; direction differs but the comparison kind is identical. |
| Injected H2 header value, content-length versus transfer-encoding (PayloadPattern, AttackTechnique) | No | N/A | non-discriminator | Changing the injected header does not change the inject-then-observe-framing action kind; the two values are enumerated inside the H2 variant. |
| Bypass versus capture versus chained goals (AttackGoal) | Yes | Yes | non-discriminator | P6 and P7 each already perform that kind of exploitation and enumerate its completion, so coverage is complete with chain payloads as parameters. |
| Reflective, restricted, cacheable, and upgrade preconditions (PreconditionEnvironment) | Yes | Yes | aspect | P6 and P7 enumerate the endpoint kinds they need, so each is a target parameter inside the skills. |
| CL.TE framing direction (PreconditionEnvironment, AttackTechnique) | Yes | Yes | aspect | P2 performs that kind of truncated-terminator probe and fully describes it, so the value is covered in-parent. |
| TE.CL framing direction (PreconditionEnvironment, AttackTechnique) | Yes | Yes | aspect | P3 performs that kind of oversized-CL probe and fully describes it, so the value is covered in-parent. |
| TE obfuscation values (AttackTechnique, PayloadPattern) | Yes | Yes | aspect | P4 performs the same obfuscation-then-observe action and enumerates tab, space, duplicate, non-standard, and CRLF values, so coverage is complete. |
| Marker string and CL sizing values (PayloadPattern) | Yes | Yes | aspect | P5 names the unique marker and P7 with tip guidance sizes the overshoot, so values are parameters. |
| Transport framing channel, HTTP/1.1 raw versus HTTP/2 header injection (PreconditionEnvironment, AttackerCapability) | Yes | No | discriminator | P8 says only to repeat the same probes over HTTP/2 and never describes HTTP/2 header-block construction, pseudo-header discipline, forbidden-header passthrough, or downgrade-mapping observation, so it bends. |

## 7. Step-coverage falsification
Transport framing channel at its HTTP/2 value: parent step P8 says repeat the same probes over HTTP/2 connections if the target supports HTTP/2.
The uncovered reality is crafting HTTP/2 header blocks with an injected regular content-length field distinct from pseudo-headers or with a spec-forbidden transfer-encoding field, then reading downgrade mapping, passthrough survival, and connection-reuse behaviour, which is a header-block construction plus mapping-observation procedure that P8 never names.
CL.TE direction: no falsification holds because P2 fully procedures the truncated-terminator probe with its delay read-out.
TE.CL direction: no falsification holds because P3 fully procedures the complete-body with oversized Content-Length probe with its timeout read-out.
TE obfuscation values: no falsification holds because P4 enumerates tab, extra space, space-before-colon, duplicate, non-standard value, and CRLF injection with per-value observation.
Injected H2 header values: no mutual falsification holds between content-length and transfer-encoding because one inject-then-observe-framing step enumerates the closed pair.
Bypass versus capture versus chained goals: no falsification holds because P6 describes restricted-endpoint smuggling and P7 describes partial-prefix reflective capture with distinct completions, and chain outcomes ride as payload choices.
Endpoint preconditions: no falsification holds because P6 and P7 name the restricted and reflective endpoint kinds they require.

## 8. Hypotheses
H1 (single-feature, four framing channels): if the class is partitioned by framing channel into CL.TE, TE.CL, H2.CL, and H2.TE, then each partition owns a distinct first non-coverable probe step and jointly covers every desync procedure.
This hypothesis is falsified if any partition lacks its own non-coverable step over the parent, which CL.TE and TE.CL do because P2 and P3 already procedure them completely, so H1 is discarded per STATE 4 branch 4a with its H2 half salvaged into H2.
H2 (single-feature, transport framing channel): if the class is partitioned into HTTP/1.1 raw framing desync versus HTTP/2 header-injection desync, then the HTTP/2 partition owns a non-coverable header-block construction step while the HTTP/1.1 partition retains the parent P1-P7 procedures with CL.TE, TE.CL, and obfuscation as internal enumerated alternatives.
This hypothesis is falsified if P8 already describes header-block construction or if the H2.CL and H2.TE values need distinct non-coverable steps rather than one enumerating step.
H3 (combined-feature, transport channel crossed with exploitation objective): if each H2 partition cell is further split by bypass versus capture versus queue-cache-websocket objective, then each cell adds its own non-coverable exploitation step.
This hypothesis is falsified if the exploitation action is already covered by parent P6 or P7 with no new non-coverable step, leaving cells with zero divergence delta.
H4 (combined-feature, transport channel crossed with TE-obfuscation family): if each partition is further split by obfuscation family (whitespace, duplicate, non-standard, CRLF injection), then each cell adds its own non-coverable probe step.
This hypothesis is falsified if P4 already enumerates every obfuscation value with the same probe kind, leaving cells with no divergence delta.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | hrs-cl-te | None; P2 already procedures the truncated-terminator probe, so this proposal has zero delta and is deleted. |
| H1 | hrs-te-cl | None; P3 already procedures the oversized-CL probe, so this proposal has zero delta and is deleted. |
| H1 | hrs-h2-cl | Craft an HTTP/2 header block with an injected regular content-length and read downgrade mapping plus connection reuse; P8 never names this. |
| H1 | hrs-h2-te | Inject spec-forbidden transfer-encoding through HTTP/2 and test passthrough with back-end TE preference; P8 never names this. |
| H2 | http-request-smuggling (retained base) | None needed; retains parent P1-P7 with CL.TE, TE.CL, obfuscation, confirmation, bypass, and capture as internal enumerated procedures. |
| H2 | http-request-smuggling-h2-desync | Craft HTTP/2 header blocks with injected framing headers (content-length or transfer-encoding) and observe downgrade mapping, passthrough survival, and connection reuse shared by both injection values. |
| H3 | H2 skills plus bypass versus capture versus chain cells per channel | Same H2 first step; cells add only an exploitation payload choice already covered by P6 or P7 with no new non-coverable step. |
| H4 | H2 skills plus per-obfuscation cells (whitespace, duplicate, non-standard, CRLF) | Same first steps; cells add only a header-encoding swap inside P4 with no new non-coverable step. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 fails divergence delta because its CL.TE and TE.CL proposals add no non-coverable step over P2 and P3, so H1 is discarded per STATE 4 branch 4a even though its H2 half is sound.
H2 scores coverage pass because the one genuine non-coverable procedure (HTTP/2 header-block construction with mapping observation) belongs to exactly one variant and every other procedure stays covered in the retained base.
H2 scores disjointness pass because raw-socket framing probes and HTTP/2 header-block injection are mutually exclusive probe constructions.
H2 scores divergence delta pass because the H2 variant adds the header-block construction plus mapping-observation step named in section 9 over P8 while the base needs none as the retained parent.
H2 scores stability pass because swapping proxy product, app-server version, marker literal, or endpoint asset leaves each procedure intact.
H2 scores parsimony pass with one collapsed feature and one new variant beside the retained base.
H3 fails divergence delta and parsimony because exploitation cells repeat P6 and P7 with no new step and multiply the set by objective, so H3 is discarded per STATE 4 branch 4a.
H4 fails divergence delta and parsimony because obfuscation cells repeat P4 enumeration with no new step and multiply the set by encoding, so H4 is discarded per STATE 4 branch 4a.
Winner is H2 with losing reason for H1 being zero-delta home-direction proposals, for H3 being zero-delta exploitation cells, and for H4 being zero-delta encoding cells.
No return to STATE 3 is needed because the winner passes coverage and disjointness.
STATE 1 completed with eight parent steps and full entity inventory and no malformed-class outlier.
STATE 2 completed with the transport channel as the sole discriminator alongside fourteen aspects and sixteen non-discriminators.
STATE 3 branch 3a did not merge further because direction values are scoped inside the HTTP/1.1 transport, and branch 3b kept obfuscation continuity, marker choice, Content-Length overshoot magnitude, and the H2.CL versus H2.TE pair as aspects with enumerable values.

## 11. Recommended set
Discrimination function in one sentence: HTTP request smuggling decomposes by transport framing channel into HTTP/1.1 raw framing desync versus HTTP/2 header-injection desync with downgrade mapping.
Retained base skill http-request-smuggling keeps parent P1-P7 with CL.TE truncated-terminator probing, TE.CL oversized-CL probing, TE obfuscation enumeration, differential confirmation, bypass craft, and capture poison as internal enumerated procedures with no split, because splitting per direction would duplicate the shared chain with zero delta.
Recommended variant http-request-smuggling-h2-desync diverges by crafting HTTP/2 header blocks with injected framing headers (content-length as a regular header with pseudo-header discipline, or spec-forbidden transfer-encoding) and observing downgrade mapping, passthrough survival, and connection reuse over parent step P8, which says only to repeat the same probes and never names header-block construction or mapping observation.
Secondary divergences documented inside the skills are TE obfuscation encodings, bypass versus capture exploitation choice, and queue-cache-WebSocket chained payloads, which are rework triggers rather than new variants.
Non-discriminators are technology stack with versions as excluded runtime axis, connection reuse with defensive normalisation and close behaviour as shared precondition and exclusion predicates, front-end access checks as exploitation targets, raw-send capability with differential confirmation and timeout signals with poisoned-socket and captured-byte artifacts as shared apparatus, bypass-versus-capture goals as already-covered parent steps, and the injected H2 header value pair as enumerated values inside the H2 variant.
Open questions: none at FAIL level; the analysis leaves no uncovered falsification and no skipped state.
Grey points: HTTP/3 QUIC desync rides outside all skills as research-stage with no described probe, which holds only until a concrete framing probe procedure is documented.
Grey points: response queue poisoning rides inside the confirming skill rather than a standalone variant, which holds only while queue delivery needs no probe beyond the channel desync plus pipelining observation.
Grey points: WebSocket handshake hijacking rides as a chained payload inside the confirming skill, which holds only while the upgrade needs no distinct framing probe beyond the channel desync.
Grey points: H2.CL and H2.TE ride as enumerated injection values inside one H2 variant rather than two variants, which holds only while one inject-then-observe-framing step keeps covering both values accurately and exhaustively.
