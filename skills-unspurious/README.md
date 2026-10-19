# skills-unspurious

The well-formed web-vulnerability testing suite (W0, phase 1).

This is not the live catalogue (`skills/`, which other streams own).
It is the de-spuriated, decomposed suite produced by the W0 stream: the imported `purple-swan` skills cleaned of spurious verbatims, decomposed into fine-grained variants, and written against a frozen ontology.

## Authorities

- `docs/design/skills-variant-boundary.md` - the variant boundary: how a class decomposes, with the decision procedure and the explicit non-discriminators.
  Every document that concerns skills references it.
- `docs/design/skills-ontology.md` - the ontology and section contract: the two layers (RDF notion sections, methodology entities), the canonical layout, and the entity-to-section mapping.
- `docs/design/skills-taxonomy.md` - the naming and taxonomy spec: the logical suite root, group levels, flat-leaf loader identity, global name uniqueness, the leaf naming convention, and the suite map.
  Every naming or placement question is answered there, and new skills follow it.

## Layout

A kept class skill is one directory holding its `SKILL.md`, exactly as imported and de-spuriated:

```
skills-unspurious/<class>/SKILL.md
```

A decomposed variant lives nested under its parent class:

```
skills-unspurious/<class>/<variant>/SKILL.md
skills-unspurious/<class>/<variant>/references/<name>.md   # only when a bulky proof belongs outside the body
```

A technique family is a level-1 group like a class, with its own variants at level 2 and no intermediate directory:

```
skills-unspurious/<family>/SKILL.md
skills-unspurious/<family>/<family>-<discriminator>/SKILL.md
```

A family leaf is named `<family>-<discriminator>` (rule R5), where the discriminator is the variant's first bent step.

The nested path is the taxonomy target (`web-vulnerability-testing -> <class> -> <variant>`, folded under the parent class directory), as fixed by `docs/design/skills-taxonomy.md`.
The name of a skill is precisely the leaf sub-directory holding its `SKILL.md`, and its frontmatter `name` equals it; the loader-facing identity is that flat leaf (rule R3 in the taxonomy spec).
The nested layout is loadable (W4): the catalogue mount (`SkillCatalogue` in `src/polymerhus/app/llm/skills.py`) indexes this directory under the logical root and resolves a skill by its flat leaf name whichever group holds it, reports leaf names only, and refuses a duplicate name loudly, naming both colliding paths (rules R1-R4).
`references/` and `scripts/` resolve inside the owning leaf, at level 1 or level 2 (rule R8).
The mount never repoints the live catalogue root `skills/`, which other streams own; a caller follows a mount only by passing it.

## What is here

