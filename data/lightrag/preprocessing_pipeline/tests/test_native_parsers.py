from pathlib import Path

import pytest

from lightrag_docprep.parsers.html import HtmlParser
from lightrag_docprep.parsers.markdown import MarkdownParser


@pytest.mark.asyncio
async def test_markdown_parser_preserves_source_and_strips_front_matter(tmp_path: Path):
    path = tmp_path / "guide.md"
    path.write_text("---\ntitle: Old\n---\n# Guide\n\nText", encoding="utf-8")

    raw = await MarkdownParser().parse(path)

    assert raw.parser_name == "markdown"
    assert raw.markdown == "# Guide\n\nText"


@pytest.mark.asyncio
async def test_html_parser_converts_structure_and_drops_script(tmp_path: Path):
    path = tmp_path / "guide.html"
    path.write_text(
        "<h1>Guide</h1><p>Text</p><ul><li>A</li></ul><script>alert(1)</script>",
        encoding="utf-8",
    )

    raw = await HtmlParser().parse(path)

    assert raw.parser_name == "html"
    assert "# Guide" in raw.markdown
    assert "Text" in raw.markdown
    assert "A" in raw.markdown
    assert "alert(1)" not in raw.markdown

from lightrag_docprep.errors import ParserUnavailableError
from lightrag_docprep.parsers.docling import DoclingParser
from lightrag_docprep.parsers.mineru import MinerUParser
from lightrag_docprep.parsers.pymupdf4llm import PyMuPDF4LLMParser


def test_docling_reports_unavailable_when_module_missing(monkeypatch):
    monkeypatch.setattr("lightrag_docprep.parsers.docling.find_spec", lambda _: None)
    assert DoclingParser().is_available() is False


@pytest.mark.asyncio
async def test_docling_parse_rejects_when_unavailable(monkeypatch, tmp_path: Path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"pdf")
    parser = DoclingParser()
    monkeypatch.setattr(parser, "is_available", lambda: False)
    with pytest.raises(ParserUnavailableError):
        await parser.parse(path)


def test_pymupdf_reports_unavailable_when_module_missing(monkeypatch):
    monkeypatch.setattr("lightrag_docprep.parsers.pymupdf4llm.find_spec", lambda _: None)
    assert PyMuPDF4LLMParser().is_available() is False


def test_mineru_reports_unavailable_when_command_missing(monkeypatch):
    monkeypatch.setattr("lightrag_docprep.parsers.mineru.shutil.which", lambda _: None)
    assert MinerUParser().is_available() is False


@pytest.mark.asyncio
async def test_mineru_consumes_markdown_and_discards_auxiliary_output(monkeypatch, tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "mineru"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "args=sys.argv\n"
        "src=pathlib.Path(args[args.index('-p')+1])\n"
        "out=pathlib.Path(args[args.index('-o')+1])/'nested'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out/(src.stem+'.md')).write_text('# Parsed\\n\\nBody')\n"
        "(out/'debug.json').write_text('{}')\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    old_path = __import__("os").environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{bin_dir}:{old_path}")

    raw = await MinerUParser().parse(source)

    assert raw.parser_name == "mineru"
    assert raw.source_profile == "generic"
    assert raw.markdown == "# Parsed\n\nBody"


@pytest.mark.asyncio
async def test_plain_text_is_accepted_as_generic_source(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("Plain technical notes\nsecond line", encoding="utf-8")

    raw = await MarkdownParser().parse(path)

    assert raw.source_profile == "generic"
    assert raw.markdown == "Plain technical notes\nsecond line"
