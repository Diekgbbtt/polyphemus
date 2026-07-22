# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This is a **multi-context** repo: a `CONTEXT-MAP.md` at the root points to one `CONTEXT.md` per bounded context, with the reasoned ontology and architectural decisions under `docs/design/`.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root - the map of bounded contexts and how they relate.
  Read it first; it tells you which `CONTEXT.md` covers the area you are about to work in.
- **The relevant `CONTEXT.md`** - the per-context domain glossary (the ubiquitous language for that context).
  Today: `agent/recon/CONTEXT.md` (L0 attack-surface discovery) and `agent/recon/analysis/CONTEXT.md` (L1 service/system abstraction).
- **`docs/design/domain-model.md`** - the reasoned ontology the glossaries derive from.
  Read it when you need the WHY behind a term, not just its definition.
- **`docs/design/`** - read the design specifications that touch the area you're about to work in.

If a file the map references does not exist yet, **proceed silently**.
Don't flag its absence; don't suggest creating it upfront.
The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates and sharpens these lazily as terms and decisions get resolved.

## Keep the model current as you build

The ontology and the glossaries are living documents, not a one-time deliverable.
When you introduce, rename, or sharpen a domain term while implementing, update the owning `CONTEXT.md` in the same change - do not batch it up or leave it for later.
When a change alters the reasoned model (a new primitive, a corrected relationship, a resolved open question), update `docs/design/domain-model.md` too.
This is the progressive-update discipline: the map, the glossaries, and the ontology track the code as it evolves, so they never drift into fiction.
See the `## Agent skills` block in `CLAUDE.md` for the binding statement of this rule.

## Anticipated contexts (named, not yet minted)

`CONTEXT-MAP.md` records contexts that need a codebase refactor before they physically exist: a project-management module, and the neo4j / postgres / mcp / llm-client client modules.
The `analysis` context is placed at `agent/recon/analysis/CONTEXT.md` now even though analysis is not yet an independent module - the file is the anchor for that scheduled refactor.
Do not treat an anticipated context as live; do not invent its glossary ahead of the refactor.

## Architectural decisions live in `docs/design/`

This repo has no `docs/adr/` directory.
The closest equivalent to an architecture decision record is a **design specification document** under `docs/design/`.
Where a skill says "read the ADRs", read the relevant design specs instead.

They are longer-form than a classic one-decision-per-file ADR - a single spec typically carries several decisions, often as an explicit numbered ledger (e.g. the `L1D-*` decision ids).
When citing one, cite the decision id where the document provides one, not just the filename.

## File structure

```
/
├── CONTEXT-MAP.md                    ← the map of bounded contexts
├── CODING_STANDARD.md                ← the design principles (DDD)
├── docs/design/
│   ├── domain-model.md               ← the reasoned ontology (glossaries derive from it)
│   ├── service-system-model-design_1.md
│   ├── l1-domain-model-catalogue.md
│   └── ...                           ← design specifications; the ADR equivalent
├── agent/
│   └── recon/
│       ├── CONTEXT.md                ← recon context glossary (L0)
│       └── analysis/
│           └── CONTEXT.md            ← analysis context glossary (L1)
├── db/
└── frontend/
```

## Use the owning context's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the `CONTEXT.md` of the context you are working in.
Don't drift to synonyms the glossary explicitly avoids.
A term defined in one context may mean something different in another (for example the L0 network-service node versus the L1 business `Service`) - use the meaning the owning context assigns.

If the concept you need isn't defined in any glossary or in `domain-model.md`, that's a signal - either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag design-spec conflicts

If your output contradicts an existing design spec, surface it explicitly rather than silently overriding:

> _Contradicts L1D-11 (identity ⊥ membership) in `service-system-model-design_1.md` - but worth reopening because…_

Several of these decisions are also restated as binding invariants in `loop-constraints.md`.
Where the two agree, they are one rule.
Where they appear to disagree, `loop-constraints.md` wins for anything an agent is about to write, and the discrepancy is an escalation.
