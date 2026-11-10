---
name: js-bundle-structure
description: >-
  Index verified generated JavaScript into bounded import, module, dependency, chunk and loader facts and explicitly acquire selected supported references through Exec.
metadata:
  version: '1.0'
---

Read `reference js-bundle-structure commands` through the supplied Exec CLI prefix before the first index operation.

1. Start for each acquired, integrity-verified generated JavaScript file after
   baseline scan and source-map recovery attempts. A failed/partial scan or
   `map_not_found` does not block structure. Run `structure <lead_id>` once
   within the batch budget. Reuse is valid only for the same verified source
   hash, parser identity and adapter configuration; an unavailable/tampered Kali
   file is a named input failure, not a successful cached index.
2. Read the result as compact evidence: index ID, format, `complete`, `partial`,
   `unsupported` or `failed`, per-kind counts, parser gaps and whether the input
   was current or historical. `complete` means the supported indexing procedure
   finished; it does not mean every runtime value or bundler shape is understood.
3. Navigate with `structure-items <lead_id> --kind import|module|dependency|chunk|loader --limit 5`.
   Follow `next_cursor` within the runner budget. Read only selected entries with
   `structure-item <item_id>`. Exact specifiers, loader expressions, source
   bodies and target URLs are private to the broker.
4. Distinguish imports from module registrations, runtime-state IDs, chunk IDs,
   resolved dependencies, ambiguous destinations and unresolved expressions.
   Do not infer a module's runtime execution order or invent a URL from an ID,
   filename pattern or loader expression.
5. Do not acquire a child merely to finish indexing. Only after triage has a
   concrete selected question that needs a supported literal child run
   `acquire-reference <item_id>`. Relative ESM references use the parent final
   URL; bare imports need applicable import-map evidence; dynamic or runtime-webpack
   references stay unresolved. This action goes through the existing broker and
   returns a normal code-derived child lead or an explicit auth/scope/quota gap.
   Acquiring one child does not recursively acquire, scan, recover, index or
   schedule its descendants. Return to evidence triage after acquiring it.
6. Persist index IDs, format/status, kind counts, inspected item IDs,
   ambiguity/unresolved gaps, any child lead ID and deferred work in notes.
7. Load `js-evidence-triage` for the same acquired generated file even after a
   partial, unsupported or failed structure attempt. Recovered sources and
   literal search may still provide readable evidence while the structural
   fact is absent. Continue with the next selected lead only after triage
   records its selected spans or explicit deferrals. No AST dump, source-body
   read without the controlled read command, behavioural claim or graph
   publication belongs to this skill.
