"""Controlled LightRAG methodology entity ontology."""

from __future__ import annotations

ENTITY_TYPES = (
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


def validate_entity_type(entity_type: str) -> str:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unsupported LightRAG entity type: {entity_type}")
    return entity_type


def normalized_entity_key(entity_type: str, canonical_name: str) -> str:
    validate_entity_type(entity_type)
    normalized_name = " ".join(canonical_name.strip().lower().split())
    if not normalized_name:
        raise ValueError("canonical_name must not be blank")
    return f"{entity_type}:{normalized_name}"
