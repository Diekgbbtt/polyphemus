# Docling Page-Break List Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair Docling list items split by a PDF page break while refusing ambiguous merges.

**Architecture:** Extend the existing Docling postprocessor with one conservative block-level pass. The pass derives page membership from `raw.page_markdown` using the same matching philosophy as page provenance and only joins adjacent list/paragraph blocks across exactly one page boundary.

**Tech Stack:** Python 3.12+, pytest, Pydantic, existing Docling adapter/postprocessor.

## Global Constraints
- Docling-specific only.
- No NIST/OWASP/source-specific rules.
- No ontology or semantic extraction.
- Preserve content; only remove the artificial page-break split.
- Ambiguous provenance means no merge.

---

### Task 1: Page-break list continuation repair

**Files:**
- Modify: `src/lightrag_docprep/postprocessors/docling.py`
- Test: `tests/test_docling_postprocessor.py`

**Interfaces:**
- Consumes: `RawParseResult.markdown`, `RawParseResult.page_markdown`
- Produces: repaired `RawParseResult.markdown` through `postprocess_docling_result(raw)`

- [ ] **Step 1: Add failing regression tests**

Add tests for a list block on page N followed by a lowercase paragraph on page N+1, plus negative cases for same-page continuation, punctuation-complete list, uppercase paragraph, and heading boundary.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest -q tests/test_docling_postprocessor.py`
Expected: new page-break list test fails because the blocks remain separated.

- [ ] **Step 3: Implement the minimal Docling-specific repair**

Add helpers that identify Markdown blocks, find conservative page matches from `page_markdown`, and merge only an adjacent LIST -> PARAGRAPH pair across N -> N+1 when the continuation signal is safe.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest -q tests/test_docling_postprocessor.py`
Expected: all focused tests pass.

- [ ] **Step 5: Run the complete suite**

Run: `pytest -q`
Expected: zero failures.
