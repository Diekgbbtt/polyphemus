# mass-assignment - variant decomposition analysis

## 1. Class and scope
Mass assignment is unauthorized field binding where client-supplied attributes flow into models or DTOs without field-level allowlists and produce privilege, ownership, gate, or billing effects.
Authority is `skills-unspurious/mass-assignment/SKILL.md` (138 lines), consulted against `skills/mass-assignment/SKILL.md` only for extra methodology detail.
Scope covers flat singleton injection as parent baseline plus nested relation writes through serializers or ORM helpers plus bulk collection injection with per-item gaps plus their nested bulk product across REST, GraphQL, and alternate encodings.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | Automatic model binding in controllers or resolvers; writable nested serializers or ORM relations; sparse or patch update support; bulk or batch endpoint with per-item enforcement gap; GraphQL input types mirroring models; inconsistent allowlists across channels | 12-16, 20-24, 35-46, 68-70, 82-86, 89-93 | Discriminator candidate (resolves to D1 depth and D2 cardinality in section 6) |
| TechnologyStack | REST with JSON; GraphQL; form-encoded and multipart bodies; text plain; Rails; Laravel; Django REST Framework; Mongoose; Prisma | 12-16, 42-44, 82-86 | Non-discriminator (excluded axis under stability) |
| DefensiveControl | Field-level allowlist; per-field authorization; read-only marking with consistent enforcement; server recomputation of derived fields; per-item bulk allowlist | 8, 89-93, 105-106, 122-126, 136-138 | Non-discriminator (control presence is invariant and evasion detail rides as aspect) |
| VulnerabilityClass | Mass assignment with unauthorized field binding | 8 | Non-discriminator (this is the class definition itself) |
| AttackGoal | Privilege escalation through role flags; ownership takeover through tenant identifiers; feature gate bypass through flags and quotas; billing manipulation through plan and credit fields | 48-67 | Non-discriminator (goal changes reporting, never the testing action) |
| AttackerCapability | Authenticated non-privileged caller able to create or update reachable objects and resubmit with added fields | 48-52, 117-121 | Non-discriminator (shared setup before any variant diverges) |
| AttackTechnique | Flat sensitive-field injection; nested or relation write; shape reshaping with dot or bracket paths and duplicate keys; content-type switching; batch per-item injection; nested bulk injection; GraphQL input addition with overfetch; race with reorder | 33-44, 68-80, 94-112 | Discriminator candidate (partitions by which step it bends, see section 6) |
| PayloadPattern | Sensitive-field names for role, ownership, limits, flags, and billing; dot or bracket paths; duplicate-key bodies; JSON Patch or Merge Patch paths; array versus scalar alternates | 27-44 | Aspect (defeat detail carried inside the owning scope variant) |
| Artifact | Per-resource candidate dictionary; before-and-after state diffs; OpenAPI or GraphQL schema excerpts; client bundle or mobile app field names; SDK mutation examples | 20-24, 117-121, 128-134 | Non-discriminator (runtime-produced evidence that parametrises proof) |
| ObservableSignal | Persisted forbidden value in a response, later GET, or overfetch; silent persistence without response echo; recomputed field ignoring input; UI-only change without persistence | 117-126 | Non-discriminator (detection signal shared by all variants) |

## 3. RDF notion map
Vuln-specific attack surface and reconnaissance: binding controllers, nested relations, patch formats, bulk endpoints, schema sources, and client bundles with parameter strategies and shape variants (lines 10-45), and this notion varies by depth and cardinality and supplies the discrimination material.
Adversarial capabilities: an authenticated non-privileged caller able to create and update objects and resubmit with added fields (implied by lines 48-70 and 117-121), and this notion is invariant setup shared by all variants.
Common trust assumptions: client fields are safe to bind, read-only markers and derived-field recomputation hold, and one encoding allowlist covers all channels (lines 8, 89-93, 136-138), and each assumption is tested inside every variant rather than defining one.
Testing methodology: the six steps S1 to S6 listed in section 5 (lines 113-121), and this notion is the invariant step-test substrate.
Proxy techniques: the class holds no proxy notion, and no hidden proxy step was found.
Defence bypass techniques: content-type switching, key-path reshaping, batch smuggling, and race with reorder (lines 94-112), and this notion varies only as defeat detail carried inside scope variants except race which is owned elsewhere.
Techniques anti-patterns: the class states no dedicated anti-pattern section, and the operative warning is to require durable state proof rather than UI-only effects.
Scripted tests (`references/`): none are shipped with the class skill, and no invariant is stated.
False positives: server recomputation ignoring input, consistent read-only enforcement, and UI-only changes without persistence (lines 122-126), and this notion is invariant confirmation discipline across variants.
Chaining: the class names no chaining section, and cross-tenant moves plus verification-flag toggles are reported as impact rather than chained procedures.

