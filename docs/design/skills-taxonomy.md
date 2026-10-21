# The skills suite taxonomy and naming spec

*Status: **normative** (B1); topology amended 2026-10-20 (the suite is the `web-vulnerability-testing/` branch; the flat live-root layout is superseded).
This is the naming and taxonomy spec of the well-formed web-vulnerability-testing skills suite.
It fixes the logical suite root, the physical grouping, the loader-facing identity of a skill, the name uniqueness rule and the leaf naming convention, the family and borderline placement, the parent contract, the metadata and bundle rules, and the map of the suite as authored.
It is written from the ratified decision record `docs/design/skills-taxonomy-decisions.md` (D-T1..D-T9; rounds 1 and 2 ratified 2026-10-03, round 3 recorded 2026-10-18); every rule below traces to a ruling there, and this document adds no rule of its own.
Its consumers are W4 (the nested-taxonomy loader), the W6 families (`defence-bypass`, `proxy-techniques`), and every later author of a suite skill.*

*Companion authorities, cited per the ubiquitous-reference rule: `docs/design/skills-variant-boundary.md` - the variant boundary, which decides when a class decomposes into a variant, and which every document that concerns skills references.
`docs/design/skills-ontology.md` - the ontology and section contract, which fixes the sections a skill is built from and their order.
This document does not restate either one.*

## 1. What this document is

It is the enforceable form of the ratified rulings: the part W4 and the authoring fleet consume mechanically.
It is not a decision record (that is `skills-taxonomy-decisions.md`), not the variant decision rule (that is the boundary), and not the section contract (that is the ontology).
Its rules are stated so a validator can check them, and section 4 is the map of the suite as authored at ratification.

| Rule | Ruling source | Enforced by |
|---|---|---|
| R1 logical suite root | D-T1 | W4 mount; conformance test |
| R2 grouping by directory level | D-T1 | layout; conformance test |
| R3 flat-leaf loader identity | D-T2 | loader; `name` == directory check |
| R4 global uniqueness, hard error | D-T3 | loader or validator raises; CI test |
| R5 leaf naming `<class>-<discriminator>` | D-T4 | authoring review; debt issue (section 5) |
| R6 family placement | D-T5 | layout; C1 authoring |
| R7 borderlines | D-T6 | map (section 4); authoring review |
| R8 metadata and skill-local bundle | D-T9 | frontmatter check |
| R9 decomposing parent contract | D-T7 | B2 pass; skills-reviewer |
| R10 non-decomposing parent | D-T8 | B2 pass; skills-reviewer |

## 2. Vocabulary

- **suite root (logical root)** - `web-vulnerability-testing/`: the logical identity of the whole catalogue.
  It is never a directory and never a segment of a skill name.
- **group** - a level-1 directory under the suite branch, holding either a class or a family.
- **class** - a vulnerability class the analyses cover; it is a level-1 entry under the suite branch and the umbrella over its variants.
- **family** - an attack-surface-agnostic technique family placed as a sibling of the classes.
- **cross-cutting methodology group** - the labelled level-1 group under the suite branch holding `two-principal-authz`, which is not one of the 29 classes.
- **leaf (leaf name)** - the directory name of a skill and its frontmatter `name`; the loader-facing identity.
- **umbrella (parent body)** - the class parent's conformed class-level body plus its `## Variants` links.
- **level 1 / level 2** - the physical directory level within the suite branch: a group sits at level 1, its variants at level 2.

The decisions record carries the same terms with their avoided synonyms; this list fixes only what the rules below use.

## 3. Normative rules

### R1 - The suite root is a logical identity

`web-vulnerability-testing/` is the suite's physical home: a top-level branch of the live catalogue root `skills/` (operator topology ruling, 2026-10-20, superseding the earlier rule that the root was only a logical identity).
The branch name is the suite's identity: it never appears as a segment of a reported skill name, and no skill is named after it.
The live root also carries the `meta/`, `internal/`, and `target-specific-procedure/` branches; a branch is a namespace, never a skill, so no branch root carries a `SKILL.md`.
Check: no path segment below the suite branch is named `web-vulnerability-testing`; no frontmatter `name` contains `/`; no branch root carries a `SKILL.md`.

