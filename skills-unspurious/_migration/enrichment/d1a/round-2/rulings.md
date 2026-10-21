# D1a round-2 assessment rulings

*Status: the operator's assessment of the round-2 synthesis (`round-2/synthesis.md`, committed `1e61eb8a`), recorded 2026-10-19 by the orchestrator.*
*This file closes W7's mining phase; D1b executes from the round-1 and round-2 rulings together.*

## 1. The rulings

- New classes: only two of the nine recommended are accepted: MFA/2FA bypass and account-recovery flow flaws.
  Every other recommended class is disregarded: SAML/SSO assertion forgery, broken-link and external-resource hijacking, legacy-protocol authentication parity, WebSocket security, clickjacking, supply chain and CI/CD, cloud IAM, and `llm-training-data-extraction` (the AI scope is not extended).
- Second-order leaves: second-order SQL injection and second-order IDOR are big lacks; a leaf is added under `sql-injection` and under `idor`.
  This supersedes the round-1 non-match reading for both (see section 2).
- `bfla-client-hint-authorization-trust`: folded into `bfla-client-identity-trust`; the Referer or any other identity-hint gate and any different testing primitive become part of that leaf, not a new leaf.
- `predictable-token-brute-force`: folded into `crypto-predictable-token`, because the reasoning is the same (almost every token is at least encoded and mixed for entropy, so the encoding assumption does not separate them).
  The `weak-credential-discovery` parent and its leaves `session-token-authority-decode` and `exposed-secret-extraction` directly reference the crypto layer in the steps that benefit from it (advanced, bypass, or reconnaissance steps that fingerprint the crypto algorithm used).
- Not-mentioned classes are disregarded: the trimming above is exhaustive for new classes.
- The two optional variants are not created as skills; their material lands as enrichments (`crypto-cipher-mode-weakness` into `crypto-weakness`; the renderer-script SSRF as the `ssrf` aspect round 1 held). Recorded here for correction if unintended.
- Everything else from the synthesis stands as recommended: the merges and enrichments are the D1b execution plan; the references execute in D1c; the rejects and deferrals stand (`llm-model-poisoning`, `llm-overreliance-hallucination`, NTLM disclosure, message-protocol injection, the network-layer set, HSTS); the grey-point recommendations hold the operator's earlier rulings.

## 2. The "reversal" explained (recorded for the operator's question)

Round 1's slice-2 recorded the second-order IDOR case as a non-match, arguing the existing leaves (`idor-deferred-artifact-redemption`, and the blind case) already carry it.
Round 1's slice-4 recorded second-order SQL injection as a non-match, arguing the parent already carries it as an Advanced-Technique paragraph; both readings cited the operator's algorithm example (a second-order IDOR that should not match) as the precedent.
The blind round-2 slice-4 proposed `sqli-second-order-injection` at high confidence: its boundary test disagreed with round 1's non-match verdict, which is what "directly reverses round 1" meant.
The operator's ruling settles it: both are genuine lacks and get leaves; the non-match reading is superseded.

## 3. The final round-2 classification map

| Item | Ruling | Taxonomy home | Next action |
|---|---|---|---|
| MFA/2FA bypass | accepted | new level-1 group `mfa-bypass` (final name at authoring) | author (D1b) |
| Account-recovery flow flaws | accepted | new level-1 group `account-recovery` (final name at authoring) | author |
| Second-order SQL injection | accepted | level-2 leaf under `sql-injection` (`<class>-<discriminator>` per R5) | author |
| Second-order IDOR | accepted | level-2 leaf under `idor`; authoring keeps it disjoint from `idor-deferred-artifact-redemption` | author |
| `bfla-client-hint-authorization-trust` | folded | `bfla-client-identity-trust` (identity-hint gates: Referer, routing headers, origin headers; their testing primitives) | enrich |
| `predictable-token-brute-force` | folded | `crypto-predictable-token`; the `weak-credential-discovery` parent, `session-token-authority-decode`, and `exposed-secret-extraction` reference the crypto layer at their crypto-fingerprinting steps | enrich and wire |
| all other recommended classes | disregarded | none | none |
| `crypto-cipher-mode-weakness` (optional) | not a skill | enrichment of `crypto-weakness` | enrich |
| `ssrf-renderer-script-ssrf` (optional) | not a skill | the round-1 `ssrf` aspect | enrich |

## 4. The state after the mining phase

The two rounds together commit 20 new skills: 16 from round 1 (7 classes, 9 leaves) plus 4 from round 2 (2 classes, 2 leaves), plus the folds and the enrichment and reference plans.
D1b executes the accepted authoring, the folds, and the union of the enrichment candidates; D1c the references and scripts.
Then the single review round, the merge into the trunk, and the final integration.