- The 30 kept level-1 skills (`two-principal-authz` included as the cross-cutting entry), de-spuriated per the Phase 2 checklist.
- 101 variant skills across 28 decomposed classes, authored against the ontology and reviewed.
- The two technique families, `defence-bypass` and `proxy-techniques` (C1 of #278): level-1 groups beside the classes, each a conformed parent plus six variant leaves, authored against the ontology and the variant boundary.
  - `defence-bypass` - `defence-bypass-signature-evasion`, `defence-bypass-encoding-differential`, `defence-bypass-parser-confusion`, `defence-bypass-allowance-gap`, `defence-bypass-edge-origin-differential`, `defence-bypass-throttle-evasion`.
  - `proxy-techniques` - `proxy-techniques-dns-rebinding`, `proxy-techniques-redirect-chain`, `proxy-techniques-url-parser-differential`, `proxy-techniques-channel-wrapping`, `proxy-techniques-cache-deception`, `proxy-techniques-relay-forwarding`.
- `INVENTORY.md` - the KEEP / DISCARD / BORDERLINE classification with a rationale per source directory.
- `SCREAMING-REPORT.md` - the de-spuriation record: what was removed, adapted, extracted, and the arsenal gaps.
- `_migration/high-value-targets/` - the extracted high-value-target material for the future threat-modeller migration.
- `_migration/bypass-proxy-techniques/` - the extracted CORS/CSP/WAF-bypass/header/enumeration material.
- `_migration/reports/` - the per-batch de-spuriation reports.
- `_analysis/` - the per-class variant-decomposition analyses (the argued decomposition) and their reviews, plus `SPEC.md` and `LEDGER.md`.
- `_authoring/` - the authoring contract (`SPEC.md`), the `WRITER.md` and `REVIEWER.md` personas, the phase-4 `LEDGER.md`, and `reviews/`.

## Counts

- Source: 50 skill directories and 7 group trees.
- Kept: 30 parents: the 29 analysed classes plus the cross-cutting `two-principal-authz` (the suite map in `docs/design/skills-taxonomy.md` is the authoritative placement).
- Discarded: 18 (the tool skills and the technology skills) plus `cve-exploitation`.
- Group trees: 46 flat duplicates dropped after folding their unique content.
- Decomposed: 28 classes into 101 variants; `graphql` does not decompose and stands as one skill.
- Families: 2 level-1 groups with 12 variant leaves between them (`defence-bypass` 6, `proxy-techniques` 6); each parent carries its `## Variants` line set equal to its own leaves (rule R9), and the 101 class children are counted apart from them.

## Conventions

- No em dashes; plain dashes.
  In authored Markdown, one full sentence per line.
- Skills stay abstract: no concrete product, version, endpoint, host, parameter, or payload literal.
  Concrete assets are parametrised at runtime from the attack-surface graph, the knowledge base, and the HTTP history.
- Duplicated content becomes a cross-reference, never a copy.
- Skills must not specify identified vulnerabilities.

## Status and open items

- The boundary and the ontology are validated by the operator (2026-09-28); the W0 residual documentation debt is closed by the W0+W1 completion stream (see `docs/design/w0-w1-completion-ledger.md`).
- `graphql` produces no variants; it stands as one skill with no `## Variants` section (rule R10 in the taxonomy spec; the outlier confirmation is D-T8).
- `two-principal-authz` is kept as a cross-cutting reference and excluded from the 29 decomposed classes; the taxonomy spec places it in a labelled cross-cutting group (rule R7).
- The 30 parents are conformed to the ontology sections (`## Adversarial Capabilities`, `## Trust Assumptions`) per the B2 ruling recorded in `docs/design/skills-taxonomy-decisions.md` (D-T7); each parent gains a `## Variants` section, and `graphql` keeps its full body without one (D-T8).
- The nested loader (W4) is implemented: the suite mounts as an index over this directory under the logical root `web-vulnerability-testing/`, resolves flat leaves, reports leaf names only, refuses duplicate names, and keeps the root out of every reported name (rules R1-R4 and R8 in the taxonomy spec).
  The mount seam and its conformance tests are `SkillCatalogue` in `src/polymerhus/app/llm/skills.py` and `tests/recon/test_skill_catalogue.py`.
- The taxonomy and naming spec is ratified as B1 (`docs/design/skills-taxonomy.md`, compiled from `docs/design/skills-taxonomy-decisions.md`); the `defence-bypass` and `proxy-techniques` families (#278) are authored per it (C1) with six leaves each, and the classes name them at their bypass and proxy steps (C2).
  The 70 leaves that do not yet carry their class prefix are normalisation debt (#372).
- Suite enrichment from the local repositories runs as D1a-D1c.
  D1a is the two-round mining pass (`_migration/enrichment/d1a/`) and its operator rulings; D1b authors the accepted new skills and applies the enrichment union; D1c authors the accepted references.
- D1b (W7) grows the suite past the ratified counts above: this pass contributes the level-1 classes `email-header-injection`, `mfa-bypass`, and `account-recovery` and the leaf `email-dns-takeover` under `subdomain-takeover`, and the other D1b slices contribute the remaining accepted classes and leaves.
  New skills are authored in the reference layout (bulleted elements with the signature in bold before the colon); ticket #388 normalises the pre-existing files later, layout and font style only.
  `_completion/verify.sh` check 8 pairs the ratified floor of 101 class children with a per-parent `## Variants` sweep, so the count stays truthful as the suite grows.
- The injection and credential slice of D1b contributes the level-1 classes `ldap-injection` and `xpath-injection`, the leaf `sqli-second-order-injection` under `sql-injection`, and the leaf `xxe-local-dtd-error-exfiltration` under `xxe`, plus the enrichment union for `nosql-injection`, `prototype-pollution`, `sql-injection`, `ssti`, `xxe`, and `weak-credential-discovery`.
  That slice also wires the `weak-credential-discovery` parent and its `session-token-authority-decode` and `exposed-secret-extraction` leaves to the `crypto-weakness` class and its `crypto-predictable-token` leaf at the steps that fingerprint a holder's algorithm, and names `proxy-techniques-dom-clobbering` at the delivery step of `prototype-pollution`.
- The request-shaping and client-side slice of D1b contributes the leaf `race-conditions-partial-construction` under `race-conditions` and the leaf `http-request-smuggling-cross-protocol-desync` under `http-request-smuggling`, and applies the enrichment union for `header-injection`, `http-request-smuggling`, `race-conditions`, `rce`, `xss`, and `ssrf`.
  That slice folds the configuration-file delegate sink plus the administrator trust context into `rce-pipeline-execution`, and names `proxy-techniques-dom-clobbering` at the `xss` proxy step.
  It also holds routing-based SSRF as a `header-injection` value whose interior-body read escalates to `ssrf`, and the renderer-script sink as an `ssrf` aspect.