## 4. Runtime parametrisation
Each variant consumes the concrete Service under test, the System mechanism overlays it lies on, and the Endpoint plus Parameter, Header, DataItem, and BaseURL atoms that locate the writable fields at runtime.
The HTTP history supplies the baseline verb and body shapes, the per-role transcripts, and the before-and-after diffs that each variant compares against.
The operator knowledge base supplies the resource inventory, the role roster, and the ORM or framework hints that parametrise dictionary entries and nested paths.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is an agent holding a non-privileged session against an application with create or update endpoints where extra fields may bind into protected attributes.
S1 Identify endpoints: enumerate create and update endpoints with GraphQL mutations, with completion when each target action has a reachable baseline request.
S2 Capture responses: record returned fields with schemas and client hints, with completion when the visible attribute set is listed per resource.
S3 Build sensitive-field dictionary: assemble per-resource candidates for role, ownership, limits, flags, and billing, with completion when each resource has a seeded candidate list.
S4 Inject candidates: send each candidate alongside a legitimate update across transports and encodings, with completion when each candidate has a paired attempt beside its control.
S5 Compare state: diff before-and-after state across roles with fresh reads, with completion when each attempt has a durable persistence verdict.
S6 Test variations: exercise nested objects, arrays, alternate shapes, duplicate keys, and batch operations, with completion when each structural shape has a recorded decision.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| AttackGoal semantic (privilege versus ownership versus gates versus billing) | No (all four use the same kind of action: add candidate field and diff persisted state) | Not applicable | Non-discriminator | S3 at line 119 and S5 at line 121 enumerate all semantics under one dictionary plus one diff action |
| TechnologyStack name (REST, GraphQL, ORM product, framework) | No (stack name changes tooling, never the binding-testing action) | Not applicable | Non-discriminator | Stability criterion excludes TechnologyStack and section 8 pitfalls exclude library versions |
| Concrete runtime values (which field string, which owner id, which tenant literal) | No (one value versus another is the same kind of action) | Not applicable | Non-discriminator | Values are runtime parameters consumed from the graph, KB, and history |
| ObservableSignal shape (echoed value versus silent persist versus recomputed ignore) | No (signals are read the same way in every variant) | Not applicable | Non-discriminator | Lines 122-126 define confirmation discipline for all variants alike |
| AttackerCapability ladder (which roles, how many sessions) | No (setup is shared before any variant diverges) | Not applicable | Non-discriminator | S5 cross-role diffs assume one working non-privileged session plus a control read |
| DefensiveControl presence (allowlist on versus off) | No (control presence decides verdict, never the probe kind) | Not applicable | Non-discriminator | Lines 122-126 and 136-138 describe enforcement as the invariant to test against |
| Artifact source (schema versus bundle versus SDK versus prior HTTP) | No (source changes harvesting effort, never the injection kind) | Not applicable | Non-discriminator | Lines 20-24 list sources as interchangeable harvest inputs to S2 and S3 |
| PayloadPattern shape evasion (dot or bracket paths, duplicate keys, patch paths, array alternates) | Yes in tooling only (reshaping to reach a binder is a distinct trick) | Yes as defeat detail (S4 names transports and encodings while S6 names shapes and duplicate keys) | Aspect, not variant axis | Lines 33-44 and 94-102 describe reshaping that rides inside whichever scope variant owns the field |
| Content-type switching (JSON versus form versus multipart versus text) | No (same candidate through another framing is the same kind of action) | Yes (S4 explicitly names across transports and encodings) | Aspect, not variant axis | Lines 42-44 and 94-97 name switching that any variant repeats without a new step |
| Binding depth (flat direct field versus nested relation write) | Yes (relation traversal with child-scope verdicts performs a different kind of action than flat field addition) | No (S6 names nested objects but never describes relation-graph reasoning or child-object authorization verdicts) | Discriminator D1 | Lines 68-70 versus S6 at line 121 |
| Binding cardinality (singleton object versus bulk collection with per-item gap) | Yes (mid-batch smuggling with per-position verdicts performs a different kind of action than singleton injection) | No (S6 names batch operations but never describes per-position reasoning or first-element-only validation) | Discriminator D2 | Lines 103-106 versus S6 at line 121 |
| Race and reorder timing | Yes (two-update interleaving performs a different kind of action) | Not applicable here (owned step) | Non-discriminator for this class, cross-referenced | Lines 108-112 describe a TOCTOU step owned by `race-conditions` per SPEC section 7 |

