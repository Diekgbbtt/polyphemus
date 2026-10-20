# Skills-reviewer report: class `http-method-tampering`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| http-method-tampering-verb-switch | PASS | none |
| http-method-tampering-override-smuggling | PASS | none |
| http-method-tampering-informational-verb | PASS | none |
| http-method-tampering-preflight-coercion | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all four live at `skills-unspurious/http-method-tampering/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all four, each `description` is front-loaded with the variant leading word (`Switch`, `Smuggle`, `Exploit`, `Coerce`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all four. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from class material. Omitted `Tooling` carries no parent material (parent ships none) and omitted `references/` is genuinely absent per analysis section 3 and ontology section 6 (proxy, scripted tests), so no omission is a stub.
4. Trust Assumptions: shared method-identity agreement body once, failing clause varied per variant (route-dispatch mapping vs override reinterpretation vs informational handling vs preflight gating), each matching analysis sections 7, 9, 11. Not a parent or sibling restatement.
5. Adversarial Capabilities: authored three-sentence sections in all four, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (dispatch-gap set vs gate-versus-executor set vs disclosure plus header-only plus echo set vs shape-pair set).
7. Bent step plus delta: `http-method-tampering-verb-switch` names dispatch-map reconstruction plus per-verb execution confirmation over P2; `http-method-tampering-override-smuggling` names gate-versus-executor divergence proof over P3; `http-method-tampering-informational-verb` names Allow-driven selection plus header-only extraction plus echo-material replay over P4; `http-method-tampering-preflight-coercion` names preflighted-blocked versus simple-executed pair plus execution confirmation over P5. Each delimits the mutex (application verbs vs informational verbs vs carrier pair vs shape pair). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns only abstract carriers (`override header carrier`, `simple shape`, `application verb`, `informational verb`) with no `Rails`, `Django`, `Spring`, header spellings, `text/plain`, verb literals, paths, hosts, or tool names in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. confirm by data or state effect, treat gate success as non-proof until executor effect); leading words (`dispatch`/`map`/`replay`, `divergence`/`gate`/`executor`, `disclosure`/`extraction`/`replay`, `shape`/`divergence`/`semantics`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body lines).

## Sibling-disjointness check

The four siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Verb-switch covers only application-decision verbs while informational-verb owns disclosure plus header-only plus echo verbs exclusively, matching the analysis section 7 and 11 mutex rule.
Smuggling needs a carrier pair while coercion needs a shape pair, so no technique falls in two variants.

## FAIL detail

None. No failures to quote.
