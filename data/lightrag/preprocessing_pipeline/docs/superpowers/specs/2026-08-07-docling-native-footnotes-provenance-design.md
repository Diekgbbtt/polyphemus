# Docling Native Footnotes and Page Provenance Design

## Goal

Improve Docling-derived documents without source-specific rules by using Docling's native document structure for two remaining issues: footnotes that interrupt body text and missing page numbers in `ContentBlock` provenance.

## Architecture

The existing Docling Markdown export remains the canonical content representation. We do not rebuild documents from Docling items and we do not add semantic interpretation.

`DoclingParser` additionally captures two transient structural views:

1. Native footnote items identified only by Docling's `FOOTNOTE` label, including their exact text and first available `page_no`.
2. Per-page Markdown exports using Docling's `page_no` export argument.

Transient footnote data is carried in a parser-only context excluded from serialized output. Per-page Markdown uses the existing `RawParseResult.page_markdown` field.

The flow is:

```text
DoclingDocument
  ├─ full export_to_markdown() ───────────────┐
  ├─ iterate_items() -> native FOOTNOTE items │
  └─ export_to_markdown(page_no=N) -> pages   │
                                               ▼
                                      RawParseResult
                                               │
                                      DoclingPostProcessor
                                      ├─ existing cleanup
                                      └─ native footnote repair
                                               │
                                           Normalizer
                                      └─ page-number assignment
                                               │
                                         DocumentModel
```

## Footnote Handling

Footnotes are never detected from numbering patterns such as `1 ...` or `2 ...`. A block is treated as a footnote only when its normalized text matches an item Docling labeled `FOOTNOTE`.

When one or more native footnote blocks occur between two body blocks, the postprocessor may bridge the surrounding text only if all of these conservative conditions hold:

- the previous block is normal paragraph/list text, not a heading, code fence, table, formula, or blockquote;
- the previous visible text does not end in sentence-closing punctuation (`.`, `?`, `!`, `:`, `;`);
- the following body block starts with a lowercase letter or continuation punctuation;
- the footnote run is exactly between those two blocks.

If bridging is safe, the continuation is appended to the preceding body block. The exact footnote text is then retained immediately after the repaired body block as a Markdown blockquote. If bridging is not safe, the exact footnote text remains in the same position, converted only to a blockquote so it is structurally distinguishable.

No footnote content is summarized, rewritten, or discarded.

## Page Provenance

For paginated Docling inputs, the parser exports a Markdown view for each page and stores these views in `RawParseResult.page_markdown`.

After the full Markdown has been parsed into sections and blocks, the normalizer assigns each block a starting page by matching a normalized prefix of the block against page-local Markdown. Matching is monotonic: as blocks progress through the document, page assignment never moves backward. This reduces false matches for repeated short text.

If a block cannot be matched confidently, `page_number` remains `None`. We prefer missing provenance over invented provenance.

The final `document.md` is unchanged by page provenance logic; page data exists only in `document.json`.

## Boundaries

The implementation must not:

- contain NIST, OWASP, 0xdf, or other source-specific rules;
- infer footnotes from numeric patterns when Docling did not label them;
- inject ontology entities, relations, methodology concepts, or semantic metadata;
- rewrite footnote wording;
- guess a page when no reliable page match is found;
- alter non-Docling parser behavior except for generic consumption of `page_markdown` when explicitly provided.

## Testing

Tests cover:

- native Docling `FOOTNOTE` collection;
- conservative repair of an interrupted list item like `service` + `identification`;
- no repair when a sentence is already complete or the next block is not a continuation;
- exact preservation of footnote text;
- monotonic page assignment from per-page Markdown;
- `None` when page matching is ambiguous/unavailable;
- parser-only context excluded from serialized models;
- non-Docling Markdown unaffected;
- full regression suite remains green.
