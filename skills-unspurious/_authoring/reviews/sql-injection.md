# Skills-reviewer report: class `sql-injection`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| sqli-union-extraction | PASS | none |
| sqli-error-based-extraction | PASS | none |
| sqli-boolean-blind-extraction | PASS | none |
| sqli-time-blind-extraction | PASS | none |
| sqli-oast-exfiltration | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all five live at `skills-unspurious/sql-injection/<variant>/SKILL.md` with the exact analysis section 11 and SPEC section 9 names.
2. Frontmatter: `name` equals the directory in all five, each `description` is front-loaded with the variant leading word (`Union`, `Error`, `Boolean`, `Timing`, `Out-of-band`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all five. Conditional `Bypass Techniques` and `Chaining Attacks` kept from parent material. Omitted `Reconnaissance`, `Advanced Techniques`, `Tooling`, `references/` carry no parent section material for this class (parent ships none of them as sections) and the analysis marks scripted tests genuinely absent (section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (shape-stability vs error-silence vs response-stability vs timing-stability vs egress-closure), each matching analysis sections 3, 9, and 11. Not a parent restatement (parent ships no `Trust Assumptions` section) and not a sibling restatement.
5. Adversarial Capabilities: authored four-entry sections in all five, drawn from analysis `AttackerCapability` rows plus parent recon probes (anonymous baseline, paired observation or listener operation, repeat-to-stability, conditional authenticated session). No stubs.
6. Detection Channels: no verbatim copy of the parent list in any variant. Each holds only live entries (rendered-row plus arity plus alignment set; shaped-error plus baseline-diff set; paired-differential plus normalization plus ordered-output set; gated-delay plus baselining plus jitter set; callback plus token-correlation set), each with its fallback signal scoped to the variant.
7. Bent step plus delta: `sqli-union-extraction` names the S5 UNION sub-value (ordering-position count plus null-row confirmation plus coercion alignment); `sqli-error-based-extraction` names the S5 error sub-value (conversion-shaper selection plus baseline-diff plus metadata scoping); `sqli-boolean-blind-extraction` names the S5 boolean sub-value (paired-truth plus substring range-halving plus digest normalization); `sqli-time-blind-extraction` names the S5 time sub-value (gated-delay plus baseline calibration plus range-halving under latency); `sqli-oast-exfiltration` names the S5 OAST sub-value (label-encoding plus primitive choice plus token attribution). Each states the parent gap explicitly (`The parent ... names/lists/prefers ... without stating/describing ..., so this variant owns ...`). Matches analysis sections 7, 9, and 11.
8. No concrete leak: body scan over product, version, host, param, payload-literal, and tool-name patterns returns only abstract placeholders (`<N>`, `<NULL-ROW>`, `<COERCED-ROW>`, `<METADATA-ROW>`, `<TARGET-ROW>`, `<CAST-SHAPER>`, `<CONVERT-SHAPER>`, `<TARGET-VALUE>`, `<METADATA-VALUE>`, `<TRUE-PREDICATE>`, `<FALSE-PREDICATE>`, `<TARGET>`, `<POSITION>`, `<LENGTH>`, `<GUESS>`, `<PREDICATE>`, `<DELAY-CALL>`, `<IDLE-VALUE>`, `<CALLBACK-PRIMITIVE>`, `<LABEL>`, `<LISTENER>`). No DBMS product literals, no function-name literals, no UNC or callback addresses, no parameter names, no tool names.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body plus aspect-carried bypass and chaining rows, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. smallest confirming read, one value per probe, inconclusive recording); leading words (`rendering`/`alignment`, `shaping`/`baseline`, `diffing`/`calibration`/`normalization`, `gating`/`baselining`, `callback`/`correlation`/`token`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by line scan; frontmatter `description` two-sentence trigger lines and `1.0.0` version dots excluded as non-body).

## Sibling-disjointness check

The five siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Grey points honored: UNION output inside error text stays in UNION while alignment proves the channel; crafted conversion errors stay in error extraction; jittered boolean pairs stay in boolean until gated sleep is the sole oracle; egress-blocked OAST records the blind fallback as a secondary divergence rather than dual membership.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
