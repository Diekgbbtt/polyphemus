---
name: xxe
description: XXE testing for external entity injection, file disclosure, and SSRF via XML parsers
metadata:
  version: 1.0.0
---

# XXE

XML external entity injection is a parser-level failure: the parser resolves references the document supplies and reaches local files, interior services, and remote definitions on the document's behalf, with unbounded expansion and downstream execution as further consequences. The same reach appears wherever a parser is unhardened, including container documents whose embedded segments are parsed implicitly. Treat every XML input as untrusted until the parser's capability set is proven hardened.

## Attack Surface

**Consumer Families**
- **Parsing consumers**: structured request APIs, document uploads, renderers, import pipelines, and background jobs that parse XML.
- **Container documents**: whose embedded XML segments are parsed implicitly during processing.
- **Transform and report pipelines**: that accept stylesheet or definition documents.
- **Signature and federation flows**: whose XML is parsed before the signature is verified.

**Carriers**
- **Carriers**: request bodies, uploads, multipart parts, embedded document segments, and stored values that a later job parses.

**Capability Families**
- **Capability families**: local file disclosure, interior fetch, remote transclusion, and expansion effects, each gated by the consumer's parser settings.

## Reconnaissance

### Consumer Inventory

- **Consumer enumeration**: enumerate every parsing consumer per endpoint, upload path, background job, converter, and third-party parser.
- **Carrier mapping**: record which carrier reaches which consumer, and whether parsing happens inline or deferred.
- **Reparse noting**: note pipeline stages that reparse: a document accepted at the front door may be parsed again later with different settings.
- **Content-type negotiation**: replay a structured body under an XML content type, and the reverse, because a parser frequently hides behind a neighbouring content type.

### Capability Probes

- **Declaration acceptance**: whether a document type declaration is honoured at all.
- **Inline-entity pre-flight**: declare an internal entity, reference it, and confirm expansion; when a harmless internal entity does not expand, external resolution will not work either.
- **Resolution**: whether external general entities resolve, and whether external parameter entities plus remotely held definitions resolve.
- **Egress**: whether the parser can reach network destinations, and whether the network stays closed while the filesystem is readable.
- **Transclusion**: whether include elements and stylesheet document fetches resolve where declaration resolution is blocked.
- **Containers**: whether an upload path parses embedded document segments implicitly.

### Oracle Setup

- **Channel establishment**: establish the observable channel per consumer before payload assembly: inline output, error text, callback receipt, or differential.
- **Token minting**: mint one token per probe for callback correlation, and record a control response's length and validator values.
- **Latency baseline**: measure a latency baseline where a fetch or expansion effect is the phenomenon under test.
- **Callback preflight**: preflight callback infrastructure so a missing arrival means blocked resolution rather than a broken receiver.

## Detection Channels

- **Inline disclosure**: inline disclosure of referenced content in the response, transformed output, or an error page.
- **Interpolating error text**: error text that interpolates a path fragment or fetched value, which discloses without a body channel.
- **Token-carrying callback**: a callback receipt at operated infrastructure carrying the per-probe token, which proves resolution and egress when nothing is reflected.
- **Two-stage chain**: a two-stage chain where the parser first fetches an attacker-held definition and then routes a read value onward, which proves the full resolution path.
- **Timing differences**: timing differences over a baseline for a slow or unroutable reference, which separate a connection attempt from a parse error.
- **Length and validator shifts**: length and validator shifts between a control document and a reference-bearing document, which prove effect on masked content.
- **Transclusion output**: transformed or rendered output carrying content fetched by the document, which proves transclusion.
- **Derived artifact**: a derived artifact (converted document or report) carrying resolved values, which proves the parse reached material the application did not supply.
- **Resource exhaustion signals**: latency growth, memory pressure, and timeouts under small document growth, which prove unbounded expansion.
- **Uniform rejection**: uniform rejection across every consumer and carrier, which reads as a hardened parser rather than a negative per path.

## Adversarial Capabilities

