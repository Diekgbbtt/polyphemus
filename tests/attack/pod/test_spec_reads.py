"""Unit tier: the pod's reads over the reduced D4 provenance (T8, S3 8.6/S5 8.4).

The typed `SkillConcretisedProcedure` has ONE home
(`attack/hunting/spec_contract.py`); the pod reads it from the top-level
`skill_concretised_procedure` and reads the optional recorded baseline from
`spec["provenance"]["baseline_ref"]`. A missing or malformed object is a
recorded gap (None), never a raise: no variant basis is derivable
basis (S5 8.6).
"""
from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.types import (
    TestImplementationSpec as D4Spec,
    baseline_ref_from_spec,
    skill_concretised_procedure_from_spec,
    spec_provenance,
)
from polymerhus.attack.hunting.spec_contract import (
    SKILL_CONCRETISED_PROCEDURE_FIELDS,
    SkillConcretisedProcedure,
)

PROCEDURE = {
    "recon_action": "crawl the item ids from the listing page",
    "bypass_technique": "swap the id in a signed URL",
    "advanced_technique": "chain the export endpoint",
    "preliminary_chaining": "first mint a low-privilege session",
    "payload_vector": "the report id in the path segment, no encoding",
    "technology_misconfiguration": "the object store trusts the URL scope",
    "technology_grounding": "the app is a Django REST API",
    "pro_tips": "compare the owner id in the body",
    "interpretation_pitfalls": "a 403 is not proof the object is absent",
}

SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/",
                        "unit_id": "service:web:soupmarket"},
    "discriminators": [
        {"axis": "object", "value": "order-id"},
        {"axis": "delivery-route", "value": "signed-url"},
    ],
    "verification_symptoms": ["the response leaks another user's order id"],
    "assumptions": ["the session cookie is the only auth factor"],
    "rationale": "IDOR over the order endpoint",
    "skill_concretised_procedure": PROCEDURE,
    "provenance": {
        "threat_id": "threat-1",
        "unit_id": "service:web:soupmarket",
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "baseline_ref": "http_01J0000000000000000000000A",
    },
}


def test_the_spec_reads_the_typed_skill_concretised_procedure():
    procedure = skill_concretised_procedure_from_spec(SPEC)
    assert isinstance(procedure, SkillConcretisedProcedure)
    assert set(PROCEDURE) == set(SKILL_CONCRETISED_PROCEDURE_FIELDS)
    for field in SKILL_CONCRETISED_PROCEDURE_FIELDS:
        assert getattr(procedure, field) == PROCEDURE[field]
    assert procedure.excerpt_length() == sum(len(v) for v in PROCEDURE.values())


def test_a_parsed_d4_model_reads_the_same_procedure():
    model = D4Spec.model_validate(SPEC)
    assert skill_concretised_procedure_from_spec(model) == \
        skill_concretised_procedure_from_spec(SPEC)


def test_a_missing_procedure_is_a_recorded_gap_not_a_raise():
    spec = {**SPEC, "skill_concretised_procedure": None}
    assert skill_concretised_procedure_from_spec(spec) is None
    assert skill_concretised_procedure_from_spec({}) is None
    assert skill_concretised_procedure_from_spec(None) is None


def test_a_malformed_procedure_is_a_recorded_gap_not_a_raise():
    spec = {**SPEC, "skill_concretised_procedure": {
        **PROCEDURE, "not_a_procedure_field": "x"}}
    assert skill_concretised_procedure_from_spec(spec) is None
    assert skill_concretised_procedure_from_spec(
        {**SPEC, "skill_concretised_procedure": "not a mapping"}) is None


def test_the_baseline_ref_is_the_provenance_pointer():
    assert baseline_ref_from_spec(SPEC) == "http_01J0000000000000000000000A"
    assert baseline_ref_from_spec(D4Spec.model_validate(SPEC)) == \
        "http_01J0000000000000000000000A"


def test_an_absent_or_blank_baseline_is_empty():
    assert baseline_ref_from_spec({**SPEC, "provenance": {}}) == ""
    assert baseline_ref_from_spec(
        {**SPEC, "provenance": {"baseline_ref": "  "}}) == ""
    assert baseline_ref_from_spec(None) == ""


def test_spec_provenance_is_empty_for_a_malformed_value():
    assert spec_provenance({"provenance": "not a mapping"}) == {}


# --- T9: the triager's bounded skill-procedure context (S5 8.6) ----------------

def test_the_triager_context_carries_the_typed_concretisation():
    """S5 8.6 step 1: the triager reads the typed concretisation from the spec
    and diffs each field against the executed procedure."""
    ctx = ExperimentLog().triager_context(SPEC, None)
    assert "skill procedure" in ctx.lower()
    for field, text in PROCEDURE.items():
        assert text in ctx, field
    assert "recon-action" in ctx and "payload-vector" in ctx
    assert "technology-misconfiguration" in ctx
    assert "interpretation-pitfall" in ctx


def test_the_triager_context_marks_an_absent_procedure_as_a_recorded_gap():
    ctx = ExperimentLog().triager_context(
        {**SPEC, "skill_concretised_procedure": None}, None)
    assert "recorded gap" in ctx.lower()
    assert "no variant basis" in ctx.lower()


def test_the_triager_context_marks_an_empty_section_as_a_skipped_class():
    spec = {**SPEC, "skill_concretised_procedure": {
        **PROCEDURE, "pro_tips": ""}}
    ctx = ExperimentLog().triager_context(spec, None)
    assert "pro-tips" in ctx
    assert "skipped" in ctx.lower()
