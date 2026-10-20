# nosql-injection - variant decomposition analysis

## 1. Class and scope
The nosql-injection class covers testing for user input that alters NoSQL query structure through operator embedding, pipeline control, script-body control, query-string breaking, or command framing.
Its authority is `skills-unspurious/nosql-injection/SKILL.md` (264 lines), consulted against `skills/nosql-injection/SKILL.md` only for extra methodology detail.
The class spans MongoDB operator bypass and blind extraction, server-side JavaScript through `$where` and `$function` and related engines, aggregation pipeline pivots, and store-specific surfaces for Redis and Elasticsearch and DynamoDB and Cassandra and CouchDB and Neo4j plus GraphQL variable pass-through.
The analysis finds five genuine variants discriminated by query-interpretation family rather than by store name alone.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | JSON body parsed into filter; bracket-notation coercion to operators; URL-encoded JSON in query or header or cookie; aggregation endpoint with user-influenceable stages; javascriptEnabled true on pre-7.0 MongoDB including 4.4 to 6.x defaults; user-controlled Painless source; user-controlled CouchDB design-doc map; APOC procedures enabled; GraphQL resolver passing filter input; CouchDB admin-party exposure | 12-25, 86-99, 126-129, 154-167, 179-196, 200-203 | Discriminator candidate (enables script and pipeline values, folded into interpretation family per STATE 3) |
| TechnologyStack | MongoDB with Mongoose or native driver or ODM wrapper; Redis; Elasticsearch with Lucene and Painless; DynamoDB with PartiQL; Cassandra with CQL; CouchDB with Mango and views; Neo4j with Cypher and APOC; GraphQL resolvers; DocumentDB and Couchbase and HBase and ScyllaDB and Memcached as same-model followers | 8, 18-25, 32-33, 105-183 | Non-discriminator as store label (excluded axis per stability criterion, stores ride inside interpretation variants) |
| DefensiveControl | Mongoose strict mode and string casting; operator-key sanitization; javascriptEnabled false and MongoDB 7.0 default off; query timeouts; prepared CQL statements; parameterized Cypher params; Painless sandboxing; WAF encoding checks | 21, 86-99, 145, 152, 174, 208-209, 245-250 | Non-discriminator (each control is detected inside its own step and never bends a step into a new kind of action) |
| VulnerabilityClass | NoSQL injection as operator and structure injection | 8, 262-264 | Non-discriminator (this is the class definition itself, not a value that bends a step) |
| AttackGoal | Authentication bypass; blind field extraction; cross-collection exfiltration; script execution; enumeration; denial of service | 52-60, 74-82, 103-104, 126-151, 198-209, 270-276 | Non-discriminator (goal is invariant across candidate splits and every goal is reachable through its own interpretation variant) |
| AttackerCapability | Anonymous HTTP request ability; authenticated low-privilege session; GraphQL variable sender; CouchDB admin-party reader; APOC caller on misconfigured Neo4j | 105-113, 167, 179-196 | Non-discriminator (capability ladder is shared setup across all variants) |
| AttackTechnique | Operator injection with `$ne` and `$gt` and `$regex` and `$in`; blind `$regex` character search; `$where` JavaScript injection with sleep timing; `$function` and `$accumulator` expression-context injection; aggregation `$match` and `$lookup.from` and `$project` injection; Redis RESP newline smuggling; Lucene `query_string` widening; Painless source injection; PartiQL quote breaking; CQL quote breaking; CouchDB Mango selector injection; CouchDB design-doc JavaScript injection; Cypher concatenation with UNION and APOC abuse; GraphQL variable pass-through; error and operator probing | 37-48, 52-99, 103-183, 184-196, 232-244 | Discriminator source (values partition into five interpretation families, see section 6) |
| PayloadPattern | `{"$ne": null}` and `{"$gt": ""}` and `{"$regex": "^a"}` and `{"$in": [...]}` operator objects; bracket-notation `field[$ne]` forms; `$where` function strings; `$expr` plus `$function` documents; `$lookup.from` collection names; RESP `key\r\nSET` frames; Lucene `*` and `role:admin` and `_exists_` strings; Painless `ctx._source` sources; PartiQL `' OR '1'='1` fragments; CQL `ALLOW FILTERING` fragments; Cypher `'}) RETURN ... UNION ... //` fragments; GraphQL `{"input": {...operators}}` variables; `$nin` and `$exists` and `$type` and `$not` and `$expr` alternatives; dotted-key versus nested-object wrappers | 37-48, 56-72, 76-99, 103-183, 192-196, 213-230 | Discriminator instrument (co-varies with technique and is collapsed into one feature per STATE 3 branch 3a) |
| Artifact | Authenticated session or token; extracted secret such as hash or reset code or API key; collection and field names from error text; GraphQL schema from introspection; Redis backdoor key; Elasticsearch index and mapping listing | 37-40, 74-82, 184-196, 200-203, 255-260 | Non-discriminator (runtime-produced evidence that parametrises proof inside every variant) |
| ObservableSignal | MongoError and CastError and ValidationError text; boolean response or status or redirect difference; sleep-driven latency differential; mapping and search-hit content; APOC fetch callback | 37-48, 76-91, 116-124, 152, 179-183, 255-260 | Non-discriminator (oracle reading is folded into interpretation family per STATE 3 branch 3a, with timing carried as secondary divergence inside the script variant) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: JSON and form and query and header and cookie inputs plus error fingerprinting plus operator probes plus GraphQL introspection form the surface (lines 10-48, 184-196).
This notion varies by interpretation family because each family needs its own probe grammar and cannot reuse the MongoDB operator probe text.
Adversarial capabilities: anonymous baseline with optional authenticated session plus GraphQL variable sending plus admin-party reading is the ladder (lines 103-113, 167, 179-196).
This notion is invariant setup because every variant starts from the same request ability and differs only afterward.
Common trust assumptions: raw filter objects are safe and concatenated queries are safe and script engines are unreachable and resolvers validate variables are the assumptions under test (lines 18-25, 184-196).
This notion varies only as the negation of each interpretation family and therefore tracks the discriminator without adding its own axis.
Testing methodology: the ten parent steps S1 to S10 (lines 232-244) are the step-test substrate.
This notion is the authority for accuracy and exhaustiveness and S9 is compound across store-specific sub-values.
Proxy techniques: APOC external fetch and GraphQL resolver reach into backing filters are the proxy-adjacent values (lines 179-196).
This notion invokes `ssrf` at the APOC fetch step and `graphql` at the resolver step instead of restating them.
Defence bypass techniques: type coercion and encoding and operator alternatives and structure manipulation are the bypasses named (lines 211-230).
This notion is an aspect inside each interpretation variant because every alternative operator or encoding preserves the underlying interpretation kind.
Techniques anti-patterns: no dedicated anti-pattern section is present beyond the false-positive guards around string casting and sanitization.
This notion is invariant across all candidates.
Scripted tests (`references/`): none are shipped with the class skill.
No invariant is stated beyond the inline payload documents.
False positives: strict-mode casting and operator stripping and `[object Object]` coercion and validation-error response deltas are the named non-findings (lines 245-250).
This notion is invariant across all candidates.
Chaining: bypass plus admin or user-list fetch and `_mapping` before script injection and introspection before variable injection are the named chains (lines 184-209, 253-260).
This notion is invariant plumbing between steps rather than a split axis.

