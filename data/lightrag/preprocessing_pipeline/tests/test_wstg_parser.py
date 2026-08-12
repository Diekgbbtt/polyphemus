from pathlib import Path

import pytest

from lightrag_docprep.parsers.wstg import WstgParser


@pytest.mark.asyncio
async def test_wstg_parser_extracts_native_metadata_without_rewriting(tmp_path: Path):
    category = tmp_path / "07-Input_Validation_Testing"
    category.mkdir()
    source = category / "05-Testing_for_SQL_Injection.md"
    original = """# Testing for SQL Injection

|ID|
|---|
|WSTG-INPV-05|

## Summary

A tester sends a single quote and observes the response.
"""
    source.write_text(original, encoding="utf-8")

    raw = await WstgParser().parse(source)

    assert raw.source_profile == "wstg"
    assert raw.title_candidate == "Testing for SQL Injection"
    assert raw.native_metadata == {
        "wstg_id": "WSTG-INPV-05",
        "wstg_category_code": "INPV",
        "wstg_category": "Input Validation Testing",
        "wstg_title": "Testing for SQL Injection",
    }
    assert raw.markdown == original.rstrip()
    assert "VulnerabilityClass" not in raw.markdown
    assert "AttackTechnique" not in raw.markdown
    assert "Ontology Query Anchors" not in raw.markdown


@pytest.mark.asyncio
async def test_wstg_parser_can_infer_id_from_category_and_filename(tmp_path: Path):
    category = tmp_path / "01-Information_Gathering"
    category.mkdir()
    source = category / "06-Identify_Application_Entry_Points.md"
    source.write_text("# Identify Application Entry Points\n\nBody", encoding="utf-8")

    raw = await WstgParser().parse(source)

    assert raw.native_metadata["wstg_id"] == "WSTG-INFO-06"
    assert raw.native_metadata["wstg_category"] == "Information Gathering"
