import json
from pathlib import Path

from agent.lightrag.preprocess import (
    build_preprocessed_documents,
    classify_fragment,
    is_relation_fragment,
    parse_markdown_source,
    preprocess_sources_for_lightrag,
    preprocess_wstg_for_lightrag,
)


def test_preprocess_builds_relation_briefs_and_facet_documents(tmp_path):
    source = tmp_path / "waf-bypass.md"
    source.write_text(
        """# WAF Bypass Methodology

## Controlled Facts

Alternate encoding probe is an AttackTechnique.

Web application firewall is a DefensiveTechnology.

Normalization mismatch is an EnvironmentalCondition.

Alternate encoding probe bypasses Web application firewall when Normalization mismatch is present.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "preprocessed"
    result = preprocess_sources_for_lightrag([source], output_dir)

    assert (output_dir / "relation-briefs.md").exists()
    assert (output_dir / "attack-methods.md").exists()
    assert (output_dir / "defenses-and-detections.md").exists()
    assert (output_dir / "prerequisites-and-environment.md").exists()

    relation_briefs = (output_dir / "relation-briefs.md").read_text(encoding="utf-8")
    assert "Alternate encoding probe bypasses Web application firewall" in relation_briefs
    assert "Ontology boundary: relation briefs are source-grounded and ontology-agnostic." in relation_briefs

    attack_methods = (output_dir / "attack-methods.md").read_text(encoding="utf-8")
    assert "Alternate encoding probe is an AttackTechnique." in attack_methods
    assert "LightRAG ontology" not in attack_methods.split("##", 1)[-1]

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["primary_document"] == "relation-briefs.md"
    assert manifest["fragments"]
    assert any(fragment["is_relation_brief"] for fragment in manifest["fragments"])
    assert result.generated_files[-1].name == ".manifest.json"


def test_preprocess_preserves_code_blocks_in_payload_facet(tmp_path):
    source = tmp_path / "payload-example.md"
    source.write_text(
        """# Payload Notes

## Example

Use this HTTP request shape only as a documentation example.

```http
GET /items?id=1%20OR%201=1 HTTP/1.1
Host: example.test
```
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "preprocessed"
    preprocess_sources_for_lightrag([source], output_dir)

    code_doc = (output_dir / "code-and-payload-examples.md").read_text(encoding="utf-8")
    assert "```http" in code_doc
    assert "GET /items?id=1%20OR%201=1 HTTP/1.1" in code_doc
    assert "Block type: code" in code_doc


def test_build_result_keeps_relation_classification_separate_from_facets(tmp_path):
    source = tmp_path / "idor.md"
    source.write_text(
        """# IDOR Chaining

Object identifier harvesting enables Cross account object access.
""",
        encoding="utf-8",
    )

    result = build_preprocessed_documents([source])

    assert len(result.fragments) == 1
    fragment = result.fragments[0]
    assert is_relation_fragment(fragment) is True
    assert "attack-methods" in result.fragment_facets[fragment.fragment_id]


def test_classifier_avoids_substring_false_positives(tmp_path):
    source = tmp_path / "terms.md"
    source.write_text(
        """# Term Notes

Multi factor authentication bypass is a VulnerabilityClass.

User-controlled SQL input is an EnvironmentalCondition.
""",
        encoding="utf-8",
    )

    fragments = parse_markdown_source(source)
    bypass_facets = classify_fragment(fragments[0])
    controlled_facets = classify_fragment(fragments[1])

    assert bypass_facets == ["vulnerability-classes"]
    assert controlled_facets == ["prerequisites-and-environment"]


def test_wstg_profile_generates_scenario_scoped_documents(tmp_path):
    source = tmp_path / "05-Testing_for_SQL_Injection.md"
    source.write_text(
        """# Testing for SQL Injection

ID
---
WSTG-INPV-05

## Summary

SQL injection testing checks whether user-controlled data can influence SQL query construction without adequate input validation.

## Test Objectives

- Identify SQL injection points.
- Assess the level of access that can be achieved.

## How to Test

The tester lists input fields and parameters, then tests them separately to interfere with the query.

`https://www.example.com/news.php?id=1 AND 1=1`

## Remediation

Use parameterized queries and strict input validation.

## References

- OWASP WSTG
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    result = preprocess_wstg_for_lightrag([source], output_dir)

    methodology_doc = output_dir / "wstg-inpv-05-methodology.md"

    assert methodology_doc.exists()
    assert not (output_dir / "wstg-inpv-05-relation-briefs.md").exists()
    assert not (output_dir / "wstg-inpv-05-attack-methods.md").exists()

    methodology_text = methodology_doc.read_text(encoding="utf-8")
    assert "# WSTG-INPV-05 - Testing for SQL Injection" in methodology_text
    assert "## Scenario Metadata" in methodology_text
    assert "## Overview" in methodology_text
    assert "## Attack Methods" in methodology_text
    assert "## Defenses And Detections" in methodology_text
    assert "## Code And Payload Examples" in methodology_text
    assert "## Relation Briefs" in methodology_text
    assert "user-controlled data can influence SQL query construction" in methodology_text
    assert "parameterized queries" in methodology_text
    assert "https://www.example.com/news.php?id=1 AND 1=1" in methodology_text

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == "wstg"
    assert manifest["primary_document_pattern"] == "<wstg-id>-methodology.md"
    assert manifest["debug_facets"] is False
    assert manifest["scenarios"][0]["wstg_id"] == "WSTG-INPV-05"
    assert manifest["scenarios"][0]["primary_document"] == "wstg-inpv-05-methodology.md"
    assert result.generated_files[-1].name == ".manifest.json"


def test_wstg_profile_can_write_debug_facet_documents(tmp_path):
    source = tmp_path / "05-Testing_for_SQL_Injection.md"
    source.write_text(
        """# Testing for SQL Injection

ID
---
WSTG-INPV-05

## How to Test

The tester changes a parameter and observes whether SQL behavior changes.

## Remediation

Use parameterized queries.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([source], output_dir, debug_facets=True)

    assert (output_dir / "wstg-inpv-05-methodology.md").exists()
    assert (output_dir / "_debug_facets" / "wstg-inpv-05-relation-briefs.md").exists()
    assert (output_dir / "_debug_facets" / "wstg-inpv-05-attack-methods.md").exists()
    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    assert manifest["debug_facets"] is True
    assert manifest["scenarios"][0]["debug_files"]


def test_wstg_profile_avoids_overwriting_duplicate_id_outputs(tmp_path):
    main_source = tmp_path / "05-Testing_for_SQL_Injection.md"
    main_source.write_text(
        """# Testing for SQL Injection

ID
---
WSTG-INPV-05

## Summary

Main SQL injection testing methodology.
""",
        encoding="utf-8",
    )
    oracle_source = tmp_path / "05.1-Testing_for_Oracle.md"
    oracle_source.write_text(
        """# Testing for Oracle

ID
---
WSTG-INPV-05

## Summary

Oracle-specific SQL injection testing methodology.
""",
        encoding="utf-8",
    )

    output_dir = tmp_path / "wstg"
    preprocess_wstg_for_lightrag([main_source, oracle_source], output_dir)

    primary_doc = output_dir / "wstg-inpv-05-methodology.md"
    oracle_doc = output_dir / "wstg-inpv-05-05-1-testing-for-oracle-methodology.md"

    assert primary_doc.exists()
    assert oracle_doc.exists()
    assert "Main SQL injection" in primary_doc.read_text(encoding="utf-8")
    assert "Oracle-specific SQL injection" in oracle_doc.read_text(encoding="utf-8")

    manifest = json.loads((output_dir / ".manifest.json").read_text(encoding="utf-8"))
    generated_names = {Path(path).name for path in manifest["generated_files"]}
    assert primary_doc.name in generated_names
    assert oracle_doc.name in generated_names
