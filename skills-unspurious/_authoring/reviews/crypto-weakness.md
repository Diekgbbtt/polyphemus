# Skills-reviewer report: class `crypto-weakness`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| crypto-predictable-token | PASS | none |
| crypto-signing-key-forgery | PASS | none |
| crypto-timing-oracle | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/crypto-weakness/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Predict`, `Forge`, `Extract`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` carries no parent material for this class (parent ships no `Tooling` section) and `references/` is genuinely absent per the ontology matrix and analysis section 3, so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (unpredictability clause vs signing-trust clause vs timing-independence clause), each matching analysis sections 7, 9, 11. Not a parent or sibling restatement. The leak-scope tailoring (account-control vs privilege vs token-value sensitivity) is licensed narrowing to the variant goal, not clause drift.
5. Adversarial Capabilities: authored five-entry sections in all three, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (inspection plus acceptance set vs signature plus acceptance set vs timing plus verdict set).
7. Bent step plus delta: `crypto-predictable-token` names proving token predictability through collection plus recomputation plus lookup plus acceptance testing; `crypto-signing-key-forgery` names breaking signing trust through offline secret search plus algorithm removal plus elevated minting; `crypto-timing-oracle` names extracting the token through baseline plus prefix iteration plus statistical separation. Each states the parent gap explicitly (`The parent ... cannot describe ..., so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns only generic words (`targets`, `role`). No Flask, JWT, digest names, secret literals, claim literals, URLs, or tool names in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with stop conditions paired with evidence bounds (e.g. full uniqueness, keyless rejection, flat distributions); leading words (`prediction`/`predictability`, `forgery`/`forged`/`minting`, `extraction`/`timing`/`separation`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by scan; methodology steps join the action and the completion criterion with `and` inside a single sentence).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause plus the licensed leak-scope tail, per SPEC section 5.
Hash derivation wording and length thresholds stay inside predictable-token, claim choice and serialisation stay inside signing forgery, and sample depth and threshold ratios stay inside timing oracle, matching analysis section 11 aspects.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
