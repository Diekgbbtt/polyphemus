# prototype-pollution - variant decomposition analysis

## 1. Class and scope
The prototype-pollution class covers testing for unsafe recursive merges of user-controlled keys into JavaScript objects, leading to shared-prototype corruption with client-side impact and Node dot js server-side impact.
Its authority is `skills-unspurious/prototype-pollution/SKILL.md` (126 lines), consulted against `skills/prototype-pollution/SKILL.md` only for extra methodology detail.
The class spans client-side gadget effects through routing and auth state and DOM sinks, server-side gadget chains through template engines and child process wrappers, and key-sanitization bypass shapes across JSON and query-string and multipart and WebSocket channels.
The analysis finds two genuine variants discriminated by exploitation-sink family rather than by payload shape or delivery channel or library name.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | User-controlled merge point in extend or merge or defaults or deep copy; JSON parser preserves `__proto__` and `constructor` and `prototype` keys; query parser supports nested objects; browser reachability to routing or auth UI or DOM sinks; Node reachability to template or child process sinks; merge runs before any instance freeze | 8, 12-25, 29-35, 49-64, 74-76 | discriminator candidate |
| TechnologyStack | JavaScript and TypeScript in browser and Node runtimes; lodash merge and defaultsDeep and jQuery extend and deep-extend and merge-options; qs and body-parser nested parsers; ejs and pug and handlebars and child process wrappers; analytics SDK config merges | 12-15, 22-25, 49-64, 119-122 | non-discriminator |
| DefensiveControl | Key blocklist on `__proto__` and `constructor` and `prototype`; null-prototype objects through Object create null; instance freeze or seal; parser stripping of proto keys before merge; WAF encoding blocks | 8, 74-76, 93-97, 99-105, 126 | non-discriminator |
| VulnerabilityClass | Prototype pollution as shared-prototype corruption through unsafe merge | 8, 126 | non-discriminator |
| AttackGoal | Auth logic bypass; DOM cross-site scripting; cookie or session manipulation; denial of service; Node remote code execution | 8, 29-34, 57-62 | non-discriminator |
| AttackerCapability | Ability to send crafted JSON bodies and query strings and multipart fields and WebSocket messages and file imports; white-box node module enumeration ability | 17-20, 64, 107-113 | non-discriminator |
| AttackTechnique | Merge-point identification; benign canary pollution probe; shape-variant probing with proto and constructor forms; channel-matrix delivery; Node gadget-chain mapping to server sinks; client sink-effect confirmation through routing and auth UI and DOM; sanitization-bypass probing; second-order store-and-trigger pollution | 66-72, 80-89, 99-105 | discriminator candidate |
| PayloadPattern | `__proto__` object wrappers and `constructor` plus `prototype` wrappers and nested bracket notation and array proto forms and unicode or fullwidth key variants and shell plus NODE_OPTIONS plus outputFunctionName gadget bodies and unique canary marker keys | 36-46, 58-62, 68-72, 81-83, 101-102, 109 | non-discriminator |
| Artifact | Polluted prototype property proven by canary; enumerated node module inventory; client-side gadget reference mapping; stored second-order payload awaiting a background merge | 64, 105, 109, 119-122 | runtime |
| ObservableSignal | Canary property readable on a shared prototype; response behavior or error or follow-up state difference; routing or auth UI or DOM rendering change; server template output or command execution evidence | 81-89, 93-97, 109 | non-discriminator |
STATE 3 collapses browser-versus-Node runtime location plus gadget-body key names plus oracle-reading shapes into exploitation-sink family per branch 3a because none of them adds a step beyond its sink procedure.
Payload key shapes and input channels and second-order timing are recorded as non-discriminator aspects documented inside each sink variant because they preserve the sink kind while varying delivery or proof delay.
Library and parser and version labels are excluded as non-discriminator TechnologyStack per the stability criterion because swaps preserve both sink procedures.

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: merge utilities and nested parsers and JSON and query-string and multipart and WebSocket and GraphQL variables and file imports plus merge-function grepping form the surface (lines 10-25, 107-113).
This notion is invariant setup because both sink variants start from the same merge-point discovery and differ only at weaponisation.
Adversarial capabilities: anonymous crafted-input sender with optional white-box module enumeration is the ladder (lines 17-20, 64, 107-113).
This notion is invariant setup because every variant starts from the same input ability and differs only afterward.
Common trust assumptions: no dedicated trust-assumption section is present and the operative assumption is that merged keys never alter shared prototypes.
This notion is invariant because it is the negation of the class definition rather than a split axis.
Testing methodology: the six parent steps S1 to S6 (lines 80-89) are the step-test substrate.
This notion is the authority for accuracy and exhaustiveness and S5 plus S6 carry the sink divergence.
Proxy techniques: no proxy technique section is present.
This notion holds none for this class.
Defence bypass techniques: key-sanitization bypasses and freeze or seal gaps and content-type switching and split-parameter and second-order merges are the bypasses named (lines 66-76, 99-105).
This notion is an aspect inside each sink variant because every bypass preserves the underlying sink kind.
Techniques anti-patterns: no dedicated anti-pattern section is present beyond the false-positive guards.
This notion is invariant across all candidates.
Scripted tests (`references/`): none are shipped with the class skill.
No invariant is stated beyond the inline payload documents.
False positives: parser stripping and null-prototype options objects and echo without merge and frozen prototypes and consistent WAF blocking are the named non-findings (lines 91-97).
This notion is invariant across all candidates.
Chaining: Node gadget chains from polluted keys into process execution and client template injection from polluted rendering config are the named chains (lines 57-64, 107-113).
This notion varies by sink family and therefore tracks the discriminator without adding its own axis.

