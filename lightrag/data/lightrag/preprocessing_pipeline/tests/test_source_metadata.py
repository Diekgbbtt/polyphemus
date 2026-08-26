from pathlib import Path
import json

import pytest

from lightrag_docprep.config import PreprocessorConfig
from lightrag_docprep.models import RawParseResult
from lightrag_docprep.normalizer import normalize_parse_result


def test_source_profile_and_native_metadata_survive_normalization(tmp_path: Path):
    source = tmp_path / "source.md"
    source.write_text("# Title\n\nBody", encoding="utf-8")
    raw = RawParseResult(
        parser_name="example",
        source_path=str(source),
        source_profile="wstg",
        native_metadata={"wstg_id": "WSTG-INFO-01"},
        markdown="# Title\n\nBody",
    )

    document = normalize_parse_result(raw, source_type="markdown")

    assert document.source_profile == "wstg"
    assert document.native_metadata == {"wstg_id": "WSTG-INFO-01"}


def test_preprocessor_config_rejects_unknown_source_profile(tmp_path: Path):
    with pytest.raises(ValueError, match="source_profile"):
        PreprocessorConfig(output_dir=tmp_path, source_profile="unknown")


def test_parser_context_is_transient_and_not_serialized(tmp_path: Path):
    raw = RawParseResult(
        parser_name="docling",
        source_path=str(tmp_path / "sample.pdf"),
        markdown="# Title\n\nBody",
        parser_context={"footnotes": [{"text": "1 Reference", "page_number": 2}]},
    )

    assert raw.parser_context["footnotes"][0]["page_number"] == 2
    assert "parser_context" not in raw.model_dump()
    assert "parser_context" not in json.loads(raw.model_dump_json())


def test_page_markdown_populates_block_page_numbers_during_normalization(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    raw = RawParseResult(
        parser_name="docling",
        source_path=str(source),
        markdown=(
            "## Section\n\n"
            "First distinctive paragraph belongs to page one.\n\n"
            "Second distinctive paragraph belongs to page two.\n"
        ),
        page_markdown=[
            "## Section\n\nFirst distinctive paragraph belongs to page one.",
            "Second distinctive paragraph belongs to page two.",
        ],
    )

    document = normalize_parse_result(raw, source_type="pdf")
    blocks = [block for section in document.sections for block in section.blocks]

    assert [block.page_number for block in blocks] == [1, 2]