- **XXE testing**: presupposes an XML carrier, a parser whose capability set is probeable, and a resolution oracle, and it consumes all three.
- **Carrier submission**: submit a document through every carrier the consumers accept: bodies, uploads, multipart parts, and embedded segments.
- **Attacker-hosted definitions**: host the remote definition document and the callback listener under attacker control, with one token per probe.
- **Container repackaging**: repackage container documents so a crafted segment lands in the part that is parsed implicitly.
- **Signal reading**: read timing, error class, and validator differences when nothing is reflected.
- **Transform reach**: reach a transform endpoint so a submitted stylesheet or definition is processed.
- **Destination control**: control a name or destination the parser resolves, so exfiltration routes back to the listener.

## Trust Assumptions

- **The agreement**: a document's references resolve only to definitions and destinations the application chose, and the parser reaches nothing else on the document's behalf.
- **Held clauses**: the agreement holds declarations to the application's own format, holds external resolution closed beyond application-chosen sources, holds transclusion to inputs the application supplies, and holds expansion to a bounded size.
- **Leak condition**: interior content and position leak when a clause fails: the parser resolves a caller-supplied definition, follows a caller-chosen destination, fetches an outside source through a transclusion path, or amplifies expansion without bound.
- **The failing clause**: each variant breaks one clause: the external-resolution clause, the transclusion clause, or the bounded-expansion clause.

## Key Vulnerabilities

### External Resolution

- **General-entity resolution**: general-entity references resolve to local files and interior destinations when the parser is unhardened, with the value landing in the response or a derived artifact.
- **Parameter entities**: parameter entities extend the reach: the document fetches an externally held definition, which itself defines further references.
- **Wrapper and scheme families**: wrapper and scheme families extend a resolved fetch, so handler support decides which destinations answer.
- **Interior mapping**: a distinct reference per port or per interior address, with timing or error class as the oracle, maps reachable destinations without a response body.
- **Stored documents**: stored documents parsed by a later job carry the same reach behind a deferred trigger.

### Blind Exfiltration

- **Resolution as oracle**: where no channel carries the value, the resolution step itself becomes the oracle: fetch a held definition, then route a read value into a caller-controlled destination.
- **Chain sequencing**: the chain is sequenced: host the definition, include it as the external subset, redefine a reference inside it, and correlate the inbound request.
- **Error-text fragments**: error text may interpolate a fragment even when inline resolution is blocked.

### Transclusion

- **Include elements**: include elements resolve local and remote content where declaration resolution is disabled, and they carry their own fetch semantics.
- **Stylesheet processing**: stylesheet processing resolves document references at transform time, which reaches files and interior destinations through a path declarations cannot use.
- **Transform-time execution**: a transform processor that exposes an extension runs host code, so a submitted stylesheet reaches execution rather than only transclusion.
- **Implicit parses**: container documents and embedded segments open the same reach with no declaration at all.

### Expansion

- **Nested definitions**: nested definitions amplify without any external target, which converts a small document into resource exhaustion.
- **Observed effects**: effects appear as latency, memory pressure, and timeouts, and they reach every consumer that shares the parser settings.
- **Shared processing paths**: where one shared processing path serves several consumers, one crafted document affects all of them.

### Verification Ordering

- **Parse-before-verify**: signature and federation flows may parse the document before verifying it, so a crafted segment is processed before the flow rejects it.
- **Window as surface**: treat the parse-before-verify window as a disclosed surface even when the final verdict is rejection.

### Parse Setting Parity

- **Setting divergence**: background processors, converters, and third-party parsers often keep different settings from the request path.
- **Per-consumer probing**: a hardened front door does not imply a hardened pipeline; probe each consumer separately.

## Advanced Techniques

**Quiet Oracle Discipline**
- **Callback preference**: prefer the callback channel; it is the quietest confirmation on production-like paths.
- **Channel establishment**: establish the observable channel per consumer before payload assembly; an unproven channel wastes the chain.

**Chain Assembly**
- **Step-by-step assembly**: assemble the two-stage chain step by step: confirm the remote definition fetch, then confirm that a redefined reference resolves, then route the value.
- **Minimal definitions**: keep the definition document minimal so each arrival is attributable to exactly one probe.

**Parity Sweep**
- **Per-consumer re-probing**: re-probe capability per consumer: one document may be accepted, blocked, and partially resolved along a single pipeline.
- **Path differences**: treat a difference between parsing and rejecting paths as a finding of its own.

**Minimal Expansion Probes**
- **Small-step growth**: grow the document in small steps and stop at the first measurable effect; a full amplification document is noisy and unnecessary.

## Bypass Techniques

