# ssti - variant decomposition analysis

## 1. Class and scope
The ssti class covers testing for user input that reaches a server-side template engine as syntax instead of as data and is evaluated in the host language with the engine's exposed runtime objects.
Its authority is `skills-unspurious/ssti/SKILL.md` (301 lines), consulted against `skills/ssti/SKILL.md` only for extra methodology detail and against `skills-unspurious/ssti/references/blind-probe-signals.md` as a normative reference.
The class spans engine-agnostic differential probing, same-response arithmetic confirmation, stored payloads rendered on deferred endpoints and views and documents, fully blind time-based and out-of-band and length-diff inference, sandbox-state probing, gadget enumeration by reflection walk, filter and parser evasion, and escalation to shell-equivalent primitives.
The analysis finds two genuine variants discriminated by evaluation observability rather than by engine name, payload literal, or goal.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | User input concatenated into a template string before render; tenant or admin template-editor control of the template itself; second-order values (YAML, TOML, JSON, format-string output, Markdown) evaluated through a template downstream | 19-23, 179, 200, 250-253 | Non-discriminator (the input-as-syntax precondition defines the class, delivery envelopes are aspects inside S1) |
| PreconditionEnvironment | Render topology: immediate same-response render versus stored payload rendered on a deferred endpoint or view or document or email versus render with no attacker-visible output at all | 58-64, 73-75, 126-129, references 4-8 | Discriminator source (values bend S1 and S3 into different kinds of action, collapsed into the observability signature per STATE 3 branch 3a) |
| TechnologyStack | Jinja2, Mako, Django, Velocity, Freemarker, Thymeleaf with SpEL, JSP EL, Handlebars, Nunjucks, EJS, Pug, Marko, Dust, ERB, Haml, Slim, Twig, Smarty, Blade, Razor, RazorEngine, plus language runtimes and library versions | 25-31, 133-231 | Non-discriminator by instruction and stability (engine swap preserves the procedure kind and only reparametrises payload literals from the knowledge base) |
| DefensiveControl | SandboxedEnvironment, SecureUberspector, template denylists, filtered attributes and globals, hardened Twig 2.x and 3.x scoping, removed Smarty php tags | 149, 177, 190-198, 233-248 | Aspect inside each variant (escape values are enumerated in the bypass grammar and preserve the gadget-search kind) |
| VulnerabilityClass | Server-side template injection as input-as-syntax evaluation | 6-8, 299-301 | Non-discriminator (this is the class definition itself, not a value that bends a step) |
| AttackGoal | Remote code execution on the rendering host; filesystem and environment exfiltration; cloud credential theft; lateral movement; persistence via web shell or keys | 255-268 | Non-discriminator (goals are downstream consequences reachable through either variant and bend no step by themselves) |
| AttackerCapability | Anonymous HTTP request ability; authenticated low-privilege session holding editable fields; tenant or admin template-editor access; attacker-hosted out-of-band callback listener | 66-88, 120-124, 21 | Non-discriminator (the capability ladder is shared setup read at runtime and identical in kind across variants) |
| AttackTechnique | Differential arithmetic probing with second-probe confirmation; reachable-global spraying; reflection and class-walk gadget enumeration; sandbox escape by attribute indirection and aliasing and token splitting; store-then-sweep every endpoint; sleep timing; out-of-band callback; file-write oracle; length and ETag diff | 41-56, 66-129, 137-231, 233-253, references 4-8 | Discriminator source (values partition by observability into reflected confirmation versus blind inference, escape values folded as aspects) |
| PayloadPattern | Arithmetic differentials (`{{7*7}}`, `${7*7}`, `<%= 7*7 %>`); engine-distinguishing string-multiplication forms; comment-syntax and filter-syntax differentials; reflection-walk strings; sleep and callback and file-write payloads; concatenation-split and encoded token assemblies | 41-56, 137-231, 242-248 | Discriminator instrument for the observability split and aspect for escape spellings (co-varies with technique and is collapsed per STATE 3 branch 3a) |
| Artifact | Rendered arithmetic output (`49`); stack traces leaking engine names; written files in webroot or tmp; outbound callback receipts; extracted secrets and cloud tokens | 37-39, 56, 108-117, 255-268 | Non-discriminator (runtime-produced evidence read through the owning variant oracle) |
| ObservableSignal | Same-response arithmetic reflection; literal template-syntax reflection (negative); response latency differential; DNS or HTTP callback receipt; body-length or ETag shift; Process object rendering proving execution | 41-56, 99-129, 153-161, 280-286, references 4-8 | Discriminator source collapsed with render topology (same-response reflection versus deferred or absent reflection bends S3) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: form and query and path and header and cookie inputs plus filenames and email and theme endpoints plus benign-string reflection grep plus error-page leakage plus the differential probe table plus the blind store-then-sweep procedure form the surface (lines 10-56, 58-129).
This notion varies by observability because the reflected grammar needs one probe table while the blind grammar needs endpoint sweeps and timing and callback oracles that the table cannot state.
Adversarial capabilities: anonymous baseline with optional authenticated session plus editable-field control plus callback-listener operation is the ladder (lines 66-88, 120-124).
This notion is invariant setup because every variant starts from the same request ability and differs only afterward.
Common trust assumptions: user input passed as a context variable is data and never re-evaluated, and sandboxed or filtered engines expose nothing useful, are the assumptions under test (lines 19-23, 149, 177, 186, 282).
This notion varies only as the negation checked inside each variant and therefore tracks the procedure without adding its own axis.
Testing methodology: the seven parent steps S1 to S7 (lines 270-278) are the step-test substrate.
This notion is the authority for accuracy and exhaustiveness and S1 plus S3 plus S7 are compound across observability sub-values.
Proxy techniques: file-write then read via traversal, and OAST callback through attacker infrastructure, are the proxy-adjacent values (lines 108-124).
This notion invokes `path-traversal-lfi-rfi` at the file-read step and keeps only the write-and-trigger proof here instead of restating traversal.
Defence bypass techniques: sandbox escape patterns plus filter and parser evasion plus polyglot and chained evaluation are the bypasses named (lines 233-253).
This notion is an aspect inside each variant because every escape spelling preserves the underlying gadget-search kind.
Techniques anti-patterns: celebrating single-shot `49` reflection, wrong-engine payload spray, confusing Thymeleaf model binding with template-source control, and mistaking `system()` server-stdout success for reflected output are the named anti-patterns (lines 179-186, 210-213, 288-297).
This notion is invariant discipline across all candidates.
Scripted tests (`references/`): the blind-probe signals note ships time-based and OAST and length-diff oracle text (references lines 4-8).
This notion varies with observability because its oracles are detection procedure inside the blind variant rather than shared setup.
False positives: literal template-syntax reflection, sandboxes exposing nothing useful, client-side template injection, build-time-only templating, and HTML-escaped masking are the named non-findings (lines 280-286).
This notion is invariant exclusion predicates across all candidates.
Chaining: file write to webroot with follow-up request, second-stage macro definition, deserialization gadgets through templates, and DNS or HTTP exfiltration are the named chains (lines 255-268).
This notion is invariant plumbing between steps rather than a split axis.