## 4. Runtime parametrisation
Each procedure consumes the concrete Service under test and the database or API System mechanism it lies on.
It consumes the Endpoint path, the BaseURL, the Header set including cookies and content type, the Parameter atoms where the logical DataItem surfaces as filter fields or sort keys or GraphQL arguments, and the prior HTTP history of baseline responses.
The operator knowledge base supplies the test credentials, the collection and field name hints, the MongoDB version and `javascriptEnabled` state, and the APOC and Painless enablement notes from prior enumeration.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is a deployed application where the agent holds anonymous HTTP access plus low-privilege test credentials and suspects that user input reaches a NoSQL query path.
S1 Identify query-receiving endpoints: enumerate login and search and filter and lookup endpoints, with completion when each candidate input sink is listed.
S2 Determine input format: classify JSON body versus bracket-notation form versus URL params versus GraphQL variables, with completion when each endpoint has a named envelope.
S3 Send error-probing payloads: submit malformed operator objects and bracket probes, with completion when MongoDB or driver errors or silent filtering are recorded.
S4 Attempt operator injection: submit `$ne` and `$gt` and `$regex` predicates against the login or filter endpoint, with completion when bypass or differential is proven or refuted.
S5 Confirm boolean oracle: compare true versus false predicates on response and status and redirect, with completion when a repeatable oracle or its absence is recorded.
S6 Extract data blindly: iterate `$regex` prefixes with binary search over tokens or keys, with completion when a full secret or a definitive negative is recorded.
S7 Test `$where`: fingerprint `javascriptEnabled` and submit function filters plus sleep timing payloads, with completion when script execution or disabled state is proven.
S8 Probe aggregation endpoints: inject operators into `filter` and `match` and `sort` fields and test `$lookup.from` pivots and `$expr` contexts, with completion when stage control or its absence is recorded.
S9 Test non-MongoDB stores: exercise Lucene `query_string` and Painless source and RESP framing and PartiQL and CQL and Mango selectors and Cypher concatenation with store-appropriate grammars, with completion when each reachable store shows injection or safe handling.
S10 Test GraphQL resolvers: enumerate operator-accepting input types through introspection and submit operator objects as variables, with completion when each candidate resolver shows pass-through or safe handling.
S10 resolver enumeration is owned jointly with the `graphql` skill and S9 APOC external fetch invokes `ssrf` at that step, so this class names those skills instead of restating them.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Document-operator filter versus pipeline-stage control versus script-body control versus concatenated query string versus command-protocol frame (interpretation family) | Yes (each value performs a different kind of action across S4, S8, S7, S9q, S9c) | No (no single parent step text covers all five grammars and oracles) | Discriminator (class signature) | S4 at 238 versus S7 at 240 versus S8 at 241 versus S9 at 242 |
| Store name alone (MongoDB versus Redis versus Elasticsearch versus DynamoDB versus Cassandra versus CouchDB versus Neo4j) | No as a label (renaming the store without changing interpretation preserves the kind of action) | No as a partition (CouchDB Mango duplicates MongoDB operators and DynamoDB PartiQL duplicates the SQL-shaped pattern) | Non-discriminator as label, interpretation family carries the split | Lines 24-25 versus stability criterion and STATE 3 branch 3a |
| Server-side script enablement (`javascriptEnabled` true versus false, Painless source reachable, design-doc map reachable) | Yes for script values (JS-body submission differs from operator predicates) | No (S7 names only top-level `$where` sleep and omits `$function` expression context and Painless source and design-doc maps) | Discriminator value folded into script variant, not a standalone axis | Lines 86-99, 126-129, 154-165 versus S7 at 240 |
| Aggregation `$lookup.from` collection pivot versus same-collection filtering | Yes (choosing a collection to read differs from filtering rows in a fixed collection) | No (S4 filter text cannot describe cross-collection pivots) | Discriminator value inside pipeline variant | Lines 103-104 versus S4 at 238 and S8 at 241 |
| Input envelope (JSON object versus bracket form versus URL-encoded JSON versus GraphQL variables) | No (every envelope performs the same kind of action of delivering a predicate to the same sink) | Yes (S2 plus bypass text enumerates every envelope) | Aspect inside each variant, not a variant axis | Lines 12-16, 184-196, 213-230 versus S2 at 236 and S10 at 243 |
| GraphQL variable pass-through as entry vector | No (variable delivery performs the same kind of action as direct operator injection at the sink) | Yes at GraphQL scope (S10 plus `graphql` introspection covers candidate enumeration) | Non-discriminator here, owned jointly with `graphql` | Lines 184-196 versus S10 at 243 and SPEC section 7 |
| Boolean versus error versus timing oracle shape | No standalone (oracle shape co-varies with interpretation and reading a response is the same kind of confirmation action) | Yes once folded (each variant text carries its own oracle) | Non-discriminator standalone, collapsed per STATE 3 branch 3a with timing as secondary divergence inside script variant | S5 at 239 versus S7 at 240 |
| Operator alternatives and encodings (`$nin`, `$exists`, `$type`, `$not`, `$expr`, dotted keys, double encoding) | No (each alternative preserves the same interpretation kind) | Yes (bypass text enumerates every alternative) | Aspect inside operator variant | Lines 213-230 |
| Attack goal (bypass versus extraction versus execution versus exfiltration versus DoS) | No (goal changes the objective while the interpretation action stays the same) | Not applicable (goals are achieved through variants, not instead of them) | Non-discriminator | Lines 270-276 |
| Attacker capability (anonymous versus authenticated versus admin-party reader) | No (one credential versus another is the same kind of action) | Not applicable | Non-discriminator and runtime parameter | Lines 103-167 |
| Defensive control presence (strict mode, sanitization, disabled scripts, prepared statements, parameterized Cypher) | No (a control changes success likelihood, not the kind of testing action) | Yes as detection (each step records enforcement versus bypass) | Non-discriminator | Lines 245-250 |
| Concrete Service, System, Endpoint, Parameter, DataItem, BaseURL, Header, HTTP history, payload literal, library version | No (swapping any runtime asset preserves the procedure) | Not applicable | Non-discriminator by stability criterion | SPEC section 4 runtime list |

