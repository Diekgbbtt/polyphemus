# The skills variant boundary

*Status: proposed, awaiting operator review. This document is the single authority on how a vulnerability-testing skill decomposes into variants. It is written from the twenty-nine class analyses in `skills-unspurious/_analysis/` (each reviewed and PASSed by an independent reviewer). Every document about skills references this one.*

## The problem

The suite must hold skills at a fine, even granularity.

Two failures threaten that granularity.

The first is **coarseness**: one skill silently holds two different procedures, so an executing agent reads a generalisation that is wrong for one of them and improvises the gap.

The second is **over-splitting**: many skills repeat one procedure under different names, so the suite grows without adding capability and the taxonomy becomes noise.

A description of a variant that is either too loose or too tight produces both failures at once.

The root cause of both is the same: a decomposition decided by intuition about which differences "look important".
Different agents pick different seams.
The suite drifts.

## The core idea

A variant exists because a step of the parent procedure does not fit a candidate.

The test is a single question, asked of every candidate difference and answered in two halves.

- **Accurate** - does some parent step perform the same kind of action as the candidate step?
- **Exhaustive** - can that parent step's description cover every value the candidate step can take?

A parent step that answers yes to both **covers** the candidate, and the difference is an **aspect** inside the parent.
A candidate with no covering step has a **bent step**, and it is a **variant**.

The discriminator is not chosen from a menu.
It is **derived per class**: you find the ontology entity values that bend a step, and those values are the class's **signature**.
There is no vuln-agnostic discriminating variable.
For one class the trust assumption is the class definition, for another it is irrelevant, and the surface and protocol are usually runtime or class-selection concerns rather than variant axes.

## The expected outcome

Each class yields one of two results.

Either the class **does not decompose**, and it stands as one skill.
Or it decomposes into a **well-formed set** of variants, each named by its first bent step, each with a positive **delta** over the parent, and each disjoint from its siblings.

A well-formed set satisfies five criteria.

- **Coverage** (critical): every bent step belongs to exactly one variant.
- **Disjointness** (critical): no technique falls in two variants.
- **Divergence delta** (high): every variant adds a bent step the parent cannot describe; a variant with no delta is deleted.
- **Stability** (high): the variants survive a change of technology stack, payload, library version, or runtime asset.
- **Parsimony** (medium): the fewest discriminators that still cover.

The architecture stays invariant across every variant; only the bent steps move.
This document defines the vocabulary the rest of the suite obeys.

## Vocabulary

- **parent** - the class skill being decomposed, for example `ssrf`.
- **step** - one action in the parent methodology, with a completion criterion.
- **cover** - a parent step covers a candidate step when it is accurate and exhaustive.
- **bent step** - a candidate step that no parent step covers.
- **discriminator** - an ontology entity value whose change bends a step.
- **signature** - the set of discriminators of one class.
- **variant** - a skill emitted for one bent step, or for a set of candidates that share one bent step.
- **aspect** - a value difference the parent step still covers; it stays inside the variant as a documented sub-block.
- **delta** - the bent step and the concrete sub-actions a variant owns over the parent.
- **outlier state** - a condition the algorithm names and reports rather than hides.

## The algorithm

Seven states run in order for one class.
Each state names its entry, action, branches, and exit.
A branch that leaves the main line is stated with its condition.

### STATE 1 - Class inventory

**Entry**: a class skill with its body and any `references/`.
**Action**: list the parent methodology steps (each as an action with a completion criterion), then pin every ontology entity value (section "Ontology entities").
**Branch 1a** (outlier): the class carries no methodology steps -> STOP, report a malformed class.
**Exit**: the step list and the entity ledger are complete.

### STATE 2 - Feature test

**Entry**: STATE 1 complete.
**Action**: for each entity value and each RDF notion, run the two-half test.
**Branch 2a**: no value bends a step -> the class does not decompose; emit ONE skill; go to STATE 6.
**Branch 2b**: at least one value bends a step -> go to STATE 3.
**Exit**: every value carries a verdict of discriminator, aspect, or non-discriminator, each with the failing step and the uncovered reality quoted.

