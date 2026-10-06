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
    assert api.read_auth("p") == api.ApiCall("GET", "/projects/p/auth")
    # The data-dependency placement builders are multipart file uploads.
    overview = api.place_auth_overview("p", b"overview: 1")
    assert overview.method == "POST"
    assert overview.path == "/projects/p/data-dependencies/auth-overview"
    assert overview.file == api.ApiFile("file", "overview.yaml", b"overview: 1")
    creds = api.place_auth_credentials("p", b"accounts: {}")
    assert creds.path == "/projects/p/data-dependencies/auth-credentials"
    assert creds.file.filename == "credentials.yaml"
    skill = api.place_authn_skill("p", b"\x1f\x8b-bundle")
    assert skill.path == "/projects/p/data-dependencies/authn-skill"
    assert skill.file.filename == "authn.tar.gz"
    l1 = api.place_l1("p", b"# kb\n")
    assert l1.path == "/projects/p/data-dependencies/l1"
    assert l1.file == api.ApiFile("file", "operator_kb.md", b"# kb\n")
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


def test_usage_and_stop_run_builders() -> None:
    assert api.usage("p") == api.ApiCall("GET", "/projects/p/usage")
    assert api.stop_run("p", "recon", "r1") == api.ApiCall(
        "POST", "/projects/p/recon/r1/stop"
    )
    assert api.stop_run("p", "analysis", "a1") == api.ApiCall(
        "POST", "/projects/p/analysis/a1/stop"
    )
    assert api.stop_run("p", "hunting", "h1") == api.ApiCall(
        "POST", "/projects/p/hunting/h1/stop"
    )


def test_stop_run_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValueError, match="run_kind"):
        api.stop_run("p", "exploit", "x1")


def test_call_display_renders_method_path_and_body() -> None:
    call = api.create_project("eval-t1")
    assert call.display() == 'POST /projects json={"name": "eval-t1"}'
    assert api.recon_status("p", "r1").display() == "GET /projects/p/recon/r1"
    assert api.place_l1("p", b"# kb\n").display() == (
        "POST /projects/p/data-dependencies/l1 upload=operator_kb.md (5 bytes)"
    )


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


def test_usage_parsers_read_the_wire_shapes() -> None:
    by_agent = {
        "recon": {
            "input_tokens": 10,
            "output_tokens": 32,
            "total_tokens": 42,
            "calls": 3,
        }
    }
    response = {"project_id": "p", "total_tokens": 42, "capped_tokens": 17,
                "generated_tokens": {"reasoning": 20, "visible": 12},
                "calls": 3, "by_agent": by_agent}

    assert api.usage_total(response) == 42
    assert api.usage_generated(response) == 32  # reasoning + visible
    assert api.usage_capped(response) == 17
    assert api.usage_by_agent(response) == by_agent


def test_usage_parsers_default_when_absent_or_malformed() -> None:
    assert api.usage_total({}) == 0
    assert api.usage_total({"total_tokens": "many"}) == 0
    assert api.usage_total({"total_tokens": True}) == 0
    assert api.usage_total(None) == 0
    assert api.usage_capped({}) == 0
    assert api.usage_capped({"capped_tokens": "many"}) == 0
    assert api.usage_capped({"capped_tokens": True}) == 0
    assert api.usage_capped(None) == 0
    assert api.usage_generated({}) == 0
    assert api.usage_generated({"generated_tokens": "many"}) == 0
    assert api.usage_generated({"generated_tokens": True}) == 0
    assert api.usage_generated(None) == 0
    assert api.usage_generated({"generated_tokens": {"reasoning": 5, "visible": "x"}}) == 5
    assert api.usage_generated({"generated_tokens": {"reasoning": True}}) == 0
    assert api.usage_by_agent({}) == {}
    assert api.usage_by_agent({"by_agent": None}) == {}
    assert api.usage_by_agent({"by_agent": "nope"}) == {}
    assert api.usage_by_agent(None) == {}


def test_terminal_vocabularies_match_the_repository() -> None:
    assert api.RECON_TERMINAL == frozenset({"complete", "failed", "stopped"})
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


def test_http_runner_posts_multipart_for_a_file_call(monkeypatch) -> None:
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["ctype"] = request.get_header("Content-type")
        seen["body"] = request.data
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)
    runner = api.HttpApiRunner("http://api.test:8080")

    result = runner(api.place_auth_overview("p", b"login: 1"))

    assert result == {"ok": True}
    assert seen["ctype"].startswith("multipart/form-data; boundary=")
    body = seen["body"]
    assert b'name="file"' in body
    assert b'filename="overview.yaml"' in body
    assert b"login: 1" in body


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
