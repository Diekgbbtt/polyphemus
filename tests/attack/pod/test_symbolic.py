"""Unit tier: the helper symbolic layer - probe construction, the dedup
signature, and the minimal symptom recogniser (the differential is gone, D84-30)."""
from polymerhus.attack.hunting.pod.symbolic import (
    default_probe_from_spec,
    evaluate_symptom,
    probe_signature,
)
from polymerhus.attack.hunting.pod.types import (
    INFEASIBILITY_SIGNAL_CLASS,
    RawObservation,
    SYMPTOM_ABSENT_CLASS,
    SYMPTOM_CONFIRMED_CLASS,
)

SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "payload_vector_space": {"method": "GET", "path": "/"},
}


def test_default_probe_built_from_vector_space():
    chain = default_probe_from_spec(SPEC, "v0")
    assert chain is not None
    core = chain.steps[0]
    assert core.role == "core" and core.method == "GET" and core.url == "/"


def test_empty_payload_vector_still_yields_a_default_probe_o12():
    # O12: an empty payload vector must not zero the loop - a default probe of
    # the target root is still derived.
    chain = default_probe_from_spec({**SPEC, "payload_vector_space": {}}, "v0")
    assert chain is not None
    assert chain.steps[0].url == "/"


def test_non_empty_vector_missing_method_or_path_yields_no_probe():
    # contract (#191): NO defaulting for any attribute - a NON-empty vector that
    # does not carry the authored method AND path yields None (never an invented
    # GET, never a url/identity-derived path); only the EMPTY dict gets the O12
    # default probe.
    for pvs in ({"path": "/api"}, {"method": "GET"}, {"url": "/api"}):
        assert default_probe_from_spec({**SPEC, "payload_vector_space": pvs}, "v0") is None


def test_probe_signature_is_stable_and_variant_sensitive():
    a = default_probe_from_spec(SPEC, "v0")
    b = default_probe_from_spec(SPEC, "v0")
    c = default_probe_from_spec(SPEC, "v1")
    assert probe_signature(a) == probe_signature(b)      # identical -> dedup
    assert probe_signature(a) != probe_signature(c)      # different variant -> distinct


def test_symbolic_symptom_confirmed_on_200_nonempty():
    obs = RawObservation(status=200, body="<html>market</html>")
    assert evaluate_symptom(SPEC["verification_symptoms"], obs) == SYMPTOM_CONFIRMED_CLASS


def test_symbolic_symptom_absent_on_wrong_status():
    obs = RawObservation(status=404, body="not found")
    assert evaluate_symptom(SPEC["verification_symptoms"], obs) == SYMPTOM_ABSENT_CLASS


def test_symbolic_symptom_absent_on_empty_body():
    obs = RawObservation(status=200, body="")
    assert evaluate_symptom(SPEC["verification_symptoms"], obs) == SYMPTOM_ABSENT_CLASS


def test_non_decidable_symptom_returns_none():
    obs = RawObservation(status=200, body="x")
    # A semantic symptom the recogniser cannot mechanically check -> defer to LLM.
    assert evaluate_symptom(["the response leaks another user's order id"], obs) is None


def test_missing_response_is_an_infeasibility_signal():
    obs = RawObservation(status=None, body="", returncode=7, stderr="connection refused")
    assert evaluate_symptom(SPEC["verification_symptoms"], obs) == INFEASIBILITY_SIGNAL_CLASS
