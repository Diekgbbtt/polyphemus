# Skills-reviewer report: class `broken-function-level-authorization`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| bfla-alternate-path | PASS | none |
| bfla-client-identity-trust | PASS | none |
| bfla-deferred-execution | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/broken-function-level-authorization/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Alternate`, `Identity-source`, `Deferred`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three. Conditional `Reconnaissance` and `Bypass Techniques` kept from parent material in all three; `Advanced Techniques` kept in `bfla-alternate-path` and `bfla-client-identity-trust` and omitted in `bfla-deferred-execution` where transport aspects belong to D1/D2 per analysis section 6. Omitted `Chaining Attacks`, `Tooling`, `references/` carry no parent section material for this class and the analysis marks anti-patterns and scripted tests genuinely absent (section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (path-locus clause vs identity-source clause vs execution-time clause), each matching analysis sections 7, 9, 11. Not a parent or sibling restatement.
5. Adversarial Capabilities: authored sections in all three, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (primary-vs-alternate denial set vs hint-change precedence set vs deferred-replay set).
7. Bent step plus delta: `bfla-alternate-path` names S3 middleware-stack diffing plus alias, shadow-route, parser-specific, and direct-to-core resubmission; `bfla-client-identity-trust` names S4 conflicting-header precedence probing plus selector-as-identity substitution; `bfla-deferred-execution` names S5 cross-context finalize plus webhook replay plus idempotent retry plus cached-decision reuse. Each states the parent gap explicitly (`The parent ... never describes ... so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: no product, version, host, parameter, payload literal, or tool name in any body. Transport capabilities are phrased abstractly (structured-query mutations, remote-procedure methods, persistent channels). Cross-references to `two-principal-authz` and the proxy family are licensed skill namings, not tool leaks.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. hold-constant pairing, triple-attempt precedence, cross-actor separation); leading words (`alternate`, `identity`, `deferred`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines; frontmatter description two-sentence trigger form is the SPEC section 3 frontmatter shape, not body prose).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Path, identity-source, and execution-time partitions never admit the same attempt twice, matching analysis section 10.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
