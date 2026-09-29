# Authoring fleet ledger (W0 phase 4)

*Outer loop = the 29-class unit pool. Inner loop = skill-writer authors a class's variants -> skills-reviewer reviews them -> (rework -> re-review) -> done. Working set target: at least 3 units active; writer and reviewer waves overlapped so the review queue never stalls the writers.*

*Contract: `SPEC.md`. Layout: `docs/design/skills-ontology.md`. Boundary: `docs/design/skills-variant-boundary.md`. Reviewer artifact: `reviews/<class>.md`. One commit per class.*

| # | unit (class) | variants | writer | reviewer | status |
|---|---|---|---|---|---|
| 01 | authentication-jwt | 4 | - | - | pending |
| 02 | broken-function-level-authorization | 3 | - | - | pending |
| 03 | business-logic | 4 | - | - | pending |
| 04 | crypto-weakness | 3 | - | - | pending |
| 05 | csrf | 5 | - | - | pending |
| 06 | graphql | 0 | - | - | n/a (does not decompose) |
| 07 | header-injection | 6 | - | - | pending |
| 08 | http-method-tampering | 4 | - | - | pending |
| 09 | http-request-smuggling | 1 | - | - | pending |
| 10 | idor | 5 | - | - | pending |
| 11 | information-disclosure | 3 | done | PASS | done |
| 12 | insecure-deserialization | 3 | - | - | pending |
| 13 | insecure-file-uploads | 5 | - | - | pending |
| 14 | llm-prompt-injection | 5 | - | - | pending |
| 15 | mass-assignment | 3 | - | - | pending |
| 16 | nosql-injection | 5 | - | - | pending |
| 17 | oauth | 5 | - | - | pending |
| 18 | open-redirect | 3 | - | - | pending |
| 19 | path-traversal-lfi-rfi | 4 | - | - | pending |
| 20 | prototype-pollution | 2 | done | PASS | done |
| 21 | race-conditions | 4 | - | - | pending |
| 22 | rce | 2 | - | - | pending |
| 23 | sql-injection | 5 | - | - | pending |
| 24 | ssrf | 3 | done | PASS | done |
| 25 | ssti | 2 | - | - | pending |
| 26 | subdomain-takeover | 3 | - | - | pending |
| 27 | weak-credential-discovery | 4 | - | - | pending |
| 28 | xss | 2 | - | - | pending |
| 29 | xxe | 3 | - | - | pending |

## Loop log

- Wave 1: ssrf (3), prototype-pollution (2), information-disclosure (3). All 8 variants authored and PASS-reviewed on first pass. Machine validated; quality spot-checked against the ontology contract.
