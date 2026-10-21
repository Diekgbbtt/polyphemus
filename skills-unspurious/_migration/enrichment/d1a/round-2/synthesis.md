# D1a enrichment round-2 synthesis (W7, C4-full enrichment)

*Report only. No suite skill was modified. No git state was changed. The orchestrator commits.*
*Synthesis of six independent round-2 slices (`slice-1.md` through `slice-6.md`, same directory).*
*Inputs: the round-1 set (`../proposal.md`, the 19 proposals A1-A20 with Sections B/C/D) and the operator's assessment (`../rulings.md`, the accepted set, the merges, the re-classings, the rejected A5, the blanket-confirmed triage items, and the classification map).*
*Round 2 ran blind: no slice read the round-1 reports or the rulings.*
*Scope: the full `skills-unspurious/` suite, 44 groups, base skills plus variant leaves.*

Source path aliases used below:

- `HS/` = `/Users/diekgbbtt/hacking-skills/skills/`
- `CBH/` = `/Users/diekgbbtt/claude-bug-hunter/skills/`
- `ACS/` = `/Users/diekgbbtt/anthropic-cybersecurity-skills/accepted/`
- `AWS/` = `/Users/diekgbbtt/awsome-offensive-security-skill/skills/`

---

## 1. Executive summary

### Round-2 totals

- New-skill proposals: 18 distinct (slice-1 3, slice-2 2, slice-3 9, slice-4 2, slice-5 2, slice-6 0).
- Enrichment candidates: 188 (slice-1 26, slice-2 18, slice-3 31, slice-4 17, slice-5 42, slice-6 54).
- References/scripts candidates: 29 (slice-2 9, slice-3 4, slice-5 6, slice-6 10; slice-1 and slice-4 carry none).
- Residual candidates: 65 raw across the six slices, about 57 after cross-slice dedup.

### The headline evaluation

The second round shows convergence in coverage and a stable extension, not a new discovery set.
The blind swarm re-found 24 of the 25 rows in the round-1 classification map.
Only one round-1 assessed item, the rejected A5 `crypto-oracle-decryption`, was not re-found.
The finding set is therefore stable: a second independent pass over the same corpus reproduced almost the whole round-1 surface.
The genuinely new value is small and sits at the suite edges: the AI surfaces, the auth-adjacent flows (SAML, MFA, account recovery), the supply-chain and cloud surfaces, and a handful of variants.

The convergence is in coverage, not in shape.
Round 2 re-found only 5 items in the same taxonomy shape as the operator's ruling.
About 19 items were re-found with a different shape: a merge re-read as a variant, a variant re-read as an aspect, a class re-read as a reference, or the reverse.
The two blind passes agree on the source material and disagree on the boundary test.
This is the central result of the round.

### The strongest 3-5 findings

1. **Coverage converges; shape does not.** 24 of 25 round-1 assessed items were re-found, but only 5 in the same shape. The boundary doc is under-determined for the disputed seams.
2. **Five boundary-verdict reversals on round-1 confirmations and merges.** Round 2 reads A10 local-DTD exfiltration, A11 email-header injection, A12 partial-construction race, and A17 cross-protocol desync as aspects or enrichments rather than leaves, and reads the A18 attempt-batching leaf as a `throttle-evasion` enrichment. Conversely it reads the A6 lfi filter-chain merge as a variant.
3. **The second-order SQL reversal.** Round 2 slice-4 (high confidence) proposes `sqli-second-order-injection` as a variant, while round 1 explicitly ruled second-order SQL a non-match using the operator's own second-order-IDOR example. This is the sharpest methodological conflict in the round.
4. **The AI-surface question recurs.** Round 2 slice-3 proposes three AI classes (`llm-training-data-extraction`, `rag-vector-store-weakness`, `mcp-tool-server`) against the operator's "keep the AI-feature surfaces minimal" ruling and the A8/A9 merges.
5. **Independent class pressure on CORS and cache-poisoning.** CORS is re-found as a class by four slices, and cache-poisoning by one, while the operator re-classed CORS as a reference and blanket-confirmed cache-poisoning as a group.

---

## 2. The overlap map (progressive extension tracking)

### 2a. Every round-1 assessed item against the round-2 finding

The classification map in `rulings.md` section 2 carries 25 rows: A1-A19 (19 items), the derived CSP companion row, and the five blanket-confirmed triage items.
The assessed item set is the 24 items (A1-A19 plus the five triage items); the CSP row is the derived companion of A19.

Shape key: **identical** = round 2 proposes the same taxonomy shape as the operator's ruling; **different shape** = round 2 re-finds the source but proposes a different fate; **not re-found** = round 2 does not carry the item.

