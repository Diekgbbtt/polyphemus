---
name: archive-zipslip-write
description: Write outside extract destinations through crafted archive entries. Use when upload pipelines accept archive content, when entry names control extract locations, when listings confirm outside writes.
metadata:
  version: 1.0.0
---

# Archive Zipslip Write

Prove that crafted archive entries resolve outside their extract destination and produce outside writes.
Treat every entry name as untrusted until synthetic extraction with outside-write location confirms containment.

## Attack Surface

- **Applicability**: user influence reaches an archive extractor that resolves entry names into write locations.
- **Path-resolution controls**: entry normalization, link handling, and destination binding decide the final write path.
- **Extractor variance**: the only variation is which extractor consumes the input and which location oracle proves the outside write.

## Reconnaissance

- **Importer inventory**: inventory archive importers across uploads, conversion pipelines, and background jobs.
- **Destination binding**: record supported archive shapes and the extract destination bound to each importer.
- **Entry-name probing**: probe entry-name handling with traversal-segment shapes, rooted-name shapes, and link shapes.
- **Canonicalization timing**: record canonicalization timing relative to the write to expose check-versus-write gaps.
- **Survey completion**: complete the survey when every importer has a recorded destination binding and a recorded entry-handling response.

## Detection Channels

- **Outside-write evidence**: post-extract listings reveal files beyond the destination for a crafted archive shape.
- **Follow-up read evidence**: a subsequent read retrieves content from the outside location.
- **Error echo**: extractor warnings expose canonicalized entry paths for a crafted archive shape.

## Adversarial Capabilities

- **Archive supply**: supply archives with traversal entries and link entries without control over server code or extractor policy.
- **Entry-name control**: control entry names, nesting depth, and link targets across synthetic archives.
- **Listing observation**: observe post-extract listings and follow-up reads to locate writes outside the destination.
- **Outcome correlation**: correlate each synthetic archive with its extraction outcome to attribute outside writes precisely.

## Trust Assumptions

- **The agreement**: the server trusts, when the file-operation feature executes, that carrier-supplied names join a base location under a normalization contract, that resolution states settle inside one intended root before any read occurs, that request primitives read only what the join permits and exposed readers stay unreachable to crafted names, and that sensitive file content never leaks to the sender through crafted resolution.
- **The failing clause**: archive entries extract outside the destination and write outside files.

## Key Vulnerabilities

- **Traversal-entry shapes**: ascend past the destination through relative segments, held as <entry-shape>.
- **Rooted-entry shapes**: discard the destination by supplying absolute names.
- **Link shapes**: redirect subsequent writes outside the destination through alias targets.
- **Format-dependent link handling**: where one format stores links as first-class entries while another drops or sanitises them, so repeat the link test across every supported format before closing the link path.
- **Canonicalization gaps**: sanitization resolves before link expansion or after the write decision.
- **Variant delta**: the delta over the parent is extract-then-locate proof with synthetic archives and outside-write location, which the parent escalation step never names.

## Advanced Techniques

- **Attribution isolation**: craft synthetic archives that isolate one entry behavior per archive for clean attribution.
- **Recursive completeness**: layer traversal segments with deep nesting to test recursive canonicalization completeness.
- **Link handling**: exercise link handling by pairing alias entries with follow-on writes that resolve through the alias.
- **Crossing confirmation**: confirm outside writes with both listings and follow-up reads before declaring extraction crossed.

## Bypass Techniques

- **Sanitizer defeat**: defeat entry sanitizers with encoded traversal spellings held as <entry-shape>.
- **Destination-binding defeat**: defeat destination binding with rooted names that discard the bound destination.
- **Link-policy defeat**: defeat link policy by introducing alias entries that resolve outside after the check completes.
- **Format-assumption defeat**: defeat format assumptions by repeating traversal entries across each supported archive shape.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Persistence writes**: carry outside writes into configuration overwrite and template replacement for persistence.
- **Served-directory writes**: carry served-directory writes into follow-on execution through the local inclusion companion.
- **Companion-skill reference**: name the local inclusion companion at the write-to-execution step rather than restating its procedure here.

## Testing Methodology

1. Inventory archive importers and record each extract destination binding.
Complete when every importer has a recorded destination binding with no unvisited extraction surface remaining.
2. Craft synthetic archives with traversal entries, rooted names, and link shapes, one behavior per archive.
Complete when every entry behavior has a dedicated synthetic archive with recorded entry names.
3. Extract each synthetic archive and record canonicalization behavior and warning output.
Complete when every synthetic archive has a recorded extraction outcome with warnings preserved.
4. Bent step: craft synthetic archives with traversal entries and symlinks and locate outside writes after extraction.
Complete when every synthetic archive has a recorded listing verdict paired with a recorded follow-up read verdict.

## False Positives

- **Canonicalizing extractors**: exclude extractors that canonicalize entries and enforce destination binding before any write occurs.
- **Virtualized extraction**: exclude virtualized extraction that materializes content into safe stores without filesystem writes.
- **Concurrent listings**: exclude listings whose outside files trace to concurrent activity rather than the crafted archive.

## Pro Tips

- **One behavior per archive**: isolate one entry behavior per archive to keep attribution exact.
- **Link and nesting coverage**: include link entries and deep nesting to test canonicalization completeness.
- **Dual-signal proof**: prefer listings plus follow-up reads over either signal alone for location proof.
- **Evidence recording**: record entry names with extraction outcomes as hard evidence for every confirmed write.

## Summary

Confirm extraction escape with synthetic traversal and link archives backed by listing and follow-up read proof.
Canonicalize every entry, enforce destination binding before writes, and resolve links inside the destination at the input-output boundary.
