# Skills-reviewer report: class `open-redirect`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| generic-redirect-parser-bypass | PASS | none |
| oauth-redirect-uri-relay | PASS | none |
| redirector-to-fetcher-pivot | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/open-redirect/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Generic`, `OAuth`, `Fetcher-pivot`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` carries no parent material for this class and the analysis marks scripted tests genuinely absent (ontology matrix row `open-redirect | 3 | scripted tests`), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (parser-agreement clause vs registration-binding clause vs hop re-verification clause), each matching analysis sections 7, 9, 11. Not a parent restatement (parent ships no Trust Assumptions section) or a sibling restatement.
5. Adversarial Capabilities: authored sections in all three, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (enforcing-vs-navigating set vs code-relay set vs fetcher-egress set).
7. Bent step plus delta: `generic-redirect-parser-bypass` names S3 enforcing-versus-navigating comparison with address-bar proof across all parser families. `oauth-redirect-uri-relay` names S2 registration matrix plus trusted-redirector relay with code delivery proof. `redirector-to-fetcher-pivot` names S4 allowlisted-redirector to internal-target chaining with server-egress confirmation. Matches analysis sections 9 and 11.
8. No concrete leak: scan over product, version, host, param, payload-literal, and tool-name patterns returns only frontmatter fences. No parameter names, host literals, payload literals, IP forms, parser names, or tool names in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target. Leading words (`parser`/`canonical`/`enforcing`, `registration`/`relay`/`code`, `fetcher`/`pivot`/`egress`/`hop`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Client-side router guards ride as an aspect inside the generic variant, post-logout looseness rides inside the OAuth variant, and external-exfiltration endings ride as secondary proof inside the fetcher variant, matching analysis section 11 grey points.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
