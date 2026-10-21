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
