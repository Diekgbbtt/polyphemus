# Skills taxonomy (B1 grilling) - decision records

*Status: RATIFIED by the operator across the B1 grilling (three rounds; session `ses_f181eb14bffei9Y8v5O30nGDjG`, 2026-10-03, resumed and closed 2026-10-18). It records the round-2 taxonomy-map answers (D-T1..D-T6), the B2 parent-conformance ruling (D-T7), the B3/B4 outlier records (D-T8, D-T6), and the round-3 parent-contract answers (D-T7, D-T8).*
*Recorded under the `/grill-with-docs` procedure (see `/Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md`): each decision states the ruling, the alternative(s) rejected, and the consequence.*
*The glossary additions land in this document and in the provisional glossary of `docs/design/skills-system-decomposition.md`; no `CONTEXT.md` is minted, because the product-skill catalogue is shared kernel under the operator ruling recorded in `CONTEXT-MAP.md`.*
*The normative deliverable this record feeds is `docs/design/skills-taxonomy.md` (B1).*

---

## D-T1 - The suite root is a logical identity; grouping is the physical directory level

**Ruling.** `web-vulnerability-testing/` is the logical identity of the whole catalogue, not a name segment and not a physical directory.
Physical layout is unchanged: `skills-unspurious/<group>/<leaf>/SKILL.md`, with groups (classes and families) at level 1 and variants nested at level 2.
Group membership is expressed by the directory level, never by metadata tags and never by a manifest index.

**Rejected.** A physical root directory now (move the 30 class dirs under `web-vulnerability-testing/`): rejected in round 1, the W4 loader mounts the root instead.
`metadata.group` tags: rejected in round 2, directory grouping carries the membership.
A tracked `taxonomy.yaml` index: rejected in round 2, no manifest is minted.
Treating `skills-unspurious/` as the root with root-stripped names: rejected, the root must be an explicit logical identity.

**Consequence.** W4 mounts the suite under the logical root. No file moves. Loader names never carry a root segment.

## D-T2 - Loader-facing identity is the flat leaf

**Ruling.** The loader resolves a skill by its leaf name alone.
The leaf name is the variant directory name and the frontmatter `name` equals it.
No class segment, no root segment, no path appears in the loader name.

**Rejected.** Path identity (`<class>/<variant>`): rejected in round 1.
Path identity with duplicates tolerated: rejected.

**Consequence.** W4 keys the loader on the flat leaf. The nested layout stays physical only.

## D-T3 - Name uniqueness is global, and a collision is a hard error

**Ruling.** Every skill name (parent class, family entry, variant leaf) is globally unique across the suite.
At ratification all 131 names (30 parents plus 101 variants) are distinct.
The W4 loader or its validator raises loudly on a duplicate leaf; a collision is never resolved silently.

**Rejected.** Unique within group only (key on group plus leaf): rejected in round 2, global uniqueness holds today and is simpler.

**Consequence.** W4 adds the collision check the loader lacks today; CI or a conformance test pins it.

## D-T4 - Leaf naming convention: `<class>-<discriminator>`, new skills only, existing grandfathered

