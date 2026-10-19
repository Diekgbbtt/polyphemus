---
name: path-traversal-lfi-rfi
description: Path traversal and file inclusion testing for local/remote file access and code execution
metadata:
  version: 1.0.0
---

# Path Traversal / LFI / RFI

Improper file path handling and dynamic inclusion enable sensitive file disclosure, config and source leakage, SSRF pivots, and code execution. Treat all user-influenced paths, names, and schemes as untrusted; normalize and bind them to an allowlist or eliminate user control entirely.

## Attack Surface

**Path Traversal**
- **Traversal reads**: read files outside intended roots via traversal shapes, encoding, and normalization gaps

**Local File Inclusion (LFI)**
- **Server-side inclusion**: include server-side files into interpreters, handlers, and templates

**Remote File Inclusion (RFI)**
- **Remote inclusion**: include remote resources through scheme handlers for code execution

**Archive Extraction**
- **Extraction writes**: archive entries that write outside the target directory on extract

**Normalization Mismatches**
- **Decoder differences**: between front-end and application in normalization order
- **OS-specific path shapes**: alternate separators, device names, UNC forms, alternate data streams

**Sinks**
- **Path-joining parameters**: download, export, preview, report, log, and template parameters that join user input into a path
- **Upload and conversion pipelines**: image and document renderers, thumbnailers, office converters
- **Non-parameter sinks**: converter-internal resource spellings and archive extractors that resolve content with no file parameter in play
- **Archive extract endpoints**: import jobs, and background workers
- **Server-side template rendering**: with dynamic template selection
- **Reverse proxies and static file servers**: in front of application handlers

## Reconnaissance

### Surface Map

- **Parameter names**: file, path, template, include, page, view, download, export, report, log, dir, theme, lang
- **Non-parameter read surfaces**: converter-internal resource spellings and extractor paths that resolve content with no file parameter
- **Upload and conversion pipelines**: renderers, thumbnailers, office converters
- **Archive extract endpoints**: and background jobs; imports of archive formats
- **Server-side template rendering**: with dynamic template names, themes, and plugins
- **Reverse proxies and static file servers**: in front of application handlers

### Capability Probes

- **Traversal baseline**: across separators: relative sequences against a canonical small file, plus platform-native path shapes for the target OS
- **Encodings**: single and double URL encoding, mixed case, overlong UTF-8 and UTF-16 forms, Unicode dot and separator equivalents
- **Normalization tests**: folded and repeated dot segments, trailing dot and trailing slash forms, repeated decoding
- **Absolute path acceptance**: rooted paths supplied where a relative name is expected
- **Front-end versus backend mismatch probes**: encoded separators and path parameters that survive the front-end

### Proof Strategy

- **Canonical proof files**: prefer canonical small files as read proof and keep writes to synthetic archives or benign destinations
- **Attribution**: record the exact input shape and the resulting path resolution for each probe so the effect is attributable
- **In-root control**: where content is masked, calibrate against an in-root control request before drawing conclusions

## Detection Channels

- **Direct response disclosure**: where the body returns file content for a crafted traversal or inclusion shape.
- **Error echo**: where exception, inclusion, or extractor warnings expose canonicalized locations for a crafted shape.
- **Masked-content shift**: where length and entity-tag values change between in-root controls and traversal candidates.
- **Direct handler disclosure**: where a wrapper or filter shape returns transformed local content for a crafted include shape.
- **Outbound fetch receipt**: where a wrapper or hosted content shape triggers a fetch that confirms handler invocation.
- **Direct deterministic output**: where the response carries a hosted marker as evaluation evidence.
- **Encoded-content disclosure**: where a filter-style read returns content that decodes to valid source, which proves the read even when the raw body is not plain text.
- **Out-of-band callback receipt**: carrying a per-sink sub-tag, which confirms a blind read and attributes it to one sink.
- **Outside-write evidence**: where post-extract listings reveal files beyond the destination for a crafted archive shape.
- **Follow-up read evidence**: where a subsequent read retrieves content from the outside location.

## Adversarial Capabilities

- **Prerequisites**: path traversal and inclusion testing presupposes a file-operation carrier, knowledge of the target's path resolution, and a readable or writable location to prove the effect, and it consumes all three.
- **Carrier reach**: reach a parameter whose input joins into path resolution, inclusion, or extract-destination logic.
- **Content hosting**: host content on a reachable origin when the scheme policy permits remote inclusion.
- **Archive crafting**: craft archive and wrapper shapes accepted by the parsing pipeline.
- **Listener operation**: operate a listener that receives the outbound fetch which proves invocation.
- **Canonical proof choice**: choose canonical small files as read proof to keep the effect minimal and unambiguous.
- **Re-read attribution**: re-read a location after an extract or write to attribute the outside effect.

## Trust Assumptions

- **The agreement**: the class rests on one agreement: a path, name, or scheme supplied by a user stays confined to the location the application intended and never selects executable content on its own. The agreement holds every input to a canonical path inside the intended root, holds each decoding hop to a single consistent decoding, holds inclusion targets to a constant application-chosen set, and holds archive entries to the extract destination. Sensitive files, write locations, and code execution leak when a user-influenced path escapes the root, a hop disagrees on normalization, or a scheme or entry selects content the application did not choose.
- **The failing clause**: each variant breaks one clause: the confinement clause, the handler-selection clause, the scheme clause, or the extract-destination clause.

## Key Vulnerabilities

### Traversal Read

