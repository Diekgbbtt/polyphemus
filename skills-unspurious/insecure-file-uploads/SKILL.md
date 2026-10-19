---
name: insecure-file-uploads
description: File upload security testing covering extension bypass, content-type manipulation, and path traversal
metadata:
  version: 1.0.0
---

# Insecure File Uploads

Upload surfaces are high risk: server-side execution, script delivery in the browser, malware distribution, storage takeover, and exhaustion. Modern stacks mix direct-to-cloud uploads, background processors, and edge caches, so authorization and validation must hold across every step.

## Attack Surface

- **Upload surfaces**: web, mobile, and API uploads, including direct-to-cloud flows and resumable multipart protocols
- **Media and document pipelines**: converters, renderers, metadata parsers, office and archive expanders
- **Compound document containers**: office and archive formats are nested containers whose inner markup a second component parses, so the xxe class owns the entity step while this class owns the pipeline step
- **Administrative and bulk importers**: archive uploads, report and template uploads, rich-text attachments
- **Serving paths**: the application itself, object storage, an edge cache, message attachments, previews and thumbnails

## Reconnaissance

### Surface Map

- **Endpoints and fields**: upload, file, avatar, image, attachment, import, media, document, template
- **Direct-to-cloud parameters**: key, bucket, access control, declared type, disposition, metadata fields, cache directives
- **Resumable APIs**: create, chunk, complete; check whether metadata and headers can be altered late
- **Background processors**: thumbnail, conversion, and scanning queues; identify timing and status transitions

### Capability Probes

- **Probe files**: small probe files of each claimed type; diff the resulting declared type, disposition, and sniffing-guard headers on download
- **Magic bytes versus extension**: a mismatch reveals reliance on the declared name or on sniffing
- **Markup probe**: does a script-capable file render inline or download
- **Archive probe**: a simple archive with traversal entries and links to detect extraction rules

### Placement and Serving

- **Placement recording**: record where each accepted file lands and which path serves it back
- **Header recording**: note per asset type the final headers and whether the type is server-set or reflected from the upload

## Detection Channels

- **Interpreter output**: returning from a requested stored object, which proves server execution.
- **Evaluation behaviour change**: after configuration-shaped placement, which proves handler activation.
- **Serving headers**: confirming server-set type adjudication, which separate executable placement from serving-context effects.
- **Script fire**: in the browser under the served context, which proves client execution.
- **Served type and header state**: a served type with disposition and sniffing-guard state, which adjudicates whether inline rendering was server-set or reflected.
- **Previewer rendering**: previewer rendering of stored document properties, which proves document-property script delivery.
- **Out-of-directory file presence**: after extraction, which proves traversal or link escape.
- **Overwritten content**: overwritten configuration or executable content, which proves high-impact write placement.
- **Processing exhaustion**: processing exhaustion with queue stalls, which proves compression-ratio abuse.
- **Processor command output**: reflected in derived artifacts or error state, which proves operator execution.
- **Out-of-scope content**: out-of-scope file content surfacing through conversion, which proves file-read operators.
- **Job behaviour deltas**: across probe families, which separate parser flaws from rendering effects.
- **Renderer-side receipt**: an outbound request or a script fire observed while a document renders, which proves a renderer engine reached beyond the uploaded content.
- **Post-gate serving**: post-gate objects served with an attacker-steered type or disposition, which proves late-control bypass.
- **Pre-verdict accessibility**: followed by a quarantine transition, which proves timing-gap exposure.
- **Serving-header comparison**: across initiation and finalization, which proves finalize-swap acceptance.

## Adversarial Capabilities

- **Prerequisites**: upload testing presupposes an authenticated upload path, control of file names and metadata, and a way to read the served result back, and it consumes all three.
- **Account holding**: hold an account entitled to upload, and a second account where sharing or foreign retrieval is in question.
- **Name and metadata control**: control the file name, the declared type, the disposition, and any direct-to-cloud parameters the client supplies.
- **Content crafting**: craft polyglot and archive content by hand, including nested and link-bearing entries.
- **Result fetching**: fetch the stored object back and read its final headers per serving path.
- **Victim session**: hold a victim browser session when client-side rendering decides the finding.
- **Processor timing**: time requests against background processors so the pre-verdict window stays measurable.