### R2 - Grouping is the physical directory level

Within `web-vulnerability-testing/`, level 1 is a group (a class, a family, or the cross-cutting group) and level 2 is a variant of that group.
Group membership is expressed by the directory level alone.
No metadata tag carries group membership, and no manifest or index file lists the taxonomy.
The live catalogue's loader indexes every `SKILL.md`-bearing directory at any depth by its flat leaf name, so the branch layout never changes a loader name.
Check: every suite `SKILL.md` sits at exactly level 1 or level 2 under `web-vulnerability-testing/`; no taxonomy tag key appears in frontmatter; no `taxonomy.yaml` or equivalent index exists.

### R3 - Loader-facing identity is the flat leaf

The loader resolves a skill by its leaf name alone.
The leaf is the directory holding `SKILL.md`, and the frontmatter `name` equals it exactly.
No root segment, no class segment, and no path appears in the loader name.
Check: for every `SKILL.md`, the frontmatter `name` equals the containing directory name, and a load by that name resolves the skill regardless of the group that holds it.

### R4 - Name uniqueness is global, and a duplicate is a hard error

Every skill name is globally unique across the suite: parents, family entries, and variant leaves alike.
At ratification all 131 names (30 parents plus 101 variants) are distinct.
A duplicate is a hard error: the loader or its validator raises loudly on the first collision and never resolves it silently by preferring one entry.
Check: the validator indexes every name and fails on the duplicate; a conformance test pins the failure.

### R5 - Leaf naming convention: `<class>-<discriminator>`