## 4. Runtime parametrisation
Each procedure consumes the concrete Service under test and the template-rendering System mechanism it lies on.
It consumes the Endpoint path, the BaseURL, the Header set including cookies and content type, the Parameter atoms where the logical DataItem surfaces as form fields or template variables or file metadata, and the prior HTTP history of baseline responses.
The operator knowledge base supplies the test credentials, the suspected engine family from prior enumeration, the reachable-global hints, the gadget-index offsets, and the callback-listener address from prior setup.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is a deployed application where the agent holds anonymous HTTP access plus low-privilege test credentials and suspects that user input reaches a server-side template renderer as syntax.
S1 Find templated input: enumerate preview panes and email previews and dashboards and custom fields and theme endpoints, with completion when each candidate input sink is listed.
S2 Fingerprint the engine: run the differential arithmetic probe table with a confirming second probe, with completion when exactly one probe grammar evaluates or error text names the engine.
S3 Confirm evaluation, not reflection: show arithmetic evaluation (`{{7*7}}` rendering as `49`) rather than literal echo, with completion when a second expression rules out coincidence and the XSS line is adjudicated.
S4 Probe sandbox state: spray reachable globals and reflection roots, with completion when the gadget pool or its denial is recorded.
S5 Enumerate gadgets: walk classes and reflection paths and require chains reachable from the pool, with completion when at least one shell-equivalent chain or a definitive negative is recorded.
S6 Reach RCE: pick the shortest gadget chain to a shell-equivalent primitive, with completion when command execution is demonstrated or the chain is proven absent.
S7 Validate side effects: prove execution through DNS callback or file write or sleep delta, with completion when an observable effect is tied to the payload.
S7 file-read follow-up invokes `path-traversal-lfi-rfi` at that step, so this class names that skill instead of restating traversal reads.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Render topology with oracle (same-response reflection versus stored deferred render versus no visible output with time or OAST or length oracle) | Yes (body comparison versus endpoint sweep versus latency measurement versus callback wait are different kinds of action across S1, S3, S7) | No (S1 plus S3 same-response text cannot cover store-in-A sweep-every-endpoint-B or sleep or callback or length-diff detection) | Discriminator (class signature, collapsed per STATE 3 branch 3a) | S1 at 272 versus S3 at 274 versus blind text at 58-129 and references 4-8 |
| Engine label and version (Jinja versus Twig versus Freemarker versus ERB versus EJS and library versions) | No (swapping engines preserves the probe-confirm-walk-invoke kind and only swaps payload literals) | Not applicable | Non-discriminator by instruction and stability criterion | Lines 25-31 versus task caution and SPEC section 8 |
| Sandbox escape grammar (attribute indirection, class-walk recovery, string games, aliasing, conversion, token splitting, encoding layering, precedence, null byte, unicode, polyglot) | Yes (escape-recovery differs from direct invocation as a tester action) | Yes (the bypass section enumerates every escape value with no residue) | Aspect inside each variant, not a variant axis | Lines 233-253 versus S4 at 275 through S6 at 277 |
| Differential probe grammar alternatives (comment-syntax and filter-syntax differentials, string-multiplication engine distinguishers) | Yes (choosing a distinguishing grammar differs from repeating one probe) | Yes (lines 41-56 enumerate every differential with a second-probe rule) | Aspect inside reflected variant | Lines 41-56, 299-305 versus S2 at 273 |
| Input envelope and second-order pipeline (form versus JSON versus GraphQL variables, filenames, YAML or TOML or JSON values, format-string chains, Markdown downstream) | Yes (tracing a multi-stage pipeline differs from point probing) | Yes (S1 input-shape list plus the polyglot section enumerate every pipeline value) | Aspect inside each variant | Lines 12-23, 250-253 versus S1 at 272 |
| Readout channel shape (body versus error text versus email versus PDF) | No (reading a body versus reading an error or a document is the same kind of inspection action) | Yes (recon text enumerates every readout) | Non-discriminator, parametrises S2 and S3 | Lines 35-39, 56 versus S2 and S3 |
| Attack goal (RCE versus exfiltration versus persistence versus lateral movement) | No (goal changes the objective while the confirmation action stays the same) | Not applicable (goals are achieved through variants, not instead of them) | Non-discriminator | Lines 255-268 |
| Attacker capability (anonymous versus authenticated versus template-editor tenant versus callback operator) | No (one credential or listener versus another is the same kind of setup action) | Not applicable | Non-discriminator and runtime parameter | Lines 66-88, 120-124 |
| Defensive control presence as pass or fail (sandboxed versus open) | No standalone (a control changes success likelihood, while the escape grammar that defeats it is already an aspect) | Yes as detection (each step records enforcement versus bypass) | Non-discriminator standalone | Lines 149, 177, 190-198, 282 |
| Concrete Service, System, Endpoint, Parameter, DataItem, BaseURL, Header, HTTP history, payload literal, engine version, gadget index | No (swapping any runtime asset preserves the procedure) | Not applicable | Non-discriminator by stability criterion | SPEC section 4 runtime list |

