# Docling Structural Postprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a Docling-specific structural cleanup stage that removes parser artifacts and normalizes document structure without adding semantic interpretation.

**Architecture:** Introduce a dedicated `postprocessors/docling.py` module that accepts a `RawParseResult` produced by Docling and returns a copied result with cleaned Markdown. Apply it in the pipeline only when `raw.parser_name == "docling"`, before the generic normalizer builds the `DocumentModel`.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest.

## Global Constraints

- Cleanup is Docling-specific, never NIST-specific or source-specific.
- No ontology application, entity extraction, relationship extraction, semantic classification, or semantic rewriting.
- Preserve source text except for structural Docling artifacts explicitly covered by tests.
- Do not attempt footnote repair in this change.
- Do not claim page provenance unless Docling provides it through the existing adapter contract.

---

### Task 1: Docling postprocessor

**Files:**
- Create: `src/lightrag_docprep/postprocessors/__init__.py`
- Create: `src/lightrag_docprep/postprocessors/docling.py`
- Test: `tests/test_docling_postprocessor.py`

**Interfaces:**
- Consumes: `RawParseResult`
- Produces: `postprocess_docling_result(raw: RawParseResult) -> RawParseResult`

- [x] Add failing tests that require exact `<!-- image -->` placeholders to be removed while preserving meaningful captions.
- [x] Add failing tests that require `Table of Contents`, `Contents`, and `List of Contents` heading sections to be removed through the next heading of equal or higher level.
- [x] Add failing tests that require numbered headings to inherit hierarchy from their numeric depth, anchored to the existing top-level numbered heading level.
- [x] Implement the minimal line-oriented Markdown cleanup to satisfy those tests.
- [x] Run `python -m pytest tests/test_docling_postprocessor.py -q` and verify it passes.

### Task 2: Pipeline integration

**Files:**
- Modify: `src/lightrag_docprep/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: successful parser `RawParseResult`
- Produces: Docling output postprocessed before `normalize_parse_result`; all other parser outputs unchanged.

- [x] Add a failing pipeline test proving cleanup runs for parser name `docling`.
- [x] Add a failing pipeline test proving equivalent Markdown from `mineru` is not passed through the Docling cleanup.
- [x] Call `postprocess_docling_result()` only for `raw.parser_name == "docling"`.
- [x] Run targeted pipeline tests and then the full suite.

### Task 3: Package documentation and release artifact

**Files:**
- Modify: `README.md`
- Modify: `examples/README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces package version `0.3.1` and documentation of the Docling-only cleanup behavior.

- [x] Document the Docling postprocessing boundary and explicitly state that footnotes/page provenance remain unchanged.
- [x] Bump package version to `0.3.1`.
- [x] Run `python -m compileall -q src` and `python -m pytest -q`.
- [x] Build a ZIP of the isolated package for user testing.