## Trust Assumptions

- **The agreement**: the class rests on one agreement: every step of the pipeline applies the same validation, and stored content is served as exactly what it is. The agreement holds the declared type to the content actually accepted, holds the placement location to a namespace that cannot execute or override configuration, holds the serving headers to a non-sniffing download for active content, holds processors to isolation from external resources and command execution, and holds the verification gate to complete before any other party can reach the object. Sensitive position leaks when any clause fails: content lands where it executes, a serving path renders it, an expander follows what it finds, or a consumer reads the object before the gate reports.
- **The failing clause**: each variant breaks one clause: the placement clause, the render clause, the extraction clause, the toolchain clause, or the gate-timing clause.

## Key Vulnerabilities

### Server-Side Execution

- **Interpreter placement**: placing interpreter-shaped content where the server executes it, including configuration files that map extensions or inject prelude paths
- **Converter evaluation**: converters that evaluate embedded operators during conversion, so an ordinary media or document file becomes a command carrier
- **Polyglot construction**: a valid magic-byte prefix followed by interpreter content, so content inspection and extension checks both pass
- **Extension tricks**: double extensions, mixed casing, and trailing separators that defeat extension-based checks

### Client-Side Script Delivery

- **Inline markup**: markup files served inline without sufficient headers fire scripts in the viewer's browser
- **Previewer script**: document formats with embedded script executed by previewers, and markup carried inside metadata fields
- **Missing sniffing guard**: missing sniffing guard on any serving path, which lets a browser treat stored bytes as script-capable markup

### Archive Extraction

- **Traversal and link entries**: traversal entries escaping the extraction directory, and link entries pointing outside it
- **Nested archives**: nested archives that re-expand into a second traversal
- **Compression-ratio abuse**: compression-ratio abuse that exhausts the expander or the queue behind it

### Toolchain Exploitation

- **External operators**: crafted images and documents invoking external operators or reading local files during conversion
- **Renderer engines**: document-to-image and screenshot services run a browser that fetches remote URLs, reads local paths, and may execute script inside the rendered document; name the ssrf skill at the fetch step and the xss skill at the script step
- **Stream demuxers**: converters that follow a stream manifest or a concatenation list fetch remote content as part of the conversion, which turns an ordinary media file into a fetch carrier
- **Metadata blocks**: metadata blocks sized or shaped to trigger parser flaws in the extraction stage
- **Derived outputs**: derived outputs that carry the operator side effect into a served artifact

### Storage and Direct-to-Cloud Vectors

- **Client-set type and disposition**: client-set type and disposition on presigned uploads, which then render inline from the bucket or edge
- **Broad read access**: broad read access on the storage location, and user-controlled key prefixes that place objects in sensitive namespaces
- **Stale signed links**: stale signed links reused later, and serving directly from storage without download and sniffing headers

### Gate Timing and Processing Races

- **Pre-verdict requests**: requesting the object after upload but before the verification or transformation step completes
- **Window widening**: widening the window with heavy conversions or large objects
- **Container formats**: container formats that bypass inspection by hiding content from the scanner

## Advanced Techniques

### Resumable Multipart

- **Finalize swap**: change metadata between initiation and completion, swapping the declared type or disposition at finalize
- **Chunk swap**: upload benign chunks, then swap the last chunk or complete from a different source

### Filename and Path

- **Lookalike names**: lookalike characters, trailing dots and spaces, device names, and reserved characters to bypass validators
- **Truncation and collisions**: truncation on legacy stacks, overlong paths, and case-insensitive collisions overwriting an existing file

### Metadata Abuse

- **Oversized blocks**: oversized metadata blocks that trigger parser flaws
- **Document properties**: payloads in document properties rendered by previewers

### Serving Header Manipulation

- **Inline forcing**: force inline rendering through a declared type plus an inline disposition
- **Cache poisoning**: poison an edge cache whose key omits the content type and disposition

