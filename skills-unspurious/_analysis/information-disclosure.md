# information-disclosure - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/information-disclosure/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/information-disclosure/SKILL.md`.
Information disclosure here is any response byte, artifact, header, or behavioral delta that reveals code, configuration, identifiers, versions, or trust boundaries and thereby accelerates exploitation.
Scope covers verbose errors and debug tooling, DVCS and backup and config artifacts, API schemas and introspection, client bundles and source maps, headers and response metadata, storage and export surfaces, observability and admin panels, differential oracles, cache-key behavior, and cross-channel mirroring.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | verbose errors and exception pages enabled in prod | 12, 73 | discriminator candidate via verbosity mechanism over P3 |
| PreconditionEnvironment | debug and dev tooling reachable in prod (debuggers, profilers, feature flags) | 13, live 35-38 | discriminator candidate via verbosity mechanism over P3 |
| PreconditionEnvironment | DVCS folders, backups, temp files, and build artifacts deployed | 14, live 41-44 | discriminator candidate via artifact mechanism over P4 |
| PreconditionEnvironment | configuration files and secrets reachable over HTTP | 15, 53, live 47-50 | discriminator candidate via artifact mechanism over P4 |
| PreconditionEnvironment | API schema or introspection or reflection interface enabled | 16, live 54-56 | discriminator candidate via artifact mechanism over P4 |
| PreconditionEnvironment | client bundles shipped with source maps or embedded env | 17, live 59-62 | discriminator candidate via artifact mechanism over P4 |
| PreconditionEnvironment | observability or admin panels exposed without auth | 20, 45, live 77-80 | discriminator candidate via artifact mechanism over P4 |
| PreconditionEnvironment | cache keyed without identity or tenant headers | 33-35, 72 | discriminator candidate via oracle mechanism over P2 |
| PreconditionEnvironment | same data served across channels with inconsistent hardening | 39-41, 71 | discriminator candidate via oracle mechanism over P2 |
| PreconditionEnvironment | storage buckets, signed URLs, or export endpoints broadly scoped | 19, live 71-74, 92-94 | discriminator candidate via artifact mechanism over P4 |
| TechnologyStack | Django, Laravel, Rails, Flask, ASP.NET, GraphQL, gRPC, CDN, S3, GCS, Azure, Prometheus, Spring Boot, Jaeger, Zipkin, Kibana | 12-21, live 28-94 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | field redaction that holds across differential oracles | 81 | aspect (checked inside oracle and artifact variants) |
| DefensiveControl | auth gating on observability and admin panels | 20, 45, live 77-80 | aspect (gating check inside artifact variant) |
| DefensiveControl | Vary and Cache-Control key correctness | 34-35 | aspect (key state recorded inside oracle variant) |
| DefensiveControl | introspection disabled and reflection closed | 16, live 54-56 | aspect (absence check inside artifact variant) |
| DefensiveControl | referrer policy and CORS expose-header strictness | live 83-85 | aspect (secondary check inside artifact variant) |
| VulnerabilityClass | information disclosure as the parent weakness | 6-8, 95-97 | non-discriminator (the class itself) |
| AttackGoal | credentials and keys, versions to CVE, paths to LFI, schemas to auth bypass, cross-tenant data | 45-48, 52-67 | non-discriminator (shared P5 correlation spine, follows leak kind) |
| AttackerCapability | ability to send arbitrary requests to the target | 8, 71-75 | non-discriminator (shared precondition of all variants) |
| AttackerCapability | sessions as owner versus non-owner versus anonymous for diffing | 26-30, 72 | non-discriminator (role core owned by two-principal-authz, apparatus here) |
| AttackTechnique | trigger controlled failures with malformed input | 73, live 28-33 | discriminator candidate via verbosity mechanism over P3 |
| AttackTechnique | enumerate debug endpoints, profilers, and feature flags | 13, live 35-38 | discriminator candidate via verbosity mechanism over P3 |
| AttackTechnique | enumerate and fetch DVCS, backups, configs, maps, bundles, listings, metadata | 74, live 41-44, 59-62, 87-89 | discriminator candidate via artifact mechanism over P4 |
| AttackTechnique | query introspection and reflection and enumerate hidden operations | 16, live 54-56 | discriminator candidate via artifact mechanism over P4 |
| AttackTechnique | replay HEAD versus GET and conditional requests | 29-30, 72 | discriminator candidate via oracle mechanism over P2 |
| AttackTechnique | probe cache keys with unkeyed input and second-session confirmation | 33-36 | discriminator candidate via oracle mechanism over P2 |
| AttackTechnique | mirror the same object across REST, GraphQL, WebSocket, gRPC, SSR, CSR | 39-41, 71 | discriminator candidate via oracle mechanism over P2 |
| AttackTechnique | review signed-URL scope and lifetime and export scoping | 19, live 71-74, 92-94 | discriminator candidate via artifact mechanism over P4 |
| PayloadPattern | malformed types, boundary values, missing params, alternate content-types | 73 | aspect (trigger values inside verbosity variant) |
| PayloadPattern | template arithmetic probes with seven-times-seven markers | live 31 | aspect (stack-identification probes inside verbosity variant) |
| PayloadPattern | conditional header shapes (If-None-Match, If-Modified-Since, Range) | 28-30, live 68 | aspect (replay shapes inside oracle variant) |
| Artifact | DVCS dumps, config dumps, secrets, maps, bundles, schemas, metrics snapshots | 14-17, 20, 52-54 | discriminator candidate via artifact mechanism over P4 |
| Artifact | exported datasets and signed URLs under test | 19, live 71-74 | discriminator candidate via artifact mechanism over P4 |
| Artifact | per-attempt diff records and normalized digests | 72, live tips 2 | non-discriminator (tester-produced apparatus per attempt) |
| ObservableSignal | stack traces, file paths, SQL fragments, framework versions | 12, live 28-33 | discriminator candidate via verbosity mechanism over P3 |
| ObservableSignal | role diff deltas on status, length, ETag, Last-Modified, Cache-Control | 28, 72 | non-discriminator for role core (owned by two-principal-authz), apparatus here |
| ObservableSignal | HEAD versus GET deltas and 304 versus 200 deltas | 29-30 | discriminator candidate via oracle mechanism over P2 |
| ObservableSignal | second session served poisoned or fragment content | 35-36 | discriminator candidate via oracle mechanism over P2 |
| ObservableSignal | cross-channel field extras for the same object | 39-41 | discriminator candidate via oracle mechanism over P2 |
| ObservableSignal | secret strings and internal hostnames inside dumps and metrics | 52-54, live 77-80 | discriminator candidate via artifact mechanism over P4 |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: error pages, debug tooling, DVCS and backups, configs, schemas, bundles and maps, headers, storage and exports, observability panels, listings at lines 10 through 21.
Invariant is every channel treated as potential intelligence, what varies is which holder emits the leak and how it is elicited.
Adversarial capabilities: arbitrary requests plus owner versus non-owner versus anonymous sessions plus cache second-session confirmation.
Invariant is no privilege beyond chosen requests and held sessions, what varies is which same-principal replay or second session confirms the leak.
Common trust assumptions: verbosity never reaches prod, debug tooling is disabled, artifacts are not deployed, introspection is closed, maps are not shipped, headers carry no secrets, caches key on identity, channels harden equally, exports scope to tenant, signed URLs are short-lived and bound.
Invariant is undisclosed means unreachable, what varies is which holder is trusted with that assumption.
Testing methodology: the five parent steps P1 through P5 at lines 71 through 75 plus the three detection procedures D1 through D3 at lines 25 through 41.
Invariant is the map-to-correlate spine, what varies is which elicitation step bends per candidate procedure.
Proxy techniques: none held as a standalone proxy family by this class, since cache confirmation names its own second-session procedure and the `proxy-techniques` family owns generic relay steps.
Defence bypass techniques: none held as a standalone bypass family by this class, since redaction, gating, Vary, and introspection checks ride as aspects inside their variants and the `defence-bypass` family owns generic bypass steps.
Techniques anti-patterns: none stated in the authority file, while the live skill warns against taking intentional docs and generic errors as findings.
These are invariant warnings.
Scripted tests (references/): none shipped with this skill, since validation is described inline at lines 87 through 93 of the analysed file.
False positives: intentional public docs, generic errors, held redaction, unreachable version banners, owner-only details at lines 77 through 83.
These are invariant exclusion predicates.
Chaining: credential extraction to cloud control, version to CVE, path disclosure to LFI, schema to auth bypass at lines 50 through 67.
Chaining targets are invariant companions, and the auth-bypass step names the authorization skills instead of restating them.

