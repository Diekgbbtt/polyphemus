"""Unit tier: the CVSS 4.0-like impact model and the combined threat risk.

Ticket 404. The impact is authored on the threat: three metrics and a literal
end-impact statement. The store computes the sub-score, the ordinal weight, the
threat risk, the unit profile, and the ranking. The tests use the known-good
literals from the ADR, never a recomputation of the implementation formula.
"""
from __future__ import annotations

import pytest

from polymerhus.attack.hunting.threat_model import (
    Confidence,
    Evidence,
    EvidenceKind,
    Impact,
    ImpactLevel,
    ImpactSeverity,
    Likelihood,
    Threat,
    RiskFactors,
    AttackVector,
    AttackRequirements,
    PrivilegesRequired,
    Complexity,
    compute_impact,
    compute_risk_profile,
    impact_severity,
    impact_weight,
    impact_weight_from_sub_score,
    threat_risk,
    normalise_threats,
    RISK_WEIGHTS,
)
from polymerhus.attack.hunting.threat_model import IMPACT_METRIC_WEIGHTS


def impact(confidentiality=ImpactLevel.NONE, integrity=ImpactLevel.NONE,
           availability=ImpactLevel.NONE) -> Impact:
    return Impact(
        confidentiality=confidentiality,
        integrity=integrity,
        availability=availability,
        end_impact="a literal end effect",
    )


def threat(*, likelihood=Likelihood.MEDIUM, impact_value=None,
         canonical="Cross-Site Scripting", web="xss") -> Threat:
    return Threat(
        fault_ref="F-1",
        vulnerability_ref="V-1",
        canonical_class=canonical,
        web_vulnerability_class=web,
        likelihood=likelihood,
        likelihood_rationale="a rationale",
        risk_factors=RiskFactors(
            attack_vector=AttackVector.NETWORK,
            attack_requirements=AttackRequirements.NONE,
            privileges_required=PrivilegesRequired.NONE,
            complexity=Complexity.LOW,
        ),
        confidence=Confidence.OBSERVED,
        evidences=[Evidence(kind=EvidenceKind.PROBE, ref="probe:test", detail="")],
        impact=impact_value or Impact.none(),
    )


def test_the_metric_weights_are_the_ratified_values():
    assert IMPACT_METRIC_WEIGHTS == {
        ImpactLevel.NONE: 0.00,
        ImpactLevel.LOW: 0.22,
        ImpactLevel.MEDIUM: 0.35,
        ImpactLevel.HIGH: 0.56,
    }


def test_the_impact_sub_score_matches_the_known_table():
    """Known-good literals from the ADR formula, not a recomputation."""
    cases = [
        ((ImpactLevel.NONE, ImpactLevel.NONE, ImpactLevel.NONE), 0.0),
        ((ImpactLevel.LOW, ImpactLevel.NONE, ImpactLevel.NONE), 0.22),
        ((ImpactLevel.MEDIUM, ImpactLevel.NONE, ImpactLevel.NONE), 0.35),
        ((ImpactLevel.HIGH, ImpactLevel.NONE, ImpactLevel.NONE), 0.56),
        ((ImpactLevel.LOW, ImpactLevel.LOW, ImpactLevel.NONE), 0.3916),
        ((ImpactLevel.MEDIUM, ImpactLevel.MEDIUM, ImpactLevel.NONE), 0.5775),
        ((ImpactLevel.HIGH, ImpactLevel.HIGH, ImpactLevel.NONE), 0.8064),
        ((ImpactLevel.HIGH, ImpactLevel.HIGH, ImpactLevel.HIGH), 0.914816),
    ]
    for (confidentiality, integrity, availability), expected in cases:
        value = impact(confidentiality, integrity, availability)
        assert compute_impact(value) == pytest.approx(expected, abs=1e-6)


def test_the_ordinal_weight_maps_the_sub_score():
    cases = [
        (0.0, 0),
        (0.22, 1),
        (0.25, 1),
        (0.2501, 2),
        (0.35, 2),
        (0.50, 2),
        (0.5001, 3),
        (0.56, 3),
        (0.75, 3),
        (0.7501, 4),
        (0.8064, 4),
        (1.0, 4),
    ]
    for sub_score, expected in cases:
        assert impact_weight_from_sub_score(sub_score) == expected


def test_the_ordinal_weight_maps_the_metric_combinations():
    assert impact_weight(impact(ImpactLevel.LOW)) == 1
    assert impact_weight(impact(ImpactLevel.MEDIUM)) == 2
    assert impact_weight(impact(ImpactLevel.HIGH)) == 3
    assert impact_weight(impact(ImpactLevel.HIGH, ImpactLevel.HIGH)) == 4


