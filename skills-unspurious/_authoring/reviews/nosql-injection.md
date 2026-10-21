# Skills-reviewer report: class `nosql-injection`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| nosql-operator-injection | PASS | none |
| nosql-server-side-script-injection | PASS | none |
| nosql-aggregation-pipeline-injection | PASS | none |
| nosql-query-language-injection | PASS | none |
| nosql-command-protocol-smuggling | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all five live at `skills-unspurious/nosql-injection/<variant>/SKILL.md` with the exact analysis section 11 names, matching the SPEC section 9 worklist.
2. Frontmatter: `name` equals the directory in all five, each `description` is front-loaded with the variant leading word (`Operator`, `Script`, `Pipeline`, `Query`, `Command`) with three distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all five. Conditional `Reconnaissance`, `Bypass Techniques`, and `Chaining Attacks` kept from parent material. Omitted `Advanced Techniques`, `Tooling`, and `references/` carry no parent material for this class (parent ships none of them) and the analysis marks scripted tests genuinely absent (section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (operator-shape clause vs script-body clause vs stage-selection clause vs literal-binding clause vs frame-singularity clause), each matching analysis sections 9 and 11. Not a parent restatement (parent ships no `Trust Assumptions` section) and not a sibling restatement.
5. Adversarial Capabilities: authored four-entry sections in all five, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (predicate-oracle set vs enablement-plus-timing set vs stage-plus-pivot set vs grammar-break set vs frame-plus-marker set).
7. Bent step plus delta: `nosql-operator-injection` names S4 operator-predicate construction plus boolean-oracle confirmation plus iterative pattern extraction; `nosql-server-side-script-injection` names S7 enablement fingerprinting plus body placement plus sleep-timing confirmation; `nosql-aggregation-pipeline-injection` names S8 stage targeting plus join-stage collection pivots; `nosql-query-language-injection` names the S9 query-language sub-value (quote-breaking plus search widening plus graph and ledger and wide-column oracles); `nosql-command-protocol-smuggling` names the S9 command-frame sub-value (delimiter framing plus persistence). Each states the parent gap explicitly (`The parent ... names/lists ... without stating/describing ..., so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns no store names, no `$`-operator literals, no version strings, no endpoints, no tool names in any body. Placeholders stay abstract (`<FIELD>`, `<OPERATOR>`, `<SCRIPT-FILTER>`, `<STAGE-FIELD>`, `<FRAME-BREAK>`). The `ssrf` mentions in the query-language variant are the licensed cross-skill invocation at the APOC external-fetch step per analysis section 11, not a tool leak.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with stops only as guardrails paired with the positive target (smallest read, marker proofs, authorized scope); leading words (`predicate`, `bodies`/`script`, `stages`/`pipeline`, `breaking`/`grammar`, `frames`/`smuggling`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan; the only multi-stop lines are frontmatter descriptions and numbered-list markers, not body prose).

## Sibling-disjointness check

The five siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
The `$expr` plus `$function` boundary is assigned to the script variant with a handoff in the pipeline variant, matching analysis section 11 grey points.
Mango selectors ride with operator injection while design-doc maps ride with script injection, matching the analysis section 11 outlier note.
APOC external fetch is carried as a secondary divergence inside query-language injection with an `ssrf` invocation, matching analysis section 11.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