## 4. Runtime parametrisation
Consumed L0/L1 runtime entities are the concrete Service under test, the Endpoint with its Parameter and Header carriers, the BaseURL, the DataItem surfacing at those carriers, the System mechanism overlays for web, API, cache, storage, and observability, and the HTTP history showing requests, responses, headers, and cache signals.
The concrete URLs, file names, header names, version strings, payload literals, bucket names, endpoint identities, and target assets are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, library version, payload literal, protocol version, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent facing an application that may talk too much through errors, artifacts, schemas, headers, caches, channels, or exports, and needing to convert each leak into minimal reversible proof or a concrete architectural risk.
Parent methodology steps with completion conditions: P1 build channel map, complete when Web, API, GraphQL, WebSocket, gRPC, mobile, background jobs, exports, and CDN channels are listed.
P2 establish diff harness, complete when owner versus non-owner versus anonymous responses are normalized on status, body length, ETag, and headers with digests.
P3 trigger controlled failures, complete when malformed types, boundary values, missing params, and alternate content-types have been submitted and verbose output is recorded or ruled out.
P4 enumerate artifacts, complete when DVCS folders, backups, config endpoints, source maps, client bundles, and API docs have been fetched and read or ruled out.
P5 correlate to impact, complete when each leak is mapped to versions-to-CVE, paths-to-LFI, keys-to-cloud, or schemas-to-auth-bypass with a minimal proof or risk statement.
D1 differential oracles at skill lines 25 through 30, complete when owner versus non-owner versus anonymous deltas plus HEAD-versus-GET plus conditional 304-versus-200 replays are recorded.
D2 CDN and cache keys at skill lines 32 through 36, complete when Authorization and tenant keying plus Vary correctness plus 206 fragment behavior are recorded.
D3 cross-channel mirroring at skill lines 38 through 41, complete when the same object is requested across REST, GraphQL, WebSocket, gRPC, SSR, and CSR and per-channel extras are recorded.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Shared request ability and session holding (AttackerCapability) | No | N/A | non-discriminator | Every candidate uses the same supply-then-observe shape with no step changing kind. |
| TechnologyStack and version values (frameworks, GraphQL, gRPC, CDN, buckets, observability products) | No | N/A | non-discriminator | Parent steps perform the same kind of action across stacks and versions are KB facts. |
| Impact goal family (AttackGoal credentials, CVE, LFI, auth bypass, cross-tenant) | No | N/A | non-discriminator | P5 correlates any leak kind with the same mapping action and the goal follows the leak rather than bending a step. |
| Trigger payload literals and template probes (PayloadPattern) | Yes | Yes | aspect | Each verbosity attempt performs the same trigger-and-read action with a swapped literal enumerated inside P3. |
| Conditional header shapes (PayloadPattern) | Yes | Yes | aspect | Each oracle attempt performs the same replay-and-compare action with a swapped header enumerated inside the oracle variant. |
| Per-attempt diff records and digests (Artifact) | No | N/A | non-discriminator | Tester-produced normalization apparatus parametrises runs rather than bending steps. |
| Owner versus non-owner versus anonymous role comparison (AttackerCapability plus ObservableSignal) | Yes | Yes | non-discriminator | P2 describes this comparison accurately and exhaustively, and the principal step is owned by two-principal-authz. |
| Redaction, gating, Vary, introspection-off, referrer and CORS checks (DefensiveControl) | Yes | Yes | aspect | Each variant performs the same elicitation action while noting the control state as a secondary check. |
| Failure-triggered verbosity with debug tooling (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via verbosity mechanism | P3 names malformed-input triggering but never names debug-page and profiler enumeration with evaluation-oracle probes. |
| Stored deployable artifacts with metadata and panels (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via shared artifact mechanism | P4 names static fetching but never names metadata parsing nor auth-gated observability triage as a unified fetch-parse-triage procedure. |
| Live schema and introspection querying (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via shared artifact mechanism | P4 says fetch API docs but never names querying live introspection or reflection to enumerate hidden or privileged operations. |
| Export scoping and signed-URL binding (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via shared artifact mechanism | P4 never names bucket, signed-URL, or export enumeration with scope and lifetime reading from a single fetched response. |
| Method and conditional differential oracles (AttackTechnique plus ObservableSignal) | Yes | No | discriminator via shared oracle mechanism | P2 compares across roles but never names same-principal HEAD-versus-GET or 304-versus-200 replay as a unified same-principal oracle. |
| Cache-key identity behavior (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via shared oracle mechanism | D2 names key and Vary checks but no single parent step names unkeyed-input probing with second-session serving plus fragment reassembly as one oracle. |
| Cross-channel field mirroring (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via shared oracle mechanism | D3 names channel comparison but no single parent step names same-object field comparison across methods, sessions, and channels as one oracle. |

## 7. Step-coverage falsification
Failure-triggered verbosity with debug tooling: parent step P3 says submit malformed types, boundary values, missing params, and alternate content-types and record verbose output.
The uncovered reality is enumerating debug pages, profiler endpoints, and feature flags plus reading evaluation-oracle probes, which needs an enumerate-debug-surfaces procedure that P3 never names.
Stored deployable artifacts with metadata and panels: parent step P4 says fetch DVCS folders, backups, config endpoints, source maps, client bundles, and API docs.
The uncovered reality is parsing file metadata out of downloads and triaging noisy auth-gated observability panels, which needs a unified download-parse plus gating-triage procedure that P4 never names as one procedure.
Live schema and introspection querying: parent step P4 says fetch static API docs.
The uncovered reality is querying the live schema interface with its native shape to enumerate hidden or privileged operations, which needs a query-live-interface procedure that P4 never names.
Export scoping and signed-URL binding: parent step P4 never names buckets, signed URLs, or export endpoints with scope and lifetime reading.
The uncovered reality is enumerating storage and export surfaces and reading scope, audience, lifetime, and foreign-dataset signals from the fetched object, which needs an enumerate-and-read-scope procedure that P4 never names.
Method and conditional differential oracles: parent step P2 says compare owner versus non-owner versus anonymous normalized on status, length, ETag, and headers.
The uncovered reality is swapping HEAD for GET and replaying conditional headers as the same principal to confirm existence or state, which needs a same-principal method-swap plus conditional-replay oracle that P2 never names.
Cache-key identity behavior: parent step P2 normalizes on ETag without manipulating keys and D2 names key and Vary checks without a serving oracle.
The uncovered reality is submitting identity-varying input that leaves the key unchanged and confirming a second session is served foreign content with 206 fragment reassembly, which needs a key-manipulation plus second-session oracle that no single parent step names.
Cross-channel field mirroring: parent step P1 says list the channels and D3 names channel comparison without a unified oracle.
The uncovered reality is requesting the same object over REST, GraphQL, WebSocket, and gRPC plus SSR versus CSR and recording per-channel field extras, which needs a mirror-and-diff-fields oracle that no single parent step names.
D1 already names HEAD-versus-GET and conditional replay for one slice, D2 already names cache keys and Vary and 206 fragments for one slice, and D3 already names cross-channel comparison for one slice.
The uncovered reality for the merged oracle is that no single parent step among P2, D1, D2, and D3 covers same-principal method plus conditional plus second-session plus cross-channel comparison as one compare-two-responses procedure.
Trigger literals and template probes: no falsification holds because P3-style triggering enumerates every malformed and evaluation value as a parameter.
Conditional header shapes: no falsification holds because the oracle variant enumerates every replay header inside one oracle.
Defensive-control states: no falsification holds because each variant records redaction, gating, Vary, introspection-off, and policy states as secondary checks.
Role comparison: no falsification holds because P2 covers it and the principal step belongs to two-principal-authz.

## 8. Hypotheses
H1 (single-feature, seven elicitation slices): if the class is partitioned by elicitation slice into failure verbosity, stored artifacts, live schema querying, method and conditional oracles, cache-key behavior, cross-channel mirroring, and export scoping, then each partition owns a distinct first non-coverable step and jointly covers all falsifications above.
This hypothesis is falsified if any two partitions share one compare-two-responses or one fetch-and-read mechanism with no mutually exclusive completion predicate.
H2 (combined-feature, mechanism crossed with defensive control defeated): if each H1 partition is further split by redaction defeated versus auth gating defeated versus Vary correctness defeated versus introspection left open, then each cell adds its own non-coverable defeat step.
This hypothesis is falsified if the defeat check is the same elicitation action across cells with control state recorded as a secondary check, leaving cells with no divergence delta.
H3 (combined-feature, mechanism crossed with technology stack): if each H1 partition is further split by web framework versus API paradigm versus object storage vendor versus observability product, then each stack cell adds its own non-coverable step.
This hypothesis is falsified if the stack swap leaves the elicitation procedure unchanged and only swaps runtime parameters, violating stability.
H4 (single-feature, three elicitation-observation mechanisms): if the class is partitioned by mechanism into failure verbosity versus single-response artifact fetch-and-read versus two-response differential comparison, then each partition owns exactly one bent parent step and jointly covers all falsifications with disjoint completion predicates.
This hypothesis is falsified if any genuine non-coverable step falls outside verbosity, artifact, and oracle or if one cached cross-channel HEAD response satisfies two completion predicates at once.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | error-verbosity-disclosure | Enumerate debug and profiler surfaces and read evaluation-oracle probes beyond malformed-input triggering. |
| H1 | stored-artifact-disclosure | Parse file metadata from downloads and triage auth-gated observability panels beyond static artifact fetching. |
| H1 | schema-introspection-disclosure | Query live introspection and reflection interfaces to enumerate hidden or privileged operations beyond fetching API docs. |
| H1 | differential-oracle-disclosure | Replay HEAD-versus-GET and conditional requests on the same resource to confirm existence or state beyond role comparison. |
| H1 | cache-mediated-disclosure | Manipulate cache keys with identity-varying input and confirm second-session serving with fragment reassembly. |
| H1 | cross-channel-disclosure | Mirror the same object across channels and record per-channel field extras with hardening deltas. |
| H1 | export-storage-disclosure | Verify signed-URL scope, binding, and lifetime and check export endpoints for foreign datasets. |
| H2 | H1 seven plus per-control cells (redaction versus gating versus Vary versus introspection-off) | Same seven first steps, since cells add only a secondary control-state check with no new non-coverable step. |
| H3 | H1 seven plus per-stack cells (framework, API paradigm, storage vendor, observability product) | Same seven first steps, since cells add only stack parameter swaps with no new non-coverable step. |
| H4 | error-verbosity-disclosure | Enumerate debug and profiler surfaces and read evaluation-oracle probes over P3 beyond malformed-input triggering. |
| H4 | stored-artifact-disclosure | Execute unified fetch-parse-triage over P4 covering deployables, live schema interfaces, and storage and export surfaces in one single-response procedure. |
| H4 | differential-oracle-disclosure | Execute unified same-principal compare-two-responses over P2 covering method and conditional replay, second-session cache serving, and cross-channel field deltas in one two-response procedure. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage pass because every falsified slice belongs to at least one variant with a named oracle.
H1 scores disjointness fail because one cached cross-channel HEAD response satisfies differential completion plus cache completion plus mirror completion at once.
H1 scores divergence delta fail because cache confirmation reuses P2 comparison apparatus with only key input swapped and export scoping reuses artifact fetching plus differential comparison without its own elicitation kind.
H1 scores stability fail because GraphQL introspection query shape does not survive a swap to gRPC reflection shape as a standalone variant.
H1 scores parsimony fail because stored plus schema plus export share fetch-and-read while differential plus cache plus mirror share compare-two-responses.
H2 fails divergence delta and parsimony because control cells repeat secondary checks with no new step and multiply the set size, so H2 is discarded per STATE 4 branch 4a.
H3 fails stability and parsimony because stack cells swap runtime parameters only and multiply variants by technology, so H3 is discarded per STATE 4 branch 4a.
H4 scores coverage pass because verbosity covers P3 falsification, artifact covers stored plus schema plus export falsifications, and oracle covers method plus cache plus mirror falsifications.
H4 scores disjointness pass because verbosity completes on single-response triggered output, artifact completes on single-response fetched content, and oracle completes only when neither response alone suffices and the delta concludes.
H4 scores divergence delta pass because each variant adds the unified non-coverable step named in section 9 over its single bent parent step.
H4 scores stability pass because swapping framework, API paradigm, storage vendor, payload literal, or runtime asset leaves each unified procedure intact with stack shapes as aspects.
H4 scores parsimony pass with one collapsed mechanism feature and three variants.
STATE 6 branch 6a triggers on H1 because the winner candidate H1 fails disjointness plus delta plus stability plus parsimony as named above.
Return to STATE 3 collapses co-varying differential, cache, and mirror values into one oracle mechanism feature and co-varying stored, schema, and export values into one artifact mechanism feature.
Winner after rerun is H4 with losing reason for H1 being overlapping oracle completions plus zero-delta cache and export plus unstable schema plus seven-way over-split.
STATE 1 completed with five parent steps P1 through P5 plus three detection procedures D1 through D3 and a full entity inventory and no malformed-class outlier.
STATE 2 completed with three mechanism discriminators, six aspects, and eight non-discriminators recorded.
STATE 3 branch 3a collapsed co-varying precondition, technique, artifact, and signal values into verbosity, artifact, and oracle mechanism features.
STATE 3 branch 3b kept payload literals, version strings, header names, and control states as aspects inside variants.

## 11. Recommended set
Discrimination function in one sentence: Information disclosure decomposes by the elicitation-observation mechanism that produces and reads the leak, namely failure verbosity versus single-response artifact fetch-and-read versus two-response differential comparison.
Recommended variant error-verbosity-disclosure diverges by enumerating debug and profiler surfaces and reading evaluation-oracle probes over parent step P3, which never names debug enumeration or evaluation oracles.
Recommended variant stored-artifact-disclosure diverges by executing unified fetch-parse-triage over deployables, live schema interfaces, and storage and export surfaces over parent step P4, which describes only fetching static artifacts and API docs.
Recommended variant differential-oracle-disclosure diverges by executing unified same-principal compare-two-responses over method replay, cache second-session serving, and cross-channel field deltas over parent step P2, which describes only cross-role comparison and never names the unified same-principal oracle.
Non-discriminators are shared request ability and session holding with the role core owned by two-principal-authz, technology stack with versions as excluded runtime axis, trigger literals and replay header shapes as per-variant aspects, per-attempt diff records as tester apparatus, defensive-control states as secondary checks, and the impact goal family as the shared P5 correlation spine.
Open questions: none at pass level, since the three-variant set leaves no uncovered falsification and no skipped state.
Grey points: referrer leakage observation rides inside stored-artifact-disclosure as a secondary check, which holds only while outbound-receiver setup stays trivial apparatus rather than its own elicitation procedure.
Grey points: tracing-header and Server-Timing reads ride inside error-verbosity-disclosure, which holds only while header reads stay trigger-adjacent rather than a standalone metadata channel.
Grey points: GraphQL-specific introspection steps name the graphql skill instead of restating it, which holds only while the disclosure procedure stays channel-agnostic.
