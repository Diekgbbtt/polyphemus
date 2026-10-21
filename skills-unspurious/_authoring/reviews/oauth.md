# Skills-reviewer report: class `oauth`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| oauth-redirect-uri-validation | PASS | none |
| oauth-state-nonce-csrf | PASS | none |
| oauth-pkce-enforcement | PASS | none |
| oauth-code-client-binding | PASS | none |
| oauth-device-approval | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all five live at `skills-unspurious/oauth/<variant>/SKILL.md` with the exact SPEC section 9 and analysis section 11 names.
2. Frontmatter: `name` equals the directory in all five.
3. Each `description` is front-loaded with the variant leading word (`Redirect`, `Freshness`, `Verifier`, `Client`, `Device`) with distinct per-branch triggers.
4. Each carries `metadata.version` `1.0.0`.
5. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all five.
6. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks`, and `Tooling` are kept from parent material plus analysis notions.
7. Omitted `references/` carries no parent material for this class.
8. The analysis marks proxy techniques and scripted tests genuinely absent (sections 3 and 6, ontology matrix), so no omission is a stub.
9. The two `No advanced divergence` bodies carry parameter guidance plus a second operative sentence, so they are narrowed sections rather than stubs.
10. Trust Assumptions: shared agreement body once, failing clause varied per variant (destination-match vs freshness-binding vs verifier-binding vs client-identity vs approval-channel).
11. Each clause matches analysis sections 7, 9, and 11.
12. No variant restates the parent or a sibling.
13. Adversarial Capabilities: authored five-to-six-entry sections in all five, drawn from analysis `AttackerCapability` rows plus parent recon probes.
14. No stubs are present.
15. Detection Channels: the parent ships no `Detection Channels` section, so nothing is copied.
16. Each variant holds only live entries plus its own bent-step channels, with sibling sets explicitly excluded in the header line.
17. Bent step plus delta: `oauth-redirect-uri-validation` names P2 per-pattern normalisation-differential plus consumer confirmation.
18. `oauth-state-nonce-csrf` names P3 binding-scope plus reuse-oracle plus nonce-replay confirmation.
19. `oauth-pkce-enforcement` names P4 issuance-without-challenge plus verifier-oracle probing.
20. `oauth-code-client-binding` names P5 authorize-versus-redemption comparison plus mix-up sequencing.
21. `oauth-device-approval` names P5 device-code polling plus approval inducement.
22. Each states the parent gap explicitly (`which names ... but never names ..., so this variant owns ...`) and matches analysis sections 9 and 11.
23. No concrete leak: pattern search over product, version, host, endpoint, parameter, payload-literal, and tool-name literals returns no body hits.
24. Bodies use abstract carriers (`destination`, `freshness carrier`, `challenge`, `verifier`, `client identity`, `user code`) with placeholder shapes only.
25. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, and no sediment.
26. Phrasing is positive with agent-directed prohibitions absent; server-side `never` statements describe check behavior rather than steering the agent.
27. Leading words (`validation`/`destination`/`matrix`, `freshness`/`binding`/`oracle`, `verification`/`verifier`/`issuance`, `binding`/`comparison`/`sequence`, `approval`/`polling`/`inducement`) repeat through each body.
28. No em dashes exist in any file.
29. Every authored prose line holds one full sentence, verified by sentence-split scan excluding frontmatter, headings, bullets, numbered steps, and code fences.

## Sibling-disjointness check

The five siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Mobile dispatch rides inside the redirect variant as a transport parameter.
Referrer harvesting rides inside redirect plus binding variants as an exfil-channel parameter.
Dynamic registration plus secretless calls plus scope over-request plus refresh reuse plus account linking ride inside the binding variant as secondary divergences.
Token-format mutation is consumed from the token companion skill and never re-proven.
These placements match analysis section 11 grey points.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
