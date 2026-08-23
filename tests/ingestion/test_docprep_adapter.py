import json
import asyncio
from pathlib import Path

import pytest

from polymerhus.ingestion.docprep_adapter import (
    DocprepError,
    normalize_document,
    normalize_downloaded_artifact,
)


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


@pytest.mark.parametrize(
    "body, source_type, expected_parser",
    [
        (
            "<html><body><main><h1>Guide</h1><p>Useful body.</p></main></body></html>",
            "html",
            "html",
        ),
        ("# Markdown Guide\n\nSome body.\n", "markdown", "markdown"),
    ],
)
def test_normalize_downloaded_artifact_reuses_existing_parsers_with_provenance(
    tmp_path,
    body,
    source_type,
    expected_parser,
):
    artifact = tmp_path / "downloaded-artifact"
    artifact.write_text(body, encoding="utf-8")
    output_root = tmp_path / "normalized"

    result = asyncio.run(
        normalize_downloaded_artifact(
            artifact,
            output_root=output_root,
            source_identity="https://example.com/doc",
            source_type=source_type,
            native_metadata={
                "canonical_url": "https://example.com/doc",
                "final_url": "https://example.com/doc",
                "http_content_type": "text/html" if source_type == "html" else "text/markdown",
            },
        )
    )

    assert result.parser == expected_parser
    assert result.markdown_path.name == "document.md"
    assert result.json_path.name == "document.json"
    data = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert data["source_path"] == "https://example.com/doc"
    assert data["source_type"] == source_type
    assert data["parser_engine"] == expected_parser
    assert data["native_metadata"]["canonical_url"] == "https://example.com/doc"
    assert data["native_metadata"]["final_url"] == "https://example.com/doc"
    assert data["native_metadata"]["http_content_type"] in {"text/html", "text/markdown"}


def test_normalize_downloaded_artifact_failure_uses_stable_code(tmp_path):
    missing = tmp_path / "downloaded-artifact"

    with pytest.raises(DocprepError) as exc:
        asyncio.run(
            normalize_downloaded_artifact(
                missing,
                output_root=tmp_path / "normalized",
                source_identity="https://example.com/doc",
                source_type="html",
                native_metadata={},
            )
        )

    assert exc.value.code == "PARSE_FAILED"


def test_ingestion_modules_never_import_url_fetcher():
    ingestion_dir = Path("src/polymerhus/ingestion")
    for module in sorted(ingestion_dir.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        assert "url_fetcher" not in source, (
            f"{module.name} must not import or call lightrag_docprep url_fetcher"
        )
