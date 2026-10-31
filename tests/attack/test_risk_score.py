"""Unit tier: the CVSS 4.0 risk module over the `cvss==3.6` library.

Every expected score is a published CVSS 4.0 value: the vector's base score as
the reference calculator reports it, never a recomputation of the same formula
this module calls. The vectors are the ones the scoring corpus uses - a full
confidentiality-and-integrity network attack, an all-none vector, and a full
triple-impact vector.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from polymerhus.attack.hunting.risk_score import (
    FACTOR_DESCRIPTIONS,
    AttackComplexity,
    AttackRequirements,
    AttackVector,
    ImpactLevel,
    PrivilegesRequired,
    RiskMetrics,
    SeverityBand,
    UserInteraction,
    build_vector,
    compute_risk,
    severity_band,
    validate_metrics,
)

# The factor name, its enum, and the vector key it serializes to. The order is
# the vector order of the CVSS 4.0 base metric group.
FACTORS = (
    ("attack_vector", AttackVector, "AV"),
    ("attack_complexity", AttackComplexity, "AC"),
    ("attack_requirements", AttackRequirements, "AT"),
    ("privileges_required", PrivilegesRequired, "PR"),
    ("user_interaction", UserInteraction, "UI"),
    ("confidentiality", ImpactLevel, "VC"),
    ("integrity", ImpactLevel, "VI"),
    ("availability", ImpactLevel, "VA"),
)


def metrics(**overrides: object) -> RiskMetrics:
    """A network attack with high confidentiality and integrity damage."""
    values: dict[str, object] = {
        "attack_vector": AttackVector.NETWORK,
        "attack_complexity": AttackComplexity.LOW,
        "attack_requirements": AttackRequirements.NONE,
        "privileges_required": PrivilegesRequired.NONE,
        "user_interaction": UserInteraction.NONE,
        "confidentiality": ImpactLevel.HIGH,
        "integrity": ImpactLevel.HIGH,
        "availability": ImpactLevel.NONE,
    }
    values.update(overrides)
    return RiskMetrics(**values)


# --- the known vectors -------------------------------------------------------

def test_known_vector_scores_9_9_critical() -> None:
    result = compute_risk(metrics())

    assert result.vector == (
        "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:N/SC:H/SI:H/SA:N"
    )
    assert result.score == 9.9
    assert result.band is SeverityBand.CRITICAL


def test_all_none_impact_scores_0_0_none() -> None:
    result = compute_risk(
        metrics(
            attack_complexity=AttackComplexity.HIGH,
            attack_requirements=AttackRequirements.PRESENT,
            privileges_required=PrivilegesRequired.HIGH,
            user_interaction=UserInteraction.ACTIVE,
            confidentiality=ImpactLevel.NONE,
            integrity=ImpactLevel.NONE,
            availability=ImpactLevel.NONE,
        )
    )

    assert result.score == 0.0
    assert result.band is SeverityBand.NONE


def test_full_triple_impact_scores_10_0_critical() -> None:
    result = compute_risk(
        metrics(availability=ImpactLevel.HIGH),
    )

    assert result.vector == (
        "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:H/SI:H/SA:H"
    )
    assert result.score == 10.0
    assert result.band is SeverityBand.CRITICAL


def test_a_fully_hedged_chain_scores_low() -> None:
    result = compute_risk(
        metrics(
            attack_vector=AttackVector.LOCAL,
            attack_complexity=AttackComplexity.HIGH,
            attack_requirements=AttackRequirements.PRESENT,
            privileges_required=PrivilegesRequired.HIGH,
            user_interaction=UserInteraction.PASSIVE,
            confidentiality=ImpactLevel.LOW,
            integrity=ImpactLevel.LOW,
            availability=ImpactLevel.LOW,
        )
    )

    assert result.score == 1.0
    assert result.band is SeverityBand.LOW


# --- the vector builder ------------------------------------------------------

def test_build_vector_emits_the_eleven_base_metrics() -> None:
    vector = build_vector(
        metrics(
            attack_vector=AttackVector.ADJACENT,
            attack_complexity=AttackComplexity.HIGH,
            attack_requirements=AttackRequirements.PRESENT,
            privileges_required=PrivilegesRequired.LOW,
            user_interaction=UserInteraction.ACTIVE,
            confidentiality=ImpactLevel.HIGH,
            integrity=ImpactLevel.LOW,
            availability=ImpactLevel.NONE,
        )
    )

    assert vector == "CVSS:4.0/AV:A/AC:H/AT:P/PR:L/UI:A/VC:H/VI:L/VA:N/SC:H/SI:L/SA:N"
    parts = vector.split("/")[1:]
    assert len(parts) == 11
    assert [part.split(":", 1)[0] for part in parts] == [
        "AV", "AC", "AT", "PR", "UI", "VC", "VI", "VA", "SC", "SI", "SA",
    ]


def test_build_vector_mirrors_the_subsequent_system_impact() -> None:
    for level, token in (
        (ImpactLevel.NONE, "N"),
        (ImpactLevel.LOW, "L"),
        (ImpactLevel.HIGH, "H"),
    ):
        vector = build_vector(
            metrics(confidentiality=level, integrity=level, availability=level)
        )
        parts = dict(part.split(":", 1) for part in vector.split("/")[1:])

        assert parts["SC"] == parts["VC"] == token
        assert parts["SI"] == parts["VI"] == token
        assert parts["SA"] == parts["VA"] == token


def test_build_vector_maps_every_enum_value() -> None:
    expected = {
        "AV": {
            AttackVector.NETWORK: "N",
            AttackVector.ADJACENT: "A",
            AttackVector.LOCAL: "L",
            AttackVector.PHYSICAL: "P",
        },
        "AC": {AttackComplexity.LOW: "L", AttackComplexity.HIGH: "H"},
        "AT": {AttackRequirements.NONE: "N", AttackRequirements.PRESENT: "P"},
        "PR": {
            PrivilegesRequired.NONE: "N",
            PrivilegesRequired.LOW: "L",
            PrivilegesRequired.HIGH: "H",
        },
        "UI": {
            UserInteraction.NONE: "N",
            UserInteraction.PASSIVE: "P",
            UserInteraction.ACTIVE: "A",
        },
    }
    for field, enum, key in FACTORS[:5]:
        for member, token in expected[key].items():
            parts = dict(
                part.split(":", 1)
                for part in build_vector(metrics(**{field: member})).split("/")[1:]
            )
            assert parts[key] == token


# --- the severity bands ------------------------------------------------------

@pytest.mark.parametrize(
    ("score", "band"),
    (
        (0.0, SeverityBand.NONE),
        (0.1, SeverityBand.LOW),
        (3.9, SeverityBand.LOW),
        (4.0, SeverityBand.MEDIUM),
        (6.9, SeverityBand.MEDIUM),
        (7.0, SeverityBand.HIGH),
        (8.9, SeverityBand.HIGH),
        (9.0, SeverityBand.CRITICAL),
        (10.0, SeverityBand.CRITICAL),
    ),
)
def test_severity_band_edges(score: float, band: SeverityBand) -> None:
    assert severity_band(score) is band


# --- the factor-set contract -------------------------------------------------

def test_precursor_with_a_non_none_impact_value_is_rejected() -> None:
    findings = validate_metrics(metrics(), "precursor")

    assert findings
    assert any("integrity" in finding for finding in findings)


def test_precursor_with_all_none_impact_values_is_accepted() -> None:
    row = metrics(
        confidentiality=ImpactLevel.NONE, integrity=ImpactLevel.NONE,
    )

    assert validate_metrics(row, "precursor") == []


def test_threat_with_all_none_impact_values_is_rejected() -> None:
    row = metrics(
        confidentiality=ImpactLevel.NONE,
        integrity=ImpactLevel.NONE,
        availability=ImpactLevel.NONE,
    )

    findings = validate_metrics(row, "threat")

    assert findings
    assert any("none" in finding for finding in findings)


def test_threat_with_one_impact_value_above_none_is_accepted() -> None:
    row = metrics(
        confidentiality=ImpactLevel.NONE,
        integrity=ImpactLevel.NONE,
        availability=ImpactLevel.LOW,
    )

    assert validate_metrics(row, "threat") == []


def test_risk_metrics_forbids_an_unknown_factor() -> None:
    with pytest.raises(ValidationError):
        metrics(exploitability=ImpactLevel.HIGH)  # type: ignore[call-arg]


def test_risk_metrics_requires_every_factor() -> None:
    with pytest.raises(ValidationError):
        RiskMetrics(
            attack_vector=AttackVector.NETWORK,
            attack_complexity=AttackComplexity.LOW,
            attack_requirements=AttackRequirements.NONE,
            privileges_required=PrivilegesRequired.NONE,
            user_interaction=UserInteraction.NONE,
            confidentiality=ImpactLevel.HIGH,
            integrity=ImpactLevel.HIGH,
        )


# --- the single-source factor descriptions -----------------------------------

def test_every_enum_value_has_a_semantic_and_an_example() -> None:
    for field, enum, _key in FACTORS:
        descriptions = FACTOR_DESCRIPTIONS[field]

        assert set(descriptions) == {member.value for member in enum}
        for member in enum:
            entry = descriptions[member.value]
            semantic, _, example = entry.partition("Example: ")
            assert semantic.strip()
            assert example.strip()
