# Skills-reviewer report: class `xxe`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| blind-parameter-entity-oob-exfiltration | PASS | none |
| transclusion-without-entity-resolution | PASS | none |
| entity-expansion-denial-of-service | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/xxe/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Blind`, `Transclusion`, `Expansion`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three. Conditional `Reconnaissance`, `Bypass Techniques`, and `Chaining Attacks` kept from parent and analysis material. Omitted `Advanced Techniques`, `Tooling`, and `references/` carry no separate parent material for this class and the analysis marks scripted tests genuinely absent (section 3), so no omission is a stub.
4. Trust Assumptions: shared five-part agreement body once, failing clause varied per variant (external parameter-entity fetch clause vs transclusion clause vs expansion-bounding clause), each matching analysis sections 7, 9, 11. Not a parent restatement (parent ships no `Trust Assumptions` section) and not a sibling restatement.
5. Adversarial Capabilities: authored four-entry sections in all three, drawn from analysis `AttackerCapability` rows plus parent capability probes. No stubs.
6. Detection Channels: no verbatim copy of the parent list. Each variant holds only live entries (OAST plus error plus timing-confirmation for blind; direct transclusion plus error plus OAST-correlation for transclusion; latency growth plus error shape plus response anomaly for expansion).
7. Bent step plus delta: `blind-parameter-entity-oob-exfiltration` names S4 two-stage subset delivery plus redefinition plus exfil with OAST correlation as secondary; `transclusion-without-entity-resolution` names S4 include href craft plus stylesheet document-fetch craft where entities are blocked; `entity-expansion-denial-of-service` names S3 exhaustion observation plus S4 nested amplification with minimal-payload discipline. Each states the parent gap through its centred methodology step. Matches analysis sections 9 and 11.
8. No concrete leak: bodies use abstract placeholders (`[CALLBACK-BASE]`, `[SUBSET-PATH]`, `[LOCAL-FILE-URI or INTERNAL-URL]`, `[INCLUDE-ELEMENT ...]`, `[ENTITY-DEF ...]`) with no product, version, host, parameter, payload-literal, or tool-name literals. Cross-skill names (`ssrf`, path traversal) are licensed step references per ontology section 8.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with negations only as guardrails paired with the positive target (callback correlation, controlled targets, minimal payloads); leading words (`blind`/`chain`/`callback`, `transclusion`/`include`/`stylesheet`, `expansion`/`nesting`/`exhaustion`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (multi-sentence matches are frontmatter `description` lines only, which carry the what-plus-triggers shape per SPEC section 3).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Blind include fetch is carried as a secondary divergence inside the transclusion variant, matching analysis section 11 grey points.
Stylesheet-driven program execution beyond document fetch is named as the code-execution boundary, matching the analysis grey point.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
