import json
from datetime import datetime, timezone
from pathlib import Path

from lightrag_docprep.exporters import export_document, render_markdown
from lightrag_docprep.models import BlockKind, ContentBlock, DocumentModel, SectionNode


def sample_document() -> DocumentModel:
    return DocumentModel(
        doc_id="abc123",
        title="SQL Injection",
        source_path="source.md",
        source_type="markdown",
        parser_engine="markdown",
        processed_at=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
        sections=[
            SectionNode(
                section_id="section-0000-sql-injection",
                heading="SQL Injection",
                level=1,
                heading_path=["SQL Injection"],
                blocks=[ContentBlock(kind=BlockKind.PARAGRAPH, content="Intro")],
            ),
            SectionNode(
                section_id="section-0001-detection",
                heading="Detection",
                level=2,
                heading_path=["SQL Injection", "Detection"],
                blocks=[
                    ContentBlock(kind=BlockKind.LIST, content="- A\n- B"),
                    ContentBlock(kind=BlockKind.CODE, content="```http\nGET /\n```"),
                ],
            ),
        ],
    )


def test_render_markdown_contains_only_ingestible_content():
    md = render_markdown(sample_document())
    assert md.startswith("# SQL Injection\n")
    assert "doc_id:" not in md
    assert "source_path:" not in md
    assert "parser_engine:" not in md
    assert "processed_at:" not in md
    assert "## Detection" in md
    assert "- A\n- B" in md
    assert "---Section Context---" not in md


def test_export_writes_only_markdown_and_json(tmp_path: Path):
    document = sample_document()
    out = export_document(document, tmp_path)

    assert {p.name for p in out.iterdir()} == {"document.md", "document.json"}
    payload = json.loads((out / "document.json").read_text(encoding="utf-8"))
    assert payload["doc_id"] == "abc123"
    assert payload["sections"][1]["heading_path"] == ["SQL Injection", "Detection"]
