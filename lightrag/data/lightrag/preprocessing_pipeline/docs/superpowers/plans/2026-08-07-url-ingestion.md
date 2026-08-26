# URL Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `lightrag-docprep "https://..."` fetch, type, parse, normalize, and export a web document with no required flags.

**Architecture:** Add a focused `URLFetcher` that materializes one URL to a typed temporary file and returns structural HTTP provenance. Extend the pipeline with `process_url()` that reuses the existing local-file processing path and then restores URL provenance before normalization/export. Keep all document parsing in the existing router/adapters.

**Tech Stack:** Python 3.11+, httpx, pathlib/tempfile, existing Pydantic document model and parser adapters.

## Global Constraints

- `--output` defaults to `normalized` and remains overridable.
- Only `http` and `https` URLs are accepted.
- Download cap is 50 MiB.
- Detection order is Content-Type -> Content-Disposition -> final URL -> original URL -> conservative signature sniffing.
- Temporary downloads are always deleted.
- No JavaScript rendering, crawling, LightRAG call, or semantic extraction.
- Existing local-file behavior must remain compatible.

---

### Task 1: URL fetching and type detection

**Files:**
- Create: `src/lightrag_docprep/url_fetcher.py`
- Modify: `pyproject.toml`
- Test: `tests/test_url_fetcher.py`

**Interfaces:**
- Produces: `FetchedURLSource(local_path: Path, source_url: str, resolved_url: str, content_type: str | None)`
- Produces: `URLFetcher.fetch(url: str) -> FetchedURLSource` as an async context manager.

- [ ] Write failing tests for supported schemes, MIME detection, Content-Disposition, extension fallback, PDF/HTML signatures, Office ZIP identification, oversize rejection, and temporary-file cleanup.
- [ ] Run `pytest tests/test_url_fetcher.py -q` and verify RED.
- [ ] Implement only the tested acquisition/type-detection behavior with streamed httpx responses.
- [ ] Run `pytest tests/test_url_fetcher.py -q` and verify GREEN.

### Task 2: Pipeline URL processing and provenance

**Files:**
- Modify: `src/lightrag_docprep/pipeline.py`
- Modify: `src/lightrag_docprep/normalizer.py`
- Test: `tests/test_pipeline_url.py`

**Interfaces:**
- Produces: `DocumentPreprocessor.process_url(url: str) -> PreprocessResult`
- `DocumentModel.source_path` is the original URL for URL inputs.
- `native_metadata` contains `source_url`, `resolved_url`, and `http_content_type`.

- [ ] Write failing integration tests using a local HTTP test server for HTML and extensionless PDF responses.
- [ ] Run `pytest tests/test_pipeline_url.py -q` and verify RED.
- [ ] Implement URL processing by feeding the fetched temporary path into the existing router/parser logic and overriding only source identity/provenance before normalization.
- [ ] Run `pytest tests/test_pipeline_url.py -q` and verify GREEN.

### Task 3: Minimal CLI URL UX

**Files:**
- Modify: `src/lightrag_docprep/cli.py`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py`
- Test: `tests/test_semantic_boundary.py`

**Interfaces:**
- `lightrag-docprep <URL>` works with no required flags.
- `--output` defaults to `normalized`.
- Local paths/directories continue to work.

- [ ] Write failing CLI tests for one-argument URL invocation and default output directory.
- [ ] Run focused CLI tests and verify RED.
- [ ] Implement URL/path distinction and default output while preserving existing local behavior.
- [ ] Update README with URL-first usage and advanced overrides.
- [ ] Bump package version to `0.3.4` and align version assertions.
- [ ] Run focused tests and verify GREEN.

### Task 4: Final regression gate

**Files:**
- Test only / packaging.

- [ ] Run `pytest -q` and require zero failures.
- [ ] Run `python -m compileall -q src`.
- [ ] Scan production code for prohibited semantic ontology injection.
- [ ] Run a real HTTP smoke test against one HTML URL and one PDF URL when network access is available; otherwise rely on the local HTTP integration tests and state the limitation.
- [ ] Build `lightrag_docprep_v3_4.zip` and verify archive integrity with `unzip -t`.
