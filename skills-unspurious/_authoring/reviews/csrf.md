# Skills-reviewer report: class `csrf`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| csrf-form-post | PASS | none |
| csrf-navigation-get | PASS | none |
| csrf-parser-differential | PASS | none |
| csrf-login-fixation | PASS | none |
| csrf-websocket-handshake | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all five live at `skills-unspurious/csrf/<variant>/SKILL.md` with the exact SPEC section 9 names, matching analysis section 11 (`csrf-websocket-handshake`; the section 9 `csrf-handshake-transport` label names the same bent step).
2. Frontmatter: `name` equals the directory in all five, each `description` is front-loaded with the variant leading word (`Deliver`, `Chain`, `Reconstruct`, `Plant`, `Open`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all five. Conditional `Reconnaissance`, `Bypass Techniques`, and `Chaining Attacks` kept from parent material. Omitted `Advanced Techniques`, `Tooling`, and `references/` carry no parent material for this class (parent ships none of them) and the analysis marks proxy plus scripted tests genuinely absent (ontology matrix, analysis section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (simple-encoding acceptance vs navigation-safety vs declared-encoding coercion vs session-direction vs transport-shape), each matching analysis sections 7, 9, 11. Not a parent restatement (parent ships no Trust Assumptions section) or a sibling restatement.
5. Adversarial Capabilities: authored five-to-six-entry sections in all five, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (encoding plus storage-effect set vs confirmation-chain plus staff-context set vs coercion plus override set vs identity-comparison set vs handshake plus over-socket set).
7. Bent step plus delta: `csrf-form-post` names per-endpoint encoding choice plus storage-effect confirmation over P5; `csrf-navigation-get` names confirmation-step chaining plus staff-context confirmation over P6; `csrf-parser-differential` names transform-then-confirm-coercion plus override smuggling over P5; `csrf-login-fixation` names clear-then-plant sequencing plus identity comparison over P3; `csrf-websocket-handshake` names handshake-opening plus issue-over-channel over P5/P6. Each states the parent gap explicitly (`The parent ... covers only ... and cannot describe ..., so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns only frontmatter fences plus the licensed `Lax-scoped` aspect enumeration (analysis section 6 marks SameSite values an aspect kept inside the navigation variant per STATE 3 branch 3b). No IPs, URLs, parameter literals, payload literals, platform names, or tool names in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body (SPEC section 5), no sediment; phrasing is positive with scoping statements as disjointness boundaries rather than prohibitions; leading words (`replay`, `navigation`/`chain`, `reconstruction`/`coercion`, `planting`/`fixation`, `two-phase`/`handshake`/`channel`) repeat through each body.
10. No em dashes in any file (verified count zero); every authored prose line holds one full sentence (verified by line scan; list numerals are the only extra period).

## Sibling-disjointness check

The five siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Identical replay vs semantic transformation vs GET reachability vs direction reversal vs socket transport are disjoint per analysis section 10.
OAuth authorize, GraphQL GET, and multipart file forgery ride as aspects inside navigation-get and form-post per analysis section 11 grey points.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
