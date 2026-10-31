"""Unit tier: the schema-5 risk shapes, the normaliser, and the risk profile.

Schema 5 (2026-10-31) makes the assessment row the scored claim: it carries the
eight authored CVSS 4.0 factors and the derived `risk` / `risk_vector`. The
threat is the dispatch grain: it references the row and mirrors the score for
the mover, and the model writes a shape (`ThreatWrite`) that cannot author the
mirror. The store fills the mirror and ranks; the model never authors a score.

The expected scores are the `cvss==3.6` CVSS 4.0 values for the literal factor
sets (`AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N` = 9.2, `VC:L` = 6.9), never a
recomputation through the code under test.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.risk_score import (
    AttackComplexity,
    AttackRequirements,
    AttackVector,
    ImpactLevel,
    PrivilegesRequired,
    UserInteraction,
    validate_metrics,
)
from polymerhus.attack.hunting.threat_model import (
    GATE_SECTIONS,
    SCHEMA_VERSION,
    Evidence,
    EvidenceKind,
    ImpactAssessment,
    ImpactDisposition,
    ModelSections,
    ModelState,
    RiskMetrics,
    RiskProfile,
    SeverityBand,
    Threat,
    ThreatWrite,
    UnitThreatModel,
    compute_risk_profile,
    normalise_threats,
)

# The known-good CVSS 4.0 scores of the two literal factor sets used below.
HIGH_RISK = 9.2
LOW_RISK = 6.9
HIGH_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:H/SI:N/SA:N"
LOW_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:L/VI:N/VA:N/SC:L/SI:N/SA:N"


def factors(
    confidentiality: ImpactLevel = ImpactLevel.HIGH,
    integrity: ImpactLevel = ImpactLevel.NONE,
    availability: ImpactLevel = ImpactLevel.NONE,
) -> RiskMetrics:
    return RiskMetrics(
        attack_vector=AttackVector.NETWORK,
        attack_complexity=AttackComplexity.LOW,
        attack_requirements=AttackRequirements.NONE,
        privileges_required=PrivilegesRequired.NONE,
        user_interaction=UserInteraction.NONE,
        confidentiality=confidentiality,
        integrity=integrity,
        availability=availability,
    )


def row(
    *,
    id: str = "IA-1",
    disposition: ImpactDisposition = ImpactDisposition.THREAT,
    risk: float = HIGH_RISK,
    vector: str = HIGH_VECTOR,
    capability_path: list[str] | None = None,
    precursor_refs: list[str] | None = None,
) -> ImpactAssessment:
    return ImpactAssessment(
        id=id,
        vulnerability_ref="V-1",
        disposition=disposition,
        impact_description="An anonymous caller reads another tenant's item.",
        exploitability_description="One unauthenticated request names the item id.",
        capability="read another tenant's item",
        capability_id="P-1",
        capability_path=capability_path or [],
        evidence_refs=["GET /api/items/2"],
        factors=factors(),
        risk=risk,
        risk_vector=vector,
        precursor_refs=precursor_refs or [],
    )


def threat(
    *,
    impact_ref: str = "IA-1",
    risk: float = 0.0,
    canonical: str = "Cross-Site Scripting",
    web: str = "xss",
    enabling: list[tuple[str, str | None]] | None = None,
) -> Threat:
    return Threat(
        fault_ref="F-1",
        vulnerability_ref="V-1",
        canonical_class=canonical,
        web_vulnerability_class=web,
        evidences=[Evidence(kind=EvidenceKind.PROBE, ref="probe:test", detail="")],
        impact_ref=impact_ref,
        enabling_precursors=enabling or [],
        risk=risk,
    )


# --- the v5 schema contract --------------------------------------------------

def test_schema_five_wires_the_seven_states_its_gate_sections():
    """The `IMPACT_ASSESSED` gate is tool-only: it accepts no model section."""
    assert SCHEMA_VERSION == 5
    assert [state.value for state in ModelState] == [
        "UNIT_TECHNICAL_SHARP",
        "TRUST_MODELLED",
        "TRUST_ASSUMPTIONS_WRITTEN",
        "VULNERABILITIES_WRITTEN",
        "PRIOR_ART",
        "IMPACT_ASSESSED",
        "COMPLETED",
    ]
    assert GATE_SECTIONS == {
        ModelState.UNIT_TECHNICAL_SHARP: ("technical_sharpening",),
        ModelState.PRIOR_ART: ("prior_art",),
        ModelState.TRUST_MODELLED: ("trust_model",),
        ModelState.TRUST_ASSUMPTIONS_WRITTEN: ("assumptions",),
        ModelState.VULNERABILITIES_WRITTEN: ("vulnerabilities",),
        ModelState.IMPACT_ASSESSED: (),
        ModelState.COMPLETED: ("threats",),
    }


def test_the_assessment_row_is_the_scored_claim():
    """The row carries the factors and the derived score, and the legacy
    precursor list stays read-only (excluded from the persisted shape)."""
    assert set(ImpactAssessment.model_fields) == {
        "id",
        "vulnerability_ref",
        "disposition",
        "impact_description",
        "exploitability_description",
        "capability",
        "capability_id",
        "capability_path",
        "evidence_refs",
        "factors",
        "risk",
        "risk_vector",
        "precursor_refs",
    }
    assert ImpactAssessment.model_fields["risk"].default == 0.0
    assert ImpactAssessment.model_fields["risk_vector"].default == ""
    assert "damage" not in ImpactAssessment.model_fields
    assert "precursor_refs" not in row().model_dump()


def test_the_v5_schema_carries_no_retired_risk_field():
    assert "likelihood" not in Threat.model_fields
    assert "likelihood_rationale" not in Threat.model_fields
    assert "risk_factors" not in Threat.model_fields
    assert "confidence" not in Threat.model_fields
    assert "impact" not in Threat.model_fields
    assert "impact_weight" not in Threat.model_fields
    assert set(RiskProfile.model_fields) == {"total", "breakdown"}
    assert "impact_breakdown" not in RiskProfile.model_fields
    assert set(UnitThreatModel.model_fields) >= {"impact_assessment", "threats"}


def test_the_model_writes_the_threat_without_a_risk_and_the_store_fills_it():
    """`ThreatWrite` is the canonical threat minus `risk`; `ModelSections`
    carries the write shape, so an authored score is an unknown field."""
    assert set(Threat.model_fields) - set(ThreatWrite.model_fields) == {"risk"}
    assert set(ModelSections.model_fields) == {
        "technical_sharpening",
        "prior_art",
        "trust_model",
        "assumptions",
        "vulnerabilities",
        "threats",
    }
    assert "impact_assessment" not in ModelSections.model_fields
    write = {
        "fault_ref": "F-1",
        "vulnerability_ref": "V-1",
        "canonical_class": "IDOR",
        "evidences": [{"kind": "probe", "ref": "probe:1"}],
        "impact_ref": "IA-1",
    }
    assert isinstance(ModelSections(threats=[write]).threats[0], ThreatWrite)
    with pytest.raises(ValueError):
        ModelSections(threats=[{**write, "risk": 9.2}])


def test_the_precursor_disposition_reads_a_legacy_placeholder():
    assert ImpactDisposition.THREAT.value == "threat"
    assert ImpactDisposition.PRECURSOR.value == "precursor"
    assert "PLACEHOLDER" not in ImpactDisposition.__members__
    legacy = ImpactAssessment(
        id="IA-1",
        vulnerability_ref="V-1",
        disposition="placeholder",
        impact_description="No end damage follows.",
        exploitability_description="One request distinguishes the handler.",
        capability="distinguish a handler from a route",
        capability_id="P-1",
        factors=factors(
            confidentiality=ImpactLevel.NONE,
        ),
    )
    assert legacy.disposition is ImpactDisposition.PRECURSOR


def test_a_legacy_enabling_id_list_reads_as_a_self_provided_chain():
    entity = threat(enabling=["P-1"])
    assert entity.enabling_precursors == [("P-1", "P-1")]


# --- the factor findings ------------------------------------------------------

def test_a_threat_row_needs_one_non_none_impact_value():
    findings = validate_metrics(
        factors(
            confidentiality=ImpactLevel.NONE,
            integrity=ImpactLevel.NONE,
            availability=ImpactLevel.NONE,
        ),
        disposition=ImpactDisposition.THREAT.value,
    )
    assert len(findings) == 1
    assert findings[0].startswith("factors.confidentiality")


def test_a_precursor_row_needs_all_three_impact_values_none():
    findings = validate_metrics(
        factors(confidentiality=ImpactLevel.LOW),
        disposition=ImpactDisposition.PRECURSOR.value,
    )
    assert findings == [
        "factors.confidentiality=low on a precursor row "
        "(a precursor row must have all three impact values none)",
    ]
    assert validate_metrics(
        factors(confidentiality=ImpactLevel.NONE),
        disposition=ImpactDisposition.PRECURSOR.value,
    ) == []


# --- the profile --------------------------------------------------------------

def test_the_profile_sums_the_risk_and_counts_the_severity_bands():
    threats = [
        threat(impact_ref="IA-1", risk=HIGH_RISK),
        threat(impact_ref="IA-2", risk=HIGH_RISK),
        threat(impact_ref="IA-3", risk=LOW_RISK),
        threat(impact_ref="IA-4", risk=0.0),
    ]
    profile = compute_risk_profile(threats)
    assert profile.total == round(HIGH_RISK + HIGH_RISK + LOW_RISK, 2)
    assert profile.breakdown == {
        SeverityBand.NONE: 1,
        SeverityBand.LOW: 0,
        SeverityBand.MEDIUM: 1,
        SeverityBand.HIGH: 0,
        SeverityBand.CRITICAL: 2,
    }


def test_the_profile_rounds_the_total_to_the_score_precision():
    profile = compute_risk_profile([threat(risk=9.25), threat(risk=6.95)])
    assert profile.total == 16.2


def test_an_empty_profile_is_zero_and_every_band_is_counted():
    profile = compute_risk_profile([])
    assert profile.total == 0.0
    assert profile.breakdown == {band: 0 for band in SeverityBand}


# --- the normaliser -----------------------------------------------------------

def test_the_normaliser_fills_the_mirror_and_ranks_by_risk_then_write_order():
    rows = [
        row(id="IA-1", risk=LOW_RISK, vector=LOW_VECTOR),
        row(id="IA-2", risk=HIGH_RISK),
        row(id="IA-3", risk=HIGH_RISK),
    ]
    written = [
        threat(impact_ref="IA-1", canonical="low"),
        threat(impact_ref="IA-2", canonical="first high tie"),
        threat(impact_ref="IA-3", canonical="second high tie"),
    ]

    ordered = normalise_threats(written, rows)

    assert [item.canonical_class for item in ordered] == [
        "first high tie", "second high tie", "low",
    ]
    assert [item.id for item in ordered] == ["threat-1", "threat-2", "threat-3"]
    assert [item.risk for item in ordered] == [HIGH_RISK, HIGH_RISK, LOW_RISK]


def test_the_normaliser_accepts_the_risk_map():
    rows = {"IA-1": LOW_RISK, "IA-2": HIGH_RISK}

    ordered = normalise_threats(
        [threat(impact_ref="IA-1"), threat(impact_ref="IA-2")], rows)

    assert [item.impact_ref for item in ordered] == ["IA-2", "IA-1"]
    assert [item.risk for item in ordered] == [HIGH_RISK, LOW_RISK]


def test_an_unresolved_reference_keeps_the_carried_risk_for_the_checker():
    """A threat whose row is missing is the referential check's finding; the
    normaliser never invents a score for it."""
    ordered = normalise_threats([threat(impact_ref="IA-missing", risk=0.0)], [row()])

    assert ordered[0].risk == 0.0
    assert ordered[0].id == "threat-1"