## 7. Step-coverage falsification
Operator-predicate value: parent S4 covers MongoDB `find` and `findOne` filters but parent S4 cannot cover `$function` expression contexts because S4 describes only top-level predicates.
Script-body value through `$function` and `$accumulator`: parent S7 fails because S7 names only top-level `$where` with sleep timing and never states the `$expr` or `$project` or `$addFields` placement rule from lines 93-99.
Script-body value through Painless source: parent S9 fails because S9 names stores without stating script-source control, while lines 126-129 show a distinct `script.source` sink.
Script-body value through CouchDB design-doc maps: parent S7 and S9 fail because neither states map-function injection that executes on every view query from lines 162-165.
Pipeline-pivot value through `$lookup.from`: parent S4 fails because S4 describes row filtering in a fixed collection, while lines 103-104 describe pivoting into a different collection for cross-tenant reads.
Pipeline-stage value through `$match` and `$project`: parent S4 fails because S4 omits stage targeting, while S8 explicitly names `filter` and `match` and `sort` fields.
Query-language value through Cypher concatenation: parent S9 fails because S9 lists Neo4j without describing quote breaking or UNION appends from lines 169-177.
Query-language value through CQL and PartiQL: parent S9 fails because S9 lists the stores without describing quote breaking plus `ALLOW FILTERING` or `OR '1'='1` expansion from lines 132-152.
Query-language value through Lucene `query_string`: parent S9 fails because S9 omits Lucene metacharacters such as `*` and `role:admin` and `_exists_` from lines 116-124.
Command-frame value through Redis RESP newlines: parent S9 fails because S9 names command construction without describing `\r\n` frame smuggling from lines 105-114.
Mango-selector value: no new step is uncovered because lines 154-160 state the same operator shape as MongoDB and S4 covers it exhaustively.
GraphQL-variable value: no new step is uncovered because S10 plus the `graphql` skill covers variable delivery and the sink action remains operator injection.
STATE 2 therefore exits through branch 2b with one signature feature carrying five values.

