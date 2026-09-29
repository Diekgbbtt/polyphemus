# Decomposition fleet ledger (W0 orchestrator)

*Passive outer/inner-loop state. Outer loop = the class pool. Inner loop = create -> review -> done (with rework on FAIL). Working set target: at least 3 classes active.*

*Spec: `SPEC.md`. Creator artifact: `<class>.md`. Reviewer artifact: `<class>.review.md`.*

## Pool (29 classes; `two-principal-authz` excluded as a cross-cutting methodology)

| # | class | creator | reviewer | status |
|---|---|---|---|---|
| 01 | authentication-jwt | - | - | queued |
| 02 | broken-function-level-authorization | - | - | queued |
| 03 | business-logic | - | - | queued |
| 04 | crypto-weakness | - | - | queued |
| 05 | csrf | - | - | queued |
| 06 | graphql | - | - | queued |
| 07 | header-injection | - | - | queued |
| 08 | http-method-tampering | - | - | queued |
| 09 | http-request-smuggling | - | - | queued |
| 10 | idor | - | - | queued |
| 11 | information-disclosure | - | - | queued |
| 12 | insecure-deserialization | - | - | queued |
| 13 | insecure-file-uploads | - | - | queued |
| 14 | llm-prompt-injection | - | - | queued |
| 15 | mass-assignment | - | - | queued |
| 16 | nosql-injection | - | - | queued |
| 17 | oauth | - | - | queued |
| 18 | open-redirect | - | - | queued |
| 19 | path-traversal-lfi-rfi | - | - | queued |
| 20 | prototype-pollution | - | - | queued |
| 21 | race-conditions | - | - | queued |
| 22 | rce | - | - | queued |
| 23 | sql-injection | - | - | queued |
| 24 | ssrf | - | - | queued |
| 25 | ssti | - | - | queued |
| 26 | subdomain-takeover | - | - | queued |
| 27 | weak-credential-discovery | - | - | queued |
| 28 | xss | - | - | queued |
| 29 | xxe | - | - | queued |

## Loop log

- (start) spec written; fleet not yet dispatched.
