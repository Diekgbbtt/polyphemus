# D1a assessment rulings and the classification map

*Status: the operator's assessment of the D1a proposal (`proposal.md`, committed `0aa597c5`), recorded 2026-10-19 by the orchestrator.*
*This file is the authoritative record of each item's fate and its taxonomy home; D1b and D1c execute from it.*

## 1. The rulings

- Blanket: every item not explicitly modified below is confirmed and enters the taxonomy as a new child or family skill.
- Rejected: A5 `crypto-oracle-decryption`.
- Merged, keeping the AI-feature surfaces minimal (the larger AI-surface refactor is deferred):
  - A8 `mcp-tool-server-abuse` -> `tool-abuse`: integrate the Model Context Protocol specific technical failure modes, namely the trust assumptions across state transitions and every instance of the interface-agreement assumptions across the full lifecycle of an MCP connection, as the source skill explains.
  - A9 `rag-vector-store-abuse` -> `indirect-injection-plant`.
- Merged otherwise:
  - A6 `lfi-filter-chain-execution` -> `lfi-include-execution`.
  - A15 `rce-config-delegate-execution` -> `rce-pipeline-execution`: the attack surface extends with this specific sink (execution primitives in configuration files) and the assumed trust context (administrator privileges).
- Re-classed:
  - A13 `dom-clobbering` -> a proxy technique: it is almost entirely a zero-impact flaw unless paired with a downstream gadget, and the downstream chains are already covered (xss, csrf, prototype pollution, open redirect, client-side path traversal, business-logic DoS); it must be referenced from the parent skills of those families in a proper advanced, proxy, or bypass techniques section.
  - A16 `css-injection-exfiltration` -> re-defined as `css-injection`, a proxy technique with the dom-clobbering profile; also leveraged by information-disclosure testing techniques.
  - A14 `client-side-path-traversal` -> `proxy-techniques-client-side-path-traversal`: no severe impact alone, and a downstream defence layer usually blocks the blast.
  - A7 `graphql-subscription-hijack` -> not a child: extend the `graphql` content with all the new primitives (new attack surface, reconnaissance actions, new key vulnerability, new testing-methodology steps), without strong emphasis, because the interaction protocol is rare.
  - A2 `excessive-data-exposure` -> a new leaf of `information-disclosure`; the parent becomes method-parametrisable, and the class also regards API surfaces.
  - A3 `api-version-consistency` -> a proxy technique (the same topological clash as the defence-bypass one, in the proxy family): a reference under the abstract proxy procedures.
  - A19 `cors-misconfiguration` -> canonically a defence-bypass procedure; the family's leaves are deliberately abstract (allowance-gap, parser-confusion, and more), so a specific CORS leaf would clash topologically: the specific bypass enters as a reference in the abstract procedures that can concretely amplify the bypass of such defences.
  - The symmetric content-security-policy lack is filled the same way: a CSP bypass reference created from the relevant source artifacts, classified like the CORS one.
  - A17 `http-request-smuggling-cross-protocol-desync` -> a new leaf under `http-request-smuggling`.
- Confirmed with caveats:
  - A4 `session-management` -> a new class, strongly coupled with the authentication-system, authorization, and two-principal-authz domains (and with lower likelihood race conditions: post-logout validity checks and synchronisations).
    The content must frequently direct the reader to follow those skills' vulnerability-testing procedures first, or to leverage the already-mapped vulnerabilities in those domains.
    Kill chains that appear session-layer-only (session fixation; session forging when the attacker knows the secret material and the signing key is public with no further fingerprints) still rest on vulnerable properties of those systems as requirements.
