# weak-credential-discovery - variant decomposition analysis

## 1. Class and scope
Source file for this analysis is `skills-unspurious/weak-credential-discovery/SKILL.md`, with extra methodology consulted non-authoritatively from `skills/weak-credential-discovery/SKILL.md`.
Weak credential discovery here is any procedure that converts an exposed secret, a vendor default, an identity oracle, or an issued token into authentication without breaking cryptography or authorization logic.
Scope covers client-source secret extraction from HTML and JavaScript, default credential replay against login endpoints, username enumeration through differential oracles, exposed config and API artifact fetching over guessable paths, and post-authentication session token and cookie decoding.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | secret embedded in served client source (comments, hidden fields, inline JS, config objects) | 10-18 | discriminator candidate via exposed-secret mechanism over P1 |
| PreconditionEnvironment | credential-bearing config or VCS or debug artifact deployed at guessable path | 90-99 | discriminator candidate via exposed-secret mechanism over P4 |
| PreconditionEnvironment | login endpoint accepts vendor or framework default credential | 40-52 | discriminator candidate via replay mechanism over P2 |
| PreconditionEnvironment | login endpoint emits per-identity differential oracle (message, timing, status, redirect) | 68-76 | discriminator candidate via oracle mechanism over P3 |
| PreconditionEnvironment | authenticated session issues client-readable token or cookie or storage value | 110-117 | discriminator candidate via decode mechanism over P5 |
| TechnologyStack | admin panels, Flask, Django, WordPress, phpMyAdmin, Jenkins, Grafana, Kibana, Flask sessions, JWT, localStorage | 42-51, 112-116 | non-discriminator (runtime stack, excluded axis) |
| DefensiveControl | none named in the authority file | none | non-discriminator (absent control family) |
| DefensiveControl | implied uniform errors, lockout, secret hygiene, token signing | 70-76, 129-136 | aspect (absence or negation checked inside variants) |
| VulnerabilityClass | weak credential exposure as the parent weakness | 6-8 | non-discriminator (the class itself) |
| AttackGoal | obtain immediate authentication or a reusable credential | 8, 63-66 | non-discriminator (shared across all variants) |
| AttackerCapability | ability to send arbitrary unauthenticated requests | 18-38, 54-66, 76-87, 99-108 | non-discriminator (shared precondition of all variants) |
| AttackerCapability | holding an authenticated session for post-auth decoding | 110-125 | aspect (gating apparatus inside the decode variant, produced by earlier success) |
| AttackTechnique | fetch rendered pages and scripts and pattern-match for secret shapes | 18-38 | discriminator candidate via exposed-secret mechanism over P1 |
| AttackTechnique | guess well-known config paths and size-filter responses | 99-108 | discriminator candidate via exposed-secret mechanism over P4 |
| AttackTechnique | replay default username and password pairs and read success signals | 54-66 | discriminator candidate via replay mechanism over P2 |
| AttackTechnique | submit fixed wrong password across candidate usernames and compare responses | 76-87 | discriminator candidate via oracle mechanism over P3 |
| AttackTechnique | decode session cookie or token and interpret identity claims | 117-125 | discriminator candidate via decode mechanism over P5 |
| PayloadPattern | secret regex shapes, base64 shapes, default pairs, candidate usernames, path wordlist | 26, 28, 57-61, 81, 101-104 | aspect (enumerated literals inside variants) |
| Artifact | exposed comment, hidden field, JS secret, config dump, env dump, VCS file, debug page | 12-16, 91-99 | discriminator candidate via exposed-secret mechanism |
| Artifact | authenticated session cookie, token, storage value, decoded claim set | 112-117 | discriminator candidate via decode mechanism over P5 |
| Artifact | per-attempt response records with status, length, time, and match flags | 85-86 | non-discriminator (tester-produced apparatus per attempt) |
| ObservableSignal | secret-pattern match in fetched source | 24-28 | discriminator candidate via exposed-secret mechanism over P1 |
| ObservableSignal | dashboard URL or logout marker or 302 after replay | 63-65 | discriminator candidate via replay mechanism over P2 |
| ObservableSignal | message or timing or status or redirect delta across identities | 70-76, 85 | discriminator candidate via oracle mechanism over P3 |
| ObservableSignal | 200 plus body-size threshold on guessed path | 104-107 | discriminator candidate via exposed-secret mechanism over P4 |
| ObservableSignal | decoded user identifier or role value from token or cookie | 117-125 | discriminator candidate via decode mechanism over P5 |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: rendered pages, linked scripts, login endpoints, guessable config and VCS and debug paths, and issued session artifacts at lines 10 through 108.
Invariant is every credential holder is treated as fetchable or submittable over HTTP, what varies is whether the holder is linked source, guessed path, login acceptor, oracle emitter, or issued token.
Adversarial capabilities: arbitrary unauthenticated requests for four procedures plus a held authenticated session for the decode procedure.
Invariant is no privilege beyond chosen requests and held sessions, what varies is which same-principal comparison or held session gates the decode step.
Common trust assumptions: served source carries no secrets, deployables carry no reachable configs, defaults are changed, login responses are uniform, and issued tokens disclose no authority.
Invariant is unexposed means unusable, what varies is which holder is trusted with that assumption.
Testing methodology: the five parent steps P1 through P5 defined in section 5 below from lines 10 through 125.
Invariant is the obtain-then-confirm spine, what varies is which obtain-and-confirm step bends per candidate procedure.
Proxy techniques: none held as a standalone proxy family by this class, since fetching and replaying use direct requests and the future proxy-techniques family owns generic relay steps.
Defence bypass techniques: none held as a standalone bypass family by this class, since lockout and uniformity and signing checks ride as aspects inside their variants and the future defence-bypass family owns generic bypass steps.
Techniques anti-patterns: none stated in the authority file, while the live skill warns implicitly to test defaults before expensive vectors and to decode every session.
These are invariant ordering warnings.
Scripted tests (references/): none shipped with this skill, since validation is described inline as executable patterns at lines 18 through 125.
False positives: intentional example credentials in docs, unreachable version banners, owner-only details without reuse, and generic errors mistaken for oracles.
These are invariant exclusion predicates.
Chaining: decoded role or identifier feeds authorization testing, enumerated usernames feed replay, and exposed secrets feed authenticated follow-on testing.
Chaining targets are invariant companions, and the token-validation step names authentication-jwt instead of restating it.

