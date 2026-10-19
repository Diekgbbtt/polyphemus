"""Unit tier: the harness verification component (the pure INIT schema gate and
the agent-output guards). No live target, no LLM, no DB.

T8 (#381): the D4 surface is the REDUCED one (S5 8.4) - target identity,
verification symptoms, assumptions, rationale, lineage, and provenance. The
gate's mandatory set is exactly a non-empty `target_identity.url` and at least
one non-blank symptom; the three retired fields are rejected as unknown.
"""
import pytest
from pydantic import ValidationError

from polymerhus.attack.hunting.pod.types import (
    ProbeChain,
    ProbeStep,
    TestImplementationSpec as D4Spec,
)
from polymerhus.attack.hunting.pod.verification import (
    validate_decision,
    validate_probe_chain,
    validate_spec,
)

VALID_SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/",
                        "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "assumptions": ["network egress allowed"],
    "rationale": "reachability",
    "provenance": {
        "loop_id": "loop-1",
        "unit_id": "service:web:soupmarket",
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
    },
}

RETIRED_FIELDS = {
    "testing_pattern": "blind-boolean",
    "payload_vector_space": {"method": "GET", "path": "/"},
    "interpretation_guidance": "a 200 with a body confirms reachability",
}


# --- the reduced D4 surface (S5 8.4) ------------------------------------------

def test_the_reduced_d4_round_trips():
    model = D4Spec.model_validate(VALID_SPEC)
    assert model.model_dump() == {**VALID_SPEC, "parent_spec_ref": None}


def test_the_retired_d4_fields_are_rejected_as_unknown():
    # S5 8.8: the reduced fields parse; the retired fields are rejected.
    for retired, value in RETIRED_FIELDS.items():
        with pytest.raises(ValidationError):
            D4Spec.model_validate({**VALID_SPEC, retired: value})


def test_the_gate_rejects_a_retired_field_by_name():
    for retired, value in RETIRED_FIELDS.items():
        violations = validate_spec({**VALID_SPEC, retired: value})
        assert any(retired in v for v in violations), (retired, violations)


# --- the INIT gate (S5 8.4) ---------------------------------------------------

def test_valid_spec_has_no_violations():
    assert validate_spec(VALID_SPEC) == []


def test_missing_verification_symptoms_is_a_violation():
    spec = {**VALID_SPEC, "verification_symptoms": []}
    violations = validate_spec(spec)
    assert any("verification_symptoms" in v for v in violations)


def test_blank_symptoms_only_is_a_violation():
    spec = {**VALID_SPEC, "verification_symptoms": ["", "   "]}
    assert any("verification_symptoms" in v for v in validate_spec(spec))


def test_a_mixed_symptom_list_is_a_violation():
    # A list that carries a non-string entry cannot parse as the reduced D4
    # (`list[str]`), so the gate rejects it too instead of passing a shape the
    # model would fail on later.
    spec = {**VALID_SPEC, "verification_symptoms": ["ok", 3]}
    assert any("verification_symptoms" in v for v in validate_spec(spec))
    with pytest.raises(ValidationError):
        D4Spec.model_validate(spec)


def test_one_non_blank_symptom_is_enough():
    spec = {**VALID_SPEC, "verification_symptoms": ["   ", "reflects the marker"]}
    assert validate_spec(spec) == []


def test_the_gate_collects_all_violations_in_one_rejection():
    # The hunter corrects the spec in one pass: both mandatory violations land
    # in the SAME rejection.
    violations = validate_spec({"target_identity": {"url": "  "},
                                "verification_symptoms": []})
    assert any("target_identity" in v for v in violations)
    assert any("verification_symptoms" in v for v in violations)


def test_every_other_field_is_optional():
    # Only the URL and the symptoms are mandatory: an absent rationale,
    # assumptions, and provenance never rejects.
    spec = {"target_identity": {"url": "http://soupmarket.shop/"},
            "verification_symptoms": ["reflects the marker"]}
    assert validate_spec(spec) == []


def test_empty_target_identity_url_is_a_violation():
    spec = {**VALID_SPEC, "target_identity": {"url": "  ", "unit_id": "svc"}}
    assert any("target_identity" in v for v in validate_spec(spec))


def test_target_identity_without_url_key_is_a_violation():
    spec = {**VALID_SPEC, "target_identity": {"unit_id": "service:web:soupmarket"}}
    assert any("target_identity" in v for v in validate_spec(spec))


def test_target_identity_non_dict_is_a_violation():
    spec = {**VALID_SPEC, "target_identity": "service:web:soupmarket"}
    assert any("target_identity" in v for v in validate_spec(spec))


def test_target_identity_carries_the_l1_unit_id():
    # The L1 service/system identifier surfaces alongside the url (#197).
    spec = {**VALID_SPEC,
            "target_identity": {"url": "http://soupmarket.shop/",
                                "unit_id": "service:web:soupmarket"}}
    assert validate_spec(spec) == []
    # unit_id is carried but NOT init-gated: absence degrades, never rejects.
    spec_no_unit = {**VALID_SPEC,
                    "target_identity": {"url": "http://soupmarket.shop/"}}
    assert validate_spec(spec_no_unit) == []


def test_a_built_model_is_also_gated():
    model = D4Spec.model_validate(VALID_SPEC)
    assert validate_spec(model) == []


# --- the agent-output guards --------------------------------------------------

def test_probe_chain_needs_exactly_one_core_call():
    chain = ProbeChain(variant_ref="v0", steps=[
        ProbeStep(role="dependency", url="/login"),
        ProbeStep(role="core", url="/api/a"),
    ])
    assert validate_probe_chain(chain) == []


def test_probe_chain_with_no_core_is_flagged():
    chain = ProbeChain(variant_ref="v0", steps=[ProbeStep(role="dependency", url="/x")])
    assert any("core" in v for v in validate_probe_chain(chain))


def test_probe_chain_step_without_url_or_command_is_flagged():
    chain = ProbeChain(variant_ref="v0", steps=[ProbeStep(role="core")])
    assert any("url" in v or "command" in v for v in validate_probe_chain(chain))


def test_decision_vocabulary_is_enforced():
    assert validate_decision({"verdict": "successful",
                              "terminal_reason": "symptom-confirmed",
                              "clean": True}) == []
    bad = validate_decision({"verdict": "maybe",
                             "terminal_reason": "infeasibility-asserted",
                             "clean": "yes"})
    assert any("verdict" in v for v in bad)
    assert any("terminal_reason" in v for v in bad)  # the OLD 4-value name is rejected
    assert any("clean" in v for v in bad)
