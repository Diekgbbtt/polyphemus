# skills-unspurious inventory and classification

*Phase 1 deliverable (W0). Source copied verbatim from `/Users/diekgbbtt/purple-swan/skills` (counts verified: 50 skill directories with `SKILL.md`, 7 group directories of flat `.md` duplicates).*
*Classification against the operator's discard rule: "all the skills not covering web vulnerability testing procedures, or relevant network-based bypass/proxy techniques must be discarded".*
*Each skill was read in full before classifying; the rationale cites its own body, not its name.*
*Borderline cases are put to the operator, never guessed (see the `BORDERLINE` table).*

## Verification of the source counts and prior-art claims

- 50 skill directories, each with `SKILL.md`. No skill in the source carries a `references/` or `scripts/` directory; every skill is a single file.
- 7 group directories: `cloud`, `frameworks`, `protocols`, `reconnaissance`, `technologies`, `tooling`, `vulnerabilities`.
- The group tree holds **46** `.md` files, not 48 as the prior art recorded. Correcting the prior art:
  - **43 byte-identical** to their flat skill (verified with `diff`).
  - `vulnerabilities/idor.md` is a **strict subset** of `idor/SKILL.md` (the flat skill carries an extra "derive verb and body from evidence" section); no unique group content.
  - `vulnerabilities/ssti.md` carries unique content beyond the flat skill: a condensed "Blind Probes" section. This is the one unique group-tree artifact to fold.
  - `tooling/agent_browser.md` has **no flat counterpart** in the source (a source-system browser-tool skill); treated as a tool skill, discarded.
  - `reconnaissance/` is empty apart from `.gitkeep`.

## KEEP (27)

| Skill | Rationale |
|---|---|
| `authentication-jwt` | JWT/OIDC token-security testing procedure (forgery, alg confusion, claim manipulation); a web vulnerability class. |
| `broken-function-level-authorization` | BFLA action-level authorization testing; a web vulnerability class. |
| `business-logic` | Workflow/state/invariant logic-abuse testing; a web vulnerability class. |
| `crypto-weakness` | Weak-crypto and predictable-token testing; a web vulnerability class. |
| `csrf` | CSRF testing procedure; a web vulnerability class. |
| `graphql` | GraphQL API security testing (introspection, injection, batching, IDOR/BFLA); a web attack-surface family class. |
| `header-injection` | CRLF/response-splitting, cache poisoning, Host confusion, cookie fixation; a web vulnerability class. |
| `http-method-tampering` | Verb/override-header authorization bypass; a web vulnerability class. |
| `http-request-smuggling` | CL.TE/TE.CL/H2 desync testing; a web vulnerability class. |
| `idor` | Object-level authorization/BOLA testing; a web vulnerability class. |
| `information-disclosure` | Error/debug/metadata/source leakage testing; a web vulnerability class. |
| `insecure-deserialization` | Deserialization testing; a web vulnerability class. |
| `insecure-file-uploads` | File-upload testing; a web vulnerability class. |
| `mass-assignment` | Unauthorized field-binding testing; a web vulnerability class. |
| `nosql-injection` | NoSQL operator/variable injection testing; a web vulnerability class. |
| `open-redirect` | Open-redirect testing; a web vulnerability class. |
| `path-traversal-lfi-rfi` | Path traversal / LFI / RFI testing; a web vulnerability class. |
| `prototype-pollution` | Client and server prototype pollution testing; a web vulnerability class. |
| `race-conditions` | TOCTOU/concurrency testing; a web vulnerability class. |
| `rce` | Command-injection/code-evaluation testing; a web vulnerability class. |
| `sql-injection` | SQL injection testing; a web vulnerability class. |
| `ssrf` | SSRF testing; a web vulnerability class. |
| `ssti` | Server-side template injection testing; a web vulnerability class. |
| `two-principal-authz` | The two-principal authorization methodology (A creates state, B acts on A's object); a web testing procedure. |
| `weak-credential-discovery` | Exposed-credential/default-password/username-enumeration testing; a web vulnerability class. |
| `xss` | Reflected/stored/DOM XSS testing; a web vulnerability class. |
| `xxe` | XML external entity injection testing; a web vulnerability class. |

## DISCARD - tool skills (9 flat + 1 group)

| Skill | Rationale |
|---|---|
| `ffuf` | ffuf fuzzing CLI syntax; a tool skill. |
| `httpx` | ProjectDiscovery httpx CLI syntax; a tool skill. |
| `katana` | Katana crawler CLI syntax; a tool skill. |
| `naabu` | Naabu port-scanner CLI syntax; a tool skill. |
| `nmap` | Nmap CLI syntax; a tool skill. |
| `nuclei` | Nuclei CLI syntax; a tool skill. |
| `semgrep` | Semgrep CLI syntax; a tool skill. |
| `sqlmap` | sqlmap CLI syntax; a tool skill. |
| `subfinder` | Subfinder CLI syntax; a tool skill. |
| `tooling/agent_browser.md` (group) | Source-system browser-tool usage (`exec_command` wrapper); a tool skill with no flat owner. |

## DISCARD - technology skills (9)

| Skill | Rationale |
|---|---|
| `aws` | AWS cloud-stack playbook; a technology skill. |
| `django` | Django framework playbook; a technology skill. |
| `fastapi` | FastAPI framework playbook; a technology skill. |
| `firebase-firestore` | Firebase/Firestore stack playbook; a technology skill. |
| `kubernetes` | Kubernetes cluster playbook; a technology skill. |
| `nestjs` | NestJS framework playbook; a technology skill. |
| `nextjs` | Next.js framework playbook; a technology skill. |
| `python` | "Run Python through exec_command in the SDK sandbox"; a tool skill (listed with the technology set by the operator). |
| `supabase` | Supabase stack playbook; a technology skill. |

## BORDERLINE - ruled by the operator (2026-09-28), resolved (5)

| Skill | Ruling | Rationale and action |
|---|---|---|
| `cve-exploitation` | DISCARD | Product-specific version-to-CVE workflow, not a vulnerability class. Deleted. |
| `llm-prompt-injection` | KEEP | An emerging web vulnerability class; de-spuriated and its high-value targets extracted. Its `## Framework-Specific` block stays, flagged for the agnosticism pass. |
| `low-hanging-fruit` | DISCARD (content extracted) | Per-target hygiene checklist, not a vulnerability-class procedure. Its CORS/CSP/WAF-bypass/header/enumeration material was extracted to `_migration/bypass-proxy-techniques/low-hanging-fruit.md` for projection into the proxy/bypass-technique notions; the severity table and finding workflow were dropped. |
| `oauth` | KEEP | Genuine web vulnerability class; source tooling (`jwt_tool`, Burp EsPReSSO) removed and adapted to `python3`/`curl`. |
| `subdomain-takeover` | KEEP | Genuine web vulnerability class; `Special Contexts` folded and the absent `nuclei` swapped for `httpx`. |