## 4. Runtime parametrisation
Consumed L0/L1 runtime entities are the concrete Service under test, the Endpoint with its Parameter and Header carriers, the BaseURL, the DataItem surfacing at those carriers, the System mechanism overlays for web presentation and authentication, and the HTTP history showing requests, responses, headers, timing, and session state.
The concrete URLs, script paths, file names, header names, username literals, password literals, regex literals, path literals, claim names, endpoint identities, and target assets are runtime facts from the attack-surface graph, the knowledge base, and the HTTP history.
These parametrise whichever variant runs and never define a variant.
Technology stack, library version, payload literal, wordlist size, protocol version, and target asset identity are excluded axes under STATE 6 stability.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent facing an application that may have left a secret in served source, left a config reachable, left a default active, left login responses distinguishable, or issued a readable token, and needing to convert the first confirmed holder into authentication with minimal noise.
Parent methodology steps with completion conditions: P1 extract secrets from client source, complete when rendered pages and linked scripts are fetched and secret-pattern matches are recorded or ruled out.
P2 replay default credentials, complete when vendor and framework pairs are submitted to the login endpoint and dashboard or logout or 302 success is recorded or ruled out.
P3 enumerate usernames through differential oracle, complete when a fixed wrong password is submitted across candidate usernames and message or timing or status or redirect deltas are recorded or ruled out.
P4 fetch exposed config and API artifacts, complete when well-known paths are requested and 200 plus body-size holders are recorded or ruled out.
P5 decode session token and cookie authority, complete when the issued cookie or token or storage value is decoded and identity or role claims are recorded or ruled out.