### STATE 3 - Signature

**Entry**: STATE 2 found at least one discriminator.
**Action**: collect the discriminators into the class signature and enumerate each one's values.
**Branch 3a**: two discriminators always co-vary, so one value of the first implies one value of the second -> collapse them into one discriminator.
**Branch 3b**: a discriminator's values are continuous or overlap with no clean partition -> keep it as an aspect inside the nearest variant, not as an axis.
**Exit**: the signature is minimal and each discriminator's values partition cleanly, or the collapse is recorded.

### STATE 4 - Hypothesise

**Entry**: a clean signature.
**Action**: state at least one single-discriminator hypothesis and one combined hypothesis, each in the form "we believe X splits the class into Y", each falsifiable by the step test.
**Branch 4a**: a hypothesis predicts a variant whose step is actually coverable -> discard that hypothesis and quote the covering step.
**Exit**: at least one surviving hypothesis.

### STATE 5 - Derive variant sets

**Entry**: a surviving hypothesis.
**Action**: for each hypothesis derive its variant set, naming each variant by its first bent step in methodology order, and carrying secondary divergences inside it.
**Branch 5a**: a combination of discriminators yields a step no single-discriminator variant covers -> emit a combined variant, but only if it owns its own bent step.
**Branch 5b**: two proposed variants share all steps, or a variant's only difference is a runtime location folded into the sink -> delete one and record the merge.
**Exit**: one variant set per surviving hypothesis.

### STATE 6 - Well-formedness evaluation

**Entry**: one or more variant sets.
**Action**: score each set on the five criteria with their weights, and state the winner with the losing reason.
**Branch 6a**: the winner fails coverage or disjointness -> return to STATE 3 with the failure named.
**Branch 6b**: the winner is well-formed -> go to STATE 7.
**Exit**: the winning set, or a return to STATE 3.

### STATE 7 - Recommendation

**Entry**: a well-formed set.
**Action**: state the class-specific discrimination function in one sentence, list the variants with their bent step and delta, list every non-discriminator explicitly, and list the open questions and grey points.
**Exit**: the analysis is complete.

## Ontology entities to pin

Every class pins all ten methodology entity types from `lightrag/data/lightrag/prompts/entity_type/methodology_entities.yml`.
State `none` where the class has none.

- `PreconditionEnvironment` - target or environment condition that must be true for a technique to apply.
- `TechnologyStack` - technology, product, framework, protocol, or component in the target.
- `DefensiveControl` - target mechanism intended to prevent, limit, or detect an attack.
- `VulnerabilityClass` - the weakness class in the target.
- `AttackGoal` - the strategic result the attacker wants.
- `AttackerCapability` - access, control, or operational ability the attacker already has.
- `AttackTechnique` - a concrete action performed by the attacker.
- `PayloadPattern` - a reusable, parameterised structure of malicious input.
- `Artifact` - a concrete object obtained or produced during an attack and reusable later.
- `ObservableSignal` - observable evidence of relevant behaviour or possible success.

Two further ontologies scope the analysis.
The **RDF notions** (`docs/design/skills-system-decomposition.md`) are the skill's sections; every notion is mapped and marked varying or invariant.
The **L0/L1 graph entities** (`docs/design/domain-model.md`: Service, System, Endpoint, Parameter, DataItem, BaseURL, Header) are the **runtime parametrisation**; they scope a variant at execution time and never define one.

## Skills bounded to their steps

A class names another skill at a step that the other skill owns, instead of restating it.
The known cross-references are:

