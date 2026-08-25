from pathlib import Path

import pytest

import lightrag_docprep
from lightrag_docprep.config import PreprocessorConfig
from lightrag_docprep.models import RawParseResult
from lightrag_docprep.pipeline import DocumentPreprocessor


def test_raw_parse_result_rejects_ontology_metadata_keys():
    with pytest.raises(ValueError, match="semantic metadata key"):
        RawParseResult(
            parser_name="bad-adapter",
            source_path="source.md",
            markdown="# Source",
            native_metadata={"VulnerabilityClass": "SQL Injection"},
        )


def test_package_version_is_v3():
    assert lightrag_docprep.__version__ == "0.3.4"


@pytest.mark.asyncio
async def test_wstg_output_contains_native_metadata_but_no_synthetic_semantic_sections(tmp_path: Path):
    source_dir = tmp_path / "wstg_raw" / "07-Input_Validation_Testing"
    source_dir.mkdir(parents=True)
    source = source_dir / "05-Testing_for_SQL_Injection.md"
    source.write_text(
        "# Testing for SQL Injection\n\n|ID|\n|---|\n|WSTG-INPV-05|\n\n## Summary\n\nOriginal source text.",
        encoding="utf-8",
    )
    output = tmp_path / "out"

    result = await DocumentPreprocessor(PreprocessorConfig(output_dir=output)).process(source)

    assert result.success
    assert result.output_dir is not None
    assert {p.name for p in result.output_dir.iterdir()} == {"document.md", "document.json"}
    markdown = (result.output_dir / "document.md").read_text(encoding="utf-8")
    json_text = (result.output_dir / "document.json").read_text(encoding="utf-8")
    assert "Attack Chain Summary" not in markdown
    assert "Technique Cards" not in markdown
    assert "Relation Briefs" not in markdown
    assert '"wstg_id": "WSTG-INPV-05"' in json_text
    assert "VulnerabilityClass" not in json_text
    assert "AttackTechnique" not in json_text