## 7. Step-coverage falsification
Stored-deferred value: parent S1 covers point inspection of preview panes and templated fields but parent S1 cannot cover storing a payload in field A and sweeping every endpoint for `49` on endpoint B.
The uncovered reality is the store-then-sweep trigger procedure with its endpoint list from lines 79-88, which needs a multi-request sweep step that S1 never names.
Time-oracle value: parent S3 covers same-response `49` comparison but parent S3 cannot cover confirming evaluation through a measured sleep delta with no reflection anywhere.
The uncovered reality is sleep-payload submission plus separate render triggering plus elapsed-time adjudication from lines 101-106 and references line 6, which needs a latency-oracle step that S3 never names.
OAST-oracle value: parent S3 and S7 cover body comparison and post-RCE validation but neither states using a DNS or HTTP callback as the primary detection oracle before execution is otherwise proven.
The uncovered reality is callback-payload submission plus listener receipt as the confirmation itself from lines 120-128 and references line 7, which needs a callback-oracle step that S3 never names.
Length-diff value: parent S3 cannot cover confirming evaluation through body-length or ETag shifts when the value itself is never visible.
The uncovered reality is the length-differential check from references line 8, which needs a masked-content oracle step that S3 never names.
Reflected value: parent S2 plus S3 name differential probes and `49` confirmation but never state the full differential grammar with the second-expression coincidence-exclusion rule and the XSS-line adjudication.
The uncovered reality is the probe table plus `{{7*8}}` rule plus literal-reflection exclusion from lines 41-56 and 280-301, which needs a differential-proof step that terse S2 plus S3 never spell out.
Escape values: no falsification holds because S4 through S6 plus the bypass section enumerate every escape spelling with no residue.
Pipeline values: no falsification holds because S1 plus the polyglot section enumerate every input shape and chained stage with no residue.
Engine and runtime and goal and capability values: no falsification holds because those values parametrise or follow the owning oracle without changing any step kind.
STATE 2 therefore exits through branch 2b with one collapsed signature feature carrying two values.

