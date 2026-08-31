"""Unit tier: the harness verification component (the pure INIT schema gate and
the agent-output guards). No live target, no LLM, no DB."""
from polymerhus.attack.hunting.pod.types import ProbeChain, ProbeStep
from polymerhus.attack.hunting.pod.verification import (
    validate_decision,
    validate_probe_chain,
    validate_spec,
)

VALID_SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/",
                        "unit_id": "service:web:soupmarket"},
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
    # The L1 service/system identifier must surface alongside the url (#197).
    spec = {**VALID_SPEC,
            "target_identity": {"url": "http://soupmarket.shop/",
                                "unit_id": "service:web:soupmarket"}}
    assert validate_spec(spec) == []
    # unit_id is carried but NOT init-gated: absence degrades, never rejects.
    spec_no_unit = {**VALID_SPEC,
                    "target_identity": {"url": "http://soupmarket.shop/"}}
    assert validate_spec(spec_no_unit) == []


def test_empty_payload_vector_space_is_valid_o12():
    # O12: an empty payload vector does NOT zero the loop - the default probe
    # still runs, so an empty (but well-typed) vector is not a schema violation.
    spec = {**VALID_SPEC, "payload_vector_space": {}}
    assert validate_spec(spec) == []


def test_dict_with_arbitrary_unknown_layer_keys_passes_init():
    # Contract (#191): payload_vector_space is ONE open dict - typed canonical
    # attributes (method/path/parameter/body) plus ANY per-attack-layer keys
    # (origin, headers, cookies, ...). There is NO validation layer: the pod
    # must not reject for missing canonical keys nor restrict unknown keys -
    # the ONLY shape rule is "must be a dict".
    spec = {**VALID_SPEC, "payload_vector_space": {
        "method": "POST",
        "path": "/state-change",
        "parameter": "role",
        "body": "role=admin",
        "origin": "attacker.site",
        "headers": {"X-Custom": "1"},
        "cookies": {"session": "attacker"},
    }}
    assert validate_spec(spec) == []
    # a dict missing ALL canonical keys is equally valid (no validation layer)
    spec_no_canonical = {**VALID_SPEC, "payload_vector_space": {
        "origin": "attacker.site", "headers": {"X-Custom": "1"}}}
    assert validate_spec(spec_no_canonical) == []


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
