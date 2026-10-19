---
name: transclusion-without-entity-resolution
description: Transclusion XXE through include and stylesheet fetch without entity resolution. Use when declarations are rejected yet includes still resolve, when transform endpoints accept stylesheet submissions, when uploads embed XML that a downstream pipeline parses.
metadata:
  version: 1.0.0
---

# Transclusion Without Entity Resolution

Transclusion treats include and stylesheet processors as fetch primitives that survive entity hardening.
Transclusion reads local files and internal URLs through element-driven fetches that need no declaration block at all.

## Attack Surface

- **Include processors**: an include processor honours namespaced include elements with fetch semantics.
- **Transform endpoints**: a transform endpoint or reporting engine evaluates submitted stylesheets with document-fetch primitives.
- **Embedded documents**: uploads or document packages embed XML that a downstream pipeline parses with transclusion enabled.
- **Entity-free primitive**: the fetch primitive lives in the element and stylesheet layers, so no entity resolution is needed.

## Reconnaissance

- **Consumer inventory**: inventory every XML consumer plus every transform endpoint plus every pipeline stage that touches uploaded documents.
- **Include probe**: probe each stage for include support by submitting a benign namespaced include element and observing whether a fetch occurs.
- **Stylesheet probe**: probe each transform endpoint for stylesheet evaluation by submitting a minimal benign stylesheet and observing whether document fetch runs.

## Detection Channels

### Direct Transclusion

- **Direct transclusion**: read transcluded content where it surfaces in the response body, the transformed output, or rendered artefacts.
- **Primary verdict**: treat reproduced file or internal-URL content in any output channel as the primary verdict.

### Error Coercion

- **Fetch-failure messages**: harvest path fragments from fetch-failure messages that name the include target or the stylesheet resource.
- **Fetch confirmation**: treat error fragments as confirmation that the fetch primitive executed even when content stays hidden.

### OAST Correlation

- **Callback watch**: watch the callback host for include or stylesheet fetches aimed at callback-owned addresses.
- **Blind-fetch divergence**: treat blind include fetches as the secondary divergence of this variant, confirmed through callback correlation.

## Adversarial Capabilities

- **Include submission**: submit attacker-shaped XML plus namespaced include elements to each inventoried consumer.
- **Stylesheet submission**: submit attacker-shaped stylesheets with document-fetch primitives to each reachable transform endpoint.
- **Upload repackaging**: repackage uploads and document archives so embedded XML reaches implicit downstream parse paths.
- **Probe attribution**: correlate blind fetch hits with probes through unique per-probe tokens.

## Trust Assumptions

- **The agreement**: the XML consumer executes attacker-supplied markup under a five-part agreement in which declarations are rejected or neutered on every code path, general-entity resolution stays disabled wherever markup is parsed, transclusion processors stay off unless the feature requires them, network access stays closed for parsers and transformers, and parsed content never carries file or internal-network data back to the requester.
- **The failing clause**: the agreement fails at the transclusion clause because the include or stylesheet processor fetches the referenced resource although general-entity resolution stays blocked.

## Key Vulnerabilities

- **Include-element craft**: injects a namespaced element whose fetch attribute names a local file or internal URL.
- **Declaration-free delivery**: include craft carries no declaration block, so declaration filtering and entity disabling both miss it.
- **Stylesheet submission**: delivers a full transform program whose document-fetch primitive reads the target resource during evaluation.
- **Stylesheet reach**: stylesheet craft reaches transform endpoints and reporting engines that never parse attacker entities at all.
- **Abstract shaping**: shape both crafts abstractly with placeholders before runtime values fill them.
  ```
  [INCLUDE-ELEMENT namespace=[INCLUDE-NS] parse=[text-or-xml] href=[LOCAL-FILE-URI or INTERNAL-URL]]
  ```

  ```
  [STYLESHEET template-match=[ROOT] fetch-primitive(document, [RESOURCE-URI]) emit-to=[OUTPUT]]
  ```

## Bypass Techniques

- **Namespace variation**: vary element namespace prefixes and attribute capitalisation so naive element filters miss the include craft.
- **Stylesheet variation**: vary stylesheet structure between minimal templates and multi-template programs to reach the evaluation path.
- **Target-family pivot**: pivot between file-URI targets and internal-URL targets inside the fetch attribute so one blocked family still yields the other.


When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.
## Chaining Attacks

- **Configuration handoff**: hand transcluded configuration content to path traversal follow-ups when the fetched file names further readable paths.
- **Internal-URL handoff**: hand transcluded internal-URL responses to the ssrf skill when the fetch reaches internal control planes.
- **Code-execution boundary**: treat stylesheet-driven program execution beyond document fetch as the boundary of the code execution skill and carry only the fetch impact here.

## Testing Methodology

1. **Inventory consumers and transformers** - list every XML sink plus every transform endpoint plus every pipeline stage that parses uploaded documents, and the step completes when every stage carries a transclusion capability question and no upload path lacks a downstream parser.
2. **Probe transclusion capability** - submit benign include elements and benign stylesheets with unique per-probe tokens to each stage, and the step completes when every stage shows either an executed fetch or recorded refusal.
3. **Fix the oracle** - record where transcluded content surfaces plus which error shapes name fetch targets plus which callback hits correlate, and the step completes when every stage has a fixed channel of direct output plus error plus callback baseline.
4. **Run the targeted fetch** - aim include href craft and stylesheet document-fetch craft at a controlled file path or internal URL and reproduce the access evidence, and the step completes when a controlled target produces reproducible content surfacing, a reproduced error fragment, or a correlated callback hit.
5. **Validate parity** - repeat the fetch craft across service endpoints plus uploads plus background jobs and record every divergence in processor options, and the step completes when every channel shows the same options or a recorded divergence.

## False Positives

- **Literal include markup**: include markup echoed literally with no fetch performed signals a disabled processor.
- **Verbatim stylesheet text**: stylesheet text returned verbatim with no evaluation signals a non-transforming consumer.
- **Mock success**: mock success simulates transformation without file or network access.
- **Client-side-only processing**: client-side-only processing renders includes where no server processor runs.

## Pro Tips

- **Post-hardening probe**: probe include and stylesheet paths after entity resolution proves disabled because transclusion often remains enabled past entity hardening.
- **Upload repackaging**: repackage uploads rather than sending standalone markup because implicit pipeline parses are the richest transclusion ground.
- **Transform separation**: test transform endpoints separately because their processor options diverge from request-path parsers most often.
- **Controlled targets**: keep each fetch target controlled and benign until the primitive proves live, then escalate to sensitive targets.
- **Probe attribution**: attribute blind include hits through per-probe tokens before claiming the fetch.

## Summary

Transclusion ends when include processing and stylesheet document fetch stay disabled on every code path alongside entity resolution.
Harden the processor layer as one surface because entity controls alone never stop element-driven fetches.