**Ruling.** All new skills use `<class>-<discriminator>` (for the #278 families: `<family>-<discriminator>`).
The 70 existing variant leaves that lack the prefix are grandfathered; 31 of the 101 already carry it.
The normalisation debt is recorded and tracked by a dedicated issue; no rename pass runs in this stream.

**Rejected.** Enforce and rename the 70 now: rejected, the diff would invalidate cross-references for no loader benefit.
No convention: rejected, the prefix carries discoverability.

**Consequence.** The families and any later authors follow the convention. The debt issue is named in the W0+W1 completion ledger.

## D-T5 - The #278 families are sibling families under the suite

**Ruling.** `defence-bypass` and `proxy-techniques` sit under the suite root at the same level as classes: `.../defence-bypass/<variant>` and `.../proxy-techniques/<variant>`.
They are attack-surface-agnostic technique families; classes cross-reference them at their steps.

**Rejected.** A `techniques/` grouping: rejected, it adds a level for two entries.
Separate top-level roots: rejected, they belong to the same catalogue identity.

**Consequence.** C1 authors the two families under this placement; C2 wires the class cross-references.

## D-T6 - Borderlines: `subdomain-takeover` is a class entry; `two-principal-authz` is a labelled cross-cutting group (B4)

**Ruling.** `subdomain-takeover` (DNS-layer class) is an ordinary class entry under the suite root.
`two-principal-authz` is a cross-cutting methodology, NOT one of the 29 classes; it stays in the suite under a labelled cross-cutting group, because classes reference it.
The exclusion of `two-principal-authz` from the 29 analysed classes was already operator-approved (audit finding 7); this record closes B4.

**Rejected.** Both as ordinary entries with no grouping: rejected, the methodology label carries meaning.
Separate roots: rejected, one catalogue identity serves both.

**Consequence.** The taxonomy lists a cross-cutting group with one entry today; auditors add to it.

## D-T7 - Parent conformance (B2): parents keep a conformed full body plus a `## Variants` section (round 3, option a)

**Ruling.** All 30 class parents are adapted to the ontology now, and stay indexable and loadable (there is not yet enough eval evidence to bake the class coverage solely into variants).
A conformed parent carries:

- `## Attack Surface`, `## Reconnaissance`, `## Detection Channels`, `## Adversarial Capabilities` (new), `## Trust Assumptions` (new), `## Key Vulnerabilities`, `## Advanced Techniques`, `## Bypass Techniques`, `## Chaining Attacks`, `## Testing Methodology`, `## Variants` (new), `## False Positives`, `## Pro Tips`, `## Summary`, in the ontology's section order;
- its full imported class-level breadth, reorganised to those sections;
- `## Detection Channels` holding the full class list (the union), while each variant keeps only the channels live for its procedure;
- a `## Variants` section placed after `## Testing Methodology`, listing each child variant leaf name with a one-line trigger, one line per child.

The removed sections stay removed (`## Validation`, `## Impact`, `## Post-Exploitation`, `## Exploitation Scenarios`, `## Framework-Specific`, and every non-RDF section).

**Rejected.** A thin umbrella shell (identity, trust assumptions, capabilities, channels, links only): rejected in round 3, it would orphan class coverage and contradict the evidence rationale.
A hybrid breadth core (drop Advanced/Bypass/Chaining from the parent): rejected.
Re-authoring nothing (parents stay imported): rejected in round 1, the operator ruled "adapt them to the ontology now".

**Consequence.** The B2 pass rewrites the 30 parents (29 classes plus the cross-cutting entry) to this contract.
The round-2 phrase "umbrella + inline variant links only" and the round-3 answer "a" resolve to exactly this contract: the parent is the umbrella and carries the class-level body; variant references appear as inline links in the dedicated section only, and variant-specific detail is never duplicated into the parent.

## D-T8 - `graphql` is confirmed non-decomposing (B3); non-decomposing parents keep the full body

**Ruling.** `graphql` passed review as a non-decomposing outlier (protocol/surface aggregator); it stands as one skill with no variants and keeps its full conformed body, with no `## Variants` section.
This confirms B3.

**Rejected.** Reopening `graphql` for a variant decomposition: rejected in round 3.

**Consequence.** B2 writes `graphql` to the full contract (D-T7) minus the `## Variants` section.

## D-T9 - Metadata and `references/`-`scripts/` placement are unchanged

**Ruling.** `metadata.version` stays semver `1.0.0` (the loader accepts any non-empty string; all existing children carry it).
`references/<slug>.md` and `scripts/<slug>` stay skill-local.

**Rejected.** Switching to `major.minor`: rejected, it would edit 101 frontmatters for no consumer.
Version free-form: rejected, uniformity is cheap.

**Consequence.** No frontmatter churn; the families and later authors inherit the same shape.

---

## What this record forces next

- **B1 (`docs/design/skills-taxonomy.md`)**: the normative naming and taxonomy spec, written from this record; it is the document W4 consumes.
- **B2**: the 30-parent conform pass under D-T7 and D-T8.
- **C1**: the two families under D-T4 and D-T5.
- **W4**: flat-leaf identity (D-T2), global uniqueness with a hard error (D-T3), the nested physical layout (D-T1), the logical root mount (D-T1).
- **Normalisation debt**: file the issue for the 70 non-conforming leaves (D-T4).

## Glossary additions (provisional)

**suite root (logical root)** - the logical identity of the whole catalogue, `web-vulnerability-testing/`; it names the catalogue, never a segment of a skill name.
_Avoid_: catalogue directory, mount path.

**group** - a level-1 directory under the catalogue holding either a class or a family; its level-2 children are the variants.
_Avoid_: category, tag.

**class** - a vulnerability class that decomposes (or not) into variants; 29 analysed classes plus the borderlines.
_Avoid_: category, family.

**family** - a technique family placed as a sibling of classes; attack-surface-agnostic, holding its own variants (`defence-bypass`, `proxy-techniques`).
_Avoid_: group, category.

**leaf (leaf name)** - the directory name of a skill and its frontmatter `name`; the loader-facing identity (flat, globally unique).
_Avoid_: slug, id.

**umbrella (parent body)** - the class parent skill's conformed class-level body over its variants, plus the `## Variants` links.
_Avoid_: shell, index.

**cross-cutting methodology** - a skill that classes reference but that is not itself a class of the 29 (`two-principal-authz`).
_Avoid_: meta skill.

## Provenance

The decisions were given by the operator in the B1 grilling of the W0+W1 completion stream: round 1 and round 2 in session `ses_f181eb14bffei9Y8v5O30nGDjG` (2026-10-03), round 3 answered on 2026-10-18 when the stream resumed.
This record was compiled by the orchestrator of the skills-system stream and is committed on the feature trunk `feat/skills-system`.
