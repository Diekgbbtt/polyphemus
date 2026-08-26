from pathlib import Path

from lightrag_docprep.config import PreprocessorConfig
from lightrag_docprep.parsers.docling import DoclingParser
from lightrag_docprep.parsers.markdown import MarkdownParser
from lightrag_docprep.router import ParserRouter


def test_txt_uses_generic_markdown_parser(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="generic"))
    assert [p.name for p in router.candidates(Path("notes.txt"))] == ["markdown"]
    assert MarkdownParser().supports(Path("notes.txt"))


def test_webp_uses_docling_image_adapter(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path, source_profile="generic"))
    assert [p.name for p in router.candidates(Path("diagram.webp"))] == ["docling"]
    assert DoclingParser().supports(Path("diagram.webp"))


def test_office_formats_use_docling_then_mineru(tmp_path: Path):
    router = ParserRouter(PreprocessorConfig(output_dir=tmp_path))
    for name in ("guide.docx", "slides.pptx", "table.xlsx"):
        assert [p.name for p in router.candidates(Path(name))] == ["docling", "mineru"]
