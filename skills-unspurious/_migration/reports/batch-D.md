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
