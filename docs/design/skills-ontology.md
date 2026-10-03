# The skill ontology and section contract

*Status: validated by the operator in session `ses_f181eb14bffei9Y8v5O30nGDjG` (2026-09-28), including the corrections that trust assumptions are the generative layer, that detection channels are multicast per variant, and that Tooling stays. This is the consolidated ontology the authoring fleet writes against: the two layers (RDF notion sections and methodology entities), the canonical section layout, and the entity-to-section mapping with its evidence sources. It consolidates three previously scattered sources (below) and is the authority for the skill-writer and skills-reviewer prompts.*

*Companion authority: `docs/design/skills-variant-boundary.md` - the variant boundary, which decides when a class decomposes into variants. This document does not restate it.*

## 1. Where the ontology was documented before

The ontology was not documented in one place.
It existed in three, none of them an authoring contract:

- The **ten methodology entities** are the closed set in `lightrag/data/lightrag/prompts/entity_type/methodology_entities.yml` (an extractor profile, not a layout spec).
- The **RDF notions** (the ordered skill sections) are in `docs/design/skills-system-decomposition.md`, component C2 and its provisional glossary.
- The **runtime entities** are the L0/L1 graph in `docs/design/domain-model.md`.

This document freezes the three into one and adds the missing piece: the mapping from each entity to the section that carries it.

## 2. The two layers

A skill is built on two orthogonal layers.

The **RDF notion layer is structural**: the ordered sections a skill is made of.
The **methodology entity layer is semantic**: the kinds of content that fill those sections.
A section is not the same thing as an entity; a section carries one entity exactly, or several, or none.

The **L0/L1 runtime entities** (Service, System, Endpoint, Parameter, DataItem, BaseURL, Header, and the HTTP history) are a third, excluded layer.
They parametrise a skill at execution time and are supplied from the attack-surface graph, the knowledge base, and the HTTP history.
They are never a section and never a discriminator.

## 3. The section contract (canonical layout)

Every child skill uses this order.
A section whose entity is genuinely absent for the class is omitted, never stubbed with a placeholder.
`variant-specific` means the section is present only when the class carries that material.

| # | Section | Realises | Presence |
|---|---|---|---|
| 0 | frontmatter `name`/`description`/`metadata.version` | identity and index | mandatory |
| 1 | `# <Title>` + one-paragraph intro | `VulnerabilityClass`, `AttackGoal` | mandatory |
| 2 | `## Attack Surface` | `PreconditionEnvironment` (derived) | mandatory |
| 3 | `## Reconnaissance` | `PreconditionEnvironment` + `AttackTechnique` | when the class seeks surfaces |
| 4 | `## Detection Channels` | `ObservableSignal` | mandatory, entries multicast per variant |
| 5 | `## Adversarial Capabilities` | `AttackerCapability` | mandatory, written from scratch |
| 6 | `## Trust Assumptions` | the generative layer of the class (no single entity) | mandatory, per-variant |
| 7 | `## Key Vulnerabilities` | `AttackTechnique` + `PayloadPattern` | mandatory |
| 8 | `## Advanced Techniques` | `AttackTechnique` | variant-specific |
| 9 | `## Bypass Techniques` | `DefensiveControl` | when a control exists to defeat |
| 10 | `## Chaining Attacks` | `AttackGoal` + `Artifact` | when composition matters |
| 11 | `## Testing Methodology` | `AttackTechnique` (backbone) | mandatory |
| 12 | `## False Positives` | exclusion predicates (no entity) | mandatory |
| 13 | `## Pro Tips` | pro techniques (no entity) | mandatory |
| 14 | `## Tooling` | no entity; kept for fluency | where the class had one |
| 15 | `## Summary` | `VulnerabilityClass` + `AttackGoal` | mandatory |
| 16 | `references/` scripted tests | `PayloadPattern` + `Artifact` | when a bulky proof belongs outside the body |

Sections already removed and not to be reintroduced: `## Validation`, `## Impact`, `## Post-Exploitation`, `## Exploitation Scenarios`, `## Framework-Specific`.

### 3.1 Detection channels are multicast, not copied

A parent lists detection channels for the whole class; the effective channel set changes per variant.
Each parent entry is distributed to the child or children where it actually fires, and a variant adds the channels its own bent step creates.
One parent entry may land in several children; that is a multicast, not duplication, because each child keeps only the entry that is live for its own procedure.

### 3.2 Trust assumptions are the generative layer

