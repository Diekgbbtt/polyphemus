# Source-Aware Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build v3 of `lightrag-docprep` with source-aware WSTG and 0xdf adapters, generic adapters for heterogeneous files, and a unified semantic-free output contract ready for LightRAG.

**Architecture:** Keep format parsing and source-specific structural cleanup in the preprocessor. Add `source_profile` and `native_metadata` to the normalized model; route WSTG and 0xdf through specialized adapters, while PDF/Office/images use MinerU/Docling/PyMuPDF4LLM and generic HTML/Markdown use conservative adapters. No ontology entities, relation briefs, attack-chain synthesis, or semantic rewriting are produced.

**Tech Stack:** Python 3.11+, Pydantic v2, BeautifulSoup4, markdownify, optional Docling, optional PyMuPDF4LLM, external MinerU CLI, pytest/pytest-asyncio.

## Global Constraints

- Preserve source meaning; no semantic rewriting.
- LightRAG owns chunking, entity extraction, relationship extraction, ontology typing, and graph construction.
- Final output per source is exactly `document.md` plus `document.json`.
- `document.md` contains clean source content only; provenance belongs in `document.json`.
- WSTG and 0xdf may use deterministic source-specific structure and metadata only.
- No persistent parser-generated asset directories.
- PDF fallback order remains configurable, defaulting to MinerU → Docling → PyMuPDF4LLM.

---

### Task 1: Extend the normalized contract with source profile and native metadata

**Files:**
- Modify: `src/lightrag_docprep/models.py`
- Modify: `src/lightrag_docprep/normalizer.py`
- Modify: `src/lightrag_docprep/config.py`
- Test: `tests/test_source_metadata.py`

**Interfaces:**
- `RawParseResult.source_profile: str | None`
- `RawParseResult.native_metadata: dict[str, Any]`
- `DocumentModel.source_profile: str | None`
- `DocumentModel.native_metadata: dict[str, Any]`
- `PreprocessorConfig.source_profile: str = "auto"`

- [x] Write failing tests asserting metadata survives normalization and unsupported profiles are rejected.
- [x] Run `python -m pytest tests/test_source_metadata.py -q` and verify RED.
- [x] Implement the fields/config validation minimally.
- [x] Run the focused test and full suite.

### Task 2: Add deterministic WSTG source adapter

**Files:**
- Create: `src/lightrag_docprep/parsers/wstg.py`
- Modify: `src/lightrag_docprep/parsers/__init__.py`
- Test: `tests/test_wstg_parser.py`

**Interfaces:**
- `WstgParser.name == "wstg"`
- Input: `.md` / `.markdown`
- Output metadata keys when observable: `wstg_id`, `wstg_category_code`, `wstg_category`, `wstg_title`
- Output `source_profile="wstg"`

- [x] Write failing tests for WSTG ID/title/category detection and semantic neutrality.
- [x] Verify RED.
- [x] Implement path/content-based metadata extraction while preserving original Markdown wording.
- [x] Verify focused and full suites.

### Task 3: Add 0xdf source adapter with article extraction

**Files:**
- Create: `src/lightrag_docprep/parsers/oxdf.py`
- Create: `src/lightrag_docprep/parsers/html_common.py`
- Modify: `src/lightrag_docprep/parsers/__init__.py`
- Test: `tests/test_oxdf_parser.py`

**Interfaces:**
- `OxdfParser.name == "0xdf"`
- Input: `.html` / `.htm`
- Prefer `<article>`, then `<main>`, then 0xdf content containers.
- Remove site chrome and TOC/tag navigation from ingestion text when identified structurally.
- Preserve preformatted code line breaks.
- Native metadata: `canonical_url`, `publication_date`, `tags`, `source_title`.

- [x] Write failing tests using representative 0xdf HTML with navbar/footer/tags/TOC/code.
- [x] Verify RED.
- [x] Implement main-content selection, metadata extraction, structural HTML→Markdown conversion.
- [x] Verify focused and full suites.

### Task 4: Improve generic HTML without 0xdf assumptions

**Files:**
- Modify: `src/lightrag_docprep/parsers/html.py`
- Reuse: `src/lightrag_docprep/parsers/html_common.py`
- Test: `tests/test_html_parser.py`

**Interfaces:**
- Generic selector priority: `article` → `main` → `[role=main]` → common content container → `body`.
- Remove script/style/noscript/nav/footer and clearly structural asides.
- Preserve headings, tables, lists, links, images/captions and pre/code.
- Output `source_profile="generic"`.

- [x] Write failing tests for main-content extraction and fallback-to-body behavior.
- [x] Verify RED.
- [x] Implement generic structural cleanup only.
- [x] Verify focused and full suites.

### Task 5: Add profile-aware routing and directory-friendly CLI

**Files:**
- Modify: `src/lightrag_docprep/router.py`
- Modify: `src/lightrag_docprep/cli.py`
- Modify: `src/lightrag_docprep/pipeline.py`
- Test: `tests/test_router.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- CLI: `--profile auto|wstg|0xdf|generic`, default `auto`.
- `auto` conservatively identifies WSTG by path/content hints and 0xdf by path/page markers, otherwise generic.
- Directory arguments expand recursively to supported source files.
- Explicit profile overrides auto detection only for compatible formats.

- [x] Write failing routing and CLI tests.
- [x] Verify RED.
- [x] Implement profile-aware routing and deterministic directory expansion.
- [x] Verify focused and full suites.

### Task 6: Consolidate heterogeneous format adapters

**Files:**
- Modify: `src/lightrag_docprep/parsers/docling.py`
- Modify: `src/lightrag_docprep/parsers/mineru.py`
- Modify: `src/lightrag_docprep/router.py`
- Modify: `pyproject.toml`
- Test: `tests/test_multiformat_routing.py`
- Test: `tests/test_native_parsers.py`

**Interfaces:**
- PDF: configurable preferred parser plus MinerU/Docling/PyMuPDF4LLM fallbacks.
- DOCX/PPTX/XLSX: Docling first, MinerU fallback where supported.
- Images: Docling first, MinerU fallback; add WEBP support.
- TXT: generic Markdown/plain-text adapter.
- No parser assets persist outside temporary directories.

- [x] Write failing routing/format tests including WEBP and TXT.
- [x] Verify RED.
- [x] Implement only the required format extensions and metadata defaults.
- [x] Verify focused and full suites.

### Task 7: Enforce semantic-free output and document test workflow

**Files:**
- Modify: `README.md`
- Modify: `src/lightrag_docprep/__init__.py`
- Test: `tests/test_semantic_boundary.py`
- Create: `examples/README.md`

**Interfaces:**
- JSON may contain source-observed native metadata only.
- Output must not introduce keys or generated headings for ontology entities, attack-chain summaries, technique cards, or relation briefs.
- README includes commands for WSTG, 0xdf, PDF, DOCX, PPTX, XLSX, image and generic HTML tests.

- [x] Write failing semantic-boundary regression test against representative WSTG/0xdf inputs.
- [x] Verify RED.
- [x] Update docs/version and ensure output contract is explicit.
- [x] Run full verification: tests, compileall, editable install, CLI smoke tests and ZIP manifest check.
