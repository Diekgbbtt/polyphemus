"""The realigned spec identity and skill-concretised procedure contract.

The identity is the ordered tuple of the DISCRIMINATE instance values over the
vulnerability class. It replaces the retired `<fault_keyword>_<strategy_keyword>`
two-word identity, whose `_` join was ambiguous and whose words had no defined
semantics against the slice.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from polymerhus.attack.hunting.spec_contract import (
    SKILL_CONCRETISED_PROCEDURE_FIELDS,
    SKILL_CONCRETISED_PROCEDURE_MAX_CHARS,
    Discriminator,
    SkillConcretisedProcedure,
    SpecProvenance,
    spec_identifier,
)


def _disc(*pairs: tuple[str, str]) -> list[Discriminator]:
    return [Discriminator(axis=axis, value=value) for axis, value in pairs]


def test_the_identity_is_the_class_then_the_ordered_values():
    ident = spec_identifier(
        "idor", _disc(("object", "report-id"), ("delivery-route", "signed-url")))
    assert ident == "idor__report-id__signed-url"


def test_the_identity_uses_the_canonical_class_when_the_web_class_is_empty():
    assert spec_identifier(
        "", _disc(("state", "post-delete"), ("actor", "viewer")),
        fallback_class="business-logic",
    ) == "business-logic__post-delete__viewer"


def test_the_identity_falls_back_to_spec_when_no_class_is_known():
    assert spec_identifier(
        "", _disc(("state", "post-delete"), ("actor", "viewer")),
    ) == "spec__post-delete__viewer"


def test_one_value_is_not_a_discrimination():
    with pytest.raises(ValueError, match="at least two"):
        spec_identifier("idor", _disc(("object", "report-id")))


def test_more_than_four_values_is_a_slice_not_a_spec():
    with pytest.raises(ValueError, match="at most four"):
        spec_identifier("idor", _disc(
            ("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"), ("e", "5")))


def test_a_duplicate_axis_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        spec_identifier("idor", _disc(
            ("object", "report-id"), ("object", "account-id")))


def test_the_join_is_unambiguous_because_values_cannot_carry_the_separator():
    with pytest.raises(ValidationError):
        Discriminator(axis="object", value="report__id")
    # A raw mapping still passes the identifier's own safety net.
    with pytest.raises(ValueError, match="safe value"):
        spec_identifier("idor", [
            {"axis": "object", "value": "report id"},
            {"axis": "delivery-route", "value": "signed url"},
        ])


def test_an_over_long_identity_is_rejected():
    with pytest.raises(ValueError, match="120"):
        spec_identifier("x" * 60, _disc(
            ("a" * 40, "b" * 60), ("c" * 40, "d" * 60)))


def test_the_skill_concretised_procedure_keeps_the_nine_fields():
    procedure = SkillConcretisedProcedure(
        recon_action="replay the sign-up request",
        bypass_technique="reuse the gate-minted cookie",
        advanced_technique="chain the reset with the invite",
        preliminary_chaining="mint a viewer first",
        payload_vector="JSON body, UTF-8",
        technology_misconfiguration="Shiro retains the gate cookie",
        technology_grounding="Shiro cookie handling",
        pro_tips="compare the byte length",
        interpretation_pitfalls="a 200 is not proof",
    )
    assert set(SKILL_CONCRETISED_PROCEDURE_FIELDS) == {
        "recon_action", "bypass_technique", "advanced_technique",
        "preliminary_chaining", "payload_vector", "technology_misconfiguration",
        "technology_grounding", "pro_tips", "interpretation_pitfalls",
    }
    assert procedure.excerpt_length() > 0
    assert procedure.excerpt_length() <= SKILL_CONCRETISED_PROCEDURE_MAX_CHARS


def test_an_over_long_concretised_procedure_is_rejected_by_the_store_validator():
    from polymerhus.attack.hunting.hunter_memory import (
        validate_skill_concretised_procedure,
    )

    too_long = {"recon_action": "x" * (SKILL_CONCRETISED_PROCEDURE_MAX_CHARS + 1)}
    with pytest.raises(ValueError, match="exceeds"):
        validate_skill_concretised_procedure(too_long)


def test_provenance_no_longer_carries_the_copied_skill_procedure():
    assert "skill_procedure" not in SpecProvenance.model_fields
    # The retired key remains an unknown field, so a stale writer is rejected.
    with pytest.raises(ValidationError):
        SpecProvenance(skill_procedure={"recon_action": "x"})