- **Out-of-root reads**: joins of user input into filesystem reads allow out-of-root reads through relative sequences, encoded forms, and absolute paths
- **Masked responses**: masked responses still answer: diff length, entity tag, and status against in-root controls
- **Decoder disagreement**: front-end and backend decoder disagreements open reads where the application-level filter alone passes

### Inclusion Handlers

- **Dynamic resolution**: dynamic include or template resolution turns a user-influenced name into file selection
- **Wrapper schemes**: wrapper schemes reach local content through filter-style transforms where the handler honours them
- **Poisonable state**: poisonable local state (logs, sessions, temporary uploads, process caches) provides attacker-influenced content for inclusion
- **Error disclosure**: inclusion errors and warnings name canonicalized locations, which confirms the resolution

### Remote Inclusion

- **Scheme-qualified names**: include sinks that accept scheme-qualified names fetch attacker-hosted content
- **Scheme policy**: the scheme policy decides reachability: remote wrappers are often disabled while alternate schemes remain
- **Outbound callbacks**: outbound callbacks from the fetcher confirm invocation with the strongest evidence
- **Local fallback**: where remote inclusion is disabled, chain upload or poisoning paths into a local inclusion instead

### Archive Extraction

- **Entry paths**: entries whose names carry relative traversal or absolute paths write outside the extract destination
- **Format and link handling**: test across archive formats and confirm symlink handling and path canonicalization before the write
- **Follow-up read**: outside writes reach served directories, configuration, and templates, so confirm the effect with a follow-up read

## Bypass Techniques

**Encoding**
- **Encoding families**: single and double URL encoding, mixed case, overlong UTF-8 and UTF-16 forms, Unicode dot and separator equivalents
- **Repeated decoding**: repeated decoding through front-end and backend hops

**Separator and Dot Tricks**
- **Mixed separators**: mixed separators and separator collapse differences across frameworks
- **Dot segments**: folded dot segments, trailing dots and slashes, appended valid extensions

**Path Shape**
- **Absolute path injection**: where the application joins a user value onto a base
- **Front-end alias mismatches**: front-end alias and root mismatches with nested route prefixes
- **Path parameters**: path parameters and encoded separators that survive the front-end but change the backend's resolution

**Disabled Primitives**
- **Wrapper substitution**: where wrappers are disabled, substitute an alternate wrapper or scheme with the same reach
- **Local poisoning**: where remote inclusion is blocked, poison local state and include it locally

**Resolution Gaps**
- **Alias and link names**: defeat canonical-path allow-lists through alias and link names the resolution admits without leaving the permitted prefix
- **Late canonicalization**: defeat a resolution that runs after the read by reaching a sink whose canonicalization completes later than the operation it guards
- **Encoding reference**: see `references/traversal-encoding-matrix.md` for the encoding families, the hop discipline, and the high-value read targets behind each probe.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Configuration disclosure**: traversal or inclusion to sensitive configuration, which yields further access
- **Code execution**: inclusion and poisoning to code execution where the handler evaluates included content
- **Internal fetches**: inclusion to internal fetches, which converts into SSRF surfaces
- **Template poisoning**: archive outside writes to template or served-directory poisoning

## Testing Methodology

1. **Inventory file operations** - Downloads, previews, templates, logs, exports and imports, report engines, uploads, archive extractors, and non-parameter read surfaces in converters and extractors
2. **Identify input joins** - Path joins, include and template loads, resource fetchers, extract destinations
3. **Probe normalization** - Separators, encodings, double decodes, case, trailing dots and slashes
4. **Compare behaviors** - Front-end versus application resolution order
5. **Escalate** - From disclosure to influence (write or extract), then to execution (wrapper and engine chains)
6. **Confirm the effect** - Keep proof minimal: a canonical small file for reads, a follow-up read for writes

## Variants

- traversal-read - Read out-of-root files where file-operation carriers join input into filesystem reads, including masked responses adjudicated by length.
- lfi-include-execution - Include local files into a handler through dynamic names, wrapper schemes, poisonable local state, and conversion-chain synthesis from a read-only filter primitive.
- rfi-remote-include - Fetch hosted content through remote-scheme inclusion, gated by scheme policy and proven by outbound callbacks.
- archive-zipslip-write - Write outside extract destinations through crafted archive entries, confirmed by listings and follow-up reads.

## False Positives

- **Virtual paths**: in-app virtual paths that do not map to the filesystem; content comes from safe stores
- **Canonicalized paths**: constrained to an allowlist or root after normalization
- **Disabled wrappers**: wrappers disabled and includes using constant templates only
- **Sanitizing extractors**: archive extractors that sanitize paths and enforce destination directories

## Pro Tips

- **Masked-content comparison**: compare length and entity tag when content is masked; read canonical small files to avoid noise
- **Front-end separation**: test front-end and application separately; decoding and normalization order differs, especially for encoded separators and dots
- **Local inclusion preference**: for local inclusion, prefer filter-style transforms over destructive payloads; enumerate readable logs and sessions
- **Extraction validation**: validate extraction code with synthetic archives; include symlinks and deep relative chains
- **Minimal proofs**: keep proofs minimal and use hard evidence such as hashes and paths; avoid noisy filesystem abuse

## Summary

Eliminate user-controlled paths where possible. Otherwise, resolve to canonical paths, enforce allowlists, forbid remote schemes, and lock down interpreters and extractors. Normalize consistently at the boundary closest to IO.