## 4. Runtime parametrisation
Each procedure consumes the concrete Service under test and the JavaScript System mechanism it lies on.
It consumes the Endpoint path, the BaseURL, the Header set including cookies and content type, the Parameter atoms where the logical DataItem surfaces as mergeable fields or config keys, and the prior HTTP history of baseline responses.
The operator knowledge base supplies the test credentials, the merge-function and parser hints from prior enumeration, and the package-version and gadget-availability notes from white-box scans.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is a deployed JavaScript application where the agent holds HTTP input ability and suspects that user-controlled keys reach an unsafe recursive merge.
S1 Identify merge points: search for extend and merge and defaults and deep copy over user-controlled objects, with completion when each candidate merge sink is listed.
S2 Baseline probe: inject a benign canary pollution marker and verify through response behavior or errors or follow-up shared-state reads, with completion when prototype corruption or its absence is proven.
S3 Shape variants: test proto and constructor prototype and nested bracket forms, with completion when each key shape shows acceptance or filtering.
S4 Channel matrix: repeat the canary across JSON body and query string and multipart and WebSocket for the same endpoint, with completion when each channel shows acceptance or rejection.
S5 Gadget hunting on Node dot js: map polluted keys to sinks in the dependency tree such as template engines and child process wrappers, with completion when a server-side gadget chain or its absence is proven.
S6 Client-side: check whether polluted properties affect routing or auth UI or DOM sinks, with completion when a client-side gadget effect or its absence is proven.
S6 confirmation consults the BlackFan client-side prototype-pollution gadget reference instead of restating it, so this class names that reference for per-library DOM sink proof.
Filter-bypass shapes at lines 66-72 include the MongoDB operator overlap that names `nosql-injection` instead of restating it, so this class points to that skill for dollar-plus-dot key handling.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Exploitation-sink family (browser-consumed properties versus Node server gadget sinks) | Yes (S5 performs dependency-tree sink mapping while S6 performs routing plus auth UI plus DOM effect checking) | No (neither S5 text nor S6 text covers the other sink weaponisation kind) | Discriminator (class signature) | S5 at 88 versus S6 at 89 |
| Client versus server runtime as bare execution location | Yes for sink values (browser confirmation differs in kind from server gadget mapping) | No standalone (location without a sink procedure adds no step) | Aspect folded into sink family, not a standalone axis | Lines 12-15 versus S5 at 88 and S6 at 89 and STATE 3 branch 3a |
| Payload key shape (`__proto__` versus `constructor` prototype versus array notation versus unicode variants) | No (every shape performs the same kind of action of delivering a pollution key) | Yes (S3 enumerates every shape) | Aspect inside each variant, not a variant axis | Lines 36-46, 68-72 versus S3 at 83 |
| Input channel (JSON body versus query string versus multipart versus WebSocket versus file import) | No (every channel performs the same kind of action of delivering the same pollution) | Yes (S4 enumerates every channel) | Aspect inside each variant, not a variant axis | Lines 17-20 versus S4 at 84 |
| Gadget-body key names (shell and NODE_OPTIONS versus outputFunctionName versus isAdmin flags) | Yes for sink values (server command keys differ in kind from client flag keys) | No standalone (names co-vary with the sink they feed) | Aspect collapsed into sink family per STATE 3 branch 3a | Lines 32-40, 58-62 versus S5 at 88 and S6 at 89 |
| Second-order timing (immediate merge versus stored payload with background merge) | No standalone (storing then triggering preserves the same sink kind while delaying proof) | Yes once folded (S2 follow-up reads plus bypass text cover delayed verification) | Secondary divergence inside each variant, not a variant axis | Lines 76, 105 versus S2 at 81-85 |
| Oracle shape (canary read versus behavior delta versus command output versus DOM change) | No standalone (oracle shape co-varies with sink and reading evidence is the same kind of confirmation action) | Yes once folded (each sink step carries its own oracle) | Non-discriminator standalone, collapsed per STATE 3 branch 3a | S2 at 81-85 versus S5 at 88 and S6 at 89 |
| Attack goal (auth bypass versus cross-site scripting versus denial of service versus remote execution) | No (goal changes the objective while the sink action stays the same) | Not applicable (goals are achieved through variants, not instead of them) | Non-discriminator | Lines 8, 29-34, 57-62 |
| Attacker capability (anonymous sender versus white-box enumerator) | No (one input ability versus another is the same kind of action) | Not applicable | Non-discriminator and runtime parameter | Lines 17-20, 64, 107-113 |
| Defensive control presence (key filtering versus null-prototype objects versus freeze versus parser stripping versus WAF) | No (a control changes success likelihood, not the kind of testing action) | Yes as detection (each step records enforcement versus bypass) | Non-discriminator | Lines 74-76, 93-97, 99-105 |
| Library name and version and parser identity (lodash versus jQuery versus qs, package versions, node module inventory) | No (swapping any library or version preserves the procedure) | Not applicable | Non-discriminator by stability criterion | Lines 22-25, 49-64 and SPEC section 8 |
| Concrete Service, System, Endpoint, Parameter, DataItem, BaseURL, Header, HTTP history, canary literal | No (swapping any runtime asset preserves the procedure) | Not applicable | Non-discriminator by stability criterion | SPEC section 4 runtime list |

