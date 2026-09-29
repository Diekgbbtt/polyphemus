# Skills-reviewer report: class `ssrf`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| no-response-egress-inference | PASS | none |
| scheme-translated-command-execution | PASS | none |
| header-gated-cloud-credential-read | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/ssrf/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Infer`, `Translate`, `Read`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three. Conditional `Bypass Techniques` and `Chaining Attacks` kept from parent material. Omitted `Reconnaissance`, `Advanced Techniques`, `Tooling`, `references/` carry no parent material for this class (parent ships none of them) and the analysis marks scripted tests genuinely absent (section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (observability clause vs plain-protocol clause vs plain-header clause), each matching analysis sections 7, 9, 11. Not a parent or sibling restatement. The leak-scope tailoring (network position vs file content vs platform credentials) is licensed narrowing to the variant goal, not clause drift.
5. Adversarial Capabilities: authored five-entry sections in all three, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (side-channel set vs handler-outcome set vs token-plus-credential set).
7. Bent step plus delta: `no-response-egress-inference` names S2 per-token correlation plus differencing plus timeout port mapping; `scheme-translated-command-execution` names S4 raw-protocol grammar crafting plus wrapper-aware reads scoped to direct oracle; `header-gated-cloud-credential-read` names S7 token-then-read sequencing plus flavour-gated flows scoped to direct oracle. Each states the parent gap explicitly (`The parent ... covers only ... and cannot describe ..., so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns only frontmatter fences and the generic word `listener`. No IPs, URLs, wrapper literals, platform names, or tool names in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. fresh-token minting, narrow reads, inconclusive recording); leading words (`inference`/`oracle`/`token`, `translation`/`grammar`/`handler`, `gated`/`token`/`sequence`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause plus the licensed leak-scope tail, per SPEC section 5.
Blind translated and blind gated cases are carried as secondary divergences inside the inference variant, matching analysis section 9 branch 5a and section 11 grey points.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
