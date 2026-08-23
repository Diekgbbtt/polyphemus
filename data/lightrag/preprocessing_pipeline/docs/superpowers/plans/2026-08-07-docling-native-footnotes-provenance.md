# Docling Native Footnotes and Page Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Docling-native footnote labels and page-local exports to repair interrupted text conservatively and populate block page provenance.

**Architecture:** Keep full Docling Markdown as canonical content. Carry Docling-only footnote observations in transient parser context, carry per-page Markdown in the existing `page_markdown` field, repair only native-labeled footnotes, and assign page numbers after structural Markdown parsing.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, optional Docling dependency.

## Global Constraints

- No source-specific rules for NIST, OWASP, 0xdf, or other content sources.
- No ontology/entity/relation extraction or semantic rewriting.
- Footnotes are recognized only from Docling native labels.
- Page numbers are best-effort and remain `None` rather than guessed.
- Non-Docling behavior must remain unchanged.

---

### Task 1: Add transient parser context

**Files:**
- Modify: `src/lightrag_docprep/models.py`
- Test: `tests/test_source_metadata.py`

**Interfaces:**
- Produces: `RawParseResult.parser_context: dict[str, Any]`, excluded from model serialization.

- [ ] Write a failing test proving parser context can be read at runtime but is absent from `model_dump()` and JSON.
- [ ] Run the focused test and verify RED.
- [ ] Add the excluded Pydantic field.
- [ ] Run the focused test and verify GREEN.

### Task 2: Capture Docling native footnotes and page views

**Files:**
- Modify: `src/lightrag_docprep/parsers/docling.py`
- Test: `tests/test_docling_native_structure.py`

**Interfaces:**
- Produces: `RawParseResult.parser_context["footnotes"]` as exact source-derived records with `text` and optional `page_number`.
- Produces: `RawParseResult.page_markdown` as one Markdown string per page when Docling exposes pagination.

- [ ] Write failing tests using a fake Docling document for native footnote labels and per-page export calls.
- [ ] Run focused tests and verify RED.
- [ ] Implement extraction without importing Docling types at module import time.
- [ ] Run focused tests and verify GREEN.

### Task 3: Repair native-labeled footnote interruptions

**Files:**
- Modify: `src/lightrag_docprep/postprocessors/docling.py`
- Test: `tests/test_docling_postprocessor.py`

**Interfaces:**
- Consumes: `RawParseResult.parser_context["footnotes"]`.
- Produces: repaired Markdown preserving exact footnote wording.

- [ ] Write failing tests for a lowercase continuation interrupted by multiple native footnotes.
- [ ] Write failing tests proving complete sentences and unlabeled numeric paragraphs are not repaired.
- [ ] Run focused tests and verify RED.
- [ ] Implement block-level exact footnote matching, conservative bridging, and blockquote retention.
- [ ] Run focused tests and verify GREEN.

### Task 4: Assign block page provenance

**Files:**
- Create: `src/lightrag_docprep/page_provenance.py`
- Modify: `src/lightrag_docprep/normalizer.py`
- Test: `tests/test_page_provenance.py`

**Interfaces:**
- Consumes: parsed `SectionNode` objects and `RawParseResult.page_markdown`.
- Produces: `ContentBlock.page_number` populated with the best reliable starting page.

- [ ] Write failing tests for ordered multi-page paragraphs and repeated text with monotonic matching.
- [ ] Write a failing test that unmatched blocks remain `None`.
- [ ] Run focused tests and verify RED.
- [ ] Implement normalized-prefix page matching with a monotonic page cursor.
- [ ] Integrate it into `normalize_parse_result` only when `page_markdown` exists.
- [ ] Run focused tests and verify GREEN.

### Task 5: Version, documentation, and full verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `examples/README.md`

**Interfaces:**
- Produces: package version `0.3.2` and documented Docling behavior.

- [ ] Document native footnote handling and best-effort page provenance.
- [ ] Run `pytest -q` and require zero failures.
- [ ] Run `python -m compileall -q src` and require exit code 0.
- [ ] Run a source scan confirming there are no NIST/OWASP-specific rules in Docling parser/postprocessor modules.
- [ ] Build a separate `lightrag_docprep_v3_2.zip` and verify `unzip -t` succeeds.
