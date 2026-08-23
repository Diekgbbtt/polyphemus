from types import SimpleNamespace
from pathlib import Path

import pytest

from lightrag_docprep.parsers import docling as docling_module
from lightrag_docprep.parsers.docling import DoclingParser


class FakeDocument:
    def __init__(self):
        self._pages = {
            1: "# Report\n\nFirst page body",
            2: "## Section\n\nSecond page body",
        }
        self._items = [
            SimpleNamespace(
                label=SimpleNamespace(value="text"),
                text="First page body",
                prov=[SimpleNamespace(page_no=1)],
            ),
            SimpleNamespace(
                label=SimpleNamespace(value="footnote"),
                text="2 Exact reference text",
                prov=[SimpleNamespace(page_no=2)],
            ),
        ]

    def num_pages(self):
        return 2

    def export_to_markdown(self, *, page_no=None):
        if page_no is None:
            return "# Report\n\nFirst page body\n\n2 Exact reference text\n\n## Section\n\nSecond page body"
        return self._pages[page_no]

    def iterate_items(self):
        for item in self._items:
            yield item, 0


def test_collects_only_native_docling_footnotes_and_page_views():
    document = FakeDocument()

    page_markdown, parser_context = docling_module._collect_native_structure(document)

    assert page_markdown == [
        "# Report\n\nFirst page body",
        "## Section\n\nSecond page body",
    ]
    assert parser_context == {
        "footnotes": [{"text": "2 Exact reference text", "page_number": 2}]
    }


@pytest.mark.asyncio
async def test_parse_carries_native_structure_into_raw_result(monkeypatch, tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    parser = DoclingParser()
    monkeypatch.setattr(parser, "is_available", lambda: True)
    monkeypatch.setattr(
        parser,
        "_convert",
        lambda path: (
            "# Report\n\nBody",
            ["# Report\n\nBody"],
            {"footnotes": [{"text": "1 Ref", "page_number": 1}]},
        ),
    )

    raw = await parser.parse(source)

    assert raw.markdown == "# Report\n\nBody"
    assert raw.page_markdown == ["# Report\n\nBody"]
    assert raw.parser_context["footnotes"] == [{"text": "1 Ref", "page_number": 1}]