## 8. Hypotheses
H1 Single-feature hypothesis on interpretation family: if query-interpretation family discriminates, then operator-filter and pipeline-stage and script-body and query-language and command-frame each deserve a variant, and it is falsified if any proposed variant lacks its own non-coverable parent step.
H2 Single-feature hypothesis on store name: if store product discriminates, then MongoDB and Redis and Elasticsearch and DynamoDB and Cassandra and CouchDB and Neo4j each deserve a variant, and it is falsified if any store pair shares one procedure or if any store internally needs two procedures.
H3 Combined-feature hypothesis on interpretation by envelope: if interpretation combined with input envelope discriminates, then JSON-operator and bracket-operator and GraphQL-variable-operator emerge as products, and it is falsified if the combination adds no step beyond S4 plus S2 plus S10.
H4 Combined-feature hypothesis on interpretation by script enablement: if interpretation combined with script enablement discriminates, then enabled-script versus disabled-script operator variants emerge, and it is falsified if enablement adds no step beyond the script variant's own S7-derived procedure.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | nosql-operator-injection | S4 Attempt operator injection | Blind `$regex` extraction loop, Mango selectors, DocumentDB parity, operator alternatives and encodings as aspects |
| H1 | nosql-server-side-script-injection | S7 Test `$where` | `$function` and `$accumulator` expression placement, Painless source control, CouchDB design-doc maps, sleep timing oracle, ReDoS and loop DoS as scoped aspects |
| H1 | nosql-aggregation-pipeline-injection | S8 Probe aggregation endpoints | `$match` and `$project` stage targeting, `$lookup.from` collection pivot, heavy-lookup DoS as scoped aspect, with `$expr` plus `$function` boundary owned by script variant |
| H1 | nosql-query-language-injection | S9 store step, query-language sub-value | Cypher UNION plus APOC-owned fetch boundary, CQL and PartiQL quote breaking, Lucene `query_string` widening, `_mapping` and `_cat` recon as aspects |
| H1 | nosql-command-protocol-smuggling | S9 store step, command-frame sub-value | RESP `\r\n` framing, backdoor-key persistence, large-`$in` scan cost carried only where the store frames commands |
| H2 | mongo-only; redis-only; elasticsearch-only; dynamodb-only; cassandra-only; couchdb-only; neo4j-only | none cleanly (Mango duplicates S4, PartiQL duplicates SQL-shaped breaking, single stores need two internal procedures) | Store labels as aspects inside H1 variants |
| H3 | json-operator; bracket-operator; graphql-variable-operator | none per product (each reuses S4 predicate logic plus S2 or S10 delivery) | Envelopes as aspects inside operator variant with `graphql` cross-reference |
| H4 | enabled-script-operator; disabled-script-operator | none per product (enablement reuses script-variant S7 procedure or its negative) | Enablement fingerprint as precondition inside script variant |

