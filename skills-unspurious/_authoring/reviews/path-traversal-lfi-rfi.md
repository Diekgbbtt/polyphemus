# Skills-reviewer report: class `path-traversal-lfi-rfi`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| traversal-read | PASS | none |
| lfi-include-execution | PASS | none |
| rfi-remote-include | PASS | none |
| archive-zipslip-write | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all four live at `skills-unspurious/path-traversal-lfi-rfi/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all four, each `description` is front-loaded with the variant leading word (`Read`, `Include`, `Fetch`, `Write`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all four. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` and `references/` carry no parent material for this class and the analysis marks proxy and scripted tests genuinely absent (section 3 and ontology matrix), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (read-containment clause vs local-inclusion clause vs remote-scheme clause vs extraction-containment clause), each matching analysis sections 7, 9, 11. Not a parent restatement (parent ships no Trust Assumptions section) or a sibling restatement.
5. Adversarial Capabilities: authored four-entry sections in all four, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: each variant holds only live entries (direct plus error plus masked-content shift vs error plus handler disclosure plus fetch receipt vs fetch receipt plus deterministic output plus fetcher error vs outside-write plus follow-up read plus extractor error). No verbatim copy of the parent list.
7. Bent step plus delta: `traversal-read` names canonical-read proof with in-root controls plus masked-content adjudication; `lfi-include-execution` names poison-then-include chaining with handler-execution proof; `rfi-remote-include` names host-then-fetch proof with scheme enablement verification and beacon confirmation; `archive-zipslip-write` names extract-then-locate proof with synthetic archives and outside-write location. Each states the parent gap explicitly. Matches analysis sections 9 and 11.
8. No concrete leak: bodies hold only abstract shapes (`<encoded-shape>`, `<dot-shape>`, `<mismatch-shape>`, `<separator-shape>`, `<absolute-shape>`, `<wrapper-shape>`, `<poison-shape>`, `<render-shape>`, `<remote-shape>`, `<entry-shape>`). No product, version, host, parameter, payload literal, or tool name in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with exclusions confined to `False Positives` predicates; leading words (`read`/`oracle`/`control`, `include`/`handler`/`poison`, `fetch`/`scheme`/`beacon`, `extract`/`entry`/`locate`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan; numbered-step prefixes excluded from the count).

## Sibling-disjointness check

The four siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Encoding, mismatch, spelling, and template-resolution values ride as aspects inside their owning variants, matching analysis sections 6, 9, and 11 grey points.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