## 7. Step-coverage falsification
Client weaponisation tested against its own covering step S6 fails because S6 states only generic routing plus auth UI plus DOM effect checking while client weaponisation requires library-indexed gadget-catalog consultation plus per-library sink driving to behavioral proof per lines 29-35 plus 119-120.
Client DOM cross-site scripting tested against S6 fails because S6 names no catalog lookup or per-library sink rule while the BlackFan reference mapping is exactly the catalog-consultation kind that turns confirmed pollution into library-specific impact.
Server weaponisation tested against its own covering step S5 fails because S5 states only generic dependency-tree sink mapping while server weaponisation requires white-box node module enumeration plus version-conditioned chain assembly plus server-execution proof per lines 57-64 plus 122.
Server template outputFunctionName tested against S5 fails because S5 names no enumeration or version-gated assembly action while lines 57-64 plus line 64 require matching polluted keys to version-specific template sinks before claiming execution.
Server shell plus NODE_OPTIONS process control tested against S5 fails because S5 names no child process proof rule while lines 58-62 require driving the assembled chain to command-execution evidence as a distinct assembly-plus-proof kind.
Browser-versus-Node runtime location alone uncovers no new step beyond the sink steps because location without a sink procedure reuses S5 plus S6 delivery.
Payload-shape value through `constructor` prototype nesting uncovers no new step because S3 names that shape explicitly at line 83.
Payload-shape value through unicode or fullwidth key variants uncovers no new step because S3 plus the bypass text enumerates alternate key forms.
Channel value through WebSocket or multipart or file import uncovers no new step because S4 names alternate channels for the same endpoint.
Second-order value through background-job merge uncovers no new step beyond delayed verification because S2 follow-up reads plus line 105 cover stored-then-merged proof as a secondary divergence.
STATE 2 therefore exits through branch 2b with one signature feature carrying two sink values.

