# Skills-reviewer report: class `header-injection`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| header-crlf-splitting | PASS | none |
| header-host-forward-spoof | PASS | none |
| header-cache-poisoning | PASS | none |
| header-method-override | PASS | none |
| header-request-smuggling | PASS | none |
| header-response-value-confusion | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all six live at `skills-unspurious/header-injection/<variant>/SKILL.md` with the exact analysis section 11 H4 names.
2. Frontmatter: `name` equals the directory in all six, each `description` is front-loaded with the variant leading word (`Splitting`, `Spoofing`, `Poisoning`, `Overriding`, `Smuggling`, `Confusing`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all six.
4. Conditional sections `Reconnaissance`, `Bypass Techniques`, and `Chaining Attacks` are kept from parent material in all six.
5. Omitted `Advanced Techniques`, `Tooling`, and `references/` carry no parent material for this class.
6. The analysis marks proxy techniques and scripted tests genuinely absent (analysis section 3, ontology matrix row for `header-injection`), so no omission is a stub.
7. Trust Assumptions: shared agreement body once per SPEC section 5, failing clause varied per variant (framing-meaning clause vs canonical-host clause vs cache-key clause vs routing-order clause vs framing-agreement clause vs client-semantics clause).
8. Each failing clause matches analysis sections 7, 9, and 11 for its variant.
9. No clause restates the parent, since the parent ships no `Trust Assumptions` section.
10. No clause restates a sibling, since stored-header-field vs link-plus-decision vs victim-key-body vs pre-check-reroute vs leftover-bytes vs same-response-client predicates are pairwise disjoint under the four analysis exclusions.
11. Adversarial Capabilities: authored four-entry sections in all six, drawn from analysis `AttackerCapability` rows plus parent recon probes.
12. No capability section is a stub.
13. Detection Channels: the parent ships no `Detection Channels` section, so nothing is copied.
14. Each variant holds only live entries (stored-framing set vs link-plus-decision set vs victim-key-body set vs order-of-check set vs leftover-leakage set vs jar-plus-render-plus-navigation set).
15. Bent step plus delta: `header-crlf-splitting` names downstream-serving proof of a stored header field to an unrelated request.
16. `header-host-forward-spoof` names swapped-precedence comparison plus out-of-band capture plus per-alias decision mapping.
17. `header-cache-poisoning` names the five-member sub-shape sweep plus eligibility handling under a clean-replay body oracle.
18. `header-method-override` names override-plus-rewrite order proof with rewrite-after-auth ownership.
19. `header-request-smuggling` names boundary-pair plus cross-version replay proof with leftover-bytes disclosure.
20. `header-response-value-confusion` names delimiter-free replacement with same-response client-behavior proof.
21. Each variant states the parent gap explicitly (`The parent ... covers only ... so this variant owns ...`).
22. Each bent step matches analysis sections 9 and 11.
23. No concrete leak: pattern scan over product, version, host, param, payload-literal, and tool-name markers returns no hits in any body.
24. No backtick literals, no percent-encodings, no concrete header-name literals, no platform names, no endpoint or asset identities appear in any variant.
25. Generic family words (`Host`, `attacker host`, `cache-signal`, `rewrite-capable stacks`) are abstract conditions at the parent abstraction level, not runtime facts.
26. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, and no sediment.
27. Phrasing is positive with boundary exclusions stated as sibling ownership (`belongs to ... so neither rides here`, `Name ... rather than restating`) paired with the positive target.
28. Leading words (`splitting`/`stored`/`framing`, `spoofing`/`precedence`/`mapping`, `poisoning`/`split`/`sweep`, `overriding`/`order`/`reroute`, `smuggling`/`boundary`/`leakage`, `confusion`/`sink`/`replacement`) repeat through each body.
29. No em dashes exist in any file.
30. Every authored prose line holds one full sentence, verified by sentence-split scan of body and bullet lines.

## Sibling-disjointness check

The six siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Line-break payloads belong solely to splitting, delimiter-free replacement solely to value-confusion, rewrite headers solely to routing, framing pairs solely to smuggling, clean-replay body proof solely to cache, and link-plus-decision proof solely to spoof, matching the four analysis disjointness exclusions.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