Every variant in every class exists because some trust agreement is misspecified.
The agreement is not only the data contract between a client and a server component.
It is also the implicit assumptions the target makes about its own states, about the capabilities and primitives used in a request, about what the server exposes, and about what sensitive information could leak with an adversarial orientation, all at the moment a specific feature is executed.
Each variant therefore states its own precise assumption: the agreement the feature implicitly makes, and the specific clause that fails.
Many variants share one assumption with only a micro-verbatim change, so the section is written once and varied at the failing clause.

## 4. Entity-to-section mapping

Five verdicts are used.

- **EXACT** - one entity owns one existing section; copy and adapt.
- **DERIVED** - the entity's material lives inside a section shared with another entity; the writer extracts and normalises it.
- **NEW** - no section exists in the parents; write from scratch.
- **IDENTITY** - the entity is the skill itself, not a section.
- **NEVER** - a runtime non-discriminator that must not become a section.

| Entity | Verdict | Home section | Evidence source for the writer |
|---|---|---|---|
| `AttackTechnique` | EXACT | `## Testing Methodology`, with detail in `## Key Vulnerabilities` and `## Advanced Techniques` | parent body; analysis section 5 (steps), 9 (variant steps), 11 |
| `ObservableSignal` | EXACT | `## Detection Channels`, entries distributed per variant | parent `## Detection Channels` where present; analysis section 2 `ObservableSignal` rows; signals embedded in `## Key Vulnerabilities` |
| `DefensiveControl` | EXACT | `## Bypass Techniques` | parent `## Bypass Techniques`/`## Bypass Methods`; analysis section 2 `DefensiveControl` rows; the #278 `defence-bypass` family |
| `PreconditionEnvironment` | DERIVED | `## Attack Surface` + `## Reconnaissance`, normalised into an applicability statement | parent `## Attack Surface` bullets; analysis section 2 `PreconditionEnvironment` rows; section 3 notion map |
| `PayloadPattern` | DERIVED | inside `## Key Vulnerabilities` or `## Core Payloads` when the class warrants one | parent payload blocks; analysis section 2 `PayloadPattern` rows (usually marked aspect) |
| `Artifact` | DERIVED | inside `## Chaining Attacks` and `## Detection Channels` | analysis section 2 `Artifact` rows; section 3 chaining notion |
| `AttackGoal` | DERIVED | the intro and `## Summary`, extended in `## Chaining Attacks` | analysis section 2 `AttackGoal` rows; section 3 chaining notion; no impact section returns |
| `AttackerCapability` | NEW | `## Adversarial Capabilities` | parent `## Reconnaissance` capability probes; analysis section 2 `AttackerCapability` rows; section 5 preconditions |
| `VulnerabilityClass` | IDENTITY | the frontmatter, title, and intro | analysis section 1 |
| `TechnologyStack` | NEVER | none | runtime knowledge base only; if it appears in the parent body it is abstracted out |

### 4.1 Why `PreconditionEnvironment` is DERIVED, not EXACT

The parent `## Attack Surface` section mixes three things: the concrete surfaces to look at (runtime L0/L1), the technology present (TechnologyStack), and the environment conditions that must hold for the technique to apply (PreconditionEnvironment).
The child states the applicability conditions as conditions, not as a surface list, and it names no concrete technology.
This is the "environment precondition written from scratch" the operator flagged: it is authored from the parent surfaces plus the analysis ledger, not copied.

### 4.2 Why `AttackerCapability` is NEW

No parent skill has an adversarial-capabilities section.
The capability content exists only as implied preconditions in `## Reconnaissance` ("if you can poison logs", "if you can host a payload", "if you hold two sessions") and as ledger rows in the analyses.
The child writes a dedicated section from scratch: what access, control, or operational ability the procedure presupposes and can consume, drawn from the capability rows of the analysis and the reconnaissance probes of the parent.

### 4.3 The notions without a single owning entity

Four RDF notions do not belong to one entity.
They are still sections the child must honour.

