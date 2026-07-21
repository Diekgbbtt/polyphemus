"""Controlled LightRAG methodology ontology for the P0 retrieval slice."""

from __future__ import annotations

ENTITY_TYPES = (
    "VulnerabilityClass",
    "DefensiveTechnology",
    "EnvironmentalCondition",
    "AttackTechnique",
)

RELATION_TYPES = (
    "exploits",
    "detectedBy",
    "requires",
    "enables",
    "mitigates",
    "bypasses",
)

RELATION_DIRECTION_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "exploits": (("AttackTechnique", "VulnerabilityClass"),),
    "detectedBy": (("AttackTechnique", "DefensiveTechnology"),),
    "requires": (("AttackTechnique", "EnvironmentalCondition"),),
    "enables": (
        ("EnvironmentalCondition", "AttackTechnique"),
        ("AttackTechnique", "AttackTechnique"),
    ),
    "mitigates": (
        ("DefensiveTechnology", "AttackTechnique"),
        ("DefensiveTechnology", "VulnerabilityClass"),
    ),
    "bypasses": (("AttackTechnique", "DefensiveTechnology"),),
}


def validate_entity_type(entity_type: str) -> str:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unsupported LightRAG entity type: {entity_type}")
    return entity_type


def validate_relation_type(relation_type: str) -> str:
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"unsupported LightRAG relation type: {relation_type}")
    return relation_type


def is_valid_relation(source_entity_type: str, relation_type: str, target_entity_type: str) -> bool:
    validate_entity_type(source_entity_type)
    validate_entity_type(target_entity_type)
    validate_relation_type(relation_type)
    return (source_entity_type, target_entity_type) in RELATION_DIRECTION_RULES[relation_type]


def validate_relation(source_entity_type: str, relation_type: str, target_entity_type: str) -> None:
    if not is_valid_relation(source_entity_type, relation_type, target_entity_type):
        raise ValueError(
            "invalid LightRAG relation direction: "
            f"{source_entity_type} -[{relation_type}]-> {target_entity_type}"
        )


def normalized_entity_key(entity_type: str, canonical_name: str) -> str:
    validate_entity_type(entity_type)
    normalized_name = " ".join(canonical_name.strip().lower().split())
    if not normalized_name:
        raise ValueError("canonical_name must not be blank")
    return f"{entity_type}:{normalized_name}"