## 8. Hypotheses
H1 Single-feature hypothesis on evaluation observability: if observability discriminates, then same-response reflection and blind inference each deserve a variant, and it is falsified if either proposed variant lacks its own non-coverable parent step.
H2 Single-feature hypothesis on sandbox confinement: if confinement discriminates, then open evaluation and sandbox escape each deserve a variant, and it is falsified if the escape grammar adds no step beyond the S4 through S6 defeat enumeration or if the blind confirmation gap is left uncovered by both variants.
H3 Combined-feature hypothesis on observability crossed with confinement: if the combination discriminates, then reflected-direct and reflected-escape and blind-direct and blind-escape emerge as products, and it is falsified if any product adds no step beyond its parents under branch 5a.
H4 Single-feature hypothesis on engine family: if engine discriminates, then Python-engine and Java-engine and Node-engine and Ruby-engine and PHP-engine variants emerge, and it is falsified if an engine swap preserves the procedure kind and only swaps payload literals.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | ssti-reflected-evaluation | S3 Confirm evaluation (with S2 carried) | Differential probe table, second-expression coincidence rule, literal-reflection XSS adjudication, comment and filter syntax differentials, error-text fingerprinting |
| H1 | ssti-blind-evaluation | S1 Find templated input | Store-then-sweep every endpoint, time-based latency oracle, OAST callback oracle, length and ETag diff oracle, file-write trigger oracle |
| H2 | ssti-open-evaluation; ssti-escape-evaluation | none cleanly for open (S4 through S6 describe it) and S4 for escape | Escape grammar as the escape variant body, with the blind confirmation gap owned by neither variant |
| H3 | reflected-direct; reflected-escape; blind-direct; blind-escape | S3 for reflected cells and S1 for blind cells, with no product adding its own step | Escape spellings and blind oracles recombined per cell with zero product-level delta |
| H4 | per-engine cells (python, java, node, ruby, php, dotnet) | none per cell (each reuses S1 through S7 kinds with swapped literals) | Engine payload catalogues as runtime knowledge-base parameters |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage pass because every falsified observability value belongs to exactly one variant and escape plus pipeline values ride as aspects inside both.
H1 scores disjointness pass because same-response `49` proof and non-same-response inference admit no shared technique, with routing by first non-coverable step in methodology order (S1 divergence claims blind, otherwise S3 claims reflected).
H1 scores divergence delta pass because reflected adds the differential-proof grammar over terse S2 plus S3 and blind adds the sweep plus latency plus callback plus length oracles over S1 plus S3 plus S7.
H1 scores stability pass because swapping engine and version and payload literal and endpoint asset leaves each procedure intact.
H1 scores parsimony pass with one collapsed feature and two variants.
H2 fails coverage because neither open nor escape text describes store-sweep or time or OAST detection, so H2 is discarded per STATE 6 branch 6a without return ambiguity.
H3 fails parsimony and branch 5a because no product adds its own non-coverable step beyond its parents, so its products collapse back to H1 and H3 is discarded per STATE 4 branch 4a.
H4 fails stability because engine cells swap runtime knowledge-base parameters only, so H4 is discarded per STATE 4 branch 4a and the task caution.
Winner is H1 with losing reason for H2 being the uncovered blind gap, for H3 being zero-delta products, and for H4 being technology-axis instability.
No return to STATE 3 was needed because the H1 signature needs no collapse beyond the documented topology plus oracle plus technique folding.
STATE 1 completed with seven parent steps and a full entity inventory and no malformed-class stop.
STATE 2 completed with six non-discriminators and four aspects recorded alongside one collapsed discriminator feature.
STATE 3 branch 3b was not needed because every signature value partitions cleanly with no continuous or overlapping range.

