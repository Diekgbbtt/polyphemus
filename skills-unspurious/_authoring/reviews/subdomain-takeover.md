# Skills-reviewer report: class `subdomain-takeover`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| dangling-record-resource-claim | PASS | none |
| cdn-alternate-domain-binding | PASS | none |
| ns-delegation-takeover | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/subdomain-takeover/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Claim`, `Bind`, `Seize`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (resource-ownership clause vs alternate-name binding clause vs delegation-liveness clause), each matching analysis sections 7, 9, 11.
5. Adversarial Capabilities: authored five-entry sections in all three, drawn from analysis `AttackerCapability` rows plus parent recon probes.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied.
7. Bent step plus delta: `dangling-record-resource-claim` names S5 exact-name creation with binding-flow plus verification-gap plus race-window handling; `cdn-alternate-domain-binding` names S5 alternate-name association with certificate handling plus edge-differential fingerprinting; `ns-delegation-takeover` names S2 delegation tracing plus expiry and liveness checks.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns no hits in any body.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body, phrasing is positive with stop conditions paired with the positive target; leading words (`Claim`, `Bind`, `Delegate`/`Seize`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
The MX mail surface and wildcard scope are carried as outlier and aspect inside the matching variant, matching analysis sections 7, 9, and 11.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
