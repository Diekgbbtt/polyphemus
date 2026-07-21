import pytest

from agent.lightrag import ontology


def test_ontology_allows_only_four_entity_types():
    assert ontology.validate_entity_type("AttackTechnique") == "AttackTechnique"
    with pytest.raises(ValueError):
        ontology.validate_entity_type("Service")


def test_ontology_allows_only_six_relations():
    assert ontology.validate_relation_type("bypasses") == "bypasses"
    with pytest.raises(ValueError):
        ontology.validate_relation_type("targets")


def test_relation_direction_rules_are_enforced():
    ontology.validate_relation("AttackTechnique", "exploits", "VulnerabilityClass")
    ontology.validate_relation("EnvironmentalCondition", "enables", "AttackTechnique")
    ontology.validate_relation("AttackTechnique", "enables", "AttackTechnique")

    with pytest.raises(ValueError):
        ontology.validate_relation("DefensiveTechnology", "exploits", "VulnerabilityClass")


def test_normalized_entity_key_rejects_blank_name():
    assert ontology.normalized_entity_key("AttackTechnique", "  Header Probe  ") == (
        "AttackTechnique:header probe"
    )
    with pytest.raises(ValueError):
        ontology.normalized_entity_key("AttackTechnique", " ")
