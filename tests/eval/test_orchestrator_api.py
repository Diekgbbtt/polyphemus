"""The thin REST client seam for the trial engine (ticket #270).

`ApiCall`/`ApiRunner` mirror `commands.Command`/`CommandRunner`: the trial
builds an `ApiCall` and the injected runner performs it. The builders encode
the ph.py payload/polling semantics; the parsers read the wire shapes. Plan
mode prints `ApiCall.display()` and never constructs a runner.
"""
from __future__ import annotations

import json

import pytest

from orchestrator import api


def test_call_builders_encode_the_ph_py_semantics() -> None:
    assert api.create_project("eval-t1") == api.ApiCall(
        "POST", "/projects", {"name": "eval-t1"}
    )
    assert api.put_settings("p", {"target_seed": "t.test"}) == api.ApiCall(
        "PUT", "/projects/p/settings", {"recon": {"target_seed": "t.test"}}
    )
    assert api.seed_auth("p", overview="sign in", accounts=[{"name": "a"}]) == api.ApiCall(
        "PUT", "/projects/p/auth", {"overview": "sign in", "accounts": [{"name": "a"}]}
    )
    assert api.read_auth("p") == api.ApiCall("GET", "/projects/p/auth")
    assert api.launch_recon("p", with_analysis=True, jobs=["crawl"]) == api.ApiCall(
        "POST", "/projects/p/recon", {"with_analysis": True, "jobs": ["crawl"]}
    )
    assert api.launch_recon("p", with_analysis=False) == api.ApiCall(
        "POST", "/projects/p/recon", {"with_analysis": False}
    )
    assert api.launch_analysis("p", "r1") == api.ApiCall(
        "POST", "/projects/p/analysis", {"run_id": "r1"}
    )
    assert api.launch_hunting("p") == api.ApiCall(
        "POST", "/projects/p/hunting", {"candidates": []}
    )
    assert api.stop_hunting("p", "h1") == api.ApiCall(
        "POST", "/projects/p/hunting/h1/stop"
    )
    assert api.recon_status("p", "r1") == api.ApiCall("GET", "/projects/p/recon/r1")
    assert api.hunting_status("p", "h1") == api.ApiCall("GET", "/projects/p/hunting/h1")
    assert api.analysis_status("p", "r1") == api.ApiCall("GET", "/projects/p/analysis/r1")
    assert api.project_graph("p") == api.ApiCall("GET", "/projects/p/graph")
    assert api.list_projects() == api.ApiCall("GET", "/projects")


def test_call_display_renders_method_path_and_body() -> None:
    call = api.create_project("eval-t1")
    assert call.display() == 'POST /projects json={"name": "eval-t1"}'
    assert api.recon_status("p", "r1").display() == "GET /projects/p/recon/r1"


def test_response_parsers_read_the_wire_shapes() -> None:
    assert api.project_id_of({"project_id": "pid"}) == "pid"
    assert api.run_id_of({"run_id": "r1"}) == "r1"
    assert api.hunting_run_id_of({"hunting_run_id": "h1"}) == "h1"
    assert api.analysis_run_id_of({"analysis_run_id": "a1"}) == "a1"
    assert api.project_ids({"projects": [{"project_id": "a"}, {"project_id": "b"}]}) == [
        "a",
        "b",
    ]
    assert api.status_of({"status": "complete"}) == "complete"
    assert api.status_of({}) is None
    assert api.per_job_rows({"per_job": [{"job": "crawl"}]}) == [{"job": "crawl"}]
    assert api.per_job_rows({}) == []


def test_terminal_vocabularies_match_the_repository() -> None:
    assert api.RECON_TERMINAL == frozenset({"complete", "failed"})
    assert api.HUNTING_TERMINAL == frozenset(
        {"complete", "stopped", "failed", "interrupted"}
    )
    assert api.ANALYSIS_TERMINAL == frozenset(
        {"drained", "withheld", "stopped", "interrupted"}
    )
    assert api.recon_terminal("complete") and not api.recon_terminal("running")
    assert api.hunting_terminal("stopped") and not api.hunting_terminal("running")
    assert api.analysis_terminal("drained") and not api.analysis_terminal("draining")


def test_graph_counts_classifies_l0_l1_and_observations() -> None:
    graph = {
        "nodes": [
            {"type": "L1Service"},
            {"type": "L1Service"},
            {"type": "L1System"},
            {"type": "Endpoint"},
            {"type": "BaseURL"},
            {"type": "Parameter"},
            {"type": "Observation"},
            {"type": None},
        ]
    }
    counts = api.graph_counts(graph)
    assert counts == api.GraphCounts(l0=3, l1=3, services=2, observations=1)


def test_graph_counts_tolerates_a_degenerate_graph() -> None:
    assert api.graph_counts(None) == api.GraphCounts(0, 0, 0, 0)
    assert api.graph_counts({}) == api.GraphCounts(0, 0, 0, 0)


# --- the real HTTP runner -----------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_http_runner_posts_json_and_decodes_the_body(monkeypatch) -> None:
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["body"] = request.data
        return _FakeResponse(json.dumps({"project_id": "pid"}).encode())

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)
    runner = api.HttpApiRunner("http://api.test:8080")

    result = runner(api.create_project("eval-t1"))

    assert result == {"project_id": "pid"}
    assert seen["url"] == "http://api.test:8080/projects"
    assert seen["method"] == "POST"
    assert json.loads(seen["body"]) == {"name": "eval-t1"}


def test_http_runner_raises_api_error_on_http_failure(monkeypatch) -> None:
    import urllib.error

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, _Reader(b'{"detail": "unknown"}')
        )

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)
    runner = api.HttpApiRunner("http://api.test:8080")

    with pytest.raises(api.ApiError, match="404"):
        runner(api.recon_status("p", "r1"))


class _Reader:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        return None