### Client-Layer Surfaces

- **Rich-text editors**: rich-text editors that accept attachments and embed links; verify sanitization and serving headers
- **Mobile clients**: mobile clients sending nonstandard types or metadata that the server trusts as already transformed
- **Serverless post-processing**: serverless and edge post-processing where the security decision is delegated to the front end

## Bypass Techniques

### Validation Gaps

- **Client-side checks**: client-side-only checks, including trust in the type the browser or client declares
- **Part-header trust**: trust in part headers of a multipart body
- **Allowlists without inspection**: extension allowlists without server-side content inspection

### Evasion Tricks

- **Name tricks**: double extensions, mixed case, hidden dotfiles, repeated dots, and long paths ending in an allowed suffix
- **Parameter divergence**: divergence between the name in the multipart part and the name carried in the parameters, plus duplicate parameters where the later wins
- **Bypass reference**: see `references/upload-bypass-matrix.md` for the bypass families and the expected verdicts behind each probe.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Upload plus server execution**: the placed object becomes an interpreter entry point
- **Upload plus client execution**: the served object fires in another user's browser session
- **Upload plus extraction**: an archive writes outside its destination into a served or executable location
- **Upload plus the document toolchain**: conversion executes the payload inside a processor
- **Upload plus cross-site delivery**: the stored markup is served under the victim's trusted origin

## Testing Methodology

1. **Map the pipeline** - Client, ingress, storage, processors, serving; note where validation and authorization occur
2. **Identify allowed types and limits** - Size limits, name rules, storage keys, and who serves the content
3. **Collect baselines** - Capture resulting locations and headers for legitimate uploads of each accepted type
4. **Exercise bypass families** - Extension games, declared types, magic bytes, polyglots, metadata payloads, archive structure
5. **Validate the effect** - Does the stored content execute on the server, fire in a browser, or write outside its destination
6. **Time the gate** - Request the object immediately after upload and again after the processor reports; the step completes when the pre-verdict window carries a verdict

## Variants

- upload-server-execution - Place uploaded content where the server interpreter executes it, through stored executable shapes and handler-mapping placement.
- upload-client-execution - Render stored uploads as script in the browser, through inline serving and missing sniffing guards.
- upload-archive-extraction - Prove traversal writes or link escapes during extraction, including compression-ratio abuse.
- upload-toolchain-execution - Trigger converters, metadata parsers, and renderer engines into executing embedded operators or fetching external content, with derived artifacts as evidence.
- upload-pipeline-deferred-trust - Prove late control points bypass earlier validation, through finalize swaps, client-set headers on direct-to-cloud flows, and pre-verdict fetching.

## False Positives

- **Never-served uploads**: upload stored but never served back, or always served as a download with a strict sniffing guard
- **Locked-down converters**: converters running in locked-down sandboxes with no external resources and no script engines
- **Quarantined payloads**: the verification step blocking the payload and quarantining it, with pre-verdict access impossible by design

## Pro Tips

- **Minimal proofs**: keep proofs minimal: a tiny markup file for script delivery, a single-line interpreter file where that is the finding
- **Download headers**: always capture download headers and the final served type; they decide browser behaviour
- **Inert renderings**: prefer transforming risky formats into inert renderings over complex sanitization
- **Direct-to-cloud constraints**: in direct-to-cloud flows, constrain every header and object key server-side
- **Archive discipline**: extract archives in an isolated directory with an explicit allowlist, drop links, and reject traversal
- **Finalize testing**: test the finalize step in resumable flows; many validations run only at initiation
- **Processor verification**: verify background processors with concatenation markers and tiny polyglots
- **Stored script delivery**: when server execution stays out of reach, aim for stored script delivery or header-driven rendering
- **Edge header honouring**: validate that the edge honours download and sniffing headers
- **Pipeline documentation**: document the pipeline behaviour per asset type

## Summary

Secure uploads are a pipeline property. Enforce strict type, size, and header controls; transform or strip active content; keep stored content out of execution and inline-rendering paths; and keep storage private behind controlled, signed access.
