# Skills-reviewer report: class `ssti`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| ssti-reflected-evaluation | PASS | none |
| ssti-blind-evaluation | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: both live at `skills-unspurious/ssti/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in both, each `description` is front-loaded with the variant leading word (`Reflected`, `Blind`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in both. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` carries no parent material (parent ships no `Tooling` section). `references/` is kept only in the blind variant where the class has the material, per the ontology matrix (`ssti`: none absent) and analysis section 3. No omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (evaluation clause with same-response reflection vs observability clause with hidden result recoverable only through deferred render or side-channel oracles), each matching analysis sections 9 and 11. Not a parent restatement (parent ships no `Trust Assumptions` section) nor a sibling restatement.
5. Adversarial Capabilities: authored four-entry sections in both, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (same-response proof plus literal-reflection negative plus error-text plus host-object rendering vs deferred-endpoint reflection plus latency plus callback plus length-or-checksum plus file-write oracle).
7. Bent step plus delta: `ssti-reflected-evaluation` names S3 confirm-evaluation as the first bent step with the differential-proof grammar plus second-expression coincidence exclusion plus literal-reflection adjudication delta. `ssti-blind-evaluation` names S1 find-templated-input through store-then-sweep as the first bent step with the sweep plus latency plus callback plus length-diff delta. Matches analysis sections 9 and 11.
8. No concrete leak: grep over engine names, payload literals, version, host, param, and tool-name patterns returns nothing in either body. Both bodies stay at abstract conditions (delimiter family, arithmetic probe, delay primitive, outbound request, attacker-operated infrastructure). Cross-skill naming of `path-traversal-lfi-rfi` at the file-read step is the licensed boundary reference, not a tool leak.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body and the shared escape-grammar aspect the analysis carries inside both variants, no sediment; phrasing is positive with exclusions only as scope guards; leading words (`differential probe`, `store-then-sweep` plus `oracle`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (methodology numbering periods excluded from the sentence count).

## References placement check

The parent `skills-unspurious/ssti/references/blind-probe-signals.md` retains concrete payload spellings and stays parent scope, outside the variant review.
The blind variant ships `ssti-blind-evaluation/references/blind-oracles.md`, which reframes the same oracle material (timing, out-of-band callback, length-differential) as abstract signal shapes with completion bars and states that concrete spellings are runtime knowledge-base facts.
The reflected variant correctly ships no `references/` dir because its differential-proof grammar lives inline in the body per analysis section 9.
No concrete tooling leaks from the parent reference into either variant body or the blind variant reference.

## Sibling-disjointness check

The two siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Same-response arithmetic proof and non-same-response inference admit no shared technique, with routing by first non-coverable step (S1 divergence claims blind, otherwise S3 claims reflected), matching analysis section 10.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
