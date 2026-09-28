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
