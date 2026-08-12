import json
import asyncio

import pytest

from agent.ingestion.docprep_adapter import DocprepError, normalize_document


def test_normalize_document_reuses_docprep_and_exports_canonical_artifacts(tmp_path):
    source = tmp_path / "inbox" / "sample.md"
    source.parent.mkdir()
    source.write_text(
        "# Sample Methodology\n\n"
        "## Request\n\n"
        "```http\nGET /admin HTTP/1.1\nHost: example.test\n```\n\n"
        "## Payload\n\n"
        "```bash\ncurl -i http://example.test/admin\n```\n",
        encoding="utf-8",
    )
    output_root = tmp_path / "normalized"

    result = asyncio.run(normalize_document(source, output_root=output_root))

    assert result.parser == "markdown"
    assert result.markdown_path.name == "document.md"
    assert result.json_path.name == "document.json"
    normalized_markdown = result.markdown_path.read_text(encoding="utf-8")
    normalized_json = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert "# Sample Methodology" in normalized_markdown
    assert "```http\nGET /admin HTTP/1.1\nHost: example.test\n```" in normalized_markdown
    assert "```bash\ncurl -i http://example.test/admin\n```" in normalized_markdown
    assert normalized_json["parser_engine"] == "markdown"
    assert "chunks" not in normalized_json
    assert "relationships" not in normalized_json


def test_normalize_document_raises_stable_error_for_failed_parse(tmp_path):
    missing = tmp_path / "inbox" / "missing.md"

    with pytest.raises(DocprepError) as exc:
        asyncio.run(normalize_document(missing, output_root=tmp_path / "normalized"))

    assert exc.value.code == "PARSE_FAILED"