def test_impact_severity_names_the_five_levels():
    assert impact_severity(0) is ImpactSeverity.NONE
    assert impact_severity(1) is ImpactSeverity.LOW
    assert impact_severity(2) is ImpactSeverity.MEDIUM
    assert impact_severity(3) is ImpactSeverity.HIGH
    assert impact_severity(4) is ImpactSeverity.CRITICAL


def test_the_threat_risk_multiplies_likelihood_and_impact():
    high_impact = impact(ImpactLevel.HIGH, ImpactLevel.NONE, ImpactLevel.NONE)
    critical_impact = impact(ImpactLevel.HIGH, ImpactLevel.HIGH, ImpactLevel.HIGH)
    assert threat_risk(Likelihood.HIGH, high_impact) == 9
    assert threat_risk(Likelihood.CRITICAL, critical_impact) == 16
    assert threat_risk(Likelihood.NONE, critical_impact) == 0
    assert threat_risk(Likelihood.LOW, Impact.none()) == 0


def test_the_profile_sums_the_threat_risk_and_counts_both_breakdowns():
    threats = [
        threat(likelihood=Likelihood.HIGH,
             impact_value=impact(ImpactLevel.HIGH)),
        threat(likelihood=Likelihood.MEDIUM,
             impact_value=impact(ImpactLevel.MEDIUM)),
        threat(likelihood=Likelihood.LOW, impact_value=Impact.none()),
        threat(likelihood=Likelihood.CRITICAL,
             impact_value=impact(ImpactLevel.HIGH, ImpactLevel.HIGH, ImpactLevel.HIGH)),
    ]
    profile = compute_risk_profile(threats)
    assert profile.total == 9 + 4 + 0 + 16
    assert profile.breakdown[Likelihood.HIGH] == 1
    assert profile.breakdown[Likelihood.MEDIUM] == 1
    assert profile.breakdown[Likelihood.LOW] == 1
    assert profile.breakdown[Likelihood.CRITICAL] == 1
    assert profile.breakdown[Likelihood.NONE] == 0
    assert profile.impact_breakdown[ImpactSeverity.HIGH] == 1
    assert profile.impact_breakdown[ImpactSeverity.MEDIUM] == 1
    assert profile.impact_breakdown[ImpactSeverity.NONE] == 1
    assert profile.impact_breakdown[ImpactSeverity.CRITICAL] == 1
    assert profile.impact_breakdown[ImpactSeverity.LOW] == 0


def test_the_ranking_is_risk_then_impact_then_likelihood_then_write_order():
    critical = threat(
        likelihood=Likelihood.HIGH,
        impact_value=impact(ImpactLevel.HIGH, ImpactLevel.HIGH, ImpactLevel.HIGH),
        canonical="critical",
    )
    first_tie = threat(
        likelihood=Likelihood.MEDIUM,
        impact_value=impact(ImpactLevel.HIGH, ImpactLevel.HIGH),
        canonical="first tie",
    )
    second_tie = threat(
        likelihood=Likelihood.MEDIUM,
        impact_value=impact(ImpactLevel.HIGH, ImpactLevel.HIGH),
        canonical="second tie",
    )
    lower_impact = threat(
        likelihood=Likelihood.CRITICAL,
        impact_value=impact(ImpactLevel.MEDIUM),
        canonical="lower impact",
    )
    ordered = normalise_threats([lower_impact, first_tie, second_tie, critical])
    assert [threat.canonical_class for threat in ordered] == [
        "critical", "first tie", "second tie", "lower impact",
    ]
    assert [threat.id for threat in ordered] == ["threat-1", "threat-2", "threat-3", "threat-4"]
    assert [threat.risk for threat in ordered] == [12, 8, 8, 8]
    assert [threat.impact_weight for threat in ordered] == [4, 4, 4, 2]


def test_a_threat_without_an_impact_contributes_zero():
    legacy = threat()
    assert legacy.impact == Impact.none()
    assert legacy.risk == 0
    assert legacy.impact_weight == 0
    assert compute_risk_profile([legacy]).total == 0


def test_the_risk_buckets_cover_the_combined_score():
    from polymerhus.attack.hunting.threat_model import risk_bucket

    assert risk_bucket(0) == "none"
    assert risk_bucket(1) == "low"
    assert risk_bucket(3) == "low"
    assert risk_bucket(4) == "medium"
    assert risk_bucket(7) == "medium"
    assert risk_bucket(8) == "high"
    assert risk_bucket(11) == "high"
    assert risk_bucket(12) == "critical"
    assert risk_bucket(16) == "critical"


def test_the_likelihood_weights_are_unchanged():
    assert RISK_WEIGHTS == {
        Likelihood.NONE: 0,
        Likelihood.LOW: 1,
        Likelihood.MEDIUM: 2,
        Likelihood.HIGH: 3,
        Likelihood.CRITICAL: 4,
    }
