# skills-unspurious

The well-formed web-vulnerability testing suite (W0, phase 1).

This is not the live catalogue (`skills/`, which other streams own).
It is the de-spuriated, decomposed suite produced by the W0 stream: the imported `purple-swan` skills cleaned of spurious verbatims, decomposed into fine-grained variants, and written against a frozen ontology.

## Authorities

- `docs/design/skills-variant-boundary.md` - the variant boundary: how a class decomposes, with the decision procedure and the explicit non-discriminators.
  Every document that concerns skills references it.
- `docs/design/skills-ontology.md` - the ontology and section contract: the two layers (RDF notion sections, methodology entities), the canonical layout, and the entity-to-section mapping.

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

The nested path is the taxonomy target (`web-vulnerability-testing -> <class> -> <variant>`, folded under the parent class directory).
The variant's name is precisely the sub-directory holding its `SKILL.md`, matching the skill-name rule.
The loader is still flat; teaching it the nested path is a later stream (W4), so the nested layout is not yet loadable.

## What is here

- The 30 kept class skills (`two-principal-authz` included), de-spuriated per the Phase 2 checklist.
- 101 variant skills across 28 decomposed classes, authored against the ontology and reviewed.
- `INVENTORY.md` - the KEEP / DISCARD / BORDERLINE classification with a rationale per source directory.
- `SCREAMING-REPORT.md` - the de-spuriation record: what was removed, adapted, extracted, and the arsenal gaps.
- `_migration/high-value-targets/` - the extracted high-value-target material for the future threat-modeller migration.
- `_migration/bypass-proxy-techniques/` - the extracted CORS/CSP/WAF-bypass/header/enumeration material.
- `_migration/reports/` - the per-batch de-spuriation reports.
- `_analysis/` - the per-class variant-decomposition analyses (the argued decomposition) and their reviews, plus `SPEC.md` and `LEDGER.md`.
- `_authoring/` - the authoring contract (`SPEC.md`), the `WRITER.md` and `REVIEWER.md` personas, the phase-4 `LEDGER.md`, and `reviews/`.

## Counts

- Source: 50 skill directories and 7 group trees.
- Kept: 30 classes (27 vulnerability classes plus the borderlines `oauth`, `subdomain-takeover`, `llm-prompt-injection`, plus `two-principal-authz`).
- Discarded: 18 (the tool skills and the technology skills) plus `cve-exploitation`.
- Group trees: 46 flat duplicates dropped after folding their unique content.
- Decomposed: 28 classes into 101 variants; `graphql` does not decompose and stands as one skill.

## Conventions

- No em dashes; plain dashes.
  In authored Markdown, one full sentence per line.
- Skills stay abstract: no concrete product, version, endpoint, host, parameter, or payload literal.
  Concrete assets are parametrised at runtime from the attack-surface graph, the knowledge base, and the HTTP history.
- Duplicated content becomes a cross-reference, never a copy.
- Skills must not specify identified vulnerabilities.

## Status and open items

- The boundary and the ontology are validated by the operator (2026-09-28); the W0 residual documentation debt is closed by the W0+W1 completion stream (see `docs/design/w0-w1-completion-ledger.md`).
- `graphql` produces no variants; its parent stands as the family entry.
  The one-line operator confirmation of that outlier is the B3 gate.
- `two-principal-authz` is kept as a cross-cutting reference and excluded from the 29 decomposed classes.
- The 30 parents are not re-authored to the new ontology sections (`## Adversarial Capabilities`, `## Trust Assumptions`); only the variants carry them.
  Whether the parents get a full conformance pass is the B2 operator ruling.
- The nested loader (W4) is required before this layout loads; it is out of scope for the W0+W1 completion stream.
- The round-2 taxonomy and naming spec is authored as B1 (`docs/design/skills-taxonomy.md`); the `defence-bypass` and `proxy-techniques` families (#278) are authored per it (C1) and the classes are rewired to them (C2).
- Suite enrichment from the local repositories runs as D1a-D1c.
