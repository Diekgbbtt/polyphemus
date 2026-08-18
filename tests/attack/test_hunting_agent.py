"""Unit tier: the hunting agent's pure mechanics and the role registration.

The catalogue predicates C1-C17 live in
tests/integration/test_hunting_agent_contracts.py and are never repeated in
this tier's red/green loop (testing-strategy.md section 2, the #82 precedent).
This tier pins the pure functions the harness relies on:

  derive_verdict(terminal_reason, *, clean, init_validation=None)
      - the D7 vierdict derivation (D67-02, Q3-amended; implementation doc
        section 2.3/5.2): reads ONLY the terminal reason plus the single
        `clean` flag (plus `init_validation` for the INIT-rejection case),
        never per-variant machinery.

  derive_technological_axis(card)
      - the deterministic technological axis for the `(fault-class, axis)`
        KB join key (IA-8, D10): derived from the unit's index card, never
        a typed predicate facet (#66 non-conflation).

  ROLES - the `hunting` role joins the LLM role registry keyed by
      `LLM_MODEL_HUNTING` (Q1).
"""
import pytest

from polymerhus.attack.hunting.hunting_agent import (
    HypothesisVerdict,
    derive_technological_axis,
    derive_verdict,
)
from polymerhus.app.llm.providers import HUNTING_ROLES, ROLES


# --- derive_verdict: the ratified Q3 map (implementation doc 2.3) ------------

def test_symptom_confirmed_derives_successful():
    assert derive_verdict("symptom-confirmed", clean=False) == "successful"


def test_space_exhausted_derives_unsuccessful():
    assert derive_verdict("space-exhausted", clean=True) == "unsuccessful"


def test_technical_infeasibility_derives_unsuccessful():
    # A structural blocker is a refutation, never insufficient-evidence (Q3).
    assert derive_verdict("technical-infeasibility", clean=False) == "unsuccessful"


def test_specific_defence_prevention_derives_unsuccessful():
    assert derive_verdict("specific-defence-prevention", clean=False) == "unsuccessful"


def test_no_symptom_evidence_blocked_derives_insufficient_evidence():
    # Blocked/unreachable observations: the absence is not established (Q3).
    assert derive_verdict("no-symptom-evidence", clean=False) == "insufficient-evidence"


def test_no_symptom_evidence_clean_derives_unsuccessful():
    # Clean completed observations: a symptom-absent is established (Q3).
    assert derive_verdict("no-symptom-evidence", clean=True) == "unsuccessful"


def test_budget_timeout_mid_flight_derives_insufficient_evidence():
    # The loop was cut mid-flight: the absence is not established (Q3).
    assert derive_verdict("budget-timeout", clean=False) == "insufficient-evidence"


def test_budget_timeout_clean_derives_unsuccessful():
    assert derive_verdict("budget-timeout", clean=True) == "unsuccessful"


def test_init_rejection_derives_underspecified_spec():
    # A pod INIT rejection (tech-infeasibility carrying init_validation)
    # derives underspecified-spec (Q3/Q5).
    assert derive_verdict(
        "technical-infeasibility",
        clean=False,
        init_validation=["symptom references an unobservable surface"],
    ) == "underspecified-spec"


def test_unknown_terminal_reason_derives_insufficient_evidence():
    # Fail-open: an out-of-enum terminal reason cannot be interpreted, so the
    # derivation is conservative - never a success or a clean absence claim.
    assert derive_verdict("something-else", clean=True) == "insufficient-evidence"


# --- derive_technological_axis: the deterministic joint-key axis (IA-8) ------

def test_axis_prefers_api_paradigm():
    card = {"kind": "Service", "spine": {"api_paradigm": "REST", "exposure": "public"}}
    assert derive_technological_axis(card) == "rest"


def test_axis_falls_back_to_navigation_model():
    card = {"kind": "System", "spine": {"navigation_model": "SPA"}}
    assert derive_technological_axis(card) == "spa"


def test_axis_defaults_to_kind():
    # CARD_A in the contract suite carries only `exposure`; the axis must
    # stay deterministic and non-empty (C1 asserts a non-empty string).
    card = {"kind": "Service", "key": {"business_function_slug": "a"}, "spine": {"exposure": "public"}}
    assert derive_technological_axis(card) == "service"


def test_axis_empty_card_defaults():
    assert derive_technological_axis({}) == "unknown"
    assert derive_technological_axis(None) == "unknown"


# --- the hunting roles join the LLM role registry (Q1, #93/#94) --------------

def test_hunting_roles_are_registered_off_app_boot():
    """The hunting agents are their own role_ids in HUNTING_ROLES (validated at the
    hunting module bootstrap), never in the app-boot ROLES (operator ruling
    2026-08-06). Both are `session` agents."""
    hunting_ids = {r.role_id for r in HUNTING_ROLES}
    assert hunting_ids == {"hunting_orchestrator", "hunting_hunter"}
    assert not (hunting_ids & {r.role_id for r in ROLES})  # off app boot
    assert all(r.agent_mode == "session" for r in HUNTING_ROLES)


def test_hypothesis_verdict_vocabulary_is_four_valued():
    assert set(HypothesisVerdict.__args__) == {
        "successful", "unsuccessful", "insufficient-evidence", "underspecified-spec",
    }