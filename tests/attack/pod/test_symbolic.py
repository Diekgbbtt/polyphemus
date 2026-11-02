"""Unit tier: the helper symbolic layer - the runner's authored probe, the dedup
signature, and the minimal symptom recogniser (the differential is gone, D84-30).

T8 (#381): with the payload vector space retired, the probe is AUTHORED from the
reduced spec - the optional `provenance.baseline_ref` first (a replay probe),
otherwise a GET of `target_identity.url` (S5 8.5). No probe derivable is a real
outcome, never an invented request.
"""
from polymerhus.attack.hunting.pod.symbolic import (
    author_probe_from_spec,
    evaluate_symptom,
    probe_signature,
)
from polymerhus.attack.hunting.pod.types import (
    INFEASIBILITY_SIGNAL_CLASS,
    RawObservation,
    SYMPTOM_ABSENT_CLASS,
    SYMPTOM_CONFIRMED_CLASS,
)

BASELINE = "http_01J0000000000000000000000A"

SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/",
                        "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "assumptions": ["network egress allowed"],
    "rationale": "reachability",
    "provenance": {"threat_id": "threat-1", "unit_id": "service:web:soupmarket",
                   "canonical_class": "IDOR", "web_vulnerability_class": "idor"},
}

BASELINE_SPEC = {**SPEC, "provenance": {**SPEC["provenance"],
                                        "baseline_ref": BASELINE}}


def test_the_runner_authors_a_probe_from_the_target_identity():
    chain = author_probe_from_spec(SPEC, "v0")
    assert chain is not None
    core = chain.steps[0]
    assert core.role == "core"
    assert core.method == "GET" and core.url == "http://soupmarket.shop/"
    assert core.request_ref == ""
    assert chain.variant_ref == "v0" and chain.signature


def test_the_baseline_ref_authors_a_replay_probe():
    # S5 8.5: when the hunter names a recorded baseline, the pod replays that
    # artifact instead of authoring the request from scratch.
    chain = author_probe_from_spec(BASELINE_SPEC, "v0")
    assert chain is not None
    core = chain.steps[0]
    assert core.role == "core" and core.request_ref == BASELINE
    assert core.url == ""
    assert chain.signature
    # A replay probe and a fresh URL probe are distinct executions (O7/C10).
    assert chain.signature != author_probe_from_spec(SPEC, "v0").signature


def test_no_probe_is_derivable_without_a_target_url_or_a_baseline():
    assert author_probe_from_spec({**SPEC, "target_identity": {}}, "v0") is None
    assert author_probe_from_spec({**SPEC, "target_identity": {"unit_id": "svc"}},
                                  "v0") is None
    assert author_probe_from_spec({}, "v0") is None


def test_probe_signature_is_stable_and_variant_sensitive():
    a = author_probe_from_spec(SPEC, "v0")
    b = author_probe_from_spec(SPEC, "v0")
    c = author_probe_from_spec(SPEC, "v1")
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
