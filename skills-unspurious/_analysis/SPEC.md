# Skills-suite variant decomposition - operational spec (W0)

*Working spec for the decomposition fleet. Single source of truth for the creator and reviewer prompts. The polished boundary document (`docs/design/skills-variant-boundary.md`) is written from this spec after all classes are processed.*

## 1. Problem framing

The suite must hold fine-grained variants of each web-vulnerability class.
A variant is a skill derived from a parent class by a genuine divergence in the testing procedure.
The risk we are eliminating is drift: coarse skills that hide genuinely different procedures, or over-split skills that duplicate one procedure under many names.

There is **no vuln-agnostic discriminating variable**.
Each class has its own inherent characteristics, and each class must be discriminated on those.
A fixed menu (observation channel, surface family, protocol, trust assumption, impact) is wrong: for one class the trust assumption *is* the class definition, for another it is irrelevant, and surface/protocol/technology are runtime or class-selection concerns, not variant axes.

## 2. Core idea

A variant exists **iff** a step of the parent methodology cannot describe a candidate procedure accurately and exhaustively.
The discriminator is not chosen from a menu; it is **derived per class** by finding which ontology entity value bends a step.

The test has two halves, and both must pass before a candidate counts as a variant:

- **Accurate** - the parent step performs the same *kind* of action as the candidate step.
- **Exhaustive** - the parent step's description covers **every value** the candidate step can take.

If both hold, the candidate is an aspect or an extension of the parent.
If either fails, the candidate is a variant.

## 3. The algorithm (decision tree)

Run this per class. The states, branch conditions, actions, and outlier states are exact.

```
STATE 1 - CLASS INVENTORY
  Action: list the class's methodology steps (from its `## Testing Methodology` and detection sections).
  Action: list the class's ontology entity values (section 4).
  Branch 1a: the class has no methodology steps -> STOP, report malformed class (outlier).

STATE 2 - FEATURE TEST (run for every candidate feature)
  For each ontology entity value V and each RDF notion section N:
    Question A (accurate): if V changes, does some parent step perform a different kind of action?
      No  -> V is a NON-DISCRIMINATOR for this class. Record why. Go to next feature.
      Yes -> ask Question B.
    Question B (exhaustive): can the parent step's description cover every value of V?
      Yes -> V is an ASPECT (documented inside the parent variant). Go to next feature.
      No  -> V is a DISCRIMINATOR. Record the failing step and the uncovered value.
  Branch 2a: no discriminator found -> the class does not decompose. Emit ONE skill. Go to STATE 6.
  Branch 2b: at least one discriminator -> go to STATE 3.

STATE 3 - SIGNATURE
  Action: the set of discriminators is the class's discrimination signature.
  Action: enumerate every value of each signature feature.
  Branch 3a: two signature features always co-vary (one value of A implies one value of B) -> collapse into one feature (avoid overlap).
  Branch 3b: a feature has continuous or overlapping values (no clean partition) -> document it as an aspect inside the nearest variant, not a variant axis.

STATE 4 - HYPHOTHESISE (define-hypothesis format)
  Action: state at least one single-feature hypothesis and one combined-feature hypothesis.
  Action: each hypothesis predicts a variant set and is falsifiable by the step test.
  Branch 4a: a hypothesis fails the step test for any of its proposed variants -> discard it and say why.

STATE 5 - DERIVE VARIANT SETS
  For each surviving hypothesis:
    Action: derive its variant set. A variant is named by its FIRST non-coverable step in methodology order.
    Action: document secondary divergences inside the variant; a secondary divergence is a rework trigger, not a new variant, unless it adds its own non-coverable step (branch 5a).
    Branch 5a: a combination yields a step no single-feature variant covers -> emit a combined variant (product) only if it has its own non-coverable step.
  Action: evaluate each set in STATE 6.

STATE 6 - WELL-FORMEDNESS EVALUATION
  Criteria, in weight order:
    Coverage (critical): every genuine non-coverable step belongs to exactly one variant.
    Disjointness (critical): no technique falls in two variants.
    Divergence delta (high): each variant adds a non-coverable step over the parent; a variant with no delta is deleted.
    Stability (high): variants survive a change of technology stack, payload, library version, or runtime asset (those are excluded axes).
    Parsimony (medium): fewest features that still cover.
  Action: score each hypothesis's set against all criteria; state the winner and the losing reason.
  Branch 6a: the winner fails coverage or disjointness -> return to STATE 3 with the failure named.
  Branch 6b: the winner is well-formed -> go to STATE 7.

STATE 7 - RECOMMENDATION
  Action: state the class-specific discrimination function as one sentence (the signature).
  Action: list the recommended variants, each with its non-coverable step and its divergence delta.
  Action: list non-discriminators explicitly.
  Action: list open questions and grey points.
