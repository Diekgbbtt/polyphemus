# Skills-reviewer report: class `business-logic`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| concurrent-duplication | PASS | none |
| value-domain-manipulation | PASS | none |
| quota-window-slicing | PASS | none |
| async-boundary-abuse | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all four live at `skills-unspurious/business-logic/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all four, each `description` is front-loaded with the variant leading word (`Duplicate`, `Submit`, `Slice`, `Trigger`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all four. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` carries no parent material for this class and `references/` matches the genuinely absent scripted tests (ontology section 6, analysis section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (run-once clause vs domain-bounds clause vs atomic-reset clause vs downstream re-enforcement clause), each matching analysis sections 9 and 11. Not a parent or sibling restatement. Licensed by SPEC section 5 micro-verbatim variation.
5. Adversarial Capabilities: authored five-entry sections in all four, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (double-commit set vs recomputation-gap set vs window-lifecycle set vs downstream-effect set).
7. Bent step plus delta: `concurrent-duplication` names S4 orchestrated parallel duplicate execution with key-scope plus store-durability forensics; `value-domain-manipulation` names S3 boundary-value oracle submission with server-side recomputation; `quota-window-slicing` names S4 reset-edge timing with reserve-complete-release lifecycle walking; `async-boundary-abuse` names S5 between-call mutation with independent compensation plus retry triggering. Each states the parent gap explicitly (`The parent ... covers only ... and cannot describe ..., so this variant owns ...`). Matches analysis sections 7, 9, and 11.
8. No concrete leak: no product, version, host, parameter, payload literal, or tool name in any body. Skill cross-references (`race-conditions`, `proxy-techniques`, `defence-bypass`, `two-principal-authz`) are licensed namings per ontology section 8, not tool leaks.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. stop-promoting paired with record-as-inconclusive); leading words (`duplication`/`burst`/`ledger`, `manipulation`/`oracle`/`boundary`, `slicing`/`window`/`counter`, `abuse`/`boundary`/`trigger`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines with list markers stripped).

## Sibling-disjointness check

The four siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Simultaneous execution lives in `concurrent-duplication` while sequential slicing lives in `quota-window-slicing`, matching analysis section 11 quota-concurrency boundary rule.
Single-transition value oracles live in `value-domain-manipulation` while cross-boundary triggering lives in `async-boundary-abuse`, matching analysis sections 7 and 9.
Secondary divergences (cross-service doubles, e-commerce plus banking plus subscription shapes, seat plus metering plus inventory shapes, multi-tenant bleed plus background-gate staleness) are carried as aspects inside their owning variant.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
