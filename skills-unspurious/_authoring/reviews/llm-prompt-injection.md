# Skills-reviewer report: class `llm-prompt-injection`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| direct-injection-override | PASS | none |
| indirect-injection-plant | PASS | none |
| context-leakage | PASS | none |
| tool-abuse | PASS | none |
| output-handling | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all five live at `skills-unspurious/llm-prompt-injection/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all five, each `description` is front-loaded with the variant leading action (`Override`, `Plant`, `Extract`, `Steer`, `Coax`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all five. Conditional `Reconnaissance`, `Bypass Techniques`, and `Chaining Attacks` kept from parent material. Omitted `Advanced Techniques`, `Tooling`, and `references/` carry no parent material for this class (parent ships none of them) and the analysis marks scripted tests genuinely absent (section 3), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (instruction-separation clause vs ingested-content-as-data clause vs hidden-text non-disclosure clause vs tool-choice-and-arguments clause vs sink-safe-output clause), each matching analysis sections 9 and 11. Not a parent or sibling restatement.
5. Adversarial Capabilities: authored five-entry sections in all five, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (chat-behavior set vs victim-context set vs disclosure-evidence set vs invocation-evidence set vs sink-behavior set).
7. Bent step plus delta: `direct-injection-override` names S2 turn-scoped replacement plus breakout plus wrapped probes; `indirect-injection-plant` names S3 placement-scoped seeding plus victim-triggered detonation; `context-leakage` names S4 ground-truth-matched verbatim plus schema plus boundary disclosure; `tool-abuse` names S5 log-confirmed steering plus argument filling plus content-to-call chaining; `output-handling` names S6 sink-proven markup plus statement plus exfiltration emission. Each states the parent gap explicitly (`The parent ... names only generic ... and cannot describe ..., so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns only frontmatter fences in the variants; all literals (`Ignore previous instructions`, `SYSTEM:`, `attacker@evil.com`, `<system>` tags, `<img src=x`, base64, ROT13, framework names) live in the parent only. Variant bodies use placeholder-shaped abstractions throughout.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body and the delivery-aspect carriage inside the sink variants, no sediment; phrasing is positive with prohibitions only as guardrails paired with the positive target (e.g. confirm in the log, match against ground truth, confirm at the sink); leading words (`override`/`replacement`/`breakout`/`wrapper`, `plant`/`seed`/`retrieval`/`detonation`, `leakage`/`disclosure`/`extraction`/`ground truth`, `abuse`/`steer`/`argument`/`chain`/`log`, `handling`/`emission`/`sink`/`encoding`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines).

## Sibling-disjointness check

The five siblings share the trust-agreement body and vary only at the failing clause, per SPEC section 5.
Delivery channel is carried as an aspect inside the three sink variants with membership decided by the terminal proving step, matching analysis section 11 grey points.
The markdown-image exfiltration pattern is attributed by proving artifact (invocation log in `tool-abuse` vs rendered request in `output-handling`), matching the analysis grey point.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
