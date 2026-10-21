# Authoring fleet ledger (W0 phase 4)

*Outer loop = the 29-class unit pool. Inner loop = skill-writer authors a class's variants -> skills-reviewer reviews them -> (rework -> re-review) -> done. Working set target: at least 3 units active; writer and reviewer waves overlapped so the review queue never stalled the writers.*

*Contract: `SPEC.md`. Writer persona: `WRITER.md`. Reviewer persona: `REVIEWER.md`. Layout: `docs/design/skills-ontology.md`. Boundary: `docs/design/skills-variant-boundary.md`. Reviewer artifact: `reviews/<class>.md`. One commit per wave.*

*Result: 101 variant skills authored across 28 classes, every one PASS on its first review. Zero reworks. Parents unmodified; no em dashes; every frontmatter `name` equals its directory.*

*The authoring contract is the operator-validated ontology (`docs/design/skills-ontology.md`, validated in session `ses_f181eb14bffei9Y8v5O30nGDjG`, 2026-09-28); the boundary (`docs/design/skills-variant-boundary.md`) carries the same validation.*

| # | unit (class) | variants | writer | reviewer | status |
|---|---|---|---|---|---|
| 01 | authentication-jwt | 4 | done | PASS | done |
| 02 | broken-function-level-authorization | 3 | done | PASS | done |
| 03 | business-logic | 4 | done | PASS | done |
| 04 | crypto-weakness | 3 | done | PASS | done |
| 05 | csrf | 5 | done | PASS | done |
| 06 | graphql | 0 | - | - | n/a (does not decompose) |
| 07 | header-injection | 6 | done | PASS | done |
| 08 | http-method-tampering | 4 | done | PASS | done |
| 09 | http-request-smuggling | 1 | done | PASS | done |
| 10 | idor | 5 | done | PASS | done |
| 11 | information-disclosure | 3 | done | PASS | done |
| 12 | insecure-deserialization | 3 | done | PASS | done |
| 13 | insecure-file-uploads | 5 | done | PASS | done |
| 14 | llm-prompt-injection | 5 | done | PASS | done |
| 15 | mass-assignment | 3 | done | PASS | done |
| 16 | nosql-injection | 5 | done | PASS | done |
| 17 | oauth | 5 | done | PASS | done |
| 18 | open-redirect | 3 | done | PASS | done |
| 19 | path-traversal-lfi-rfi | 4 | done | PASS | done |
| 20 | prototype-pollution | 2 | done | PASS | done |
| 21 | race-conditions | 4 | done | PASS | done |
| 22 | rce | 2 | done | PASS | done |
| 23 | sql-injection | 5 | done | PASS | done |
| 24 | ssrf | 3 | done | PASS | done |
| 25 | ssti | 2 | done | PASS | done |
| 26 | subdomain-takeover | 3 | done | PASS | done |
| 27 | weak-credential-discovery | 4 | done | PASS | done |
| 28 | xss | 2 | done | PASS | done |
| 29 | xxe | 3 | done | PASS | done |

## Loop log

- Wave 1: ssrf (3), prototype-pollution (2), information-disclosure (3). 8 variants, all PASS first pass. Machine validated; quality spot-checked against the ontology contract.
- Wave 2: idor (5), csrf (5), sql-injection (5), oauth (5), xxe (3). 23 variants, all PASS first pass.
- Wave 3: authentication-jwt (4), broken-function-level-authorization (3), business-logic (4), crypto-weakness (3), header-injection (6). 20 variants, all PASS first pass.
- Wave 4: http-method-tampering (4), http-request-smuggling (1), insecure-deserialization (3), insecure-file-uploads (5), llm-prompt-injection (5). 18 variants, all PASS first pass.
- Wave 5: mass-assignment (3), nosql-injection (5), open-redirect (3), path-traversal-lfi-rfi (4), race-conditions (4). 19 variants, all PASS first pass.
- Wave 6: rce (2), ssti (2), subdomain-takeover (3), weak-credential-discovery (4), xss (2). 13 variants, all PASS first pass.
- Whole-suite sweep: 101 child `SKILL.md`, 0 em dashes, 101 of 101 `name` == directory, 28 class reviews.