**Declaration Variants**
- **Declaration forms**: PUBLIC and SYSTEM forms, mixed case, and internal versus external subset placement.
- **Subset edge handling**: multi-declaration edge handling and nested subset forms.

**Encoding Variants**
- **Encoding layers**: alternate document encodings and declarations, mixed newlines, and comment or wrapper sections.

**Network and File Pivots**
- **Filesystem pivot**: where the network is closed but the filesystem is readable, pivot to local disclosure.
- **Network pivot**: where files are blocked but the network is open, pivot to fetch and callback exfiltration.

**Transclusion Fallbacks**
- **Fallback paths**: where declaration resolution is blocked, reach the same content through include and stylesheet paths, or through an implicitly parsed container segment.

- **Family hand-off**: declaration shapes that a text filter misses and encoding layers that survive one are the defence-bypass family's steps; name it there and keep the class-specific declaration grammar here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Credential stores**: file disclosure to credential and configuration stores, then movement to other systems.
- **Control services**: interior fetch to metadata and control services, which yields credential material and position.
- **Deserialization**: wrapper and transform reach to the deserialization class where resolved content becomes a decoded object.
- **Path traversal**: disclosed paths to the path-traversal class where the value names further reachable content.
- **Availability loss**: expansion to availability loss on shared processing paths, where one crafted document affects several consumers.

## Testing Methodology

1. **Inventory consumers** - Endpoints, upload paths, background jobs, converters, and third-party parsers, each with its carrier
2. **Probe capabilities** - Declaration acceptance, external resolution, egress, transclusion, and container handling, per consumer
3. **Establish the oracle** - Error shape, length and validator differences, callbacks, or latency
4. **Escalate** - Targeted local-file and interior-fetch references, then the blind chain where no channel answers
5. **Validate parity** - The same settings must hold across request, upload, transform, and background paths
6. **Confirm the effect** - Every claim carries a disclosed value, a correlated callback, or a measured resource effect

## Variants

- blind-parameter-entity-oob-exfiltration - Chain a held external definition with two-stage reference redefinition and a callback destination when no response carries the value.
- transclusion-without-entity-resolution - Reach local and remote content through include elements, submitted stylesheets, and implicitly parsed container segments where declaration resolution is blocked.
- entity-expansion-denial-of-service - Amplify nested definitions to exhaust shared processing paths, observed as latency, memory, and timeout growth under small document growth.
- xxe-local-dtd-error-exfiltration - Repurpose a definition document already installed on the host and force a read value into a parse error when remote resolution stays closed.

## False Positives

- **Accepted declarations without reach**: declarations accepted but no external resolution occurs and no transclusion path is reachable.
- **Literal-emitting filters**: filters and sandboxes that emit the reference text literally without any IO.
- **Simulating mocks**: mocks and stubs that simulate success without network or filesystem access.
- **Client-only parsing**: documents parsed only on the client, with no server-side parse.
- **Structure injection**: where declarations are stripped: element or attribute injection and section-boundary manipulation alter the parsed tree without resolving anything, which is a markup-shape finding rather than external resolution.
- **Unexplained parse errors**: parse errors with no IO evidence behind them.
- **Foreign callbacks**: a callback that arrives from a different source than the consumer's egress path.

## Pro Tips

- **Callbacks first**: prefer callbacks first; they are the quietest confirmation on production-like paths.
- **Sanitised content**: when content is sanitised, use error text plus length and validator differences.
- **Include and stylesheet paths**: probe include and stylesheet paths even where declaration resolution is disabled; they often stay enabled.
- **Interior targets**: aim interior fetches at control planes, orchestrators, and data stores before public destinations.
- **Container repackaging**: in uploads, repackage a container document rather than a standalone one; many pipelines parse embedded segments implicitly.
- **Minimal documents**: keep documents minimal; grow expansion in small steps and stop at the first measurable effect.
- **Background processors**: probe background processors separately; they often keep different parser settings.
- **Option verification**: verify parser options in code and configuration; a filter in front of the parser is not hardening.
- **Class composition**: compose with the path-traversal and deserialization classes where disclosed content flows downstream.

## Summary

XXE is eliminated at the parser: refuse caller-supplied declarations, close external resolution, bound expansion, and apply the same settings on every path that parses XML.
One unhardened consumer is enough, and implicitly parsed container segments count as consumers.
