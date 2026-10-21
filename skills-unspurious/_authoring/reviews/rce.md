# Skills-reviewer report: class `rce`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| rce-command-injection | PASS | none |
| rce-pipeline-execution | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: both live at `skills-unspurious/rce/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in both, each `description` is front-loaded with the variant leading word (`Command`, `Pipeline`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in both. Conditional `Bypass Techniques` and `Chaining Attacks` kept from parent material. Omitted `Reconnaissance`, `Advanced Techniques`, `Tooling`, `references/` carry no parent material for this class (parent ships none of them) and the analysis marks scripted tests genuinely absent (section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (quoting-role clause vs rendition-only clause), each matching analysis sections 9 and 11. Not a parent or sibling restatement.
5. Adversarial Capabilities: authored five-entry sections in both, drawn from analysis `AttackerCapability` rows plus parent capability probes. No stubs.
6. Detection Channels: no verbatim copy of the parent list. Each variant holds only live entries (delay plus callback plus reflected-output plus quoting-break plus flag-acceptance plus context-confirmation for command injection; job-trigger plus derived-artifact plus callback plus job-duration plus planted-marker plus policy-gate for pipeline execution).
7. Bent step plus delta: `rce-command-injection` names P1 wrapper and CLI discovery plus shell-context probing over direct strings; `rce-pipeline-execution` names P1 file-mediated construction against delegate semantics. Each states the parent gap explicitly (`that generic find-it plus oracle-it language never names`, `that parameter break-out language never names`). Matches analysis sections 9 and 11.
8. No concrete leak: bodies use abstract shapes with placeholders denoting the break token, the probe command, the delay value, the callback marker, the container header, the operator directive, and the probe command. Substring matches (`mapping`, `spellings`, `unmarshal`, `timeout-only`) are generic words, not product, version, host, parameter, payload-literal, or tool-name literals. Cross-skill names are licensed step references per ontology section 8 and analysis section 11.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with negations only as guardrails paired with the positive target (scope positions, fallback handling, inconclusive recording); leading words (`command`/`wrapper`/`oracle`, `pipeline`/`delegate`/`operator`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (multi-sentence matches are frontmatter `description` lines only, which carry the what-plus-triggers shape per SPEC section 3).

## Sibling-disjointness check

The two siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Direct-string probing and file-mediated crafting occupy distinct loci with first-step assignment resolving any mixed upload-plus-parameter case, matching analysis section 10.
Template, deserialization, chained-service, and container-boundary sinks hand off to their owning skills at the owning step in both variants, matching analysis section 11 cross-references.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
