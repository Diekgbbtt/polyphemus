# Skills-reviewer report: class `http-request-smuggling`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| http-request-smuggling-h2-desync | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: the variant lives at `skills-unspurious/http-request-smuggling/http-request-smuggling-h2-desync/SKILL.md` with the exact analysis section 11 and SPEC section 9 name.
2. Frontmatter: `name` equals the directory, `description` is front-loaded with the variant leading word (`Downgrade`) with distinct triggers (downgrade path condition, declared-length disagreement, spec-forbidden framing survival), and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` and `references/` carry no parent material for this class and the analysis marks scripted tests genuinely absent (sections 3, 6), so no omission is a stub.
4. Trust Assumptions: states the shared agreement (back-end trusts front-end parsed framing on the shared socket) with a variant-specific failing mapping clause (downgrade path derives back-end framing from an attacker-supplied header field the HTTP/2 framing never authorised), matching analysis sections 9 and 11. The parent ships no Trust Assumptions section and there are no siblings, so no restatement.
5. Adversarial Capabilities: authored five-entry section drawn from the analysis discriminator `AttackerCapability` row plus parent recon probes (raw header-block crafting, declared-length vs pseudo-header discipline, spec-forbidden framing, reused-connection observation, short-prefix shaping). No stub.
6. Detection Channels: holds only live entries (downgrade mapping, passthrough survival, length divergence, connection correspondence, differential marker confirmation). No verbatim copy of the parent timing, obfuscation, or H2-detection lists.
7. Bent step plus delta: names header-block construction with injected framing headers plus downgrade-mapping, passthrough-survival, and connection-reuse observation over parent P8, with H2.CL and H2.TE carried as enumerated injection values inside the one variant. Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, endpoint, payload-literal, and tool-name patterns returns only abstract placeholders (`declared-length placeholder`, `smuggled-prefix placeholder`, `forbidden-field placeholder`, `pseudo-header fields`). No proxy products, app servers, Burp, hostnames, endpoint paths, chunk bytes, marker literals, or obfuscation values in the body.
9. Style: no no-ops, no cross-section duplication beyond the licensed technique-to-methodology backbone, phrasing is positive with the close-out guardrail paired with the positive target (reconcile or reject at translation); leading words (`downgrade`, `mapping`, `passthrough`, `marker`) repeat through the body.
10. No em dashes in the file; every authored prose line holds one full sentence (verified by sentence-split scan).

## Sibling-disjointness check

Single-variant class beside the retained base; raw-socket framing probes stay in the base per analysis H2, header-block injection belongs to exactly this variant. No technique falls in two variants.

## FAIL detail

None. No failures to quote.