| Round-1 item | Round-1 ruling | Round-2 finding | Shape | Reconciliation verdict |
|---|---|---|---|---|
| A1 `email-dns-takeover` | confirmed, level-2 leaf under `subdomain-takeover` | slice-1 re-proposes the same source as `mail-record-takeover`, a class with two variants (`mail-receipt-claim` from `CBH/hunt-subdomain` item 13, `mail-authorisation-claim` from chain 5) | different shape | Convergent source, competing shape. The round-2 `mail-authorisation-claim` is exactly A1. Keep the operator's leaf; the receipt variant is genuinely new and needs a separate fate. |
| A2 `excessive-data-exposure` | confirmed reshaped, level-2 leaf under `information-disclosure`; parent method-parametrisable | slice-2 Proposal 2 re-proposes it as `excessive-field-disclosure`, a fourth `information-disclosure` variant, same sources | identical | Converged. Keep the operator's leaf. Carry the slice-2 caveat that it may fold into `differential-oracle-disclosure`. |
| A3 `api-version-consistency` | re-classed, proxy-technique reference | slice-2 residual 1 re-proposes it as the class `api-inventory-shadow`; slice-6 keeps the shadow-route material in `defence-bypass-edge-origin-differential` | different shape | Keep the operator's reference. The class shape is the same topological clash the operator already rejected. |
| A4 `session-management` | confirmed caveated, new level-1 group | slice-1 residual 10 re-proposes a session class | identical | Converged. Keep the operator's group. |
| A5 `crypto-oracle-decryption` | rejected | not re-found | not re-found | Converged by absence. The rejection stands. The adjacent slice-3 `crypto-cipher-mode-weakness` is a different mechanism. |
| A6 `lfi-filter-chain-execution` | merged, enrichment of `lfi-include-execution` | slice-3 Proposal 1 re-proposes it as the variant `lfi-filter-chain-code-execution` | different shape | Keep the operator's merge. Round 2's variant shape is a competing reading of the same source. |
| A7 `graphql-subscription-hijack` | reshaped, content extension of `graphql` (light emphasis) | slice-3 re-proposes it as a low-confidence variant | different shape | Keep the operator's content extension. Round 2 itself offers the enrichment fallback. |
| A8 `mcp-tool-server-abuse` | merged, enrichment of `tool-abuse` | slice-3 Proposal 3 re-proposes it as the class `mcp-tool-server` (or a `tool-abuse` variant) | different shape | Keep the operator's merge. The class shape conflicts with the minimal-AI ruling. |
| A9 `rag-vector-store-abuse` | merged, enrichment of `indirect-injection-plant` | slice-3 Proposal 2 re-proposes it as the class `rag-vector-store-weakness` (or a `llm-prompt-injection` variant) | different shape | Keep the operator's merge. Same minimal-AI conflict. |
| A10 `xxe-local-dtd-error-exfiltration` | confirmed, level-2 leaf under `xxe` | slice-4 re-finds the source, rejects the variant on the two-half test, and records it as an aspect enrichment | different shape | Sharp conflict. The operator confirmed the leaf; round 2 reads the failing clause as unchanged external resolution. Hold the operator's confirmation and record the counter-argument. |
| A11 `email-header-injection` | confirmed, new level-1 group | slice-5 re-finds the source, calls it an aspect of the `header-injection` parent (transport is not a variant axis) | different shape | Sharp conflict. The operator confirmed the group. Round 2 reads transport as excluded. Hold the operator's group; record the counter-argument. |
| A12 `race-conditions-partial-construction` | confirmed, level-2 leaf under `race-conditions` | slice-5 re-finds the source, calls the different-requests race an enrichment of the parent atomicity-gap step | different shape | Sharp conflict. Hold the operator's leaf; record the counter-argument. |
| A13 `dom-clobbering` | re-classed, level-2 leaf `proxy-techniques-dom-clobbering` | slice-5 re-proposes it as `xss-dom-clobbering`, a third `xss` variant | different shape | Keep the operator's proxy-techniques leaf. The round-2 xss variant is a competing home. |
| A14 `client-side-path-traversal` | re-classed, level-2 leaf `proxy-techniques-client-side-path-traversal` | slice-5 residual 1 re-proposes it as a new class; slice-6 houses the parse-differential part in `proxy-techniques-url-parser-differential` | different shape | Keep the operator's leaf. Slice-6 already covers the parse half. |
| A15 `rce-config-delegate-execution` | merged, enrichment of `rce-pipeline-execution` | slice-5 re-finds the source as an aspect of `rce-command-injection` Internal Service Sinks | different shape (same enrichment kind, different home) | Both agree on an enrichment. Keep the operator's home; reconcile the home (`rce-pipeline-execution` versus `rce-command-injection`). |
| A16 `css-injection` | re-classed, level-2 leaf `proxy-techniques-css-injection` | slice-5 residual 2 re-proposes it as a class | different shape | Keep the operator's leaf. Round 2 itself flags the naming as low confidence. |
| A17 `http-request-smuggling-cross-protocol-desync` | re-classed, level-2 leaf under `http-request-smuggling` | slice-5 re-finds the source, calls it an aspect of the parent translation-hop step | different shape | Sharp conflict. Hold the operator's leaf; record the counter-argument. |
| A18 `defence-bypass-attempt-batching` | confirmed, level-2 leaf under `defence-bypass` | slice-6 folds the per-request cost amplification into `defence-bypass-throttle-evasion` as an enrichment | different shape | Sharp conflict. Hold the operator's leaf; record the counter-argument and the round-2 enrichment home. |
| A19 `cors-misconfiguration` | re-classed, defence-bypass reference | slices 1, 2, 5, and 6 re-propose it as a class (or an `allowance-gap` variant) | different shape | Keep the operator's reference. Record the four-slice class pressure. |
| CSP bypass (derived companion) | filled like A19, defence-bypass reference | slices 5 and 6 carry CSP as `defence-bypass-allowance-gap` enrichment | different shape (both non-class) | Converged in substance. Keep the reference; the enrichment home is compatible. |
| triage `rate-limit-bypass` | blanket-confirmed, new level-1 group | slice-4 residual 3 re-proposes a class; slices 2, 5, and 6 fold it into `throttle-evasion`/`weak-credential-discovery` | different shape (mixed) | Keep the operator's group; record the round-2 tension (the bypass is a `throttle-evasion` enrichment). |
| triage `http-parameter-pollution` | blanket-confirmed, new level-1 group | slice-6 folds it into `defence-bypass-parser-confusion`; slices 2 and 5 offer a class or a leaf | different shape (mixed) | Keep the operator's group; record the round-2 fold. |
| triage LDAP injection | blanket-confirmed, new level-1 group | slices 4 and 5 re-propose a class (combined with XPath) | identical | Converged. Keep the operator's group. |
| triage XPath injection | blanket-confirmed, new level-1 group | slices 4 and 5 re-propose a class (combined with LDAP) | identical | Converged. Keep the operator's group. |
| triage `cache-poisoning` | blanket-confirmed, new level-1 group | slice-6 residual 2 re-proposes a class; the `cache-deception` grey point offers an aspect reading | identical | Converged. Keep the operator's group. |

