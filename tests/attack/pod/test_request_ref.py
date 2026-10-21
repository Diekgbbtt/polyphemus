"""#196/S5 8.5: the baseline replay contract on the reduced D4.

The replay capability stays after the payload vector space retires: `baseline_ref`
is a single optional artifact pointer carried in `spec["provenance"]`, the runner
authors a `ProbeStep` with `request_ref`, and the replay tool resolves it at
runtime. The INIT gate never ranges over the nested replay shape.
"""
from __future__ import annotations

from polymerhus.attack.hunting.pod.symbolic import author_probe_from_spec
from polymerhus.attack.hunting.pod.types import ProbeChain, ProbeStep
from polymerhus.attack.hunting.pod.verification import validate_probe_chain, validate_spec

BASELINE = "http_01J0000000000000000000000A"

_SPEC = {
    "target_identity": {"url": "http://target.example/", "unit_id": "service:web:t"},
    "verification_symptoms": ["HTTP 403 on GET /admin"],
    "provenance": {"loop_id": "loop-1", "baseline_ref": BASELINE},
}


def test_probe_step_carries_request_ref_and_overrides():
    step = ProbeStep(request_ref=BASELINE, overrides={"query": {"q": "1"}})
    assert step.request_ref == BASELINE
    assert step.overrides == {"query": {"q": "1"}}
    assert ProbeStep().request_ref == "" and ProbeStep().overrides == {}


def test_the_baseline_ref_authors_a_replay_chain():
    chain = author_probe_from_spec(_SPEC, "v0")
    core = next(s for s in chain.steps if s.role == "core")
    assert core.request_ref == BASELINE
    assert core.overrides == {}
    assert chain.signature
    assert validate_probe_chain(chain) == []


def test_without_a_baseline_the_runner_authors_the_target_probe():
    chain = author_probe_from_spec(
        {**_SPEC, "provenance": {"loop_id": "loop-1"}}, "v0")
    assert chain.steps[0].request_ref == ""
    assert chain.steps[0].url == "http://target.example/"


def test_validate_spec_does_not_range_over_the_retired_vector():
    # The gate's mandatory set is exactly the URL and the symptoms; the retired
    # field is rejected as unknown, never re-validated as a nested shape.
    assert validate_spec(_SPEC) == []
    retired = {**_SPEC, "payload_vector_space": {"request_ref": BASELINE}}
    assert any("payload_vector_space" in v for v in validate_spec(retired))


def test_validate_probe_chain_accepts_a_reference_step():
    chain = ProbeChain(variant_ref="v0", steps=[ProbeStep(request_ref=BASELINE)])
    assert validate_probe_chain(chain) == []
    assert validate_probe_chain(
        ProbeChain(variant_ref="v0", steps=[ProbeStep()])
    ) == ["a probe step has neither a url nor a command"]
