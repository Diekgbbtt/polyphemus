# graphql - variant decomposition analysis

## 1. Class and scope
The graphql class is a protocol and attack-surface aggregator rather than a single weakness class.
Its authority is `skills-unspurious/graphql/SKILL.md` (168 lines), consulted against `skills/graphql/SKILL.md` only for extra methodology detail.
The class bundles insecure defaults and schema disclosure, resolver-argument injection, cost-based denial of service, broken authorization over queries and mutations, batching-enabled brute force, request-variant transport, and verbose error disclosure into one testing order.
The analysis finds that this bundle does not decompose on its own characteristics and therefore recommends one skill (STATE 2 branch 2a outlier, reported honestly).

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | GraphQL endpoint reachable at a JSON POST path; introspection enabled or disabled; GraphiQL or Playground or Altair exposed; field-suggestion errors enabled; resolvers accepting string or id arguments; unbounded depth or amount or alias cost; JSON-array or alias batching accepted; cookie-auth GET mutations enabled | 20, 34-42, 46, 64-90, 129-140, 144-151 | Non-discriminator (every value is covered by its own named parent step, see section 6) |
| TechnologyStack | GraphQL engine (Apollo-style batching and Relay node semantics named); JSON POST versus form versus application/graphql versus GET transport; backend resolver sinks SQL, NoSQL, OS, LDAP, XML, HTTP | 10-18, 46, 58, 110, 129-151 | Non-discriminator (excluded axis per SPEC pitfalls and stability criterion) |
| DefensiveControl | Introspection disabled; depth or amount or cost or rate limits; per-object and per-field authorization checks; Web Application Firewall; parameterized resolver inputs; sanitized error responses | 40, 62, 90, 114-123, 149, 162-168 | Non-discriminator (each control maps to detection inside its own step, never bends a step into a new kind of action) |
| VulnerabilityClass | Information disclosure via introspection and errors; injection families via resolver args; denial of service via cost; BOLA or IDOR and BFLA via queries and mutations; brute force via batching; CSRF via cookie-auth GET | 30-140 | Non-discriminator (this aggregate is the class definition itself, not a value that bends a step) |
| AttackGoal | Disclose schema and sensitive fields; read foreign objects; invoke admin mutations; inject backend interpreters; exhaust server resources; brute-force login or OTP material | 44, 60, 90, 106-121, 140 | Non-discriminator (goal is invariant across candidate splits) |
| AttackerCapability | Anonymous baseline; authenticated low-privilege session or token; cookie reuse across JSON POST and GET; ability to send batched or aliased operations | 22-28, 94-96, 144-151 | Non-discriminator (capability ladder is shared setup, principal handling owned with `two-principal-authz`) |
| AttackTechnique | Typename and schema confirmation probes; introspection query; GraphiQL path fetch; field brute force with suggestion harvesting; unknown-field versus unauthorized-field differential; string-arg injection probes; depth nesting and amount inflation and alias fan-out probes; owned-versus-foreign alias comparison; node or nodes relay traversal; sensitive-field and admin-mutation replay; JSON-array and alias batching; transport switching across content types and GET and variables and fragments | 20, 34-42, 46-58, 66-89, 96-121, 129-151 | Non-discriminator in aggregate (each technique is already the body of its own parent step, so no technique bends a step from outside) |
| PayloadPattern | Introspection query document; `{__typename}` confirmation document; cyclic depth-nesting document; `first: 9999` amount document; alias fan-out document; JSON batch array envelope; injection strings placed inside resolver args; fragment and comment evasion wrappers | 20, 34-36, 48-58, 66-89, 129-149 | Non-discriminator (each pattern is the documented instrument of its own step, and swapping one pattern for another never changes the kind of action) |
| Artifact | Enumerated Query and Mutation field map; obtained schema; leaked field suggestions; stack-trace or SQL error text; foreign apiKey or token or PII; Set-Cookie or returned token; before-and-after response pair | 36, 40-44, 106-108, 152-160, 166-171 | Non-discriminator (runtime-produced evidence that parametrises proof) |
| ObservableSignal | `data` versus `errors` JSON body; `Did you mean` suggestion text; unknown-field versus unauthorized-field error difference; extra rows or time delay or fetched internal body; latency or size explosion; foreign secrets in `data`; whole-endpoint 401 versus field-level denial | 20, 28, 40-42, 60, 90, 106-108, 153-168 | Non-discriminator (detection signals are read the same way by every candidate split) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: the GraphQL endpoint, its Query and Mutation fields, its resolver arguments, and its GraphiQL consoles are the surface (lines 10-28, 144-157).
This notion is invariant as a transport description because every candidate procedure starts from the same confirmed endpoint and field map.
Adversarial capabilities: anonymous probing followed by low-privilege authenticated testing with cookie or token reuse is the capability ladder (lines 22-28, 94-96).
This notion is invariant setup and delegates principal handling to `two-principal-authz`.
Common trust assumptions: possession of an id is authorization, introspection exposure is harmless, resolver args are safe, and HTTP-layer rate limits cover batched operations are the assumptions under test (lines 32-44, 92-96, 127-140).
This notion varies only across aggregated weakness families, and each family is owned by its own weakness skill rather than by a graphql-internal split.
Testing methodology: the eight testing-order steps S1 to S8 (lines 151-160) are the step-test substrate.
This notion is invariant as parent text and each step already names its own fallback values.
Proxy techniques: alternate transport forms and SSRF-reached internal targets via URL-like args are reached here (lines 58, 144-151).
This notion invokes the `proxy-techniques` family and `ssrf` at the reached step instead of restating them.
Defence bypass techniques: fragment and comment WAF evasion plus alias-based rate-limit bypass are the bypasses named (lines 127-149).
This notion is an aspect inside the batching and injection steps because the parent text already covers both values.
Techniques anti-patterns: treating whole-endpoint 401 as absence of GraphQL and treating public hello fields as findings are the named anti-patterns (lines 28, 162-168).
This notion is invariant across all candidates.
Scripted tests (`references/`): none are shipped with the class skill.
No invariant is stated beyond the inline GraphQL documents.
False positives: nonexistent fields, whole-endpoint 401, public health fields, enforced empty foreign reads, and expected-disabled introspection are the named non-findings (lines 162-168).
This notion is invariant across all candidates.
Chaining: batching multiplies IDOR enumeration and OTP brute force, and error text feeds injection targeting (lines 44, 60, 140).
This notion is invariant plumbing between steps rather than a split axis.

