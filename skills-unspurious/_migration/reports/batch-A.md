# De-spuriation report - batch A

## authentication-jwt
- **Classification:** KEEP
- **Internal agentic tools:** none found, and the previously removed `## Tooling` (jwt_tool) section is verified still absent.
- **Arsenal:** the skill invokes no tool commands at all, so nothing was removed or adapted.
- **Special contexts:** the `## Special Contexts` heading was deleted, `### Mobile` was moved verbatim into `## Attack Surface`, and `### SSO Federation` was moved verbatim into `## Advanced Techniques`.
- **High-value targets:** none (the skill has no such section).
- **Other removals:** none.
- **Arsenal gaps:** none (all described techniques are manual token-mutation checks needing only curl or python3).

## broken-function-level-authorization
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** the only tooling mention is the generic phrase "via GraphQL or gRPC tools", which names no absent tool, so nothing was removed or adapted.
- **Special contexts:** none present (the skill has no such section).
- **High-value targets:** extracted to _migration/high-value-targets/broken-function-level-authorization.md (the `## High-Value Actions` section verbatim, with the required H1 prepended).
- **Other removals:** none.
- **Arsenal gaps:** none.

## business-logic
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** the skill invokes no tool commands at all, so nothing was removed or adapted.
- **Special contexts:** the `## Special Contexts` heading was deleted, and `### E-commerce`, `### Banking/Fintech`, and `### SaaS/B2B` were moved verbatim into `## Advanced Techniques`.
- **High-value targets:** extracted to _migration/high-value-targets/business-logic.md (the `## High-Value Targets` section verbatim, with the required H1 prepended).
- **Other removals:** none.
- **Arsenal gaps:** none.

## crypto-weakness
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** the skill named flask-unsign and hashcat, both absent from the arsenal, so the `## JWT Secret Brute-Force` bash block was removed (`pip install flask-unsign flask-unsign[wordlist]`, `flask-unsign --unsign --cookie "<cookie>" --no-literal-eval`, `flask-unsign --unsign --cookie "<cookie>" --wordlist /path/to/wordlist.txt`, `# hashcat -a 0 -m 16500 "<header>.<payload>.<signature>" wordlist.txt`) and replaced with a manual python3 HMAC-SHA256 secret-guessing snippet using only present tooling.
- **Special contexts:** none present (the skill has no such section).
- **High-value targets:** none (the skill has no such section).
- **Other removals:** none (the hashes.com lookup stays because it is plain python3 requests code, and the `http://target/...` placeholders stay as generic illustrative targets).
- **Arsenal gaps:** no dedicated JWT or Flask-session secret cracker is present (flask-unsign, hashcat, and jwt_tool are all absent), though the HS256 guessing technique survives via the manual python3 formulation.

## csrf
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** the skill invokes no tool commands at all, so nothing was removed or adapted.
- **Special contexts:** the `## Special Contexts` heading was deleted, and `### Mobile/SPA` and `### Integrations` were moved verbatim into `## Attack Surface`.
- **High-value targets:** extracted to _migration/high-value-targets/csrf.md (the `## High-Value Targets` section verbatim, with the required H1 prepended).
- **Other removals:** none.
- **Arsenal gaps:** none.

## graphql
- **Classification:** KEEP
- **Internal agentic tools:** no verbatim tool names were found, but two source-system glue references were adapted generically.
- **Arsenal:** the skill invokes no absent-tool commands (graphql-cop is never invoked), so nothing was removed or adapted.
- **Special contexts:** none present (the skill has no such section).
- **High-value targets:** none (the skill has no such section).
- **Other removals:** two environment and workflow glue phrases were adapted, namely `Use project secrets (`TESTUSER_EMAIL` / `TESTUSER_PW`) for login.` becoming `Authenticate with available test credentials for login.`, and `(or use already-recorded `POST /path Query.field` attack-surface items)` becoming `(or use previously enumerated Query/Mutation fields)`.
- **Arsenal gaps:** none.
