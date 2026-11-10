# Source-map recovery commands

```text
<prefix> recover <lead_id>
<prefix> recovered-sources <lead_id> --limit 5
<prefix> recovered-sources <lead_id> --limit 5 --cursor <next_cursor>
<prefix> recovered-source <source_id>
<prefix> note --text 'Recovered <count> sources for <lead>; gaps <reasons>; pending <IDs>'
```

After each acquired lead, record the recovery outcome and continue to the next
selected lead. `map_not_found` is a named result for that lead, not a reason to
stop processing the rest of the batch.

`recover` reads the manifest-authorized JavaScript bytes in Kali, sends them
privately to the agent-owned broker, resolves the source-map link and transfers
each recovered source back through opaque artifact routes. Ordinary output
contains only counts, IDs, hashes, sizes and gaps. No source body is printed.

Map references come from the private `SourceMap`/`X-SourceMap` response headers
or a real sourceMappingURL comment. Header wins; conflicting annotations are a
gap. A relative map URL resolves against the final JavaScript response URL and
keeps its query. A single `<final-js>.map` companion may be guessed only when no
declared link exists.

The recovered index is occurrence-based:

- `source_id` binds lead/context/map/section/source ordinal;
- identical bytes share a physical Kali file without merging provenance;
- `content_state` is `text`, `empty`, `null` or `missing`;
- `work_file_ref` is a temporary `/work/js-analysis/<run>/recovered/<sha>.js`
  file, not a permanent blob;
- pagination uses the returned `next_cursor`.

Never use a recovered source filename as a local filesystem path. Missing or
tampered Kali files make `recover` verify/refetch only through the scoped
broker. A completed recovery command does not authorize deletion, scanning or
retention decisions.