- `## Trust Assumptions` is the generative layer, mandatory in every variant. It is not a hybrid of two entities; it is the root from which the class's vulnerabilities are yielded. Each variant states the precise agreement the feature implicitly makes and the clause that fails (section 3.2).
- proxy techniques are an external family (#278), not an in-body section: the child names the family at its proxy step rather than restating relay mechanics.
- techniques anti-patterns fold into `## Pro Tips` and `## False Positives`.
- scripted tests live in `references/`, sourced from `PayloadPattern` plus the proof `Artifact`.

## 5. Sections kept ubiquitously

Per the operator's ruling, every mapped section is kept in every child, minus the already-removed ones.
The sections kept in every child regardless of class are: `## Attack Surface`, `## Detection Channels`, `## Adversarial Capabilities`, `## Trust Assumptions`, `## Key Vulnerabilities`, `## Testing Methodology`, `## False Positives`, `## Pro Tips`, and `## Summary`.
Two content types are kept even where the class has no dedicated section for them, because removing them would cost the parent its fluency: payload shapes (`PayloadPattern`) stay inside the technique sections, and capability framing stays inside the adversarial-capabilities section and the intro.
`## Tooling` is kept where the class had one.
`## Reconnaissance`, `## Advanced Techniques`, `## Bypass Techniques`, `## Chaining Attacks`, and `references/` are kept where the class has the material.
A section is omitted only when its entity or notion is genuinely absent for that class (section 6), never stubbed with a placeholder.

## 6. Missing-entity matrix (per class)

All 29 analyses populated all 10 entity rows, so no class is entity-silent.
What is genuinely absent is per-class **notion** material.
This matrix is the writer's checklist: the `absent` column lists the sections the child may omit for that class.
`scripted tests` is absent everywhere except `ssti` (which ships `references/`) and `xss` (inline).

| Class | Recommended variants | Notions genuinely absent |
|---|---|---|
| authentication-jwt | 4 | proxy, anti-patterns, scripted tests |
| broken-function-level-authorization | 3 | anti-patterns, scripted tests |
| business-logic | 4 | scripted tests |
| crypto-weakness | 3 | proxy, anti-patterns, scripted tests |
| csrf | 5 | proxy, scripted tests |
| graphql | does not decompose | scripted tests |
| header-injection | 6 | proxy, scripted tests |
| http-method-tampering | 4 | proxy, scripted tests |
| http-request-smuggling | 2 | proxy, scripted tests |
| idor | 5 | scripted tests |
| information-disclosure | 3 | proxy, bypass, anti-patterns, scripted tests |
| insecure-deserialization | 3 | proxy, anti-patterns, scripted tests |
| insecure-file-uploads | 5 | proxy, scripted tests |
| llm-prompt-injection | 5 | scripted tests |
| mass-assignment | 3 | proxy, anti-patterns, scripted tests, chaining |
| nosql-injection | 5 | anti-patterns, scripted tests |
| oauth | 5 | proxy, scripted tests |
| open-redirect | 3 | scripted tests |
| path-traversal-lfi-rfi | 4 | proxy, scripted tests |
| prototype-pollution | 2 | proxy, anti-patterns, scripted tests |
| race-conditions | 4 | scripted tests |
| rce | 2 | proxy, anti-patterns, scripted tests |
| sql-injection | 5 | scripted tests |
| ssrf | 3 | scripted tests |
| ssti | 2 | none |
| subdomain-takeover | 3 | proxy, anti-patterns, scripted tests |
| weak-credential-discovery | 4 | proxy, bypass, anti-patterns, scripted tests |
| xss | 2 (plus baseline) | none |
| xxe | 3 | scripted tests |

## 7. The abstractness rule

Children stay at the same abstraction level as the parents.
No concrete product, version, endpoint, hostname, parameter name, payload literal, or tool name appears in the body.
Concrete values are runtime knowledge-base facts and belong to the oscillation between the skill and the KB, never to the skill.
The analysis content is adapted to this level before it is copied in: a ledger row naming concrete technologies is reframed as its abstract condition.

## 8. Skills bounded to their steps

A child names another skill at a step that other skill owns, rather than restating it.
The cross-references in force: `two-principal-authz` (authorization principal), `race-conditions` (TOCTOU), the `defence-bypass` and `proxy-techniques` families (#278), `graphql` (GraphQL steps), `oauth`/`authentication-jwt` (token and flow steps).

## 9. What the fleet enforces

The skill-writer authors each child against this contract.
The skills-reviewer verifies, per child: the section layout is exact; every ubiquitous section is present and every omission is one the analysis marks genuinely absent; the `## Trust Assumptions` section states the precise failing clause of the agreement and is not a restatement of the parent's; the `## Adversarial Capabilities` section is authored, not stubbed; the `## Detection Channels` entries are the ones live for this variant, not a copy of the parent list; no concrete reference leaks; the abstraction level matches the parent; the writing obeys `writing-great-skills` (no no-ops, no duplication, no sediment, positive phrasing, leading words); and the variant keeps the parent's fluency.