Tally: identical 5, different shape 19, not re-found 1.
Identical = A2, A4, LDAP, XPath, cache-poisoning.
Not re-found = A5.

### 2b. Reverse table: round-2 proposals and residuals that round 1 did not carry

These are the round-2 items with no round-1 counterpart.
Confidence is preserved from the slice reports.

| Round-2 item | Slice(s) | Kind | Confidence | Round-1 status |
|---|---|---|---|---|
| `sqli-second-order-injection` | 4 | proposal (variant under `sql-injection`) | high | round 1 explicitly ruled it a NON-MATCH |
| `bfla-client-hint-authorization-trust` | 2 | proposal (fourth BFLA variant) | medium | not carried |
| `predictable-token-brute-force` | 4 | proposal (variant under `weak-credential-discovery`) | medium | not carried |
| `oauth-response-type-swap` | 1 | proposal | low-medium | round 1 folded it into an aspect |
| `oauth-consent-grant-abuse` | 1 | proposal | low | round 1 folded it into an aspect |
| `mail-record-takeover` (two variants) | 1 | proposal (class or variant family) | medium | round 1 carried the chain-5 half as A1 only |
| `xss-dom-clobbering` | 5 | proposal (third `xss` variant) | medium | round 1 re-classed A13 to `proxy-techniques` |
| `ssrf-renderer-script-ssrf` | 5 | proposal (fourth `ssrf` variant) | medium | round 1 kept it an aspect |
| `crypto-cipher-mode-weakness` | 3 | proposal (variant of `crypto-weakness`) | medium | not carried |
| `crypto-key-reference-injection` | 3 | proposal (variant of `crypto-weakness`) | medium | round 1 treated it as an enrichment |
| `deserialization-parser-order-bypass` | 3 | proposal (variant of `insecure-deserialization`) | low-medium | round 1 treated it as an enrichment |
| `deserialization-lookup-triggered-class-load` / `lookup-injection` | 3 | proposal (variant or class) | low | round 1 flagged a possible escalation |
| `graphql-subscription-hijack` | 3 | proposal (variant of `graphql`) | low | round 1 reshaped it to a content extension (A7) |
| `lfi-filter-chain-code-execution` | 3 | proposal (variant of `path-traversal-lfi-rfi`) | medium-high | round 1 merged it (A6) |
| `llm-training-data-extraction` | 3 | proposal (new class) | medium | not carried |
| `rag-vector-store-weakness` | 3 | proposal (new class) | medium | round 1 merged it (A9) |
| `mcp-tool-server` | 3 | proposal (new class) | medium | round 1 merged it (A8) |
| SAML / SSO assertion forgery | 1, 5 | residual (new class) | high / medium | round 1 ruled it a NON-MATCH (baseline absent) |
| Broken-link / external-resource hijacking | 1 | residual (new class) | high | round 1 flagged it as an enrichment, arguably a distinct class |
| Legacy-protocol authentication-endpoint parity | 1 | residual (new class) | high | round 1 ruled it a NON-MATCH (baseline absent) |
| WebSocket security | 1, 5, 6 | residual (new class) | medium-high | round 1 folded it into `csrf` and `proxy-techniques` |
| Clickjacking | 1, 5, 6 | residual (new class) | medium | not carried |
| MFA / 2FA bypass | 1, 2, 5 | residual (new class) | medium-high | round 1 flagged it as an authentication boundary case |
| Account-recovery / password-reset flow flaws | 1, 4 | residual (class or variant) | medium | not carried |
| Loose-comparison coercion / type juggling | 1, 4, 6 | residual (class or aspect) | medium / high | round 1 ruled it a NON-MATCH (language-level) |
| Client-controlled authorization state | 1 | residual (class or technique) | medium | not carried |
| Forced browsing / unprotected-interface discovery | 2 | residual (class or BFLA variant) | medium-high | round 1 flagged it as a BFLA recon enrichment |
| SPA backend-API route mapping | 2 | residual (technique leaf) | medium | not carried |
| Authentication-challenge metadata disclosure (NTLM) | 2 | residual (`information-disclosure` variant) | medium | round 1 flagged NTLM as a concrete aspect |
| Forged external confirmation (unsigned webhook) | 2 | residual (`business-logic` variant) | medium-low | round 1 carried it as an enrichment |
| Account-takeover taxonomy as a chaining reference | 2 | residual (reference) | medium | not carried |
| Server-side parameter pollution in backend URL construction | 2 | residual (class or technique) | medium | round 1 carried the value in `proxy-techniques-url-parser-differential` |
| Framework-specific debug-surface families | 2 | residual (enrichment only) | low as a class | round 1 carried it as an enrichment |
| `llm-model-poisoning` | 3 | residual (new class) | low | not carried |
| `llm-overreliance-hallucination` | 3 | residual (no home) | low | not carried |
| AI code-completion sabotage | 3 | residual (technique leaf) | low | round 1 carried it as a LOW enrichment |
| `ai-data-extraction-via-ssrf` | 3 | residual (cross-reference) | low | round 1 carried it as an `ssrf` enrichment |
| XML injection without external entities | 4 | residual (aspect) | low | not carried |
| Message-protocol / wire-format injection | 4 | residual (weak) | low | not carried |
| Supply chain and CI/CD pipeline attacks | 5 | residual (new class) | medium | not carried |
| Cloud IAM and identity attacks | 5 | residual (new class) | medium | not carried |
| CAPTCHA bypass | 6 | residual (aspect) | low-medium | round 1 carried a captcha enrichment |
| postMessage origin-check weakness | 6 | residual (aspect or carrier) | low | round 1 carried it as an `xss-dom` enrichment |
| Network-layer interception / transport downgrade | 1, 6 | residual (out of scope) | n/a | round 1 ruled it out of scope |
| HSTS / security-headers audit | 6 | residual (out of family) | n/a | round 1 ruled it out of scope |

