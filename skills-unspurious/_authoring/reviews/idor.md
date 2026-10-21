# Skills-reviewer report: class `idor`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| idor-direct-object-swap | PASS | none |
| idor-collection-batch-scope | PASS | none |
| idor-deferred-artifact-redemption | PASS | none |
| idor-context-carrier-substitution | PASS | none |
| idor-nested-expansion-binding | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all five live at `skills-unspurious/idor/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all five, each `description` is front-loaded with the variant leading word (`Swap`, `Scope`, `Redeem`, `Substitute`, `Expand`) with three distinct per-branch triggers and no synonym restatement, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all five. Conditional `Reconnaissance`, `Bypass Techniques`, and `Chaining Attacks` kept from parent material. Omitted `Advanced Techniques`, `Tooling`, and `references/` carry no parent material for this class (parent ships none of them) and the analysis plus ontology matrix mark scripted tests genuinely absent, so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (foreign-identifier substitution vs per-member set validation vs retrieval-time recheck vs adversary-controlled channel resolution vs parent-binding inheritance), each matching analysis sections 7, 9, and 11. Not a parent restatement (parent ships no such section) nor a sibling restatement. The shared body with micro-verbatim clause change is licensed by SPEC section 5.
5. Adversarial Capabilities: authored capability sections in all five, drawn from analysis `AttackerCapability` rows plus parent reconnaissance probes, each naming the procedure owned by `two-principal-authz` rather than restating it. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (control-pair differentials vs per-position and filter-skip signals vs redemption and scope-expiry signals vs precedence and audience signals vs per-hop and per-node expansion signals).
7. Bent step plus delta: `idor-direct-object-swap` names control-paired substitution with evidence-derived verb plus differential confirmation; `idor-collection-batch-scope` names adversarial pagination with per-position verdicts; `idor-deferred-artifact-redemption` names two-phase create-then-redeem binding with scope and expiry; `idor-context-carrier-substitution` names identity-source precedence probing with audience binding checks; `idor-nested-expansion-binding` names projection-parameter escalation with per-hop resolver verdicts. Each states the parent gap explicitly (`is the bent step this variant owns over the parent`). Matches analysis sections 9 and 11.
8. No concrete leak: scan over product, version, host, param, payload-literal, and tool-name patterns returns only licensed skill cross-references in backticks (`two-principal-authz`, `race-conditions`, `graphql`, `authentication-jwt`, `oauth`). No IPs, URLs, wrapper literals, header literals, knob literals with backticks, or tool names in any body. Generic words (`include`, `expand`, `headers`, `selectors`) appear without literals and name abstract categories, not concrete values.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. differential reading, per-position deciding, re-check verification); leading words (`swap`, `scope`, `redeem`, `substitute`, `expand`) repeat through each body and anchor the description.
10. No em dashes in any file; every authored body and bullet prose line holds one full sentence (numbered-step `N.` prefixes excluded as labels, frontmatter fences excluded, methodology action-plus-completion-criterion lines counted as one sentence by design per precedent).

## Sibling-disjointness check

The five siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Grey-point assignments from analysis section 11 are honoured: routing-only selectors stay in the direct variant while selector-as-identity lives in the carrier variant; storage signed-URL work rides in the deferred variant as scope-and-expiry redemption; GraphQL aliasing and batching ride in the expansion variant as multiplexed per-node verdicts; parser, cache-key, and race detail invoke the bypass, proxy, and race families by name only.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