## 11. Recommended set
Discrimination function: SSTI discriminates by evaluation observability, namely whether template evaluation is confirmed by same-response arithmetic reflection or must be inferred without visible reflection through deferred rendering, timing, out-of-band callbacks, or length differentials.
Recommended variant ssti-reflected-evaluation diverges first at S3 with delta of differential arithmetic probe grammar plus second-expression coincidence exclusion plus literal-reflection adjudication that terse S2 plus S3 never spell out.
Recommended variant ssti-blind-evaluation diverges first at S1 with delta of store-then-sweep every endpoint plus time-based latency plus OAST callback plus length-diff detection oracles that S1 plus S3 plus S7 never state as detection procedure.
Non-discriminators are all engine labels with versions as TechnologyStack, all L0 and L1 runtime assets including Service and System and Endpoint and Parameter and DataItem and BaseURL and Header and HTTP history, all payload literals with gadget indices, all attack goals, the full capability ladder, control presence as pass or fail, and readout channel shapes.
Aspects carried inside both variants are the sandbox-escape grammar, the probe-grammar alternatives, the input envelopes with second-order pipelines, and error-text fingerprinting.
STATE 4 hypothesised two single-feature splits on observability and confinement plus one combined split plus one engine split, all falsifiable by the step test.
STATE 5 derived four variant sets and deleted every zero-delta product under branch 5a.
STATE 6 scored all sets on weighted criteria and selected H1 for coverage plus disjointness plus delta plus stability plus parsimony.
STATE 7 recommends the two-variant set stated in this section.
Outlier: Thymeleaf normal model binding never re-evaluates `${userInput}` as SpEL so template-source control is a class-scope precondition guarding both variants rather than a variant axis, and client-side template injection is out of class scope because its impact is XSS rather than server-side execution.
Grey point: stored payloads that reflect `49` on a different endpoint ride inside blind evaluation although their oracle is still body comparison, which holds only while the store-then-sweep trigger procedure is what distinguishes them.
Grey point: sleep and OAST serve as detection oracles inside blind evaluation and as post-RCE validation inside both variants, which holds only while the using step (S3 detection versus S7 proof) routes the technique.
Grey point: sandbox escape rides as an aspect inside both variants rather than a standalone variant, which holds only while escape stays gadget search of the same kind with fully enumerated spellings.
Grey point: multi-stage pipelines (format-string output and Markdown content reaching a template) ride as S1 aspects, which holds only while tracing needs no procedure beyond shape enumeration plus per-stage probes.
Open questions: no FAIL-level uncertainty blocks this recommendation.
Open question at note level: engine-specific gadget-index drift (such as Jinja subclass offsets) stays a runtime knowledge-base fact and never promotes an engine cell to a variant.