### 2c. The sharp conflicts to reconcile

1. **Second-order SQL injection versus the operator's second-order example.** Round 1 ruled second-order SQL a non-match (the parent already carries it as an Advanced Technique; the same shape as the second-order-IDOR example). Round 2 slice-4 (high) proposes `sqli-second-order-injection` as a variant, arguing the parent is single-request and the two-operation sequence is a bent step. This is the only round-2 proposal that directly reverses a round-1 non-match.
2. **Local-DTD exfiltration.** Round 1 proposed it (A10) and the operator confirmed it as a `xxe` leaf. Round 2 slice-4 called it an aspect: the failing clause is still external resolution.
3. **DOM-clobbering.** The operator ruled a `proxy-techniques` leaf. Round 2 slice-5 proposes an `xss` leaf (`xss-dom-clobbering`).
4. **Renderer-script SSRF.** Round 1 kept it an aspect. Round 2 slice-5 proposes the variant `ssrf-renderer-script-ssrf` (branch 5a applies).
5. **Mail-record takeover.** Round 1 carried the chain-5 material as the A1 `subdomain-takeover` leaf. Round 2 slice-1 proposes a class with two variants.
6. **OAuth response-type-swap and consent-grant.** Round 1 folded both into aspects. Round 2 slice-1 re-proposes both as variants.
7. **GraphQL subscription.** The operator ruled a content extension of `graphql`. Round 2 slice-3 re-proposes the variant (low confidence).
8. **MCP and RAG.** The operator ruled merges (A8 to `tool-abuse`, A9 to `indirect-injection-plant`). Round 2 slice-3 re-proposes both as classes.
9. **LFI filter chain.** The operator ruled a merge. Round 2 slice-3 proposes the variant `lfi-filter-chain-code-execution`.
10. **Excessive-field-disclosure versus the accepted A2.** Round 2 slice-2 (`excessive-field-disclosure`) converges with the accepted A2 `information-disclosure` leaf; the difference is naming and the boundary caveat, not shape.
11. **Crypto key-reference injection and deserialization parser-order bypass.** Round 1 carried both as enrichments. Round 2 slice-3 proposes both as variants.

---

## 3. The residual registry

Every round-2 residual candidate and round-2-only proposal, deduplicated across slices.
Confidence flags are preserved from the slice reports.
The "convergence" column states whether the item converges with a round-1 assessed item or is genuinely new.
The recommended fate uses the operator's vocabulary: new level-1 class, level-2 variant, merge into an existing skill, reference, or reject.

### 3a. Residuals that converge with a round-1 item (keep the operator's ruling)