- `two-principal-authz` at the authorization principal step.
- `race-conditions` at the TOCTOU step.
- the `defence-bypass` and `proxy-techniques` families (#278) at bypass and proxy steps.
- `graphql` at GraphQL-specific steps.
- `oauth` and `authentication-jwt` at token and flow steps.

## Worked example - `ssrf`

The `ssrf` analysis (`skills-unspurious/_analysis/ssrf.md`) is reproduced here in condensed form.

**STATE 1.** The parent methodology has eight steps.
S1 inventories surfaces.
S2 establishes the oracle.
S3 pivots to internal addressing.
S4 tests protocol variations.
S5 tests parser differentials.
S6 tests redirect behaviour.
S7 tests header and method control.
S8 targets high-value assets.

**STATE 2.** The two-half test runs over the pinned values.
Plain direct HTTP addressing covers S3 and S8, so it stays the parent baseline, not a variant.
Parser families cover S5 exhaustively, and redirect depth covers S6, so both stay aspects.
Three values do not cover.
Egress visibility direct versus no-response fails S2: the quiet-callback description cannot describe per-token correlation plus timing, size, TLS, and ETag differencing plus timeout binary-search port mapping.
Scheme translation HTTP versus gopher, file, and dict fails S4: the handler-variation description cannot describe raw text-protocol grammar crafting.
Header and method control absent versus controlled fails S7: the single-fetch question cannot describe a PUT token fetch followed by an authenticated metadata GET.

**STATE 3.** `ObservableSignal` collapses into egress visibility because each signal value implies exactly one visibility value.
Contrary to the intuition that "protocol" is an axis, the protocol difference is a value of `AttackTechnique`, not a separate feature.
Technology stack, defensive control alone, the class itself, impact alone, attacker capability, payload families, evidence artifacts, and the high-value-target name are all non-discriminators.

**STATE 4.** H1 (egress visibility alone) is falsified because scheme translation and header gating need steps beyond oracle handling.
H2 (request expressive power alone) is falsified because no-response inference needs a step beyond request construction.
H3 (visibility crossed with expressive power) survives.

**STATE 5.** H3 yields three variants, each named by its first bent step.
`no-response-egress-inference` (S2) owns per-token correlation plus timing, size, TLS, and ETag differencing plus timeout port mapping.
`scheme-translated-command-execution` (S4) owns raw-protocol grammar crafting plus wrapper-aware file reads, scoped to a direct oracle.
`header-gated-cloud-credential-read` (S7) owns token-then-read sequencing plus flavour-gated GET flows, scoped to a direct oracle.
Branch 5a emits no blind-translated product because blind craft adds no step beyond S2 inference plus S4 craft carried as a secondary.
Branch 5a emits no blind-gated product for the same reason.
Blind translated and blind gated cases are carried as secondary divergences because S2 precedes S4 and S7 in methodology order.

**STATE 6.** H1 loses because protocol smuggling and header-gated sequencing have no home.
H2 loses because no-response statistical inference has no home.
H3 wins: coverage, disjointness, delta, stability, and parsimony all pass.

**STATE 7.** SSRF discriminates by server egress observability crossed with server request expressive power.
The recommended set is the three variants above, with plain direct HTTP internal mapping as the parent baseline.
The open questions are whether file-wrapper reads deserve separation from gopher command craft, and how blind-translated cases should be attributed.

## Pitfalls

These are the outlier states and traps observed across the twenty-nine analyses.

- Imposing a universal axis. `proxy-techniques` and `defence-bypass` are families, not class axes; trust-assumption is the class for authorization and irrelevant for prototype pollution.
- Treating a runtime location folded into a sink as a delta. A variant that only relocates the same step is deleted (branch 5b).
- Accepting a step description that is plausible but not exhaustive. The exhaustive half is what separates an aspect from a variant.
- Splitting by output context (XSS HTML, attribute, URL) or by identifier encoding (IDOR integer, UUID). Those are aspects.
- Letting technology stack or library versions discriminate. Versions are runtime knowledge-base facts.
- Letting pure impact or severity discriminate. Impact bends a step only through a required request shaping.
- Under-splitting: a bent step left inside the parent is the coarseness failure this whole document exists to prevent.
- Over-splitting: two variants with no divergent step are a merge waiting to happen.
