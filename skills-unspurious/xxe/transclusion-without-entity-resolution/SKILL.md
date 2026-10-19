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

Transclusion applies wherever an include processor honours namespaced include elements with fetch semantics.
Transclusion applies wherever a transform endpoint or reporting engine evaluates submitted stylesheets with document-fetch primitives.
Transclusion applies wherever uploads or document packages embed XML that a downstream pipeline parses with transclusion enabled.
Transclusion needs no entity resolution because the fetch primitive lives in the element and stylesheet layers.

## Reconnaissance

Inventory every XML consumer plus every transform endpoint plus every pipeline stage that touches uploaded documents.
Probe each stage for include support by submitting a benign namespaced include element and observing whether a fetch occurs.
Probe each transform endpoint for stylesheet evaluation by submitting a minimal benign stylesheet and observing whether document fetch runs.

## Detection Channels

### Direct Transclusion

Read transcluded content where it surfaces in the response body, the transformed output, or rendered artefacts.
Treat reproduced file or internal-URL content in any output channel as the primary verdict.

### Error Coercion

Harvest path fragments from fetch-failure messages that name the include target or the stylesheet resource.
Treat error fragments as confirmation that the fetch primitive executed even when content stays hidden.

### OAST Correlation

Watch the callback host for include or stylesheet fetches aimed at callback-owned addresses.
Treat blind include fetches as the secondary divergence of this variant, confirmed through callback correlation.

## Adversarial Capabilities

Submit attacker-shaped XML plus namespaced include elements to each inventoried consumer.
Submit attacker-shaped stylesheets with document-fetch primitives to each reachable transform endpoint.
Repackage uploads and document archives so embedded XML reaches implicit downstream parse paths.
Correlate blind fetch hits with probes through unique per-probe tokens.

## Trust Assumptions

The XML consumer executes attacker-supplied markup under a five-part agreement.
Declarations are rejected or neutered on every code path.
General-entity resolution stays disabled wherever markup is parsed.
Transclusion processors stay off unless the feature requires them.
Network access stays closed for parsers and transformers.
Parsed content never carries file or internal-network data back to the requester.
The agreement fails at the transclusion clause.
The include or stylesheet processor fetches the referenced resource although general-entity resolution stays blocked.

## Key Vulnerabilities

Include-element craft injects a namespaced element whose fetch attribute names a local file or internal URL.
Include craft carries no declaration block, so declaration filtering and entity disabling both miss it.
Stylesheet submission delivers a full transform program whose document-fetch primitive reads the target resource during evaluation.
Stylesheet craft reaches transform endpoints and reporting engines that never parse attacker entities at all.
Shape both crafts abstractly with placeholders before runtime values fill them.

```
[INCLUDE-ELEMENT namespace=[INCLUDE-NS] parse=[text-or-xml] href=[LOCAL-FILE-URI or INTERNAL-URL]]
```

```
[STYLESHEET template-match=[ROOT] fetch-primitive(document, [RESOURCE-URI]) emit-to=[OUTPUT]]
```

## Bypass Techniques

Vary element namespace prefixes and attribute capitalisation so naive element filters miss the include craft.
Vary stylesheet structure between minimal templates and multi-template programs to reach the evaluation path.
Pivot between file-URI targets and internal-URL targets inside the fetch attribute so one blocked family still yields the other.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Hand transcluded configuration content to path traversal follow-ups when the fetched file names further readable paths.
Hand transcluded internal-URL responses to the ssrf skill when the fetch reaches internal control planes.
Treat stylesheet-driven program execution beyond document fetch as the boundary of the code execution skill and carry only the fetch impact here.

## Testing Methodology

1. **Inventory consumers and transformers.**
List every XML sink plus every transform endpoint plus every pipeline stage that parses uploaded documents.
Completion holds when every stage carries a transclusion capability question and no upload path lacks a downstream parser.
2. **Probe transclusion capability.**
Submit benign include elements and benign stylesheets with unique per-probe tokens to each stage.
Completion holds when every stage shows either an executed fetch or recorded refusal.
3. **Fix the oracle.**
Record where transcluded content surfaces plus which error shapes name fetch targets plus which callback hits correlate.
Completion holds when every stage has a fixed channel of direct output plus error plus callback baseline.
4. **Run the targeted fetch.**
Aim include href craft and stylesheet document-fetch craft at a controlled file path or internal URL and reproduce the access evidence.
Completion holds when a controlled target produces reproducible content surfacing, a reproduced error fragment, or a correlated callback hit.
5. **Validate parity.**
Repeat the fetch craft across service endpoints plus uploads plus background jobs and record every divergence in processor options.
Completion holds when every channel shows the same options or a recorded divergence.

## False Positives

Include markup echoed literally with no fetch performed signals a disabled processor.
Stylesheet text returned verbatim with no evaluation signals a non-transforming consumer.
Mock success simulates transformation without file or network access.
Client-side-only processing renders includes where no server processor runs.

## Pro Tips

Probe include and stylesheet paths after entity resolution proves disabled because transclusion often remains enabled past entity hardening.
Repackage uploads rather than sending standalone markup because implicit pipeline parses are the richest transclusion ground.
Test transform endpoints separately because their processor options diverge from request-path parsers most often.
Keep each fetch target controlled and benign until the primitive proves live, then escalate to sensitive targets.
Attribute blind include hits through per-probe tokens before claiming the fetch.

## Summary

Transclusion ends when include processing and stylesheet document fetch stay disabled on every code path alongside entity resolution.
Harden the processor layer as one surface because entity controls alone never stop element-driven fetches.