| Name | Source(s) | Confidence | Converges with | Recommended fate |
|---|---|---|---|---|
| `session-management` | `CBH/hunt-session`, `HS/web/session/session-fixation`, `HS/web/session/cookie-attacks` | medium | A4 (confirmed group) | New level-1 class, as ruled. Boundary: a session lifecycle trust assumption the suite does not own. |
| `http-parameter-pollution` | `ACS/W9/performing-http-parameter-pollution-attack` | high for the class, medium for placement | triage (confirmed group) | New level-1 class, as ruled, or a `defence-bypass-parser-confusion` merge. Boundary: a duplicate-parameter precedence class with its own matrix. |
| `cors-misconfiguration` | `ACS/W4/testing-cors-misconfiguration`, `HS/web/client-side/cors-misconfig`, `CBH/hunt-cors`, `AWS/.../cors-misconfiguration-exploitation` | medium-high | A19 (re-classed reference) | Keep the reference. Boundary: the permit-enumeration mechanism fits `allowance-gap`; the browser credentialed-read proof is the only disputed bent step. |
| `cache-poisoning` | `ACS/W6/performing-web-cache-poisoning-attack`, `AWS/.../web-cache-poisoning-deception`, `CBH/hunt-cache-poison` | medium | triage (confirmed group) | New level-1 class, as ruled. Boundary: mass delivery is the disputed bent step over `cache-deception`. |
| LDAP + XPath injection | `CBH/hunt-ldap`, `ACS/W3/testing-for-xml-injection-vulnerabilities` | high (slice-4) / medium (slice-5) | triage (two confirmed groups) | New level-1 classes, as ruled. Boundary: distinct grammars (RFC 4515 filters; XPath expressions). |
| `rate-limit-bypass` | `CBH/hunt-brute-force`, `ACS/W5/performing-api-rate-limiting-bypass`, `AWS/.../api-rate-limit-bypass-techniques` | medium | triage (confirmed group) | New level-1 class, as ruled; keep the `throttle-evasion` bypass enrichment. Boundary: the class owns the four-state limit classification. |
| `api-inventory-shadow` | `CBH/hunt-shadow-api`, `ACS/W8/detecting-shadow-api-endpoints`, `ACS/W8/performing-api-inventory-and-discovery` | high (slice-2) | A3 (re-classed reference) | Keep the reference. Boundary: the class shape is the topological clash the operator already rejected. |
| `client-side-path-traversal` | `HS/web/client-side/cspt` | medium | A14 (re-classed leaf) | Keep the `proxy-techniques-client-side-path-traversal` leaf. Boundary: the client request-path traversal is the leaf's own step. |
| `css-injection-exfiltration` | `CBH/hunt-dom`, `ACS/W4/performing-content-security-policy-bypass` | medium (slice-5 flags low on naming) | A16 (re-classed leaf) | Keep the `proxy-techniques-css-injection` leaf. Boundary: a no-execution data channel. |
| Email and SMTP header injection | `ACS/W3/testing-for-email-header-injection` | high | A11 (confirmed group) | Keep the group. Boundary: the operator treats the transport difference as a class; round 2 reads it as an aspect. Hold the ruling. |
| `graphql-subscription-hijack` | `CBH/hunt-graphql` | low | A7 (content extension) | Keep the content extension. Boundary: the push-channel authorization step is the only disputed bent step. |
| `rag-vector-store-weakness` | `CBH/hunt-rag-vector`, `AWS/.../rag-poisoning-and-data-exfiltration` | medium | A9 (merge) | Keep the merge into `indirect-injection-plant`; route the direct-read half to `idor` or `information-disclosure`. Boundary: storage and isolation clauses. |
| `mcp-tool-server` | `AWS/.../mcp-protocol-exploitation` | medium | A8 (merge) | Keep the merge into `tool-abuse`. Boundary: server-side permission enforcement. |
| `lfi-filter-chain-code-execution` | `CBH/hunt-lfi` (Phase 4) | medium-high | A6 (merge) | Keep the merge into `lfi-include-execution`. Boundary: the operator judges filter transformation exhaustive over synthesis. |
| Local-DTD error exfiltration | `CBH/hunt-xxe`, `HS/web/injection/xxe` | medium | A10 (confirmed leaf) | Keep the leaf. Boundary: round 2 reads the failing clause as unchanged external resolution. Hold the ruling. |
| `xss-dom-clobbering` | `CBH/hunt-dom`, `ACS/W4/performing-content-security-policy-bypass` | medium | A13 (re-classed leaf) | Keep the `proxy-techniques-dom-clobbering` leaf. Boundary: a zero-impact proxy primitive referenced from downstream families. |

### 3b. Genuinely-new round-2 residuals and round-2-only proposals

