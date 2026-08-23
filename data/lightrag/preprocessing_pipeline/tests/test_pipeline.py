import json
from pathlib import Path

import pytest

from lightrag_docprep.config import PreprocessorConfig
from lightrag_docprep.errors import ParserExecutionError
from lightrag_docprep.models import RawParseResult
from lightrag_docprep.parsers.base import ParserAdapter
from lightrag_docprep.pipeline import DocumentPreprocessor
from lightrag_docprep.router import ParserRouter


class FakeParser(ParserAdapter):
    supported_suffixes = frozenset({".pdf"})

    def __init__(self, name: str, *, markdown: str | None = None, error: str | None = None):
        self.name = name
        self._markdown = markdown
        self._error = error

    def is_available(self) -> bool:
        return True

    async def parse(self, path: Path) -> RawParseResult:
        if self._error:
            raise ParserExecutionError(self._error)
        return RawParseResult(
            parser_name=self.name,
            source_path=str(path),
            markdown=self._markdown or "",
        )


@pytest.mark.asyncio
async def test_pipeline_falls_back_and_records_warning(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    config = PreprocessorConfig(output_dir=tmp_path / "out")
    router = ParserRouter(
        config,
        parsers=[
            FakeParser("mineru", error="boom"),
            FakeParser("docling", markdown="# Parsed\n\nBody"),
            FakeParser("pymupdf4llm", markdown="# Last"),
        ],
    )
    pipeline = DocumentPreprocessor(config, router=router)

    result = await pipeline.process(source)

    assert result.success is True
    assert result.output_dir is not None
    assert any("mineru failed" in warning.lower() for warning in result.warnings)
    md = (result.output_dir / "document.md").read_text(encoding="utf-8")
    payload = json.loads((result.output_dir / "document.json").read_text(encoding="utf-8"))
    assert "parser_engine:" not in md
    assert payload["parser_engine"] == "docling"
    assert "# Parsed" in md


@pytest.mark.asyncio
async def test_process_many_isolates_document_failure(tmp_path: Path):
    good = tmp_path / "good.pdf"
    bad = tmp_path / "bad.pdf"
    good.write_bytes(b"pdf")
    bad.write_bytes(b"pdf")

    class ConditionalParser(FakeParser):
        async def parse(self, path: Path) -> RawParseResult:
            if path.name == "bad.pdf":
                raise ParserExecutionError("broken")
            return RawParseResult(parser_name=self.name, source_path=str(path), markdown="# Good\n\nBody")

    config = PreprocessorConfig(output_dir=tmp_path / "out", max_concurrency=2)
    router = ParserRouter(config, parsers=[ConditionalParser("mineru", markdown="# ignored")])
    pipeline = DocumentPreprocessor(config, router=router)

    results = await pipeline.process_many([good, bad])

    assert [result.success for result in results] == [True, False]
    assert results[0].output_dir is not None
    assert results[1].output_dir is None
    assert "broken" in (results[1].error or "")


@pytest.mark.asyncio
async def test_pipeline_applies_docling_postprocessing_only_to_docling(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    markdown = (
        "# Report\n\n<!-- image -->\n\n"
        "## Table of Contents\n\nNoise\n\n"
        "## 1. Introduction\n\nBody\n\n"
        "## 1.1 Scope\n\nScope body\n"
    )
    config = PreprocessorConfig(output_dir=tmp_path / "out")
    router = ParserRouter(config, parsers=[FakeParser("docling", markdown=markdown)])

    result = await DocumentPreprocessor(config, router=router).process(source)

    assert result.success is True
    md = (result.output_dir / "document.md").read_text(encoding="utf-8")
    assert "<!-- image -->" not in md
    assert "Table of Contents" not in md
    assert "Noise" not in md
    assert "## 1. Introduction" in md
    assert "### 1.1 Scope" in md


@pytest.mark.asyncio
async def test_pipeline_does_not_apply_docling_postprocessing_to_other_parsers(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    markdown = "# Report\n\n<!-- image -->\n\n## Table of Contents\n\nKeep this.\n"
    config = PreprocessorConfig(output_dir=tmp_path / "out")
    router = ParserRouter(config, parsers=[FakeParser("mineru", markdown=markdown)])

    result = await DocumentPreprocessor(config, router=router).process(source)

    assert result.success is True
    md = (result.output_dir / "document.md").read_text(encoding="utf-8")
    assert "<!-- image -->" in md
    assert "## Table of Contents" in md
    assert "Keep this." in md
