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

Applies where user influence reaches an archive extractor that resolves entry names into write locations.
Applies where entry normalization, link handling, and destination binding decide the final write path.
Varies only in which extractor consumes the input and which location oracle proves the outside write.

## Reconnaissance

Inventory archive importers across uploads, conversion pipelines, and background jobs.
Record supported archive shapes and the extract destination bound to each importer.
Probe entry-name handling with traversal-segment shapes, rooted-name shapes, and link shapes.
Record canonicalization timing relative to the write to expose check-versus-write gaps.
Complete the survey when every importer has a recorded destination binding and a recorded entry-handling response.

## Detection Channels

Outside-write evidence where post-extract listings reveal files beyond the destination for a crafted archive shape.
Follow-up read evidence where a subsequent read retrieves content from the outside location.
Error echo where extractor warnings expose canonicalized entry paths for a crafted archive shape.

## Adversarial Capabilities

Supply archives with traversal entries and link entries without control over server code or extractor policy.
Control entry names, nesting depth, and link targets across synthetic archives.
Observe post-extract listings and follow-up reads to locate writes outside the destination.
Correlate each synthetic archive with its extraction outcome to attribute outside writes precisely.

## Trust Assumptions

When the file-operation feature executes, the server trusts that carrier-supplied names join a base location under a normalization contract.
The server trusts that resolution states settle inside one intended root before any read occurs.
The server trusts that request primitives read only what the join permits and that exposed readers stay unreachable to crafted names.
The server trusts that sensitive file content never leaks to the sender through crafted resolution.
That trust fails at the extraction-containment clause: archive entries extract outside the destination and write outside files.

## Key Vulnerabilities

Traversal-entry shapes that ascend past the destination through relative segments, held as <entry-shape>.
Rooted-entry shapes that discard the destination by supplying absolute names.
Link shapes that redirect subsequent writes outside the destination through alias targets.
Canonicalization gaps where sanitization resolves before link expansion or after the write decision.
The delta over the parent is extract-then-locate proof with synthetic archives and outside-write location, which the parent escalation step never names.

## Advanced Techniques

Craft synthetic archives that isolate one entry behavior per archive for clean attribution.
Layer traversal segments with deep nesting to test recursive canonicalization completeness.
Exercise link handling by pairing alias entries with follow-on writes that resolve through the alias.
Confirm outside writes with both listings and follow-up reads before declaring extraction crossed.

## Bypass Techniques

Defeat entry sanitizers with encoded traversal spellings held as <entry-shape>.
Defeat destination binding with rooted names that discard the bound destination.
Defeat link policy by introducing alias entries that resolve outside after the check completes.
Defeat format assumptions by repeating traversal entries across each supported archive shape.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Carry outside writes into configuration overwrite and template replacement for persistence.
Carry served-directory writes into follow-on execution through the local inclusion companion.
Name the local inclusion companion at the write-to-execution step rather than restating its procedure here.

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

Exclude extractors that canonicalize entries and enforce destination binding before any write occurs.
Exclude virtualized extraction that materializes content into safe stores without filesystem writes.
Exclude listings whose outside files trace to concurrent activity rather than the crafted archive.

## Pro Tips

Isolate one entry behavior per archive to keep attribution exact.
Include link entries and deep nesting to test canonicalization completeness.
Prefer listings plus follow-up reads over either signal alone for location proof.
Record entry names with extraction outcomes as hard evidence for every confirmed write.

## Summary

Confirm extraction escape with synthetic traversal and link archives backed by listing and follow-up read proof.
Canonicalize every entry, enforce destination binding before writes, and resolve links inside the destination at the input-output boundary.
