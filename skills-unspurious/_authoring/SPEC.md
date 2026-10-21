# Skills-suite authoring spec (W0 phase 4)

*Working spec for the authoring fleet. Single source of truth for the skill-writer and skills-reviewer prompts. Companions: `docs/design/skills-ontology.md` (the section contract), `docs/design/skills-variant-boundary.md` (what makes a variant), and the per-class analyses in `../_analysis/`.*

## 1. Purpose

Author the decomposed variant skills from the ratified analyses.
The parent class skills already exist and are the copy source; they stay as the family umbrella and are not re-authored in this pass.

## 2. Unit of work

One **unit** is one class.
Its **skill-writer** authors every recommended variant of that class as its own skill directory.
Its **skills-reviewer** reviews every variant of that class.
Splitting by class, not by variant, keeps the variants disjoint and fluent because they share one parent, one analysis, and one trust-assumption root.

## 3. Output layout

A variant lives under its parent:

```
skills-unspurious/<parent>/<variant>/SKILL.md
skills-unspurious/<parent>/<variant>/references/<name>.md   # only when a bulky proof belongs outside the body
```

The variant directory name is the variant name exactly as the analysis and the boundary doc state it.
Examples: `skills-unspurious/ssrf/no-response-egress-inference/SKILL.md`, `skills-unspurious/path-traversal-lfi-rfi/traversal-read/SKILL.md`.
The nested path is the W4 nested-taxonomy target; the loader change is W4's concern, so the writer does not worry about the flat loader rule.

Frontmatter (Agent Skills spec subset):
- `name`: the variant directory name (non-empty).
- `description`: what the variant does plus the branches that trigger it, front-loaded with the variant's leading word, one trigger per branch, no synonyms restating one branch.
- `metadata`: a string map carrying a non-empty `version`.

## 4. The section contract

Follow `docs/design/skills-ontology.md` exactly.
The canonical order and the ubiquitous/conditional rule are there.
In brief, the sections kept in every variant are `## Attack Surface`, `## Detection Channels`, `## Adversarial Capabilities`, `## Trust Assumptions`, `## Key Vulnerabilities`, `## Testing Methodology`, `## False Positives`, `## Pro Tips`, `## Summary`.
`## Reconnaissance`, `## Advanced Techniques`, `## Bypass Techniques`, `## Chaining Attacks`, `## Tooling`, and `references/` are kept where the class has the material.
A section is omitted only when its entity or notion is genuinely absent for that class, per the matrix in the ontology doc section 6.

## 5. What the writer derives, per variant

The variant is defined by its first bent step (the analysis section 9 and section 11 name it) and its delta over the parent.
The writer adapts the parent body and the analysis content to build:

- **Trust assumptions (the generative layer).** State the precise trust agreement the feature implicitly makes, at the moment the feature executes, and the clause that fails.
  The agreement covers the data contract between components, the states, the capabilities and primitives used in the request, what the server exposes, and what sensitive information could leak with an adversarial orientation.
  Many variants of one class share the agreement with only a micro-verbatim change at the failing clause; write the shared body once and vary the clause.
- **Adversarial capabilities.** State what access, control, or operational ability the variant presupposes and consumes, drawn from the analysis `AttackerCapability` rows and the parent reconnaissance probes.
- **Detection channels.** Take the parent channel entries that are live for this variant and the channels its own bent step creates; do not copy the whole parent list.
- **Testing methodology.** The ordered steps with checkable, exhaustive completion criteria, centred on the variant's bent step.
- **Adversarial technique detail.** The class material from `## Key Vulnerabilities`, `## Advanced Techniques`, and `## Bypass Techniques`, reframed to the variant.
- **Chaining, false positives, pro tips, summary.** Carried from the parent and narrowed to the variant.

## 6. The abstraction rule

Stay at the parent's abstraction level.
No concrete product, version, endpoint, hostname, parameter name, payload literal, or tool name in the body.
Concrete values are runtime knowledge-base facts.
Reframe every concrete analysis row as its abstract condition before it enters the body.
Payload shapes stay abstract structures with placeholders.

## 7. The writing style

Obey `writing-great-skills` (`/Users/diekgbbtt/.agents/skills/writing-great-skills/SKILL.md`, glossary in the same directory).
Every line earns its place: no no-ops, no duplication across sections, no sediment.
Prefer leading words.
Phrase positively; a prohibition stays only as a hard guardrail paired with what to do instead.
Steps end on checkable completion criteria.
Keep the parent's fluency; the reader should not feel the seam of the split.

## 8. Acceptance criteria (what the skills-reviewer checks)

A class PASSES only when every variant satisfies all of these.

