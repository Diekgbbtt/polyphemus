"""Unit tier: the fault-risk scheduling policy (`attack/hunting/fault_risk.py`,
the candidates-rewrite operator-authored risk tiers).

The schedule is order-based; this module is the deterministic correction that
re-sorts the per-fault work items RISK-DESCENDING so a budget-capped pass
reasons about the riskiest faults first. Contracts under assertion:

  * the operator's three criteria land the TOP tier: broken access control,
    missing-or-weak validation, sophisticated-system targets (Authentication-
    Mechanism / AuthorizationSystem / session Systems);
  * the analysis COVERS the catalogue: every selection-tier fault_id of the
    shipped fault-KB carries an explicit analysed tier - an id falling to the
    default tier means the KB grew past the analysis and must be re-ranked;
  * total + deterministic: an unknown id never raises and sorts after every
    analysed tier, equal-tier faults keep their intake relative order.
"""
import pytest

from polymerhus.attack.hunting.fault_kb import load_fold_families
from polymerhus.attack.hunting.fault_risk import (
    _DEFAULT_TIER,
    risk_tier,
    sort_risk_desc,
)


# --- the operator's criteria ----------------------------------------------------

def test_broken_access_control_is_the_top_tier():
    for fid in ("CWE-639", "CWE-862", "CWE-425", "CWE-638", "CWE-266",
                "CWE-1220", "CWE-650"):
        assert risk_tier(fid) == 0, fid


def test_missing_or_weak_validation_is_tier_one():
    for fid in ("CWE-78", "CWE-89", "CWE-502", "CWE-94", "CWE-1336", "CWE-79",
                "CWE-22", "CWE-611", "CWE-918"):
        assert risk_tier(fid) == 1, fid


def test_sophisticated_system_targets_are_tier_two():
    # AuthenticationMechanism / AuthorizationSystem / session loci: full
    # account-takeover power, one rung below direct compromise
    for fid in ("CWE-306", "CWE-288", "CWE-290", "CWE-304", "CWE-352",
                "CWE-384", "CWE-613", "CWE-346"):
        assert risk_tier(fid) == 2, fid


def test_exposure_and_residual_lag_behind_the_criteria():
    assert risk_tier("CWE-201") == 3      # sensitive-data disclosure
    assert risk_tier("CWE-489") == 3      # debug code
    assert risk_tier("CWE-601") == 4      # open redirect
    assert risk_tier("CWE-1021") == 4     # clickjacking


def test_riskiest_sort_ahead_of_lexicographic_accident():
    # the whole point: catalogue order would put CWE-1021 before CWE-639
    ranked = sort_risk_desc(["CWE-1021", "CWE-601", "CWE-89", "CWE-639"])
    assert ranked == ["CWE-639", "CWE-89", "CWE-1021", "CWE-601"]


# --- totality + determinism -----------------------------------------------------

def test_unknown_fault_falls_to_the_conservative_default():
    assert risk_tier("CWE-99999") == _DEFAULT_TIER
    assert _DEFAULT_TIER > max(risk_tier(f) for f in (
        "CWE-639", "CWE-89", "CWE-306", "CWE-201", "CWE-601"))


def test_sort_is_stable_within_a_tier():
    intake = ["CWE-862", "CWE-639", "CWE-425"]   # all tier 0
    assert sort_risk_desc(intake) == intake       # first-emission order kept


# --- catalogue coverage ---------------------------------------------------------

def test_analysis_covers_every_selection_tier_fault_of_the_shipped_catalogue():
    """The policy is total over the SHIPPED KB: any selection-tier id missing
    from the analysis silently degrades to the default tier - which defeats the
    risk-first schedule. This guard fails when the KB grows, prompting a
    re-ranking of the new faults."""
    from polymerhus.attack.hunting.fault_risk import _RISK_TIERS
    families = load_fold_families()
    unanalysed = sorted(set(families) - set(_RISK_TIERS))
    assert not unanalysed, f"unanalysed selection-tier faults: {unanalysed}"
