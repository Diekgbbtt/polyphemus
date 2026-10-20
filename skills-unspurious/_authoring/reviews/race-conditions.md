# Skills-reviewer report: class `race-conditions`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| idempotency-dedup-bypass | PASS | none |
| optimistic-guard-evasion | PASS | none |
| cross-service-consistency-race | PASS | none |
| single-request-fanout | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all four live at `skills-unspurious/race-conditions/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all four, each `description` is front-loaded with the variant leading word (`Idempotency`, `Optimistic`, `Cross-service`, `Fanout`) with distinct per-branch triggers matching the three Key Vulnerabilities subsections, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all four. Conditional `Reconnaissance`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Advanced Techniques`, `Tooling`, `references/` carry no parent material for this class (parent ships none of them) and the analysis marks scripted tests genuinely absent (sections 3 and 11, ontology matrix), so no omission is a stub.
4. Trust Assumptions: shared agreement body once per SPEC section 5, failing clause varied per variant (durable dedup clause vs version-guard clause vs visibility-ordering clause vs one-request-one-effect clause), each matching analysis sections 9 and 11. Not a parent or sibling restatement.
5. Adversarial Capabilities: authored four-to-five-entry sections in all four, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: each variant holds only live entries (dedup-shaped doubles vs guard-shaped overwrites vs ordering-shaped divergence vs intra-request multiplication), narrowed from parent signals, no verbatim parent copy.
7. Bent step plus delta: `idempotency-dedup-bypass` names S4 key-scope reuse plus commit-window probing plus response-versus-effect forensics; `optimistic-guard-evasion` names S4 token omission plus stale replay plus cross-path gaps; `cross-service-consistency-race` names S2 write-versus-publish ordering plus retry storms plus compensation triggering; `single-request-fanout` names S4 batched plus aliased plus persisted packing with persistent-channel emits. Each states the parent gap explicitly (`The parent ... covers only ... and cannot describe ..., so this variant owns ...`). Matches analysis sections 7, 9, and 11.
8. No concrete leak: scan over product, version, host, param, payload-literal, and tool-name patterns returns only the generic isolation-level word `Serializable` (same abstraction as the parent) and the licensed cross-skill names (`graphql`, `two-principal-authz`, `business-logic`, `proxy-techniques`, `defence-bypass` families per ontology section 8). No IPs, URLs, parameter names, payload literals, or tool names in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. transient echoes recorded as inconclusive); leading words (`Idempotency`, `Optimistic`, `Cross-service`, `Fanout`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines).

## Sibling-disjointness check

The four siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Key-scope forensics, token-mutation probing, cross-service window triggering, and intra-request fan-out are disjoint by execution shape and locus, matching analysis section 10.
Storage finalize and one-time-token races stay in the parent core as aspects per analysis sections 6, 7, and 11.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