## 6. Feature-verdict table
| Candidate feature (entity value) | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Shared anonymous request ability (AttackerCapability) | No | N/A | non-discriminator | Every candidate uses the same supply-then-observe shape with no step changing kind. |
| Authenticated session holding (AttackerCapability) | Yes | Yes | aspect | P5 describes decoding under a held session accurately and exhaustively as gating apparatus. |
| TechnologyStack and version values (frameworks, panels, Flask, JWT) | No | N/A | non-discriminator | Parent steps perform the same kind of action across stacks and versions are KB facts. |
| Shared authentication goal (AttackGoal) | No | N/A | non-discriminator | Every candidate ends in the same obtain-and-confirm shape and the goal follows the holder. |
| Payload literals and wordlists (PayloadPattern) | Yes | Yes | aspect | Each attempt performs the same fetch-or-submit action with a swapped literal enumerated inside its variant. |
| Per-attempt response records (Artifact) | No | N/A | non-discriminator | Tester-produced normalization apparatus parametrises runs rather than bending steps. |
| Named defensive controls and their absence (DefensiveControl) | Yes | Yes | aspect | Each variant performs the same elicitation action while noting uniformity or lockout or signing as a secondary check. |
| Client-source secret extraction (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via shared exposed-secret mechanism | Generic fetch-and-read names pattern matching but never names linked-page plus script-harvest plus shape-match as distinct from path guessing. |
| Guessed-path config artifact fetching (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via shared exposed-secret mechanism | Generic fetch-and-read names path probing but never names unlinked-guess plus size-filter plus holder-parse as distinct from linked-source matching. |
| Default credential replay (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via replay mechanism | No fetch-or-compare step names submitting guessable pairs and reading authentication-success signals as one replay procedure. |
| Username differential oracle (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via oracle mechanism | P3-adjacent comparison is never covered by any single-response fetch step and needs a same-secret compare-two-responses oracle. |
| Session token and cookie decoding (PreconditionEnvironment plus AttackTechnique) | Yes | No | discriminator via decode mechanism | No unauthenticated fetch-or-submit step names base64-split plus decode plus claim-interpretation under a held session. |

## 7. Step-coverage falsification
Client-source secret extraction: parent step P1 says fetch rendered pages and linked scripts and pattern-match for secret shapes.
The uncovered reality for the merged exposed-secret variant is that no single parent step among P1 and P4 covers linked-source harvesting plus unlinked path guessing plus holder parsing as one fetch-and-read procedure.
Guessed-path config artifact fetching: parent step P4 says request well-known paths and record 200 plus body-size holders.
The uncovered reality is parsing env versus JSON versus VCS versus debug output from one fetched body with holder-specific reading, which needs a unified fetch-parse-triage procedure that P4 never names as one procedure.
Default credential replay: parent step P2 says submit default pairs and read dashboard or logout or 302 success.
The uncovered reality is that no fetch-and-read step and no differential-oracle step performs credential submission with authentication-success reading, which needs a submit-and-read-success procedure that only P2 names.
Username differential oracle: parent step P3 says submit a fixed wrong password across usernames and compare message or timing or status or redirect deltas.
The uncovered reality is that no single-response fetch step covers same-secret two-response comparison with timing normalization, which needs a compare-two-responses oracle that only P3 names.
Session token and cookie decoding: parent step P5 says decode the issued cookie or token and interpret identity or role claims.
The uncovered reality is that no unauthenticated step covers session-gated splitting plus padding plus base64 decode plus claim interpretation, which needs a split-decode-interpret procedure that only P5 names.
Payload literals and wordlists: no falsification holds because each variant enumerates every regex shape, pair, username, and path inside one procedure as a parameter.
Per-attempt records: no falsification holds because recording status plus length plus time plus match flags is tester apparatus that parametrises every attempt.
Defensive-control states: no falsification holds because each variant records uniformity, lockout, hygiene, and signing states as secondary checks.
Shared goal and anonymous ability: no falsification holds because obtain-and-confirm plus arbitrary requests describe every variant without bending a step.

## 8. Hypotheses
H1 (single-feature, five holder slices): if the class is partitioned by holder into client source versus guessed config path versus default acceptor versus identity oracle versus issued token, then each partition owns a distinct first non-coverable step and jointly covers all falsifications above.
This hypothesis is falsified if any two partitions share one fetch-and-read mechanism with no mutually exclusive completion predicate.
H2 (combined-feature, mechanism crossed with technology stack): if each H1 partition is further split by web framework versus admin product versus token format, then each stack cell adds its own non-coverable step.
This hypothesis is falsified if the stack swap leaves the elicitation procedure unchanged and only swaps runtime parameters, violating stability.
H3 (combined-feature, mechanism crossed with defensive control defeated): if each H1 partition is further split by uniformity defeated versus lockout absent versus hygiene absent versus signing absent, then each cell adds its own non-coverable defeat step.
This hypothesis is falsified if the defeat check is the same elicitation action across cells with control state recorded as a secondary check, leaving cells with no divergence delta.
H4 (single-feature, four credential-lifecycle mechanisms): if the class is partitioned by mechanism into single-response exposed-secret fetch-and-read versus credential-replay submit-and-read-success versus two-response identity compare versus session-gated split-decode-interpret, then each partition owns exactly one bent step family and jointly covers all falsifications with disjoint completion predicates.
This hypothesis is falsified if any genuine non-coverable step falls outside exposed-secret, replay, oracle, and decode or if one fetched config body satisfies two completion predicates at once.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step |
|---|---|---|
| H1 | client-source-secret-extraction | Harvest linked pages and scripts and shape-match secrets beyond generic fetching. |
| H1 | exposed-config-artifact-fetch | Guess unlinked paths and size-filter plus parse holders beyond linked-source matching. |
| H1 | default-credential-replay | Submit guessable pairs and read authentication-success signals beyond fetch-and-read. |
| H1 | username-enumeration-oracle | Compare two responses under one fixed secret with timing normalization beyond single-response reading. |
| H1 | session-token-authority-decode | Split plus decode plus interpret issued claims under a held session beyond unauthenticated steps. |
| H2 | H1 five plus per-stack cells (framework, admin product, token format) | Same five first steps, since cells add only stack parameter swaps with no new non-coverable step. |
| H3 | H1 five plus per-control cells (uniformity, lockout, hygiene, signing) | Same five first steps, since cells add only a secondary control-state check with no new non-coverable step. |
| H4 | exposed-secret-extraction | Execute unified fetch-parse-triage over linked source plus guessed config paths in one single-response procedure. |
| H4 | default-credential-replay | Submit guessable pairs to the login acceptor and read authentication-success signals in one replay procedure. |
| H4 | username-enumeration-oracle | Execute same-secret compare-two-responses with timing normalization in one two-response procedure. |
| H4 | session-token-authority-decode | Execute session-gated split-decode-interpret over cookies plus tokens plus storage values in one decode procedure. |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage pass because every falsified holder belongs to at least one variant with a named step.
H1 scores disjointness fail because one fetched JavaScript bundle that embeds a config endpoint satisfies client-source completion plus config-fetch completion at once.
H1 scores divergence delta pass because each of the five adds its named non-coverable step over the generic spine.
H1 scores stability pass because swapping comment versus script versus env versus token format leaves each procedure intact as parameters.
H1 scores parsimony fail because linked-source matching plus guessed-path fetching share single-response fetch-parse-triage while differing only in holder enumeration.
H2 fails divergence delta and parsimony because stack cells repeat parameter swaps with no new step and multiply the set size, so H2 is discarded per STATE 4 branch 4a.
H3 fails divergence delta and parsimony because control cells repeat secondary checks with no new step and multiply the set size, so H3 is discarded per STATE 4 branch 4a.
H4 scores coverage pass because exposed-secret covers P1 plus P4 falsifications, replay covers P2, oracle covers P3, and decode covers P5.
H4 scores disjointness pass because exposed-secret completes on a reusable secret without authentication, replay completes only on an authentication-success signal after submission, oracle completes only when neither response alone suffices and the delta concludes, and decode completes only under a held session with interpreted claims.
H4 scores divergence delta pass because each variant adds the unified non-coverable step named in section 9 over its bent parent steps.
H4 scores stability pass because swapping framework, admin product, token format, payload literal, or runtime asset leaves each unified procedure intact with holder shapes as aspects.
H4 scores parsimony pass with one collapsed mechanism feature and four variants.
STATE 6 branch 6a triggers on H1 because the candidate winner H1 fails disjointness plus parsimony as named above.
Return to STATE 3 collapses co-varying client-source and guessed-path values into one exposed-secret mechanism feature per branch 3a.
Winner after rerun is H4 with losing reason for H1 being overlapping fetch completions plus five-way over-split on one shared fetch-and-read mechanism.
STATE 1 completed with five parent steps P1 through P5 plus a full entity inventory and no malformed-class outlier.
STATE 2 completed with four mechanism discriminators, four aspects, and six non-discriminators recorded.
STATE 3 branch 3a collapsed co-varying precondition, technique, artifact, and signal values for linked source and guessed paths into one exposed-secret feature.
STATE 3 branch 3b kept payload literals, wordlist entries, version strings, path names, and control states as aspects inside variants.

## 11. Recommended set
Discrimination function in one sentence: Weak credential discovery decomposes by the credential-lifecycle mechanism that yields authentication, namely single-response exposed-secret fetch-and-read versus credential-replay submit-and-read-success versus two-response identity comparison versus session-gated split-decode-interpret.
Recommended variant exposed-secret-extraction diverges by executing unified fetch-parse-triage over linked pages plus scripts plus guessed config paths over parent steps P1 and P4, which never name linked harvesting and unlinked guessing plus holder parsing as one procedure.
Recommended variant default-credential-replay diverges by submitting guessable pairs and reading dashboard or logout or 302 success over parent step P2, which no fetch-and-read or oracle step covers.
Recommended variant username-enumeration-oracle diverges by executing same-secret compare-two-responses with timing normalization over parent step P3, which no single-response step covers.
Recommended variant session-token-authority-decode diverges by executing session-gated split-decode-interpret over cookies plus tokens plus storage values over parent step P5, which no unauthenticated step covers.
Non-discriminators are shared anonymous request ability, technology stack with versions as excluded runtime axis, shared authentication goal as the obtain-and-confirm spine, per-attempt response records as tester apparatus, the parent weakness class itself, and absent control families with uniformity and lockout and hygiene and signing as secondary checks.
Open questions: none at pass level, since the four-variant set leaves no uncovered falsification and no skipped state.
Grey points: JWT claim-validation steps name authentication-jwt instead of restating it, which holds only while the decode procedure stays at base64 split plus claim reading rather than signature bypass.
Grey points: GraphQL and REST config-endpoint shapes ride inside exposed-secret-extraction as holder aspects, which holds only while live schema querying stays a static fetch rather than its own interrogation procedure.
Grey points: rate-limit and lockout evasion rides inside replay and oracle variants as a secondary check, which holds only while throttle handling stays timing politeness rather than its own bypass procedure.
Grey points: post-authentication token analysis arguably overlaps the authentication-jwt class boundary, which is resolved here by keeping claim reading for authority discovery while validation bypass belongs to authentication-jwt.
