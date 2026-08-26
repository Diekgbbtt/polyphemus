from pathlib import Path

import pytest

from lightrag_docprep.config import PreprocessorConfig
from lightrag_docprep.errors import UnsupportedSourceError
from lightrag_docprep.router import ParserRouter


def test_pdf_default_chain_prefers_mineru(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path))
    assert [p.name for p in router.candidates(Path("paper.pdf"))] == [
        "mineru",
        "docling",
        "pymupdf4llm",
    ]


def test_filename_hint_overrides_first_parser(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path))
    assert [p.name for p in router.candidates(Path("paper.[docling].pdf"))] == [
        "docling",
        "mineru",
        "pymupdf4llm",
    ]


def test_html_uses_lightweight_parser_before_docling(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path))
    assert [p.name for p in router.candidates(Path("guide.html"))] == ["html", "docling"]


def test_unsupported_source_raises(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path))
    with pytest.raises(UnsupportedSourceError):
        router.candidates(Path("archive.zip"))


def test_explicit_wstg_profile_uses_wstg_adapter_first(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="wstg"))
    assert [p.name for p in router.candidates(Path("scenario.md"))][:2] == ["wstg", "markdown"]


def test_explicit_0xdf_profile_uses_0xdf_adapter_first(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="0xdf"))
    assert [p.name for p in router.candidates(Path("writeup.html"))][:2] == ["0xdf", "html"]


def test_auto_profile_detects_wstg_from_path(tmp_path: Path):
    path = tmp_path / "wstg_raw" / "07-Input_Validation_Testing" / "05-SQL_Injection.md"
    path.parent.mkdir(parents=True)
    path.write_text("# SQL Injection\n\n|ID|\n|---|\n|WSTG-INPV-05|", encoding="utf-8")
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="auto"))
    assert router.candidates(path)[0].name == "wstg"


def test_auto_profile_detects_0xdf_from_path(tmp_path: Path):
    path = tmp_path / "0xdf" / "2024-01-01-htb-test.html"
    path.parent.mkdir(parents=True)
    path.write_text("<html><title>HTB: Test | 0xdf hacks stuff</title></html>", encoding="utf-8")
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="auto"))
    assert router.candidates(path)[0].name == "0xdf"


def test_generic_profile_disables_source_specific_adapters(tmp_path: Path):
    md_router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="generic"))
    html_router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="generic"))
    assert md_router.candidates(Path("scenario.md"))[0].name == "markdown"
    assert html_router.candidates(Path("writeup.html"))[0].name == "html"