## 7. Step-coverage falsification
D1 value nested relation write in a singleton object: parent S6 covers trying nested objects, but the uncovered reality is traversing writable serializers or ORM relations to create or link one child object and judging that child against caller scope.
D1 value flat direct field in a singleton object: no standalone falsification holds because parent S4 covers injecting a candidate alongside a legitimate update and parent S5 covers durable diffs with UI-only exclusion.
D2 value bulk per-item smuggling with flat fields: parent S6 covers trying batch operations, but the uncovered reality is placing a malicious flat object mid-batch where only boundary elements are validated and each position needs its own persistence verdict.
D2 value singleton injection with flat fields: no standalone falsification holds because parent S4 covers single-object injection with paired controls.
D1xD2 product value nested relation write inside a bulk batch: parent S6 covers nested objects plus batch operations as separate shapes, but the uncovered reality is running a per-position outer loop where each batch position needs full relation-graph traversal with its own child-scope verdict.
Goal semantic values: no falsification holds because S3 builds one per-resource dictionary and S5 runs one diff discipline for privilege, ownership, gate, and billing alike.
Shape evasion values: no falsification holds as variant axes because S4 plus S6 enumerate alternate shapes, duplicate keys, and encodings while the owning scope variant keeps the verdict.
Content-type values: no falsification holds as variant axes because S4 explicitly names across transports and encodings for the same candidate.
GraphQL transport values: no falsification holds as variant axes because input-field addition plus fragment overfetch repeats the same inject-and-diff kind with a different framing.
Race values: no falsification is claimed here because the interleaving step is owned by `race-conditions` and each mass-assignment variant records only its binding delta.

## 8. Hypotheses
H1 Single-feature hypothesis on binding depth: if the only discriminator is D1, then the class yields the parent baseline for flat singletons plus one singleton nested-relation variant, and it is falsified if bulk per-position reasoning bends any step beyond singleton S6 handling.
H2 Single-feature hypothesis on binding cardinality: if the only discriminator is D2, then the class yields the parent baseline for flat singletons plus one flat bulk-collection variant, and it is falsified if relation traversal with child-scope verdicts bends any step beyond singleton S6 handling.
H3 Combined-feature hypothesis on depth by cardinality with product: if D1 bends S6 on relation reasoning while D2 bends S6 on per-position reasoning while neither co-varies with the other and their product needs both reasonings at once, then the class yields the parent baseline plus singleton-nested plus flat-bulk plus combined nested-bulk variants, and it is falsified if any proposed variant lacks its own non-coverable step or two variants claim the same depth-by-cardinality input.
H4 Goal-split hypothesis: if privilege, ownership, gate, and billing semantics each deserve a variant, then each goal adds its own non-coverable step, and it is falsified by S3 plus S4 plus S5 naming all four semantics under one dictionary, one injection, and one diff action.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | mass-assignment-nested-relation-write (singleton only) | S6 (relation-graph traversal with child-scope verdicts on one object) | Dot or bracket paths; patch paths; ORM-specific nesting; GraphQL input nesting |
| H1 | parent baseline for flat singleton and all bulk shapes (no variant) | none (S4 plus S5 already cover flat singleton injection with diffs) | Goal semantics; transports; encodings as baseline discipline |
| H2 | mass-assignment-bulk-collection-injection (flat fields only) | S6 (per-position verdicts against first-element-only validation on flat objects) | Array alternates; batch smuggling position; GraphQL aliasing compare |
| H2 | parent baseline for flat singleton and all nested shapes (no variant) | none (S4 plus S5 already cover flat singleton injection with diffs) | Goal semantics; transports; encodings as baseline discipline |
| H3 | mass-assignment-nested-relation-write (singleton nested only) | S6 (relation-graph traversal with child-scope verdicts on one object) | Dot or bracket paths; patch paths; ORM nesting; GraphQL input nesting |
| H3 | mass-assignment-bulk-collection-injection (flat bulk only) | S6 (per-position verdicts against first-element-only validation on flat objects) | Mid-batch smuggling; boundary-only validation; GraphQL aliasing compare |
| H3 | mass-assignment-bulk-nested-relation-write (nested objects inside bulk batches) | S6 (per-position outer loop where each position needs full relation-graph traversal with its own child-scope verdict) | Batch position selection plus serializer or ORM relation reasoning combined |
| H4 | privilege versus ownership versus gates versus billing | none per variant (S3 plus S4 plus S5 already name all four with one action) | Semantic labels only, no procedural delta |