## 8. Hypotheses
H1 Single-feature hypothesis on exploitation-sink family: if sink family discriminates, then a client-side variant covering S6 and a server-side variant covering S5 each deserve a skill, and it is falsified if either covering step text proves accurate plus exhaustive for its own weaponisation kind.
H2 Single-feature hypothesis on payload key shape: if key shape discriminates, then proto-key and constructor-prototype-key variants each deserve a skill, and it is falsified if both shapes share one probing procedure under S3.
H3 Combined-feature hypothesis on sink family by input channel: if sink combined with channel discriminates, then JSON-client and query-server and similar products emerge, and it is falsified if the combination adds no step beyond S4 delivery plus the covering sink step.
H4 Combined-feature hypothesis on sink family by payload shape: if sink combined with shape discriminates, then constructor-server and proto-client products emerge, and it is falsified if the combination adds no step beyond S3 shape probing plus the covering sink step.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | prototype-pollution-client-side | S6 Client-side check (generic effect text is neither accurate nor exhaustive for catalog-consultation plus per-library sink proof) | Shape alternatives and channel alternatives and second-order timing and BlackFan gadget lookup and frozen-prototype negatives as aspects |
| H1 | prototype-pollution-server-side | S5 Gadget hunting on Node dot js (generic mapping text is neither accurate nor exhaustive for enumeration plus version-gated chain assembly plus execution proof) | Shape alternatives and channel alternatives and second-order timing and YAML load sink and dollar-plus-dot MongoDB keys and version-pinned chain proof as aspects |
| H2 | proto-key-only; constructor-key-only | none cleanly (both shapes reuse the S3 probing procedure) | Key shapes as aspects inside both H1 variants |
| H3 | json-client; query-server; multipart-server; websocket-client | none per product (each reuses S4 delivery plus its covering sink step) | Channels as aspects inside each H1 variant |
| H4 | constructor-server; proto-client | none per product (each reuses S3 probing plus its covering sink step) | Shapes as aspects inside each H1 variant |