| Name | Source(s) | Confidence | New? | Recommended fate and boundary justification |
|---|---|---|---|---|
| SAML / SSO assertion forgery | `CBH/hunt-saml`, `CBH/hunt-auth-bypass` | high (slice-1) / medium (slice-5) | new (round 1 non-match) | New level-1 class. Boundary: assertion-signature scope is a distinct trust assumption from token and flow. Round 1 rejected it on the baseline-absent rule; rule the baseline question explicitly. |
| Broken-link / external-resource hijacking | `ACS/W6/exploiting-broken-link-hijacking`, `CBH/hunt-subdomain` chains 3 and 5 | high | new | New level-1 class. Boundary: the page trusts a third-party reference, not a record of its own name. |
| Legacy-protocol authentication-endpoint parity | `CBH/hunt-auth-bypass` (Legacy-Protocol Matrix) | high | new (round 1 non-match) | New level-1 class or an `authentication-jwt` variant. Boundary: one authentication surface is assumed to cover every surface issuing the same authority. |
| WebSocket security | `CBH/hunt-websocket`, `AWS/.../websocket-hijacking-testing`, `ACS/W5/exploiting-websocket-vulnerabilities` | medium-high | new | New level-1 class for the message layer; keep the handshake in `csrf-websocket-handshake` and the carrier in `proxy-techniques-channel-wrapping`. Boundary: per-message authorization and signed-message replay are not carrier steps. |
| Clickjacking / UI redressing | `CBH/hunt-clickjacking`, `ACS/W4/performing-clickjacking-attack-test`, `AWS/.../clickjacking-ui-redressing` | medium | new | New level-1 class. Boundary: a real but hidden interaction is its own bent step. Low impact alone explains its earlier omission. |
| MFA / 2FA bypass | `CBH/hunt-mfa-bypass`, `AWS/.../logic-flaws/2fa-bypass` | medium-high | new | New level-1 class. Boundary: the second factor is assumed enforced on every sensitive transition. |
| Account-recovery / password-reset flow flaws | `HS/web/auth/password-reset-flaws`, `CBH/hunt-forgot-password`, `CBH/hunt-ato` | medium | new | New level-1 class or a `weak-credential-discovery` variant. Boundary: token replay, missing expiry, and missing binding are a distinct recovery flow. |
| Loose-comparison coercion / type juggling | `ACS/W1/exploiting-type-juggling-vulnerabilities`, `HS/web/auth/auth-bypass` | medium / high | new (round 1 non-match) | Merge into `defence-bypass-encoding-differential` (slice-6 reading) or a new class. Boundary: the disputed step is a language-semantics comparison, not a decode step. |
| Client-controlled authorization state | `HS/web/auth/auth-bypass` | medium | new | Merge into `broken-function-level-authorization` (client-hint) or a new class. Boundary: the authority itself is client-controlled. |
| Forced browsing / unprotected-interface discovery | `ACS/W2/bypassing-authentication-with-forced-browsing`, `HS/web/auth/auth-bypass`, `AWS/.../deep-dive-labs/access-control` | medium-high | new | Merge into BFLA reconnaissance or a new class. Boundary: the interface is assumed unreachable, not actor-checked. |
| SPA backend-API route mapping | `CBH/hunt-spa-api` | medium | new | Merge into `information-disclosure`/BFLA recon. Boundary: the bundle-to-route-to-authz workflow is a recon procedure. |
| Authentication-challenge metadata disclosure (NTLM) | `CBH/hunt-ntlm-info` | medium | new | Defer or reject: the baseline-absent rule applies. Boundary: a fourth disclosure mechanism with no suite protocol baseline. |
| Forged external confirmation (unsigned webhook) | `CBH/hunt-business-logic` | medium-low | new | Merge into `async-boundary-abuse`. Boundary: an unauthenticated external confirmation is accepted as authoritative. |
| Account-takeover taxonomy as a chaining reference | `CBH/hunt-ato` | medium | new | Reference. Boundary: a cross-class chaining corpus, not a class. |
| Server-side parameter pollution in backend URL construction | `CBH/hunt-api-misconfig` | medium | new | Merge into `proxy-techniques-url-parser-differential` (round 1 already carries it as the strongest slice-6 enrichment). Boundary: a server-side URL builder is a second reader. |
| Framework-specific debug-surface families | `CBH/hunt-springboot`, `hunt-laravel`, `hunt-aspnet`, `hunt-nextjs` | low as a class | new | Merge (enrichment into `error-verbosity-disclosure`). Boundary: product instances abstract to families. |
| `llm-training-data-extraction` | `AWS/.../model-extraction/model-inversion-attacks`, `.../model-exploitation/data-extraction-training-data` | medium | new | New level-1 class (AI scope flag). Boundary: memorized-record regurgitation is not hidden prompt context. |
| `crypto-cipher-mode-weakness` | `HS/mobile/crypto/mobile-weak-crypto` | medium | new | Level-2 variant of `crypto-weakness` or a new class. Boundary: ciphertext confidentiality under a weak mode or IV. |
| `crypto-key-reference-injection` | `CBH/hunt-jwt-crypto`, `ACS` catalog `exploiting-jwt-algorithm-confusion-attack` | medium | new (round 1 enrichment) | Keep the round-1 enrichment (`authentication-jwt` header injection plus the abstract `crypto-weakness` clause). Boundary: the key basis is resolved from attacker-influenced input. |
| `deserialization-parser-order-bypass` | `CBH/hunt-aspnet` | low-medium | new (round 1 enrichment) | Keep the round-1 enrichment in `deserialization-signed-forgery` Bypass Techniques. Boundary: the divergence delta is a bypass form. |
| `lookup-injection` | `CBH/hunt-deserialization` (Phase 5) | low | new | Keep the round-1 enrichment (parent and `deserialization-gadget-chain`), or a class if a lookup-capable baseline is confirmed. Boundary: interpolation reaches a remote class loader. |
| `llm-model-poisoning` | `AWS/.../ai-data-poisoning`, `.../ml-security/data-poisoning-and-backdoors`, `.../supply-chain-analysis/llm-supply-chain-poisoning` | low | new | Reject or defer: the target is a training pipeline, not a reachable endpoint. Boundary: out of live-target scope. |
| `llm-overreliance-hallucination` | `AWS/.../llm-overreliance-hallucination` | low | new | Reject. Boundary: impact depends on user trust, not a testable weakness. |
| AI code-completion sabotage | `CBH/hunt-llm-ai` | low | new (round 1 LOW enrichment) | Keep the round-1 LOW enrichment. Boundary: thin evidence, possibly its own class. |
| `ai-data-extraction-via-ssrf` | `AWS/.../ai-data-extraction-via-ssrf` | low | new (round 1 enrichment) | Merge into `ssrf` (the LLM-tool carrier precondition). Boundary: the fetch sink is `ssrf`'s. |
| XML injection without external entities | `ACS/W3/testing-for-xml-injection-vulnerabilities` | low | new | Merge into `xxe` as a documented aspect. Boundary: tag injection with DOCTYPE stripped is neither XXE nor header injection. |
| Message-protocol / wire-format injection | `ACS/W3/exploiting-nosql-injection-vulnerabilities` | low | new | Reject. Boundary: likely a runtime fact, not a class. |
| Supply chain and CI/CD pipeline attacks | `CBH/supply-chain-attack-recon`, `CBH/hunt-cicd`, `HS/cicd/*` | medium | new | New level-1 class or defer (out of slice reach). Boundary: dependency confusion and workflow injection have no home. |
| Cloud IAM and identity attacks | `CBH/cloud-iam-deep`, `m365-entra-attack`, `okta-attack`, `AWS/cloud-security/*` | medium | new | New level-1 class or defer (out of slice reach). Boundary: cloud IAM enumeration and privilege escalation. |
| CAPTCHA bypass | `CBH/hunt-captcha-bypass` | low-medium | new | Merge into `defence-bypass-throttle-evasion` or `allowance-gap`. Boundary: the gate is client-side-only or not bound to the action. |
| postMessage origin-check weakness | `CBH/hunt-dom`, `CBH/hunt-cors` | low | new | Merge into `xss-dom` (round 1) or `proxy-techniques-channel-wrapping`. Boundary: a message channel with a missing or loose origin check. |
| `sqli-second-order-injection` | `ACS/W3/performing-second-order-sql-injection`, `AWS/.../advanced-sql-injection-sqli`, `CBH/hunt-sqli` | high | new (round 1 NON-MATCH) | Level-2 variant under `sql-injection`. Boundary: a two-operation sequence with a stored-data-trust clause; the baseline is the parent. This reverses the round-1 non-match; rule explicitly. |
| `bfla-client-hint-authorization-trust` | `AWS/.../deep-dive-labs/access-control` (Lab 13), `HS/web/authz/authz-bypass`, `ACS/W2/bypassing-authentication-with-forced-browsing` | medium | new | Level-2 variant under `broken-function-level-authorization`, or fold into `bfla-client-identity-trust` as an aspect. Boundary: a client-supplied hint decides the verdict, not the actor credential. |
| `predictable-token-brute-force` | `CBH/hunt-brute-force`, `CBH/hunt-forgot-password`, `HS/web/auth/password-reset-flaws` | medium | new | Level-2 variant under `weak-credential-discovery`, or fold into `exposed-secret-extraction`. Boundary: the failing clause is "issued artifacts are unguessable". |
| `oauth-response-type-swap` | `CBH/hunt-oauth` | low-medium | new (round 1 aspect) | Keep the round-1 aspect (fold into `oauth-redirect-uri-validation`). Boundary: the destination step covers the delivery channel. |
| `oauth-consent-grant-abuse` | `ACS` catalog `attacking-oauth-with-device-code-phishing` | low | new (round 1 aspect) | Keep the round-1 aspect/enrichment. Boundary: description-only evidence, not decision-grade. |
| `mail-record-takeover` | `CBH/hunt-subdomain` (item 13 and chain 5) | medium | new (the receipt half) | Keep the A1 leaf for the authorisation half; rule the receipt half as a second leaf or an aspect. Boundary: message interception and reset-link capture are a distinct completion criterion. |
| `ssrf-renderer-script-ssrf` | `CBH/hunt-ssrf`, `HS/web/injection/ssrf`, `ACS/W6/performing-blind-ssrf-exploitation` | medium | new (round 1 aspect) | Keep the round-1 aspect, or accept the variant on branch 5a. Boundary: the caller supplies code, not a destination; the disputed step is response reading from inside the fetcher. |

