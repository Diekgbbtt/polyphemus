---
name: js-sourcemap-recovery
description: >-
  Recover and inventory original sources associated with an acquired JavaScript lead through a source map, preserving resumable Kali files and provenance.
metadata:
  version: '1.0'
---

Read `reference js-sourcemap-recovery commands` through the supplied Exec CLI prefix.

1. Start after a lead has an acquired/verified JavaScript file, including when
   its baseline scan failed or was partial. Run `recover <lead_id>` once.
   Recovery checks the exact acquired SHA-256, finds
   the declared `SourceMap` header or real sourceMappingURL annotation first,
   and tries at most one conservative guessed companion when no declaration
   exists. Never supply a URL or local path.
2. Treat map-not-found, authentication loss, redirect/scope rejection, invalid
   JSON, parser limits, partial source count and transfer failure as named
   gaps. Inline base64 and URL-encoded maps are local input; no terminal
   credentials or browser cookies are inherited by Kali.
3. Read the result index with `recovered-sources <lead_id> --limit 5
   [--cursor <next_cursor>]`. Every row is an occurrence: the same source name
   in different sections is distinct. Empty content is a valid zero-byte
   source; null and missing content are unavailable states, not empty code.
4. Use `recovered-source <source_id>` only for metadata and provenance. This
   task deliberately has no source-body read command. Do not infer behaviour,
   execution, language validity or retention value from a filename or type.
5. On interruption, rerun `recover <lead_id>`: verified files and stable
   source IDs are reused; incomplete files are replaced only after size/hash
   verification. Do not delete recovered work files at command end.
6. Record map/source counts, gaps, pagination cursor and useful source IDs in
   notes. Distinguish declared map links from guessed links and browser-requested
   discovery from execution.
7. Load `js-bundle-structure` for the same acquired generated file regardless
   of map availability. `map_not_found` or another recovery gap is recorded for
   that lead but does not end the acquisition/structure workflow. After
   structure records its outcome, `js-bundle-structure` hands the same file to
   `js-evidence-triage` for bounded searches, selected reads and typed
   shortlist state. After triage records its outcome, continue to the next selected
   lead. Once the bounded batch is covered, stop at the shortlist and
   write the shared resumable summary; behavioural reconstruction, formatting
   and final publication are later tasks.