- Deferred to a distinct work item: the suite-wide layout and font-style normalisation (section 3).
- Blanket-confirmed triage items (not explicitly addressed; the proposal's reservations are carried as notes): `rate-limit-bypass`, `http-parameter-pollution`, LDAP injection, XPath injection, `cache-poisoning`.

## 2. The classification map

| D1a item | Ruling | Taxonomy home | Next action |
|---|---|---|---|
| A1 `subdomain-takeover/email-dns-takeover` | confirmed | level-2 leaf `email-dns-takeover` under `subdomain-takeover` | author (D1b) |
| A2 `excessive-data-exposure` | confirmed, reshaped | level-2 leaf under `information-disclosure`; the parent becomes method-parametrisable and covers API surfaces | author plus parent edit |
| A3 `api-version-consistency` | re-classed | proxy-technique reference under the abstract procedures (`proxy-techniques` channel-wrapping; the tier-route inventory) | reference (D1c) |
| A4 `session-management` | confirmed, caveated | new level-1 group `session-management` (parent now, variants later) | author |
| A5 `crypto-oracle-decryption` | rejected | none | none |
| A6 `lfi-filter-chain-execution` | merged | enrichment of `lfi-include-execution` | enrich (D1b) |
| A7 `graphql-subscription-hijack` | reshaped | content extension of `graphql` (attack surface, reconnaissance, key vulnerabilities, methodology steps; light emphasis) | enrich |
| A8 `mcp-tool-server-abuse` | merged | enrichment of `tool-abuse` (MCP lifecycle trust and interface-agreement failure modes) | enrich |
| A9 `rag-vector-store-abuse` | merged | enrichment of `indirect-injection-plant` | enrich |
| A10 `xxe-local-dtd-error-exfiltration` | confirmed | level-2 leaf under `xxe` | author |
| A11 `email-header-injection` | confirmed | new level-1 group `email-header-injection` | author |
| A12 `race-conditions-partial-construction` | confirmed | level-2 leaf under `race-conditions` | author |
| A13 `dom-clobbering` | re-classed | level-2 leaf `proxy-techniques-dom-clobbering`; referenced from the `xss`, `csrf`, `prototype-pollution`, `open-redirect`, `client-side-path-traversal`, `business-logic` parents in their advanced, proxy, or bypass sections | author plus wire |
| A14 `client-side-path-traversal` | re-classed | level-2 leaf `proxy-techniques-client-side-path-traversal` | author |
| A15 `rce-config-delegate-execution` | merged | enrichment of `rce-pipeline-execution` (attack surface plus the configuration-file sink; the administrator trust context) | enrich |
| A16 `css-injection` | re-classed | level-2 leaf `proxy-techniques-css-injection`; also referenced by `information-disclosure` | author plus wire |
| A17 `http-request-smuggling-cross-protocol-desync` | re-classed | level-2 leaf under `http-request-smuggling` | author |
| A18 `defence-bypass-attempt-batching` | confirmed | level-2 leaf under `defence-bypass` | author |
| A19 `cors-misconfiguration` | re-classed | defence-bypass reference under the abstract procedures (the permit-enumeration and allowance-gap step) | reference (D1c) |
| CSP bypass (the symmetric lack) | filled like A19 | defence-bypass reference created from the source artifacts | reference (D1c) |
| triage `rate-limit-bypass` | blanket-confirmed | new level-1 group `rate-limit-bypass` (notes: the identifier-rotation taxonomy stays a `defence-bypass-throttle-evasion` enrichment; the concurrent-counter part stays a `race-conditions` aspect; the batch-collapse mechanism is A18) | author |
| triage `http-parameter-pollution` | blanket-confirmed | new level-1 group `http-parameter-pollution` (note: the duplicate-header-pollution part remains a `header-injection` bypass aspect; the precedence taxonomy becomes a reference) | author plus reference |
| triage LDAP injection | blanket-confirmed | new level-1 group `ldap-injection` | author |
| triage XPath injection | blanket-confirmed | new level-1 group `xpath-injection` | author |
| triage `cache-poisoning` | blanket-confirmed | new level-1 group `cache-poisoning` (note: `proxy-techniques-cache-deception` keeps the cache-key mechanics) | author |

## 3. The deferred work item: layout normalisation

The defect: the trunk's suite lost the reference layout and font scheme through the improvement layers; bulleted elements with the signature in bold before the colon (`- **Signature**: text`) degraded to plain paragraphs, plain bullets, or numbered lists.
The reference: the `feat-skills-suite` worktree's suite, for example `skills-unspurious/csrf/csrf-form-post/SKILL.md`, where 111 of the 131 `SKILL.md` files carry the pattern; the trunk carries it in 2 of 145 (the `authentication-jwt` and `header-injection` parents only).
Filed as ticket #388; the work item is distinct from W7 (the impact is suite-wide), and it must change layout and font style only, never content.

## 4. Next: the second mining round

A fresh, independent subagent swarm re-mines from scratch (the same algorithm and slice structure, with no access to the first round's reports).
Its synthesis produces a cumulative registry: the converged items (found by both rounds), the round-2-only residuals, and the round-1-only items, so the extension of the suite is tracked progressively and overlapping efforts in the evolution are visible.