### 3c. Out of scope (recorded, not proposed)

| Name | Source(s) | Fate |
|---|---|---|
| IPv6 DNS takeover / network-layer interception and credential relay | `AWS/network/ipv6-dns-takeover-mitm`, `ACS/N3/conducting-man-in-the-middle-attack-simulation`, `ACS/W7/performing-ssl-stripping-attack` | Reject. Boundary: internal-network attack, not a web procedure. |
| HSTS / security-headers audit | `ACS/W4/performing-security-headers-audit`, `CBH/hunt-tls-network` | Reject. Boundary: not a bypass or proxy mechanism. |

---

## 4. The grey points

Each grey point is an aspect-versus-variant-or-class question a slice raised.
Each gives the competing readings and a recommendation.

1. **Silent shadow-throttle (slice-6 grey point 1; slice-4 enrichment).**
   The limit returns an admit signal while the known-good effect stops being produced.
   Reading A (aspect): the accounting clause already covers a limit whose answer no longer reflects the effect; the addition is an observable and a false-positive predicate.
   Reading B (variant): a success-signal-versus-effect divergence is a step the leaf cannot describe.
   Recommendation: aspect. Keep it as an `ObservableSignal` enrichment in `defence-bypass-throttle-evasion` and a `weak-credential-discovery` false-positive note.

2. **Cache poisoning (slice-6 grey point 2; round-1 A20 noted it).**
   Reading A (aspect): the `cache-deception` leaf's "read as a second caller" step covers both directions; poisoning and deception differ only in who reads the entry.
   Reading B (class): mass delivery is a bent step the cache-key variant does not describe.
   Recommendation: class, per the operator's blanket confirmation of the `cache-poisoning` group; keep the cache-key mechanics in `proxy-techniques-cache-deception`.

3. **The CORS permit (slice-6 grey point 3; slices 1, 2, 5).**
   Reading A (aspect): origin reflection, null origin, and prefix or suffix regex are routes the permit list omits; this fits `defence-bypass-allowance-gap`.
   Reading B (class or variant): the browser-side credentialed cross-origin read proof is a bent step the allowance-gap variant does not describe.
   Recommendation: keep the operator's defence-bypass reference; the browser-proof step is the only disputed element.

4. **GraphQL subscription (slice-3; the operator ruled a content extension).**
   Reading A (content extension): the class does not decompose; the interaction protocol is rare; extend the body without strong emphasis.
   Reading B (variant): per-channel and per-message authorization over a long-lived connection is a bent step no request-time resolver step names.
   Recommendation: content extension, per the operator's A7 ruling.

5. **Comparison coercion (slice-6 grey point 4; slices 1, 4).**
   Reading A (aspect): folding is the `defence-bypass-encoding-differential` folding clause; the type-juggling reader pair is a second reader of one value.
   Reading B (distinct step or class): a language-semantics comparison step is not a decode step.
   Recommendation: aspect, with the class option flagged for the operator.

6. **CSRF-token presence-only validation (slice-6 grey point 5).**
   Reading A (signature-evasion): "token validated only if present" is a matcher gap.
   Reading B (allowance-gap): "token not session-bound" is a permit-enumeration gap.
   Recommendation: split as slice-6 reads it: the presence case to `signature-evasion`, the session-binding case to `allowance-gap`. Low confidence.

7. **Routing-based SSRF (slice-5).**
   Reading A (aspect): the parent's authority-family step is accurate; only the sink differs, so it stays a `header-host-forward-spoof` value.
   Reading B (ssrf variant): returning the fetched interior body is a bent step.
   Recommendation: aspect, as round 1 ruled; the interior-body read escalates to `ssrf`, not to a `header-injection` variant.

