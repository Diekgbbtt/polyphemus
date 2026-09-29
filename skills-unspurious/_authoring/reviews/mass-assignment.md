# Skills-reviewer report: class `mass-assignment`

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| mass-assignment-nested-relation-write | PASS | none |
| mass-assignment-bulk-collection-injection | PASS | none |
| mass-assignment-bulk-nested-relation-write | PASS | none |

## Criterion-by-criterion notes (all PASS, grounding)

1. Dir path and exact variant name: all three live at `skills-unspurious/mass-assignment/<variant>/SKILL.md` with the exact analysis section 11 names.
2. Frontmatter: `name` equals the directory in all three, each `description` is front-loaded with the variant leading word (`Nested`, `Bulk`, `Bulk-nested`) with distinct per-branch triggers, and `metadata.version` is `1.0.0`.
3. Ubiquitous sections: all nine (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`) present in all three. Conditional `Reconnaissance`, `Advanced Techniques`, `Bypass Techniques` kept from parent material. Omitted `Chaining Attacks`, `Tooling`, `references/` carry no parent material for this class and the analysis marks proxy, anti-patterns, scripted tests, and chaining genuinely absent (ontology section 6 matrix), so no omission is a stub.
4. Trust Assumptions: shared agreement body once, failing clause varied per variant (nested-scope clause vs collection-scope clause vs combined-scope clause), each matching analysis sections 9 and 11. Not a parent restatement (parent ships no `Trust Assumptions` section) and not a sibling restatement. The leak-scope tailoring (privilege plus ownership plus gate plus billing reached through a child vs through a batch slot vs through a child hidden inside a batch slot) is licensed narrowing to the variant goal, not clause drift.
5. Adversarial Capabilities: authored five-to-six-entry sections in all three, drawn from analysis `AttackerCapability` rows plus parent recon probes. No stubs.
6. Detection Channels: parent ships no `Detection Channels` section, so nothing is copied. Each variant holds only live entries (child-state set vs per-position slot set vs per-position child set, each with its own non-finding guard).
7. Bent step plus delta: `mass-assignment-nested-relation-write` names S6 relation-graph traversal with child-scope verdicts on one object; `mass-assignment-bulk-collection-injection` names S6 per-position verdicts against boundary-only validation on flat objects; `mass-assignment-bulk-nested-relation-write` names S6 per-position outer loop where each position needs full relation-graph traversal with its own child-scope verdict. Each states the parent gap explicitly (`The parent variation step names ... but never describes ..., so this variant owns ...`). Matches analysis sections 9 and 11.
8. No concrete leak: grep over product, version, host, param, payload-literal, and tool-name patterns returns only the generic word `roles` (cross-role diffs, an abstract setup term) and frontmatter fences. No field-name literals, no framework names, no encodings literals, no payload literals, no tool names in any body. The `race-conditions` mention is the licensed cross-reference at the owned TOCTOU step, not a leak.
9. Style: no no-ops, no cross-section duplication beyond the licensed shared trust body plus sibling-scope guards, no sediment; phrasing is positive with prohibitions only as scope guardrails paired with the positive target (e.g. fresh reads, narrow attempts, inconclusive recording); leading words (`relation`/`child`/`traversal`, `batch`/`slot`/`position`, `combined`/`outer`/`inner`) repeat through each body.
10. No em dashes in any file; every authored prose line holds one full sentence (verified by sentence-split scan of body and bullet lines; methodology numbering is list markup, not a second sentence).

## Sibling-disjointness check

The three siblings share the trust-agreement body and vary only at the failing clause plus the licensed goal tail, per SPEC section 5.
Singleton versus batch selects the outer home and flat versus nested selects the inner home, matching analysis section 10 disjointness and section 11 grey points.
Shape evasion, content-type switching, and GraphQL framing ride as defeat aspects inside the owning scope variant, never as standalone variants.
No technique falls in two variants.

## FAIL detail

None. No failures to quote.