Every skill authored after ratification is named `<class>-<discriminator>`, where the class is the level-1 group that owns the skill.
The discriminator is the class-derived one the variant boundary yields (the variant's first bent step); this spec governs the shape of the name, the boundary governs the choice.
For the two families the convention reads `<family>-<discriminator>` (D-T5).
The existing variant leaves that lack the prefix are grandfathered at their current names; they are normalisation debt (section 5), not a licence for new names.
Check: a leaf authored after ratification starts with the name of its level-1 group followed by a hyphen; the grandfathered set is the only exception list, and it shrinks as the debt is paid.

### R6 - Family placement

`defence-bypass` and `proxy-techniques` are level-1 groups, siblings of the classes under the suite root: `web-vulnerability-testing/defence-bypass/<leaf>` and `web-vulnerability-testing/proxy-techniques/<leaf>`.
They are attack-surface-agnostic technique families, not class axes and not an in-body section.
A class names a family at the step that family owns, per the ubiquitous cross-reference rule (`docs/design/skills-ontology.md` section 8).
Check: no `techniques/` intermediate level exists; the two family directories sit directly at level 1, and their variants follow R5.

### R7 - Borderlines

`subdomain-takeover` is an ordinary class entry: a level-1 group under the suite root, decomposing into its variants, its parent conformed under R9.
`two-principal-authz` is a cross-cutting methodology, not one of the 29 analysed classes; it stays in the suite under the level-1 cross-cutting methodology group, because classes cross-reference it.
The group holds one entry today, the level-1 skill itself, and auditors add to it.
Because R2 forbids metadata tags, the cross-cutting label lives in this spec's map; physically the group is a level-1 directory like any other.
Check: a coverage report counts 29 classes, and the cross-cutting group and the two families are never counted among them.

### R8 - Metadata and the skill-local bundle

`metadata.version` stays at semver `1.0.0`: every skill that carries the key carries that value (today all 101 variants), and skills authored later carry it too.
No alternative version scheme and no free-form version is introduced.
`references/<slug>.md` and `scripts/<slug>` stay skill-local, inside the owning skill directory at either level.
No new frontmatter key is introduced for taxonomy purposes: the leaf `name` carries the identity, and the directory level carries the placement.
Check: every frontmatter version value in the suite equals `1.0.0`; no reference file or script sits outside a skill directory.

### R9 - The decomposing parent contract

The parent of a decomposing class is the umbrella over its variants: it keeps a conformed full body and adds a `## Variants` section.
The parent carries the ontology sections in the ontology's order (`docs/design/skills-ontology.md` section 3), including the two sections the ontology adds, `## Adversarial Capabilities` and `## Trust Assumptions`.
`## Variants` is placed after `## Testing Methodology`, and it lists one line per child variant in the form `<leaf> - <one-line trigger>`.
The parent's `## Detection Channels` holds the full class list (the union), while each variant keeps only the channels live for its own procedure.
Variant references appear in the `## Variants` section only, and variant-specific detail is never duplicated into the parent.
The removed sections stay removed: `## Validation`, `## Impact`, `## Post-Exploitation`, `## Exploitation Scenarios`, `## Framework-Specific`, and every non-RDF section.
Check: per parent, the section order holds, `## Variants` follows `## Testing Methodology`, its line set equals the child leaf set, and every child has exactly one line.

### R10 - The non-decomposing parent

`graphql` does not decompose: it stands as one skill with no level-2 children and keeps its full conformed body, with no `## Variants` section.
A class with no variants is the only case where a class parent carries no `## Variants` section.
Check: every class with level-2 children carries `## Variants`; a class without children carries none.

## 4. The suite map

The map records the suite as authored at ratification: 30 level-1 groups and 101 level-2 variants.
The 29 analysed classes are inside the 29 class groups; `subdomain-takeover` is one of them, placed as an ordinary class entry per R7.
`two-principal-authz` is the 30th group; the two families were authored after ratification (C1, #278) and their leaves are recorded in rows 31 and 32.
In the leaf column, a trailing `*` marks a leaf that already conforms to R5; 31 of the 101 class leaves do, and every unmarked class leaf is normalisation debt (section 5).
The 12 family leaves are authored after ratification and conform to R5; they are marked in rows 31 and 32.
`graphql` has no level-2 children (R10).
The `_analysis/`, `_authoring/`, `_completion/`, and `_migration/` directories are stream artefacts, not groups: they hold no `SKILL.md` and are not part of the taxonomy.

| # | Level-1 group | Kind | Level-2 variants |
|---|---|---|---|
| 1 | `authentication-jwt` | class | `jwt-claims-confusion`, `jwt-flow-lifecycle`, `jwt-key-resolution`, `jwt-signature-forgery` |
| 2 | `broken-function-level-authorization` | class | `bfla-alternate-path`, `bfla-client-identity-trust`, `bfla-deferred-execution` |
| 3 | `business-logic` | class | `async-boundary-abuse`, `concurrent-duplication`, `quota-window-slicing`, `value-domain-manipulation` |
| 4 | `crypto-weakness` | class | `crypto-predictable-token`, `crypto-signing-key-forgery`, `crypto-timing-oracle` |
| 5 | `csrf` | class | `csrf-form-post`*, `csrf-login-fixation`*, `csrf-navigation-get`*, `csrf-parser-differential`*, `csrf-websocket-handshake`* |
| 6 | `graphql` | class, does not decompose | none (R10) |
| 7 | `header-injection` | class | `header-cache-poisoning`, `header-crlf-splitting`, `header-host-forward-spoof`, `header-method-override`, `header-request-smuggling`, `header-response-value-confusion` |
| 8 | `http-method-tampering` | class | `http-method-tampering-informational-verb`*, `http-method-tampering-override-smuggling`*, `http-method-tampering-preflight-coercion`*, `http-method-tampering-verb-switch`* |
| 9 | `http-request-smuggling` | class | `http-request-smuggling-h2-desync`* |
| 10 | `idor` | class | `idor-collection-batch-scope`*, `idor-context-carrier-substitution`*, `idor-deferred-artifact-redemption`*, `idor-direct-object-swap`*, `idor-nested-expansion-binding`* |
| 11 | `information-disclosure` | class | `differential-oracle-disclosure`, `error-verbosity-disclosure`, `stored-artifact-disclosure` |
| 12 | `insecure-deserialization` | class | `deserialization-deferred-trigger`, `deserialization-gadget-chain`, `deserialization-signed-forgery` |
| 13 | `insecure-file-uploads` | class | `upload-archive-extraction`, `upload-client-execution`, `upload-pipeline-deferred-trust`, `upload-server-execution`, `upload-toolchain-execution` |
| 14 | `llm-prompt-injection` | class | `context-leakage`, `direct-injection-override`, `indirect-injection-plant`, `output-handling`, `tool-abuse` |
| 15 | `mass-assignment` | class | `mass-assignment-bulk-collection-injection`*, `mass-assignment-bulk-nested-relation-write`*, `mass-assignment-nested-relation-write`* |
| 16 | `nosql-injection` | class | `nosql-aggregation-pipeline-injection`, `nosql-command-protocol-smuggling`, `nosql-operator-injection`, `nosql-query-language-injection`, `nosql-server-side-script-injection` |
| 17 | `oauth` | class | `oauth-code-client-binding`*, `oauth-device-approval`*, `oauth-pkce-enforcement`*, `oauth-redirect-uri-validation`*, `oauth-state-nonce-csrf`* |
| 18 | `open-redirect` | class | `generic-redirect-parser-bypass`, `oauth-redirect-uri-relay`, `redirector-to-fetcher-pivot` |
| 19 | `path-traversal-lfi-rfi` | class | `archive-zipslip-write`, `lfi-include-execution`, `rfi-remote-include`, `traversal-read` |
| 20 | `prototype-pollution` | class | `prototype-pollution-client-side`*, `prototype-pollution-server-side`* |
| 21 | `race-conditions` | class | `cross-service-consistency-race`, `idempotency-dedup-bypass`, `optimistic-guard-evasion`, `single-request-fanout` |
| 22 | `rce` | class | `rce-command-injection`*, `rce-pipeline-execution`* |
| 23 | `sql-injection` | class | `sqli-boolean-blind-extraction`, `sqli-error-based-extraction`, `sqli-oast-exfiltration`, `sqli-time-blind-extraction`, `sqli-union-extraction` |
| 24 | `ssrf` | class | `header-gated-cloud-credential-read`, `no-response-egress-inference`, `scheme-translated-command-execution` |
| 25 | `ssti` | class | `ssti-blind-evaluation`*, `ssti-reflected-evaluation`* |
| 26 | `subdomain-takeover` | class (R7 borderline) | `cdn-alternate-domain-binding`, `dangling-record-resource-claim`, `ns-delegation-takeover` |
| 27 | `weak-credential-discovery` | class | `default-credential-replay`, `exposed-secret-extraction`, `session-token-authority-decode`, `username-enumeration-oracle` |
| 28 | `xss` | class | `xss-dom`*, `xss-stored`* |
| 29 | `xxe` | class | `blind-parameter-entity-oob-exfiltration`, `entity-expansion-denial-of-service`, `transclusion-without-entity-resolution` |
| 30 | `two-principal-authz` | cross-cutting methodology group (R7) | none; the group holds the level-1 skill itself |
| 31 | `defence-bypass` | family (C1) | `defence-bypass-allowance-gap`*, `defence-bypass-edge-origin-differential`*, `defence-bypass-encoding-differential`*, `defence-bypass-parser-confusion`*, `defence-bypass-signature-evasion`*, `defence-bypass-throttle-evasion`* |
| 32 | `proxy-techniques` | family (C1) | `proxy-techniques-cache-deception`*, `proxy-techniques-channel-wrapping`*, `proxy-techniques-dns-rebinding`*, `proxy-techniques-redirect-chain`*, `proxy-techniques-relay-forwarding`*, `proxy-techniques-url-parser-differential`* |

Ten decomposing classes are already fully conforming under R5 (`csrf`, `http-method-tampering`, `http-request-smuggling`, `idor`, `mass-assignment`, `oauth`, `prototype-pollution`, `rce`, `ssti`, `xss`); they carry 31 of the 101 leaves.
The remaining 18 decomposing classes carry the 70 grandfathered leaves.

## 5. Normalisation debt

70 of the 101 variant leaves do not carry their class prefix; 31 do, and the map marks them.
The 70 are grandfathered: no rename pass runs in this stream, because the diff would invalidate cross-references for no loader benefit (D-T4).
The convention binds every new skill: the two families, the enrichment work, and later authors.
Several grandfathered leaves carry an abbreviation rather than the class name (`jwt-`, `bfla-`, `deserialization-`, `upload-`, `sqli-`, `crypto-`); under the strict rule they are debt like the rest.
The debt is discoverability only: the loader identity is flat and all names are unique today, so no loader behaviour depends on the renames.
The debt is tracked as [issue #372](https://github.com/Diekgbbtt/polyphemus/issues/372) (`enhancement`, `needs-triage`), which lists the 70 leaves grouped by class.
The W0+W1 completion ledger names this issue under B1 at integration.

## 6. The W4 consumption contract

W4 consumes this spec; the nested-taxonomy loader must enforce the following.
It is a contract of observable behaviour, not a design.

- **The suite branch.** The suite is the `web-vulnerability-testing/` branch of the live `skills/` root; the branch is an identity, and no reporter emits it as part of a skill name (R1).
- **Group nesting.** Within the branch, discovery walks level 1 for groups and level 2 for variants; a level-1 directory carrying `SKILL.md` is a group parent, and a level-2 directory carrying `SKILL.md` is a variant (R2, R9).
- **Flat-leaf identity at any depth.** A skill resolves by its leaf name alone; the resolved name is the containing directory name, never the path relative to the catalogue, and a name resolves regardless of which group holds it (R3).
- **Global uniqueness with a loud duplicate error.** The loader or its validator indexes every name and raises a hard error on the first duplicate, naming both collisions; it never picks one silently (R4).
- **Skill-local bundle.** `references/` and `scripts/` resolve relative to the leaf directory at any depth (R8).
- **Branch rules.** The `meta/` branch keeps its path-shaped names; the `target-specific-procedure/` branch stays out of the shared index and resolves project-first; every other bundle reports its flat leaf name, and a `SKILL.md` at a branch root is refused.
- **The live loader.** `SkillCatalogue` (a lazy default over `_SKILLS_ROOT`) indexes the whole tree recursively, refuses a duplicate and a branch-root bundle, and the project seam (`SkillStore`) probes the project branch first and falls over to the shared catalogue only on absence.

## 7. Cross-references

- `docs/design/skills-taxonomy-decisions.md` - the ratified rulings this spec compiles (D-T1..D-T9); normative source.
- `docs/design/skills-variant-boundary.md` - the variant boundary; the ubiquitous reference for every document that concerns skills.
- `docs/design/skills-ontology.md` - the ontology and section contract; the section order R9 refers to.
- `skills-unspurious/README.md` - the suite prose; it cites this spec for naming and taxonomy.
- `docs/design/skills-system-decomposition.md` - the cross-stream map and provisional glossary; updated by the orchestrator at integration.
- `docs/design/w0-w1-completion-ledger.md` - the completion evidence; check 6 of `skills-unspurious/_completion/verify.sh` verifies this document exists.

## Provenance

Compiled as B1 of the W0+W1 completion stream, branch `feat/w1-taxonomy` based on `feat/skills-system`.
The rules are the operator's ratified rulings in the B1 grilling (rounds 1 and 2 in session `ses_f181eb14bffei9Y8v5O30nGDjG`, 2026-10-03; round 3 on 2026-10-18), compiled in `docs/design/skills-taxonomy-decisions.md`.
The map is derived from the tree at ratification: 30 level-1 groups, 101 level-2 variants, 131 distinct names, 31 leaves conforming to R5.
