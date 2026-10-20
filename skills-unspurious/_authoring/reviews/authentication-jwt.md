# Skills-reviewer report: class `authentication-jwt`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| jwt-signature-forgery | PASS | none |
| jwt-key-resolution | PASS | none |
| jwt-claims-confusion | PASS | none |
| jwt-flow-lifecycle | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all four live at `skills-unspurious/authentication-jwt/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all four, each `description` is front-loaded with the variant leading word (`Forge`, `Seize`, `Prove`, `Drive`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all four.
Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, and `Chaining Attacks` are kept from parent material.
Omitted `Tooling` and `references/` carry no parent material for this class and the analysis marks scripted tests genuinely absent, so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (signature algorithm and signing key clause vs expected key source clause vs issuer, audience, lifetime, and token type clause vs protocol run and lifecycle state clause), each matching analysis sections 9 and 11.
Not a parent restatement (the parent ships no `Trust Assumptions` section) and not a sibling restatement.
The shared body is the licensed micro-verbatim pattern from SPEC section 5.
5. Adversarial Capabilities: authored four-entry sections in all four, drawn from analysis `AttackerCapability` rows plus parent reconnaissance probes (token possession, re-presentation, offline recovery, remote hosting with fetch correlation, rollover timing, cross-context comparison, full run driving, lifecycle oracles).
No stubs.
6. Detection Channels: the parent ships no `Detection Channels` section, so nothing is copied.
Each variant holds only live entries (forged acceptance plus verdict difference plus error-text orientation vs attacker-resolved key acceptance plus fetch evidence plus fallback plus rotation signals vs cross-context plus single-service plus verdict difference plus nested ordering signals vs cross-client plus downgrade plus lifecycle oracle plus device approval signals).
7. Bent step plus delta: `jwt-signature-forgery` names forging or stripping signature validity (confusion, stripping, strictness, offline recovery); `jwt-key-resolution` names seizing key selection (selector injection, remote hosting with fetch confirmation, inline embedding, timing and fallback); `jwt-claims-confusion` names proving cross-context acceptance (cross-context replay, single-service claim acceptance, token type confusion); `jwt-flow-lifecycle` names driving and corrupting the protocol lifecycle (cross-client redemption, downgraded flows, lifecycle oracles).
Each intro states the held-constant bindings explicitly, so the delta over parent steps P4-P6 is visible.
Matches analysis sections 9 and 11.
8. No concrete leak: body scan returns no backtick literals, no header or claim literals, no endpoint literals, no host literals, and no tool names.
Technology names stay abstract (selector, remote reference, embedded key, issuer, audience, privilege, lifetime, challenge, verifier, state, binding) with no product, version, or payload literal.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with no agent-facing prohibitions; leading words (`Forge`, `Seize`, `Prove`, `Drive`, plus `Record` and `Verify` framing) repeat through each body.
10. No em dashes or en dashes in any file; every authored prose line holds one full sentence (verified by line scan; the only multi-period lines are the frontmatter `description` trigger lists and the `1.0.0` version token, neither of which is body prose).

## Sibling-disjointness check

The four siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
A forged signature, an attacker-resolved key, a mis-scoped but validly signed token, and a corrupted flow each occupy exactly one variant, matching analysis section 10.
Confusion versus none versus strictness versus cracking stays an aspect inside signature-forgery; kid payload family stays an aspect inside key-resolution; claim and cell choice stays an aspect inside claims-confusion; client and verifier shape stays an aspect inside flow-lifecycle.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
