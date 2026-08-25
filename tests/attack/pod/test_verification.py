"""Unit tier: the harness verification component (the pure INIT schema gate and
the agent-output guards). No live target, no LLM, no DB."""
from polymerhus.attack.hunting.pod.types import ProbeChain, ProbeStep
from polymerhus.attack.hunting.pod.verification import (
    validate_decision,
    validate_probe_chain,
    validate_spec,
)

VALID_SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability",
    "interpretation_guidance": "a 200 with a body confirms reachability",
}


def test_valid_spec_has_no_violations():
    assert validate_spec(VALID_SPEC) == []


def test_missing_verification_symptoms_is_a_violation():
    spec = {**VALID_SPEC, "verification_symptoms": []}
    violations = validate_spec(spec)
    assert any("verification_symptoms" in v for v in violations)


def test_empty_target_identity_is_a_violation():
    spec = {**VALID_SPEC, "target_identity": "  "}
    assert any("target_identity" in v for v in validate_spec(spec))


def test_empty_payload_vector_space_is_valid_o12():
    # O12: an empty payload vector does NOT zero the loop - the default probe
    # still runs, so an empty (but well-typed) vector is not a schema violation.
    spec = {**VALID_SPEC, "payload_vector_space": {}}
    assert validate_spec(spec) == []


def test_non_dict_payload_vector_space_is_a_violation():
    spec = {**VALID_SPEC, "payload_vector_space": ["not", "a", "dict"]}
    assert any("payload_vector_space" in v for v in validate_spec(spec))


def test_nl_fields_are_not_part_of_the_mandatory_typed_base():
    # D67-10: the typed base excludes the two NL fields; their absence is not a
    # schema violation.
    spec = {**VALID_SPEC, "rationale": "", "interpretation_guidance": ""}
    assert validate_spec(spec) == []


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