```

## 4. The ontologies to pin (deduction, not induction)

Every class analysis must fill an **ontology entity ledger**.
Pin every value; state `none` where the class has none.
The derivation of discriminators must be deductive from these values plus the step test - never an induction from surface patterns.

Methodology entities (closed set of 10, from `lightrag/data/lightrag/prompts/entity_type/methodology_entities.yml`):

- `PreconditionEnvironment` - target/environment condition that must be true for a technique to apply.
- `TechnologyStack` - technology/product/framework/protocol/component present in the target.
- `DefensiveControl` - target mechanism intended to prevent, limit, or detect an attack.
- `VulnerabilityClass` - the weakness class in the target.
- `AttackGoal` - strategic result the attacker wants.
- `AttackerCapability` - access/control/operational ability the attacker already has.
- `AttackTechnique` - concrete action performed by the attacker.
- `PayloadPattern` - reusable parameterised structure of malicious input.
- `Artifact` - concrete object obtained or produced during an attack and reusable later.
- `ObservableSignal` - observable evidence indicating relevant behaviour or possible technique success.

RDF notions (from `docs/design/skills-system-decomposition.md`): vuln-specific attack surface and reconnaissance; adversarial capabilities; common trust assumptions; testing methodology; proxy techniques; defence bypass techniques; techniques anti-patterns; scripted tests (`references/`); false positives; chaining.

Runtime parametrisation (non-discriminators, from the L0/L1 graph in `docs/design/domain-model.md`): the concrete Service, System, Endpoint, Parameter, DataItem, BaseURL, Header, and the HTTP history.
These are supplied at runtime from the attack-surface graph, the knowledge base, and the HTTP history.
They parametrise a variant; they never define one.

## 5. Required analysis format

Write one Markdown file per class at `skills-unspurious/_analysis/<class>.md`, with exactly these sections:

1. `# <class> - variant decomposition analysis`
2. `## 1. Class and scope` - what the class is, which file it comes from, one paragraph.
3. `## 2. Ontology entity ledger` - a table with one row per methodology entity type: value(s), source line(s) in the skill, role (discriminator candidate / non-discriminator / runtime).
4. `## 3. RDF notion map` - per notion section, what the class holds; note what varies and what is invariant.
5. `## 4. Runtime parametrisation` - the L0/L1 entities the variant consumes at runtime; hence non-discriminators.
6. `## 5. Agent-with-skill walkthrough` - the realistic hunting circumstance, then the parent methodology steps, each described as an action with its completion condition.
7. `## 6. Feature-verdict table` - one row per candidate feature: accurate? exhaustive? verdict (discriminator / aspect / non-discriminator), evidence.
8. `## 7. Step-coverage falsification` - per feature value, the exact parent step and the uncovered reality.
9. `## 8. Hypotheses` - H1..Hn in define-hypothesis format, single and combined, each falsifiable.
10. `## 9. Variant sets per hypothesis` - a table, each variant with its non-coverable step.
11. `## 10. Well-formedness evaluation` - criteria, weights, per-set scores, winner, losing reason.
12. `## 11. Recommended set` - the class-specific discrimination function (one sentence) and the variant list with deltas; non-discriminators; open questions.

## 6. Acceptance criteria (what the reviewer checks)

The analysis PASSES only when all of these hold:

1. Every one of the 12 sections is present and non-empty.
2. All 10 methodology entity types are addressed; `none` is stated where applicable.
3. The discriminator derivation is **deductive**: each discriminator traces to a named ontology entity value and a named step, not to a surface pattern or a universal menu.
4. Every recommended variant satisfies the two-half test: a named parent step whose description is neither accurate nor exhaustive for it.
5. Every recommended variant has positive divergence delta, is disjoint from its siblings, and is stable against technology, payloads, versions, and runtime assets.
6. Non-discriminators are stated explicitly with the reason.
7. The hypotheses are falsifiable and the evaluation uses the weighted criteria.
8. No workflow state (STATE 1-7) is skipped; any outlier was reported, not hidden.
9. No em dashes; one full sentence per line where prose is authored.

Any failure -> verdict FAIL with the section, the violated criterion, and the exact line.
The reviewer must ground its verdict on the **faithfulness and robustness of the argumentation**: does the deduction actually follow, and would the variant set survive an adversarial change of assumptions.

## 7. Skills bounded to their step

When a class analysis reaches a step owned by another skill, it names that skill instead of restating it.
Known cross-references: `two-principal-authz` for the BOLA/authorization principal step; `race-conditions` for the TOCTOU step; the `defence-bypass` and `proxy-techniques` families (#278) for bypass/proxy steps; `graphql` for GraphQL-specific steps; `oauth`/`authentication-jwt` for token steps.

## 8. Pitfalls (from four prior walkthroughs)

- Imposing a universal axis. Trust-assumption is the class definition for BOLA and inapplicable to prototype pollution.
- Treating surface family, protocol, or pure impact as a discriminator without tracing it to a bent step.
- Accepting a step description that is plausible but not exhaustive.
- Splitting by payload context (XSS HTML/attribute/URL) or by identifier encoding (IDOR integer vs UUID); those are aspects.
- Over-splitting (two variants, no divergent step) and under-splitting (a non-coverable step left in the parent).
- Letting technology stack or library versions discriminate; versions are runtime KB facts.
