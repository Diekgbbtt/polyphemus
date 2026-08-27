"""Unit tier: the real hunting HTTP probing pod (`attack/hunting/hunting_pod.py`).

The pod is the IA-3/IA-4 executor: it takes the authored D4 spec and returns
the D5+D6 evidence envelope deterministically. Hermetic: every test injects an
`httpx.MockTransport`, so no live target is ever contacted.
"""
from __future__ import annotations

import httpx

from polymerhus.attack.hunting.hunting_pod import HuntingHttpPod


def _spec(*, target_url: str | None = None, payload: dict | None = None) -> dict:
    return {
        "d4_typed_base": {
            "target_identity": ({"url": target_url} if target_url else {}),
            "payload_vector_space": payload or {"method": "GET", "path": "/api/users/{id}"},
        }
    }


def _run(handler, spec) -> dict:
    pod = HuntingHttpPod(transport=httpx.MockTransport(handler))
    return pod(spec)


def test_pod_requires_target_url_without_network():
    pod = HuntingHttpPod()
    out = pod(_spec(target_url=None))
    assert out["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert out["evidence"]["init_validation"]
    assert out["verdict"] == "unsuccessful"


def test_pod_confirms_symptom_when_tampered_id_allowed_and_baseline_denied():
    def handler(request: httpx.Request) -> httpx.Response:
        if "124" in request.url.path:
            return httpx.Response(200, text="data")
        return httpx.Response(403, text="denied")

    out = _run(handler, _spec(target_url="https://target.test"))
    assert out["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert out["evidence"]["clean"] is True
    assert out["verdict"] == "successful"


def test_pod_reports_no_symptom_when_all_requests_denied():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    out = _run(handler, _spec(target_url="https://target.test"))
    assert out["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert out["evidence"]["clean"] is True
    assert out["verdict"] == "unsuccessful"


def test_pod_insufficient_evidence_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("target unreachable")

    out = _run(handler, _spec(target_url="https://target.test"))
    assert out["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert out["evidence"]["clean"] is False


def test_pod_rejects_unsupported_methods_with_init_validation():
    pod = HuntingHttpPod(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    out = pod(_spec(target_url="https://target.test", payload={"method": "POST", "path": "/api/users"}))
    assert out["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert out["evidence"]["init_validation"]


def test_pod_rejects_a_non_dict_payload_vector_space():
    pod = HuntingHttpPod(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    out = pod(_spec(target_url="https://target.test", payload=["GET /api/users"]))
    assert out["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert out["evidence"]["init_validation"]


def test_pod_rejects_a_dict_missing_method_or_path_without_defaulting():
    pod = HuntingHttpPod(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    # contract (#191): NO defaulting for any attribute - a dict that does not
    # carry BOTH a method and a path yields no vectors (an invented GET or a
    # url-derived path is never read).
    for payload in ({"path": "/api/users"}, {"method": "GET"}, {"url": "/api/users"}):
        out = pod(_spec(target_url="https://target.test", payload=payload))
        assert out["evidence"]["terminal_reason"] == "technical-infeasibility"
        assert any("payload_vector_space" in v for v in out["evidence"]["init_validation"])
