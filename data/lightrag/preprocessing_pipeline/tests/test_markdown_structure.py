from pathlib import Path

from lightrag_docprep.markdown_structure import parse_markdown_structure
from lightrag_docprep.models import BlockKind, RawParseResult
from lightrag_docprep.normalizer import normalize_parse_result


def test_preserves_heading_paths_and_block_types():
    md = """# SQL Injection

Intro paragraph.

## Detection

- Send a quote
- Compare the response

```http
GET /?id=1'
```

| Input | Result |
| --- | --- |
| quote | error |
"""
    sections = parse_markdown_structure(md)

    assert [s.heading for s in sections] == ["SQL Injection", "Detection"]
    assert sections[1].heading_path == ["SQL Injection", "Detection"]
    assert [b.kind for b in sections[1].blocks] == [
        BlockKind.LIST,
        BlockKind.CODE,
        BlockKind.TABLE,
    ]


def test_preserves_intro_before_first_heading():
    sections = parse_markdown_structure("Intro text.\n\n# Heading\n\nBody")
    assert sections[0].level == 0
    assert sections[0].heading == ""
    assert sections[0].blocks[0].content == "Intro text."


def test_normalizer_derives_stable_document_identity_and_title(tmp_path: Path):
    source = tmp_path / "guide.md"
    source.write_text("ignored", encoding="utf-8")
    raw = RawParseResult(
        parser_name="markdown",
        source_path=str(source),
        markdown="# Guide\r\n\r\nBody\x00  \r\n",
    )

    first = normalize_parse_result(raw, source_type="markdown")
    second = normalize_parse_result(raw, source_type="markdown")

    assert first.doc_id == second.doc_id
    assert len(first.doc_id) == 20
    assert first.title == "Guide"
    assert first.sections[0].blocks[0].content == "Body"



def test_recognizes_single_column_wstg_table():
    md = """# Identify Application Entry Points

|ID          |
|------------|
|WSTG-INFO-06|
"""
    sections = parse_markdown_structure(md)

    assert len(sections[0].blocks) == 1
    assert sections[0].blocks[0].kind == BlockKind.TABLE
    assert sections[0].blocks[0].content == "|ID          |\n|------------|\n|WSTG-INFO-06|"


def test_converts_standalone_image_reference_to_text_without_asset_path():
    md = r"""# Search Operators

![Google Site Operation Search Result Example](images/Google_site_Operator_Search_Results_Example_20200406.png)\ *Figure 4.1.1-1: Google Site Operation Search Result Example*
"""
    sections = parse_markdown_structure(md)

    block = sections[0].blocks[0]
    assert block.kind == BlockKind.IMAGE_TEXT
    assert block.content == "Figure 4.1.1-1: Google Site Operation Search Result Example"
    assert "images/" not in block.content


def test_linked_image_with_following_caption_becomes_single_image_text_block():
    markdown = """# Box Info

[![Principal](/icons/box-principal.png)](https://hackthebox.com/machines/principal)
*Figure 1: Principal machine card*
"""

    sections = parse_markdown_structure(markdown)

    assert len(sections) == 1
    assert len(sections[0].blocks) == 1
    assert sections[0].blocks[0].kind == BlockKind.IMAGE_TEXT
    assert sections[0].blocks[0].content == "Figure 1: Principal machine card"