1. The directory is `skills-unspurious/<parent>/<variant>/SKILL.md` with the exact variant name.
2. Frontmatter is valid: `name` == the variant directory, non-empty `description` with distinct per-branch triggers, `metadata.version`.
3. Every ubiquitous section is present; every omitted section is one the analysis marks genuinely absent for that class; no omitted section is stubbed.
4. `## Trust Assumptions` states a precise failing clause, is variant-specific, and is not a restatement of the parent's or a sibling's.
5. `## Adversarial Capabilities` is authored, not a stub.
6. `## Detection Channels` holds only the entries live for this variant; no verbatim copy of the parent list.
7. The variant's bent step is present and named, and the delta over the parent is visible.
8. No concrete reference leaks (no product, version, host, param, payload literal, tool name).
9. The style obeys `writing-great-skills`: sentences are live, sections are not duplicated, phrasing is positive, leading words are used.
10. No em dashes; one full sentence per line where prose is authored.

Any failure -> verdict FAIL with the variant, the section, the violated criterion, and the exact line.
The reviewer grounds its verdict on faithfulness to the analysis and on whether the variant would survive an adversarial change of assumptions.

## 9. The worklist (29 units, 101 variants)

| Unit | Parent | Variants to author |
|---|---|---|
| authentication-jwt | authentication-jwt | jwt-signature-forgery, jwt-key-resolution, jwt-claims-confusion, jwt-flow-lifecycle |
| broken-function-level-authorization | broken-function-level-authorization | bfla-alternate-path, bfla-client-identity-trust, bfla-deferred-execution |
| business-logic | business-logic | concurrent-duplication, value-domain-manipulation, quota-window-slicing, async-boundary-abuse |
| crypto-weakness | crypto-weakness | crypto-predictable-token, crypto-signing-key-forgery, crypto-timing-oracle |
| csrf | csrf | csrf-form-post, csrf-navigation-get, csrf-parser-differential, csrf-login-fixation, csrf-websocket-handshake |
| graphql | graphql | none (does not decompose) |
| header-injection | header-injection | header-crlf-splitting, header-host-forward-spoof, header-cache-poisoning, header-method-override, header-request-smuggling, header-response-value-confusion |
| http-method-tampering | http-method-tampering | http-method-tampering-verb-switch, http-method-tampering-override-smuggling, http-method-tampering-informational-verb, http-method-tampering-preflight-coercion |
| http-request-smuggling | http-request-smuggling | http-request-smuggling-h2-desync |
| idor | idor | idor-direct-object-swap, idor-collection-batch-scope, idor-deferred-artifact-redemption, idor-context-carrier-substitution, idor-nested-expansion-binding |
| information-disclosure | information-disclosure | error-verbosity-disclosure, stored-artifact-disclosure, differential-oracle-disclosure |
| insecure-deserialization | insecure-deserialization | deserialization-gadget-chain, deserialization-signed-forgery, deserialization-deferred-trigger |
| insecure-file-uploads | insecure-file-uploads | upload-server-execution, upload-client-execution, upload-archive-extraction, upload-toolchain-execution, upload-pipeline-deferred-trust |
| llm-prompt-injection | llm-prompt-injection | direct-injection-override, indirect-injection-plant, context-leakage, tool-abuse, output-handling |
| mass-assignment | mass-assignment | mass-assignment-nested-relation-write, mass-assignment-bulk-collection-injection, mass-assignment-bulk-nested-relation-write |
| nosql-injection | nosql-injection | nosql-operator-injection, nosql-server-side-script-injection, nosql-aggregation-pipeline-injection, nosql-query-language-injection, nosql-command-protocol-smuggling |
| oauth | oauth | oauth-redirect-uri-validation, oauth-state-nonce-csrf, oauth-pkce-enforcement, oauth-code-client-binding, oauth-device-approval |
| open-redirect | open-redirect | generic-redirect-parser-bypass, oauth-redirect-uri-relay, redirector-to-fetcher-pivot |
| path-traversal-lfi-rfi | path-traversal-lfi-rfi | traversal-read, lfi-include-execution, rfi-remote-include, archive-zipslip-write |
| prototype-pollution | prototype-pollution | prototype-pollution-client-side, prototype-pollution-server-side |
| race-conditions | race-conditions | idempotency-dedup-bypass, optimistic-guard-evasion, cross-service-consistency-race, single-request-fanout |
| rce | rce | rce-command-injection, rce-pipeline-execution |
| sql-injection | sql-injection | sqli-union-extraction, sqli-error-based-extraction, sqli-boolean-blind-extraction, sqli-time-blind-extraction, sqli-oast-exfiltration |
| ssrf | ssrf | no-response-egress-inference, scheme-translated-command-execution, header-gated-cloud-credential-read |
| ssti | ssti | ssti-reflected-evaluation, ssti-blind-evaluation |
| subdomain-takeover | subdomain-takeover | dangling-record-resource-claim, cdn-alternate-domain-binding, ns-delegation-takeover |
| weak-credential-discovery | weak-credential-discovery | exposed-secret-extraction, default-credential-replay, username-enumeration-oracle, session-token-authority-decode |
| xss | xss | xss-stored, xss-dom |
| xxe | xxe | blind-parameter-entity-oob-exfiltration, transclusion-without-entity-resolution, entity-expansion-denial-of-service |
