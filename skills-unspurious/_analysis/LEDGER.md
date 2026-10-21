# Decomposition fleet ledger (W0 orchestrator)

*Final state. Outer loop = the 29-class pool. Inner loop = create -> review -> (rework -> re-review) -> done. Working set target: at least 3 classes active; creator and reviewer waves overlapped so the review queue never stalled the creators.*

*Spec: `SPEC.md`. Creator artifact: `<class>.md`. Reviewer artifact: `<class>.review.md` (all PASS). Boundary: `docs/design/skills-variant-boundary.md`.*

*The operator validated the boundary and all 29 analyses in session `ses_f181eb14bffei9Y8v5O30nGDjG` (2026-09-28); the boundary status line now records that validation.*

## Pool result (29 classes; `two-principal-authz` excluded as a cross-cutting methodology)

| # | class | creator | reviewer | status | recommended variants |
|---|---|---|---|---|---|
| 01 | authentication-jwt | yes | PASS | done | 4: jwt-signature-forgery, jwt-key-resolution, jwt-claims-confusion, jwt-flow-lifecycle |
| 02 | broken-function-level-authorization | yes | PASS | done | 3: bfla-alternate-path, bfla-client-identity-trust, bfla-deferred-execution |
| 03 | business-logic | yes | PASS | done | 4: concurrent-duplication, value-domain-manipulation, quota-window-slicing, async-boundary-abuse |
| 04 | crypto-weakness | yes | PASS | done | 3: crypto-predictable-token, crypto-signing-key-forgery, crypto-timing-oracle |
| 05 | csrf | yes | PASS | done | 5: form-post, navigation-get, parser-differential, login-fixation, websocket-handshake |
| 06 | graphql | yes | PASS | done | does not decompose (protocol/surface aggregator) |
| 07 | header-injection | yes (rework) | PASS | done | 6: crlf-splitting, host-forward-spoof, cache-poisoning, method-override, request-smuggling, response-value-confusion |
| 08 | http-method-tampering | yes (rework) | PASS | done | 4: verb-switch, override-smuggling, informational-verb, preflight-coercion |
| 09 | http-request-smuggling | yes | PASS | done | 2: base + h2-desync |
| 10 | idor | yes | PASS | done | 5: direct-object-swap, collection-batch-scope, deferred-artifact-redemption, context-carrier-substitution, nested-expansion-binding |
| 11 | information-disclosure | yes (rework) | PASS | done | 3: error-verbosity, stored-artifact, differential-oracle |
| 12 | insecure-deserialization | yes | PASS | done | 3: gadget-chain, signed-forgery, deferred-trigger |
| 13 | insecure-file-uploads | yes | PASS | done | 5: server-execution, client-execution, archive-extraction, toolchain-execution, pipeline-deferred-trust |
| 14 | llm-prompt-injection | yes | PASS | done | 5: direct-injection-override, indirect-injection-plant, context-leakage, tool-abuse, output-handling |
| 15 | mass-assignment | yes (rework) | PASS | done | 3: nested-relation-write, bulk-collection-injection, bulk-nested-relation-write |
| 16 | nosql-injection | yes | PASS | done | 5: operator-injection, server-side-script-injection, aggregation-pipeline-injection, query-language-injection, command-protocol-smuggling |
| 17 | oauth | yes | PASS | done | 5: redirect-uri-validation, state-nonce-csrf, pkce-enforcement, code-client-binding, device-approval |
| 18 | open-redirect | yes | PASS | done | 3: generic-redirect-parser-bypass, oauth-redirect-uri-relay, redirector-to-fetcher-pivot |
| 19 | path-traversal-lfi-rfi | yes | PASS | done | 4: traversal-read, lfi-include-execution, rfi-remote-include, archive-zipslip-write |
| 20 | prototype-pollution | yes (rework) | PASS | done | 2: client-side, server-side |
| 21 | race-conditions | yes | PASS | done | parent core + 4: idempotency-dedup-bypass, optimistic-guard-evasion, cross-service-consistency-race, single-request-fanout |
| 22 | rce | yes | PASS | done | 2: command-injection, pipeline-execution |
| 23 | sql-injection | yes | PASS | done | 5: union-extraction, error-based-extraction, boolean-blind-extraction, time-blind-extraction, oast-exfiltration |
| 24 | ssrf | yes | PASS | done | 3: no-response-egress-inference, scheme-translated-command-execution, header-gated-cloud-credential-read |
| 25 | ssti | yes | PASS | done | 2: reflected-evaluation, blind-evaluation |
| 26 | subdomain-takeover | yes | PASS | done | 3: dangling-record-resource-claim, cdn-alternate-domain-binding, ns-delegation-takeover |
| 27 | weak-credential-discovery | yes | PASS | done | 4: exposed-secret-extraction, default-credential-replay, username-enumeration-oracle, session-token-authority-decode |
| 28 | xss | yes (rework) | PASS | done | parent baseline + 2: stored, dom (reflected folded to baseline) |
| 29 | xxe | yes | PASS | done | baseline + 3: blind-parameter-entity-oob-exfiltration, transclusion-without-entity-resolution, entity-expansion-denial-of-service |

## Loop log

- Wave 1 creators (01-03); wave 1 reviews all PASS.
- Wave 2 creators (04-06); wave 2 reviews all PASS.
- Wave 3 creators (07-09); header-injection and http-method-tampering FAILed, reworked, re-reviewed PASS; smuggling PASS.
- Wave 4 creators (10-12); idor PASS, insecure-deserialization PASS, information-disclosure FAILed, reworked, re-reviewed PASS.
- Wave 5 creators (13-15); file-uploads PASS, llm-prompt-injection PASS, mass-assignment FAILed, reworked, re-reviewed PASS.
- Wave 6 creators (16-19); all PASS.
- Wave 7 creators (20-22); prototype-pollution FAILed, reworked, re-reviewed PASS; race-conditions PASS, rce PASS.
- Wave 8 creators (23-26); all PASS.
- Wave 9 creators (27-29); weak-credential-discovery PASS, xss FAILed, reworked, re-reviewed PASS, xxe PASS.
- All 29 classes complete with an independent PASS review. Boundary document authored.