8. **Binary-translation desync (slice-5; the operator confirmed A17 as a leaf).**
   Reading A (aspect): a translation-hop framing disagreement, already the parent step.
   Reading B (third variant): the binary attribute encoding is a distinct craft.
   Recommendation: hold the operator's A17 leaf; record the counter-reading.

9. **Config-as-code injection (slice-5; round-1 A15 merge).**
   Reading A (aspect of `rce-command-injection`): a value of the internal-service-sink step.
   Reading B (merge into `rce-pipeline-execution`): the operator's home.
   Recommendation: enrichment; reconcile the home to `rce-pipeline-execution` as ruled.

10. **DOM-clobbering home (slice-5; the operator ruled a proxy-techniques leaf).**
    Reading A (proxy-techniques leaf): almost entirely a zero-impact flaw unless paired with a downstream gadget.
    Reading B (xss variant): markup-only injection that shadows a trusted global.
    Recommendation: hold the operator's leaf.

11. **Renderer-script SSRF (slice-5; round 1 kept it an aspect).**
    Reading A (aspect): blind renderer cases fold into `no-response-egress-inference`.
    Reading B (variant): response reading plus arbitrary egress from inside the fetcher.
    Recommendation: hold the aspect; branch 5a applies.

12. **CSS-injection naming (slice-5).**
    The mechanism is real; the naming and the home are disputed.
    Recommendation: keep the operator's `proxy-techniques-css-injection` leaf; the naming flag is low confidence.

13. **HTTP parameter pollution placement (slice-5; slices 2, 6).**
    Reading A (class): the operator's blanket-confirmed group.
    Reading B (defence-bypass-parser-confusion merge): slice-6's reading.
    Recommendation: keep the group; carry the merge as the fallback.

---

## 5. The progressive extension

### 5a. Count table

| Metric | Round 1 | Round 2 | Note |
|---|---|---|---|
| New-skill proposals (raw) | 21 | 18 | round 1 collapsed to 19 after cross-slice dedup; round 2 has no cross-slice proposal duplicate |
| New-skill proposals (distinct) | 19 | 18 | |
| Enrichment candidates | 214 | 188 | both are raw across slices |
| References/scripts candidates | 48 (45 firm, 3 flagged) | 29 | round 2 flags several medium-confidence |
| Out-of-slice triage candidates | 7 | folded into residuals | |
| Residual candidates | 0 (round 1 called them triage) | 65 raw / about 57 deduped | |
| Round-1 assessed items re-found | n/a | 24 of 25 | only the rejected A5 not re-found |
| Re-found identically | n/a | 5 | A2, A4, LDAP, XPath, cache-poisoning |
| Re-found with a different shape | n/a | 19 | |
| Not re-found | n/a | 1 | A5 `crypto-oracle-decryption` |
| Round-2-only residuals and proposals | n/a | about 39 | mostly suite-edge surfaces |
| Sharp conflicts to reconcile | n/a | 11 | section 2c |

### 5b. Projected taxonomy growth if the recommendations are accepted

Committed round-1 delta (from `rulings.md`):

- New level-1 groups: 7 (A4 `session-management`, A11 `email-header-injection`, and the five triage groups).
- New level-2 leaves: 9 (A1 `email-dns-takeover`, A2 `information-disclosure` leaf, A10 `xxe` leaf, A12 `race-conditions` leaf, A13, A14, A16 `proxy-techniques` leaves, A17 `http-request-smuggling` leaf, A18 `defence-bypass` leaf).
- References: 3 (A3, A19, CSP).
- Merges (enrichments, no new skill): 4 (A6, A8, A9, A15).
- Content extension: 1 (A7).
- Rejected: 1 (A5).
- Committed total: 16 new skills.

Round-2 recommended delta (if my fates are accepted):

- New level-1 classes: 9 (SAML/SSO, broken-link hijacking, legacy-protocol parity, WebSocket, clickjacking, MFA, account-recovery, supply chain/CI-CD, cloud IAM) plus `llm-training-data-extraction` if the AI scope is extended, for a maximum of 10.
- New level-2 variants: 3 to 5 (`sqli-second-order-injection`, `predictable-token-brute-force`, `bfla-client-hint-authorization-trust`, optionally `crypto-cipher-mode-weakness` and `ssrf-renderer-script-ssrf`).
- Merges and enrichments: the remaining residuals (about 20), including the converged round-1 items.
- References: 1 to 3 (the ATO taxonomy; the server-side parameter pollution note).
- Rejected or deferred: about 8 (`llm-model-poisoning`, `llm-overreliance-hallucination`, NTLM disclosure, message-protocol injection, network-layer set, HSTS, and the re-shapes of confirmed round-1 items).

Recommended total: about 12 to 15 new skills on top of the committed 16, giving a suite growth of about 28 to 31 new skills over the two rounds.
A conservative reading (convergence only, accept no round-2-only proposal) yields the committed 16 plus zero, because the round-2-only items are all at the suite edges.

### 5c. Overlapping effort visible at a glance

- The coverage effort is almost fully duplicated: the blind second swarm re-mined the same 44 groups and re-found 24 of 25 assessed items.
- The taxonomy effort is not duplicated but conflicted: 19 items carry two competing shapes.
- The enrichment effort overlaps heavily: 188 round-2 enrichments against 214 round-1, drawn from the same source corpus; the union is the execution plan, and the intersection is the reliable core.
- The round-2-only effort is small and edge-weighted: the AI surfaces, the auth-adjacent flows, the supply-chain and cloud surfaces, and a few variants.

The evolution is therefore a stable extension in coverage and an open question in shape.
Section 3 and section 4 are what need operator rulings.

---

*Report only. No suite skill was modified. No git state was changed. The orchestrator commits.*
