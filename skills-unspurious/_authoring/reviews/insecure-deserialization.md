# Skills-reviewer report: class `insecure-deserialization`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| deserialization-gadget-chain | PASS | none |
| deserialization-signed-forgery | PASS | none |
| deserialization-deferred-trigger | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/insecure-deserialization/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Gadget-chain`, `Signed-forgery`, `Deferred-trigger`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` and `references/` carry no parent material for this class (parent ships neither) and the analysis marks scripted tests genuinely absent (sections 3 and 6), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (unsigned-graph clause vs signature-binding clause vs storage-stability clause), each matching analysis sections 9 and 11. Not a parent restatement (parent ships no `Trust Assumptions` section) and not a sibling restatement.
5. Adversarial Capabilities: authored four-entry sections in all three, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (native-graph plus oracle-gate set vs tamper plus fallback plus re-sign set vs delayed-correlation plus trigger-record set).
7. Bent step plus delta: `deserialization-gadget-chain` names the P4-span oracle-gated assembly spanning matched and selection-free formats; `deserialization-signed-forgery` names P4 signature-layer breaking through recovery or stripping plus minting; `deserialization-deferred-trigger` names the P1 locus-splitting plant-and-trigger pair with delayed correlation. Each states the parent gap explicitly. Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns no matches in any body. Magic bytes, hex literals, gadget names, secret values, claim values, cookie names, and tool names from the parent are abstracted out. Placeholder shapes use abstract tokens only.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with negations only as descriptive conditions or guardrails paired with the positive target; leading words (`oracle-gated`/`chain`/`graph`, `binding`/`mint`/`re-sign`, `plant`/`trigger`/`correlat`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body, bullet, and step lines).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Signed-plus-deferred combos assign by first non-coverable step, phar content resolves toward the trigger pair, and type-named construction stays inside the gadget chain, matching analysis section 11 grey points.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
