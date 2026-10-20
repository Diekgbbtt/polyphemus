# Skills-reviewer report: class `weak-credential-discovery`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| exposed-secret-extraction | PASS | none |
| default-credential-replay | PASS | none |
| username-enumeration-oracle | PASS | none |
| session-token-authority-decode | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all four live at `skills-unspurious/weak-credential-discovery/<variant>/SKILL.md` with the exact analysis section 11 and SPEC section 9 names.
2. Frontmatter: `name` equals the directory in all four, each `description` is front-loaded with the variant leading word (`Extract`, `Replay`, `Enumerate`, `Decode`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all four. Conditional `Reconnaissance` and `Chaining Attacks` kept from parent material. Omitted `Bypass Techniques` plus `references/` are genuinely absent per ontology matrix section 6 (`proxy, bypass, anti-patterns, scripted tests`) and analysis section 3, so no omission is a stub. `Advanced Techniques` and `Tooling` carry no standalone parent section for this class and ride inside the technique sections per ontology section 5.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (served-content clause vs default-pair clause vs uniformity clause vs token-disclosure clause), each matching analysis sections 9 and 11. Not a parent or sibling restatement.
5. Adversarial Capabilities: authored sections in all four, drawn from analysis `AttackerCapability` rows (shared anonymous requests plus held-session aspect for decode) plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (single-response shape plus size set vs post-submission success set vs cross-response delta set vs holder-content claim set), matching analysis `ObservableSignal` rows.
7. Bent step plus delta: `exposed-secret-extraction` names unified fetch-parse-triage over P1 plus P4; `default-credential-replay` names submit-and-read-success replay over P2; `username-enumeration-oracle` names same-secret compare-two-responses with timing normalization over P3; `session-token-authority-decode` names session-gated split-decode-interpret over P5. Each states the parent gap explicitly (`The parent ... never names ... as one procedure` / `no ... step covers ..., so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns only parent-file hits plus benign negation words in the variants. No framework names, default pairs, usernames, paths, regex literals, claim names, or tool names in any variant body. Token-validation naming of `authentication-jwt` is the licensed cross-reference per ontology section 8.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body and procedure-to-tip operationalization, no sediment; phrasing is positive with negations only as scope guardrails or sibling disambiguators paired with the positive target; leading words (`extraction`/`holder`/`fetch`, `replay`/`acceptor`/`success`, `oracle`/`delta`/`identity`, `decode`/`holder`/`claim`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan; numbered-list `1.` periods are the only false positives).

## Sibling-disjointness check

The four siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Completion predicates are disjoint: reusable secret without authentication vs authentication-success signal after submission vs delta that neither response alone yields vs interpreted claims under a held session, matching analysis section 10 H4.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
