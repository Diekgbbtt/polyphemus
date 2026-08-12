# Docling Page-Break List Repair Design

## Goal
Repair list items that Docling splits into a list block followed by a paragraph when the item crosses a PDF page boundary, without source-specific rules or semantic rewriting.

## Scope
- Applies only to `parser_name == "docling"` through the existing Docling postprocessor.
- Uses Docling `page_markdown` provenance already captured in v3.2.
- Does not inspect NIST/OWASP/source names.
- Does not merge arbitrary paragraphs or lists.

## Conservative repair rule
A list block may absorb the immediately following paragraph only when all are true:
1. the list block ends with an unfinished list item (last character is not `.?!:;`);
2. the following block is a plain paragraph, not heading/table/code/formula/blockquote/list;
3. the following paragraph begins with lowercase text or continuation punctuation;
4. provenance can place the list block on page N and the following paragraph on page N+1;
5. both blocks remain in the same Markdown section (no heading between them).

The merged text preserves the original list marker and appends the continuation with a single space. If any condition is uncertain, no merge occurs.

## Interaction with existing footnote repair
Footnote repair runs first. Page-break list repair runs after footnotes are moved/bridged, so native footnote blocks cannot be accidentally swallowed into list text.

## Testing
Regression tests cover: successful page-boundary list repair, no merge on same page, no merge after complete sentence, no merge for uppercase paragraph, no merge across headings, and preservation of fenced code/list formatting.