## 10. Well-formedness evaluation
Weights in order are coverage (critical), disjointness (critical), divergence delta (high), stability (high), parsimony (medium).
H1 scores coverage fail because flat bulk smuggling plus nested bulk injection belong to no variant and the parent baseline covers only flat singletons.
H1 scores disjointness pass for its one variant but coverage failure alone discards it per STATE 6 branch 6a.
H2 scores coverage fail because singleton nested traversal plus nested bulk injection belong to no variant, so H2 is discarded per STATE 6 branch 6a.
H4 scores coverage pass formally but fails divergence delta because no goal semantic adds a step over S3 plus S4 plus S5, and it duplicates one procedure under four names, so H4 is discarded per STATE 4 branch 4a.
H3 scores coverage pass because flat singleton maps to the parent baseline while singleton nested plus flat bulk plus nested bulk map each to exactly one variant per the section 7 product row.
H3 scores disjointness pass by deterministic input mutex where singleton versus batch selects the outer home and flat versus nested selects the inner home so no attempt is claimable twice.
H3 scores divergence delta pass because singleton nested adds relation-graph traversal plus flat bulk adds per-position verdicts plus combined nested bulk adds per-position child-scope verdicts that neither single-feature step covers.
H3 scores stability pass because depth and cardinality survive stack, payload, library, and runtime-asset swaps.
H3 scores parsimony pass with two features and three variants as the fewest set that covers both axes plus their proven product step.
Winner is H3, with losing reason for H1 and H2 being coverage failure and for H4 being zero-delta goal labels.
No return to STATE 3 was needed beyond scoping each variant input because the winner passes coverage and disjointness.
STATE 1 completed with S1 to S6 plus full entity inventory and no malformed-class outlier.
STATE 2 tested every ledger value with both halves and recorded seven non-discriminator groups with reasons.
STATE 3 branch 3a kept depth and cardinality separate because nested singletons, flat batches, and nested batches all occur without co-variance.
STATE 3 branch 3b kept shape evasion, content-type switching, GraphQL framing, and signal shapes as aspects rather than variant axes.
STATE 5 branch 5a emitted the combined nested bulk variant because the product needs per-position child-scope verdicts that neither single-feature variant covers.

## 11. Recommended set
Discrimination function in one sentence: Mass assignment discriminates by binding depth (flat field versus nested relation write) combined with binding cardinality (singleton object versus bulk collection with per-item enforcement) with the nested bulk product owned by a combined variant.
Parent baseline covers flat singleton injection as hardened discipline with minimal single-field isolation beside a control plus durable-state proof under S4 plus S5, and it is not a variant because it adds no non-coverable step.
Recommended variant mass-assignment-nested-relation-write diverges by relation-graph traversal with child-scope verdicts on singleton objects over parent step S6, which names nested objects but never names serializer or ORM relation reasoning or per-child authorization decisions.
Recommended variant mass-assignment-bulk-collection-injection diverges by per-position verdicts against boundary-only validation on flat bulk objects over parent step S6, which names batch operations but never names mid-batch smuggling or per-element persistence decisions.
Recommended variant mass-assignment-bulk-nested-relation-write diverges by per-position child-scope verdicts where each bulk position needs full relation-graph traversal over parent step S6, which names nested objects plus batch operations separately but never names their conjunction.
Non-discriminators are goal semantics with impact labels, TechnologyStack names with versions and transport framings, concrete runtime field and identifier values, the AttackerCapability setup, Artifact evidence objects, ObservableSignal shapes, DefensiveControl presence, and shape or encoding evasion as shared defeat aspects.
Open questions: none at FAIL level, and no uncertainty blocks the baseline plus three-variant recommendation.
Grey points: every batch payload is owned by a bulk-owning variant by outer cardinality first, and every nested relation inside a batch is owned by the combined variant which runs the per-position outer loop with child-scope inner checks.
Grey points: the singleton nested variant takes only non-batch payloads with nested relations, and the flat bulk variant takes only batch payloads with flat fields.
Grey points: dot or bracket reshaping plus duplicate keys plus patch paths ride as defeat aspects inside the owning scope variant, never as standalone variants.
Grey points: content-type switching rides as a defeat aspect inside each variant because S4 already names transports and encodings.
Grey points: GraphQL input addition with fragment overfetch rides as a framing plus confirmation aspect inside each variant, which holds only while GraphQL needs no resolver-hop binding beyond field persistence.
Grey points: race and reorder invokes `race-conditions` mid-procedure, and each mass-assignment variant records only its binding delta.
