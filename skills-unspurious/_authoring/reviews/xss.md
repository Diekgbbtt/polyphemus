# Skills-reviewer report: class `xss`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| xss-stored | PASS | none |
| xss-dom | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: both live at `skills-unspurious/xss/<variant>/SKILL.md` with the exact analysis section 11 names. Reflected folds to the parent baseline per analysis H4 and is correctly absent as a child.
2. Frontmatter: `name` equals the directory in both, each `description` is front-loaded with the variant leading word (`Stored`, `DOM`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in both. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks`, `Tooling` kept from parent material. The ontology matrix marks no notion genuinely absent for this class and scripted tests are inline, so no `references/` omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (persistence clause vs server-mediation clause), each matching analysis sections 7, 9, 11. Not a parent restatement (parent ships no `Trust Assumptions` section) and not a sibling restatement.
5. Adversarial Capabilities: authored five-entry sections in both, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (later-view retrieval set vs instrumented sink-invocation set).
7. Bent step plus delta: `xss-stored` names S1 plus S2 two-phase write-then-retrieve mapping with locus-appropriate confirmation; `xss-dom` names S2 browser-instrumented client-only tracing with sink-invocation confirmation only. Each states the parent gap explicitly. Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns nothing in either body. No code identifiers, URLs, platform names, or tool names. Transports are abstracted (`direct calls`, `query APIs`, `socket channels`, `event streams`, `background workers`).
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. second-view rendering, sink-log entry, write-to-retrieval mapping first); leading words (`stored`/`retrieval`/`pair`, `instrumentation`/`sink`/`trace`) repeat through each body.
10. No em dashes in either file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines).

## Sibling-disjointness check

The two siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
The persistence-presence mutex plus the server-reflection mutex for the non-persistent remainder hold: any technique with a persistence boundary belongs to stored even with a client sink, and DOM owns only non-persistent client-only flows.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