## 10. Well-formedness evaluation
Coverage (critical): H1 covers every non-coverable step with exactly one owner and resolves the `$expr` plus `$function` overlap by assigning JS execution to the script variant, while H2 leaves Painless versus Lucene and `$lookup.from` versus Mango uncovered inside single-store buckets.
Disjointness (critical): H1 is disjoint because operator objects and stage names and script bodies and quoted query strings and RESP frames admit no shared technique, while H2 fails because Mango belongs in two buckets and H3 fails because one GraphQL variable attempt is simultaneously an operator attempt.
Divergence delta (high): every H1 variant adds a positive step delta over the parent, while every H2 store label and every H3 and H4 product without its own step carries zero delta and is deleted.
Stability (high): H1 survives swaps of store and version and payload and runtime asset, while H2 depends on product names that DocumentDB parity directly falsifies.
Parsimony (medium): H1 uses one feature with five values which is the fewest that still covers, while H2 uses one feature with seven overlapping buckets and H3 and H4 add features without adding coverage.
Winner: H1 is well-formed and H2 loses on coverage plus disjointness plus stability with zero-delta buckets, and H3 and H4 lose on zero divergence delta.
No return to STATE 3 was needed because the H1 signature needs no collapse beyond the documented oracle and payload folding.

## 11. Recommended set
Discrimination function: nosql-injection discriminates by query-interpretation family, namely whether user input becomes a document operator filter, a pipeline stage with collection pivot, a server-side script body, a concatenated query-language string, or a smuggled command-protocol frame.
Recommended variant nosql-operator-injection diverges first at S4 with delta of operator-predicate construction plus boolean-oracle confirmation plus iterative `$regex` extraction that S4 through S6 state only for this grammar.
Recommended variant nosql-server-side-script-injection diverges first at S7 with delta of script-body placement plus enablement fingerprinting plus sleep-timing confirmation that S7 states only for top-level `$where`.
Recommended variant nosql-aggregation-pipeline-injection diverges first at S8 with delta of stage targeting plus `$lookup.from` cross-collection pivot that S4 cannot describe.
Recommended variant nosql-query-language-injection diverges first at S9 query-language sub-value with delta of quote-breaking grammar plus Lucene metacharacter widening plus Cypher and CQL and PartiQL oracles that S9 lists without describing.
Recommended variant nosql-command-protocol-smuggling diverges first at S9 command-frame sub-value with delta of RESP newline framing plus injected-command persistence that S9 lists without describing.
Non-discriminators: all store-product labels as TechnologyStack, all input envelopes, GraphQL variable delivery, oracle-reading shapes, all attack goals, the full capability ladder, all defensive controls, all produced artifacts, and all L0 and L1 runtime assets including Service and System and Endpoint and Parameter and DataItem and BaseURL and Header and HTTP history.
STATE 1 inventoried ten parent steps S1 to S10 with no malformed-class stop.
STATE 2 tested every ledger value with both halves and exited through branch 2b with one signature feature.
STATE 3 enumerated five interpretation values and collapsed payload patterns and oracle shapes into that feature without needing continuous-value folding.
STATE 4 hypothesised two single-feature and two combined-feature falsifiable splits.
STATE 5 derived four variant sets and assigned `$expr` plus `$function` to the script variant as the only product boundary needing a rework trigger.
STATE 6 scored all sets on weighted criteria and selected H1 for coverage plus disjointness plus delta plus stability plus parsimony.
STATE 7 recommends the five-variant set stated in this section.
Outlier: CouchDB is split across two variants because Mango selectors ride with operator injection while design-doc maps ride with script injection, which reflects genuinely different procedures rather than a store split.
Grey point: `$expr` with `$ne` used as an operator alternative stays in operator injection, while `$expr` with `$function` belongs to script injection because only the latter introduces a script body.
Grey point: APOC external fetch is recorded as a secondary divergence inside query-language injection and invokes `ssrf` at that step rather than duplicating its procedure.
Grey point: S9 is treated as two sub-values because one parent line lists disjoint grammars that no single description covers exhaustively.
Open questions: no FAIL-level uncertainty blocks this recommendation.
Open question at note level: version-specific `javascriptEnabled` defaults shift exploitability but never change the script-variant procedure, so versions remain runtime facts.
