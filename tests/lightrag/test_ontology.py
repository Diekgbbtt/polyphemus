from pathlib import Path

import pytest

from lightrag import ontology


def test_ontology_allows_only_ten_entity_types():
    assert ontology.ENTITY_TYPES == (
        "PreconditionEnvironment",
        "TechnologyStack",
        "DefensiveControl",
        "VulnerabilityClass",
        "AttackGoal",
        "AttackerCapability",
        "AttackTechnique",
        "PayloadPattern",
        "Artifact",
        "ObservableSignal",
    )

    assert ontology.validate_entity_type("AttackTechnique") == "AttackTechnique"
    assert ontology.validate_entity_type("AttackerCapability") == "AttackerCapability"

    with pytest.raises(ValueError):
        ontology.validate_entity_type("Service")


def test_normalized_entity_key_rejects_blank_name():
    assert ontology.normalized_entity_key("AttackTechnique", "  Header Probe  ") == (
        "AttackTechnique:header probe"
    )
    with pytest.raises(ValueError):
        ontology.normalized_entity_key("AttackTechnique", " ")


def test_entity_prompt_forbids_fallback_types():
    prompt = Path("data/lightrag/prompts/entity_type/methodology_entities.yml").read_text(
        encoding="utf-8"
    )

    for entity_type in ontology.ENTITY_TYPES:
        assert entity_type in prompt
    assert "closed set" in prompt
    assert "Type names are case-sensitive" in prompt
    assert "output AttackTechnique, never attacktechnique" in prompt
    assert "overrides any generic extractor fallback instruction" in prompt
    assert "Never output fallback or catch-all types such as Other, other, UNKNOWN" in prompt
    assert "Weakness-family roots remain VulnerabilityClass" in prompt
    assert 'Do not type the broad family entity "SQL' in prompt
