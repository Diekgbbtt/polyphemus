# Skills-reviewer report: class `insecure-file-uploads`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| upload-server-execution | PASS | none |
| upload-client-execution | PASS | none |
| upload-archive-extraction | PASS | none |
| upload-toolchain-execution | PASS | none |
| upload-pipeline-deferred-trust | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all five live at `skills-unspurious/insecure-file-uploads/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all five, each `description` is front-loaded with the variant leading word (`Server`, `Client`, `Archive`, `Toolchain`, `Pipeline`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all five. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques`, `Chaining Attacks` kept from parent material. Omitted `Tooling` carries no parent material for this class and scripted tests are genuinely absent per analysis section 3 and ontology section 6, so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (server-interpreter confinement vs serving-context confinement vs extraction confinement vs converter confinement vs timing consistency), each matching analysis sections 7, 9, 11. Not a parent or sibling restatement.
5. Adversarial Capabilities: authored three-entry sections in all five, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: each variant holds only live entries (interpreter-output set vs script-fire set vs out-of-directory plus exhaustion set vs processor side-effect set vs post-gate plus pre-verdict set). No verbatim copy of the parent list.
7. Bent step plus delta: `upload-server-execution` names place-then-invoke-handler with execution-URL discovery; `upload-client-execution` names capture-headers-then-prove-render; `upload-archive-extraction` names extract-then-locate-outside with exhaustion oracles; `upload-toolchain-execution` names trigger-job-then-read-side-effect; `upload-pipeline-deferred-trust` names act-after-the-gate with finalize plus delegated plus pre-verdict control. Each states the delta over parent steps P4 or P5 explicitly. Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns no hits (no interpreter product names, no handler-directive literals, no magic-byte literals, no traversal literals, no converter product names, no presigned parameter literals, no tool names). Abstract vocabulary (`script-shaped`, `configuration-shaped`, `disposition hints`, `sniffing guard`, `link-shaped entries`, `high-ratio`, `operator content`, `delegated control`, `pre-verdict polling`) is used throughout.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body and the required bent-step restatement, no sediment; phrasing is positive with exclusions stated as predicates; leading words (`placement`/`handler`/`interpreter`, `rendering`/`serving-header`/`script-fire`, `extraction`/`traversal`/`exhaustion`, `conversion`/`processor`/`side-effect`, `gate`/`finalize`/`pre-verdict`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines).

## Sibling-disjointness check

The five siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Presigned inline rendering routes to pipeline-deferred-trust by first-divergence order, cache-key effects ride as a serving secondary, and conversion-load timing rides as a timing secondary, matching analysis section 11 grey points.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