## 10. Well-formedness evaluation
Coverage (critical): H1 covers every genuine non-coverable step with exactly one weaponisation owner because S5-weaponisation owns server chain assembly while S6-weaponisation owns client catalog proof, while H2 leaves both sink steps uncovered inside shape buckets.
Shared S1 through S4 preamble is declared shared setup rather than owned, so canary proof plus shape plus channel evidence is reused by both H1 variants without breaking single ownership of weaponisation.
Disjointness (critical): H1 is disjoint at weaponisation because catalog-driven DOM proof admits no technique that is simultaneously version-gated server chain assembly, while H3 fails because one JSON attempt is simultaneously a sink attempt and H4 fails because one constructor payload is simultaneously a sink attempt.
Isomorphic pollution feeding both a DOM sink and a server sink stays disjoint by rule because shared S1 through S4 runs once and then server weaponisation is proven first for execution claims before client weaponisation reuses the canary for DOM claims.
Divergence delta (high): each H1 variant adds a positive kind delta over its own covering text because catalog consultation is a reference-driven proof kind beyond S6 generic checking and enumeration-plus-assembly is an inventory-driven construction kind beyond S5 generic mapping, while every H2 shape label plus every H3 plus H4 product without its own step carries zero delta and is deleted.
Stability (high): client assignment survives swapping jQuery plus qs plus Chrome for Popper plus body-parser plus Firefox because catalog consultation plus DOM proof stays the same kind, while server assignment survives swapping lodash plus ejs plus qs for deep-extend plus pug plus body-parser plus an alternate package version because enumeration plus version-gated assembly stays the same kind.
Parsimony (medium): H1 uses one feature with two values which is the fewest that still covers, while H2 uses one feature with overlapping buckets and H3 plus H4 add features without adding coverage.
Winner: H1 is well-formed under corrected own-step falsification and H2 loses on coverage plus zero divergence delta, and H3 plus H4 lose on zero divergence delta plus disjointness.
No return to STATE 3 was needed beyond the documented runtime plus gadget-body plus oracle folding because the corrected H1 signature already collapses co-varying values without overlap.

## 11. Recommended set
Discrimination function: prototype-pollution discriminates by exploitation-sink family, namely whether a confirmed prototype pollution is weaponised through browser-consumed properties or through Node dot js server-side gadget sinks.
Recommended variant prototype-pollution-client-side diverges at its covering S6 with delta of library-indexed gadget-catalog consultation plus per-library DOM sink driving that S6 generic checking cannot describe.
Recommended variant prototype-pollution-server-side diverges at its covering S5 with delta of white-box module enumeration plus version-conditioned chain assembly plus server-execution proof that S5 generic mapping cannot describe.
Non-discriminators: all library and parser and version labels as TechnologyStack, all payload key shapes, all input channels, second-order timing, oracle-reading shapes, all attack goals, the full capability ladder, all defensive controls, all produced artifacts, and all L0 plus L1 runtime assets including Service and System and Endpoint and Parameter and DataItem and BaseURL and Header and HTTP history.
STATE 1 inventoried six parent steps S1 to S6 with no malformed-class stop.
STATE 2 tested every ledger value with both halves and exited through branch 2b with one signature feature.
STATE 3 enumerated two sink values and collapsed runtime location and gadget-body names and oracle shapes into that feature without needing continuous-value folding.
STATE 4 hypothesised two single-feature and two combined-feature falsifiable splits.
STATE 5 derived four variant sets and kept second-order timing as a secondary divergence because it adds no non-coverable step of its own.
STATE 6 rescored all sets on weighted criteria with own-step falsification plus shared-preamble disjointness plus concrete swap stability and selected H1 for coverage plus disjointness plus delta plus stability plus parsimony.
STATE 7 recommends the two-variant set stated in this section.
Outlier: none malformed and YAML load sinks ride with the server-side variant because unsafe load feeds the same server merge procedure rather than a third procedure.
Grey point: isomorphic applications where one pollution feeds both a DOM sink and a server sink run shared S1 through S4 once and then prove server weaponisation before reusing the canary for client weaponisation rather than minting a combined variant.
Grey point: dollar and dot keys at the MongoDB overlap are recorded as a secondary divergence inside the server-side variant under Filter Bypasses at line 72 and invoke `nosql-injection` at that bypass step rather than duplicating its procedure.
Grey point: S2 canary verification stays shared preamble because it proves pollution while saying nothing about which sink weaponises it.
Open questions: no FAIL-level uncertainty blocks this recommendation.
Open question at note level: package-version-specific gadget availability shifts exploitability but never changes either variant procedure, so versions remain runtime facts.
