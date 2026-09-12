"""#196 hunting contract: request_ref inside the open payload_vector_space."""
from __future__ import annotations

from polymerhus.attack.hunting.hunting_pod import HuntingHttpPod
from polymerhus.attack.hunting.pod.symbolic import (
    default_probe_from_spec,
    mutations_from_pvs,
)
from polymerhus.attack.hunting.pod.types import ProbeChain, ProbeStep
from polymerhus.attack.hunting.pod.verification import validate_probe_chain, validate_spec

_SPEC = {
    "target_identity": {"url": "http://target.example/", "unit_id": "service:web:t"},
    "verification_symptoms": ["HTTP 200 with a non-empty body"],
    "testing_pattern": "authz",
    "payload_vector_space": {
        "request_ref": "http_01J0000000000000000000000A",
        "mutations": [
            {"location": "query", "name": "search", "values": ["'", "' OR 1=1--"]}
        ],
    },
}

# HuntingHttpPod consumes the nested D4 envelope (`d4_typed_base`).
_POD_SPEC = {"d4_typed_base": _SPEC}


def test_probe_step_carries_request_ref_and_overrides():
    step = ProbeStep(request_ref="http_01J0000000000000000000000A", overrides={"query": {"q": "1"}})
    assert step.request_ref == "http_01J0000000000000000000000A"
    assert step.overrides == {"query": {"q": "1"}}
    assert ProbeStep().request_ref == "" and ProbeStep().overrides == {}


def test_mutations_are_parsed_into_overrides():
    overrides = mutations_from_pvs(_SPEC["payload_vector_space"])
    assert overrides == [{"query": {"search": "'"}}, {"query": {"search": "' OR 1=1--"}}]


def test_default_probe_from_spec_builds_a_reference_chain():
    chain = default_probe_from_spec(_SPEC, "v0")
    core = next(s for s in chain.steps if s.role == "core")
    assert core.request_ref == "http_01J0000000000000000000000A"
    assert core.overrides == {"query": {"search": "'"}}
    assert chain.signature


def test_inline_no_defaulting_from_191_is_untouched():
    spec = {**_SPEC, "payload_vector_space": {"method": "GET", "body": "x"}}
    assert default_probe_from_spec(spec, "v0") is None
    inline = default_probe_from_spec(
        {**_SPEC, "payload_vector_space": {"method": "GET", "path": "/a"}}, "v0"
    )
    assert inline.steps[0].url == "/a"


def test_validate_spec_still_only_requires_a_dict():
    assert validate_spec(_SPEC) == []
    bad = {**_SPEC, "payload_vector_space": ["not", "a", "dict"]}
    assert any("payload_vector_space" in v for v in validate_spec(bad))


def test_validate_probe_chain_accepts_a_reference_step():
    chain = ProbeChain(variant_ref="v0", steps=[ProbeStep(request_ref="http_01J0000000000000000000000A")])
    assert validate_probe_chain(chain) == []
    assert validate_probe_chain(
        ProbeChain(variant_ref="v0", steps=[ProbeStep()])
    ) == ["a probe step has neither a url nor a command"]


def _replay_fn(statuses):
    def replay(project_id, artifact_id, overrides):
        key = "baseline" if not overrides else str(sorted(overrides.items()))
        status = statuses.get(key)
        if status is None:
            return None
        return {"status": status, "artifact_id": artifact_id}

    return replay


def test_request_ref_produces_a_replay_probe():
    def _key(override):
        return str(sorted(override.items()))

    statuses = {
        "baseline": 403,
        _key({"query": {"search": "'"}}): 400,
        _key({"query": {"search": "' OR 1=1--"}}): 200,
    }
    pod = HuntingHttpPod(
        replay_fn=_replay_fn(statuses), project_id="proj-1", transport=object()
    )
    out = pod(_POD_SPEC)
    assert out["verdict"] == "successful"
    assert out["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert "init_validation" not in out["evidence"]


def test_unresolvable_request_ref_is_technical_infeasibility_not_init():
    pod = HuntingHttpPod(replay_fn=lambda *a: None, project_id="proj-1")
    out = pod(_POD_SPEC)
    assert out["verdict"] == "unsuccessful"
    assert out["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert "init_validation" not in out["evidence"]


def test_missing_replay_capability_is_technical_infeasibility():
    pod = HuntingHttpPod(project_id="proj-1")
    out = pod(_POD_SPEC)
    assert out["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert "init_validation" not in out["evidence"]