## 4. Runtime parametrisation
Each procedure consumes the concrete Service under test and the GraphQL System mechanism it lies on.
It consumes the Endpoint path, the BaseURL, the Header set including cookies, the Parameter atoms where the logical DataItem surfaces as resolver arguments, and the operation name with its GraphQL document.
The HTTP history supplies the prior `data` versus `errors` transcripts, the authorized-versus-unauthorized response pairs, and the latency and size baselines that cost probes compare against.
The operator knowledge base supplies the test credentials, the role roster, and the schema notes from prior enumeration.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is a deployed application where the agent suspects a `/graphql`-style path and holds anonymous access plus low-privilege test credentials.
S1 Confirm GraphQL: send `{__typename}` as JSON POST and accept `data`, `errors`, or path-scoped 401 as confirmation, with completion when the endpoint is confirmed or ruled out.
S2 Map the schema: run the introspection query, fetch GraphiQL consoles, and fall back to field brute force with suggestion harvesting, with completion when Query and Mutation fields are enumerated or proven undiscoverable.
S3 Authenticate and re-enumerate: log in through the login mutation and repeat S2, with completion when the post-login schema delta is recorded.
S4 Test query authorization: request owned versus foreign ids in one aliased operation including `node` traversal and sensitive fields, with completion when each id-taking Query shows an enforcement decision.
S5 Test mutation authorization: invoke admin, update, and delete mutations unauthenticated, low-priv, and cross-user, with completion when each Mutation shows an enforcement decision.
S6 Test resolver injection: place interpreter payloads in string args of the mapped fields, with completion when each string arg shows parameterized failure or true injection, a step owned jointly with `sql-injection`, `ssrf`, and `rce`.
S7 Test cost and batching: send modest depth, amount, and alias probes plus JSON-array or alias batching on login or OTP operations, with completion when missing limits are proven or enforcement is observed.
S8 Record error disclosure: capture stack-trace, path, and SQL text in `errors`, with completion when each error-bearing response is judged disclosure or benign.
S4 and S5 principal-comparison procedure is owned by the cross-cutting `two-principal-authz` methodology and the BFLA split analysis, and S6 sink interpretation is owned by the sink skills, so this class references those skills instead of restating them.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Introspection enabled versus disabled (with GraphiQL and suggestion fallback) | No (enabled and disabled paths are the same kind of action: schema discovery through S2) | Yes (S2 text names introspection, consoles, brute force, suggestions, and the unknown-versus-unauthorized differential) | Non-discriminator | Lines 34-42 versus S2 at lines 152-157 |
| Depth versus amount versus alias cost shape | No (all three are the same kind of action: send a costly query and check for missing limits through S7) | Yes (S7 text names depth, amount, and alias amplification with example documents) | Non-discriminator | Lines 64-90 versus S7 at line 159 |
| JSON-array versus alias batching envelope | No (both are the same kind of action: multiply resolver or auth attempts past HTTP-layer limits through S7) | Yes (section 5 text names both forms with examples) | Non-discriminator | Lines 127-140 versus S7 at line 159 |
| Query IDOR versus mutation BFLA versus injection versus DoS (weakness-family split) | Yes (each performs a different kind of action) | Not applicable as a graphql-internal axis (each is already a distinct parent step S4, S5, S6, S7, and each step's sink or principal logic is owned by its own weakness skill) | Non-discriminator for this class (aggregation, not discrimination) | Lines 44-140 versus S4-S7 at lines 156-159; SPEC section 7 cross-references apply |
| Transport form (JSON POST versus form versus application/graphql versus GET versus variables versus inline) | No (switching envelopes is the same kind of action: reach the resolver through S1 transport fallback) | Yes (Request-variants text enumerates every form) | Aspect inside S1, not a variant axis | Lines 144-151 |
| Fragment and comment WAF evasion wrappers | No (wrapping is the same kind of action as the underlying probe) | Yes (covered inside the batching and injection steps once applied) | Aspect, not a variant axis | Line 149 per STATE 3 branch 3b |
| Relay `node` versus direct `user(id:)` object access | No for this class (both are the same kind of action at GraphQL scope: alternate-path object reach, and the authorization split is owned by the BFLA alternate-path variant) | Yes as a transport aspect (S4 text names both paths) | Aspect here; discriminator lives in `bfla-alternate-path`, not here | Lines 96-113 |
| Backend sink family (SQL versus NoSQL versus OS versus LDAP versus XML versus HTTP) | No (sink name changes the payload dictionary, not the kind of GraphQL testing action) | Not applicable (sink interpretation is owned by the sink skills) | Non-discriminator | Lines 46-62; stability criterion excludes TechnologyStack |
| Error-text verbosity (stack trace versus SQL versus path) | No (reading `errors` is the same kind of action through S8 regardless of which text appears) | Yes (S8 text covers recording path, SQL, and exception text) | Non-discriminator | Lines 42-44, 160 |
| Credential or token or cookie value used | No (one secret versus another is the same kind of action) | Not applicable | Non-discriminator (runtime parameter) | Lines 22-28 |

## 7. Step-coverage falsification
Introspection-disabled value: parent S2 covers it because S2 names brute-force field names, suggestion harvesting, and the unknown-field versus unauthorized-field differential as the fallback reality.
Depth, amount, and alias values: parent S7 covers every one because S7 ships an example document for each shape and a single completion condition of proven-missing-limits versus observed enforcement.
JSON-array and alias batching values: parent section 5 plus S7 covers both because both envelopes are named with examples and share one completion condition.
Transport-form values: parent Request-variants text covers all of them because each envelope, GET form, variables-versus-inline choice, and CSRF note is enumerated.
Fragment-evasion value: parent line 149 covers it as an aspect because it is named as a wrapper inside the existing probe rather than as its own step.
Node-traversal value: parent S4 covers it at GraphQL scope because the `node(id:)` query is given inline, while its authorization-testing split is owned by the BFLA analysis rather than left uncovered here.
Sink-family values: no parent graphql step is left uncovered because sink interpretation was never a graphql-owned step in the first place.
No candidate value was found for which a named parent step performs a different kind of action yet fails to cover every value of that feature.
STATE 2 therefore exits through branch 2a with zero discriminators.

## 8. Hypotheses
H1 Single-feature hypothesis on weakness family: if the aggregated weakness families discriminate, then schema-disclosure, injection, cost-DoS, authorization, and batching each deserve a graphql-internal variant, and it is falsified if any proposed variant lacks its own non-coverable graphql step because its step is owned by another skill.
H2 Single-feature hypothesis on cost shape: if depth versus amount versus alias discriminates, then each cost shape deserves a variant, and it is falsified if parent S7 text already covers every shape with one completion condition.
H3 Combined-feature hypothesis on envelope by capability: if batching envelope combined with attacker capability discriminates, then anonymous-batch versus authed-batch versus alias-amplified variants emerge, and it is falsified if the combination adds no step beyond S7 batching plus S3 authentication.
H4 Transport-split hypothesis: if transport form discriminates, then JSON POST, GET, form, and application/graphql each deserve a variant, and it is falsified by the stability criterion because renaming the envelope preserves the testing procedure.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | graphql-schema-disclosure | none (S2 covers enabled, disabled, consoles, brute force, and suggestions) | Introspection documents and console paths as aspects |
| H1 | graphql-resolver-injection | none (S6 states the GraphQL action fully, and sink interpretation is owned by `sql-injection`, `ssrf`, `rce`) | Sink payload dictionaries as aspects owned elsewhere |
| H1 | graphql-cost-dos | none (S7 covers depth, amount, and alias with one completion condition) | Cost documents as aspects |
| H1 | graphql-authorization | none (S4 and S5 state the GraphQL action fully, and principal logic is owned by `two-principal-authz` with splits owned by the BFLA analysis) | Alias comparison and node traversal as aspects here |
| H1 | graphql-batching | none (section 5 plus S7 covers both envelopes with one completion condition) | Batch envelopes as aspects |
| H2 | graphql-depth; graphql-amount; graphql-alias | none per variant (no shape adds its own non-coverable step beyond S7) | Shape documents as aspects inside S7 |
| H3 | graphql-anonymous-batch; graphql-authed-batch; graphql-alias-amplified | none per variant (the combination reuses S3 plus S7 without adding a step) | Capability and envelope pairs as runtime parameters |
| H4 | graphql-json; graphql-get; graphql-form; graphql-applied-graphql | none per variant (no envelope adds its own non-coverable step beyond S1 fallback) | Envelope forms as aspects inside S1 |

## 10. Well-formedness evaluation
Coverage (critical): H2, H3, and H4 each cover their own narrow values but H1 is the only hypothesis spanning the class, yet every H1 variant fails the divergence-delta gate so no hypothesis yields a covering variant set.
Disjointness (critical): H1 fails because injection, authorization, and batching overlap on the same aliased operations (an aliased foreign-id batch is simultaneously IDOR evidence, BFLA evidence, and batching evidence), so the weakness-family partition admits one attempt into three variants.
Divergence delta (high): every proposed variant across H1 to H4 carries no positive delta over its parent step, because each parent step already names the candidate values or because the step is owned by another skill, so every proposed variant is deleted.
Stability (high): H2 and H4 pass trivially but irrelevantly on empty sets, while H1 and H3 depend on sink names and envelope labels that the stability criterion excludes.
Parsimony (medium): the fewest features that still cover is zero features and one skill, which is exactly the STATE 2 branch 2a outcome.
Winner: none of the hypotheses is well-formed, and the losing reason in every case is zero divergence delta compounded for H1 by disjointness failure.
No return to STATE 3 was needed because the failure is absence of any discriminator rather than a mis-partitioned signature.

## 11. Recommended set
Discrimination function: graphql does not discriminate on its own characteristics because every candidate feature is either covered exhaustively by its own parent step or owned procedurally by another skill.
Recommended variant graphql-single-skill: the class emits exactly one skill covering S1 through S8, with no divergence delta claimed because no split survived the two-half test.
The single skill references `two-principal-authz` for principal-comparison logic, the BFLA split for authorization-path partitions, `sql-injection`, `ssrf`, and `rce` for sink interpretation, and the `proxy-techniques` family for SSRF-reached internal targets.
Non-discriminators: all PreconditionEnvironment values including introspection state, console exposure, cost preconditions, and batching acceptance; all TechnologyStack names including engine, envelope, and sink family; all DefensiveControl values; the aggregated VulnerabilityClass itself; all AttackGoal values; the AttackerCapability ladder; the full AttackTechnique repertoire; all PayloadPattern documents; all Artifact evidence objects; all ObservableSignal shapes.
STATE 1 completed with eight parent steps S1 to S8 and no malformed-class stop.
STATE 2 tested every ledger value with both halves and exited through branch 2a with zero discriminators.
STATE 3 produced no signature and therefore no collapse or continuous-value folding was needed.
STATE 4 hypothesised four falsifiable splits and STATE 5 derived their sets, and STATE 6 deleted every proposed variant for zero delta with H1 additionally failing disjointness.
Grey points: an aliased foreign-id batch that simultaneously proves IDOR, multiplies cost, and bypasses rate limits is recorded once under the single skill with cross-references rather than triplicated.
Grey points: relay `node` traversal sits procedurally inside S4 here while its authorization split is owned by the BFLA alternate-path variant, so the two analyses share one technique without duplicating it.
Grey points: resolver-arg injection payloads that succeed are interpreted by the sink skills, and the graphql skill records only the GraphQL action of reaching the resolver with the aliased response pair.
Open questions: none at FAIL level, and no uncertainty blocks the one-skill recommendation.
