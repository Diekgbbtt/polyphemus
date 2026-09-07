"""Contract predicates (integration tier) for #208 - httpx_reprofile: one pod.

Mechanises C1-C7 of the assertion catalogue attached to #208. These range over
the COMPILED dispatch seam - `run_job` (the real compiled job-agent graph + real
`default_preprocess_fn`, injected recording pod_invoke) and the real pod graph's
configurator/triager seams. They touch NO Neo4j (the reprofile dispatch is pure:
the endpoint population enters as a plain list); expected values come from the
#208 spec and the D16 dedup semantics, never recomputed from the code.

These gate the verifier and are NOT selected by the tdd unit red/green loop
(the unit tier drives the same mechanics during the loop; this tier is the
gate's copy of the contract, at the compiled seam).
"""
import asyncio

from polymerhus.recon.control import job_agent as ja
from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain import pod
from polymerhus.recon.domain.types import ExecResult, PodExport


def _make_recording_pod_invoke():
    calls: list[dict] = []

    def pod_invoke(pod_input, job, run_id, phase):
        calls.append(pod_input)
        return PodExport(input_asset=pod_input["input_asset"], verdict="success")

    pod_invoke.calls = calls
    return pod_invoke


def _reprofile_assets():
    return [
        {"url": "https://h/api/v1/users/1", "baseurl": "https://h", "path": "/api/v1/users/1"},
        {"url": "https://h/api/v1/users/2", "baseurl": "https://h", "path": "/api/v1/users/2"},
        {"url": "https://h/api/v1/orders", "baseurl": "https://h", "path": "/api/v1/orders"},
    ]


# --- C1: exactly ONE pod regardless of endpoint count -------------------------

def test_C1_reprofile_dispatches_exactly_one_pod(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 1000)
    pod_invoke = _make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    asyncio.run(ja.run_job(
        JOBS["httpx_reprofile"], _reprofile_assets(), run_id="c1", phase=6, extra={},
        agent=agent,
    ))

    assert len(pod_invoke.calls) == 1  # ONE pod regardless of endpoint count


# --- C2: the D16 dedup iteration set rides along unchanged --------------------

def test_C2_dedup_iteration_set_rides_along(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 1000)
    pod_invoke = _make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    asyncio.run(ja.run_job(
        JOBS["httpx_reprofile"], _reprofile_assets(), run_id="c2", phase=6, extra={},
        agent=agent,
    ))

    endpoints = pod_invoke.calls[0]["input_asset"]["endpoints"]
    # /users/1 and /users/2 collapse to one representative; root `/` materialised
    paths = sorted(e.get("path") or "/" for e in endpoints)
    assert paths == ["/", "/api/v1/orders", "/api/v1/users/1"]


# --- C3: empty population -> zero pods (job would be "skipped") ----------------

def test_C3_empty_set_dispatches_zero_pods(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    pod_invoke = _make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    asyncio.run(ja.run_job(
        JOBS["httpx_reprofile"], [], run_id="c3", phase=6, extra={}, agent=agent,
    ))

    assert pod_invoke.calls == []  # nothing to enrich -> skipped, no pod


# --- C4: the pod pays ONE exec + ONE triager turn over the whole set ----------

def test_C4_real_pod_graph_pays_one_exec_and_one_triage_turn():
    exec_calls: list[str] = []
    triage_calls: list = []

    def exec_fn(cmd, sid, t):
        exec_calls.append(cmd)
        return ExecResult(
            stdout=(
                '{"url":"https://h/api/v1/orders","input":"https://h/api/v1/orders",'
                '"status_code":200,"content_type":"application/json"}\n'
                '{"url":"https://h/","input":"https://h/","status_code":200,'
                '"content_type":"text/html"}'
            ),
            stderr="", returncode=0, duration_ms=5,
        )

    def triage_fn(er, assets, job):
        triage_calls.append(er)
        return []

    g = pod.build_pod_graph(
        exec_fn=exec_fn, curate_fn=lambda a, o, p: (len(a), len(o), a, o),
        triage_fn=triage_fn,
    )
    out = g.invoke({
        "job": JOBS["httpx_reprofile"],
        "input_asset": {"endpoints": [
            {"url": "https://h/api/v1/orders", "baseurl": "https://h", "path": "/api/v1/orders"},
            {"url": "https://h/", "baseurl": "https://h", "path": "/"},
        ]},
        "asset_context": "", "extra": {}, "session_id": "c4", "iteration": 0,
        "project_id": "proj-c4",
    })

    assert out["export"].verdict == "success"
    assert len(exec_calls) == 1      # one exec over the whole `-l` list
    assert len(triage_calls) == 1    # O(1) triager turns per job, not O(N)
    assert "httpx -l" in exec_calls[0]
    assert out["export"].stats.get("endpoints_total") == 2


# --- C5: a triager failure degrades; the parsed profiles still curate ---------

def test_C5_triager_failure_degrades_but_profiles_still_curate():
    captured = {}

    def exec_fn(cmd, sid, t):
        return ExecResult(stdout=(
            '{"url":"https://h/api/v1/orders","input":"https://h/api/v1/orders",'
            '"status_code":200,"content_type":"application/json"}'
        ), stderr="", returncode=0, duration_ms=5)

    def curate_fn(assets, obs, pid):
        captured["assets"] = assets
        captured["observations"] = obs
        return (len(assets), len(obs), assets, obs)

    def triage_fn(er, assets, job):
        raise RuntimeError("triager blackloop")

    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({
        "job": JOBS["httpx_reprofile"],
        "input_asset": {"endpoints": [
            {"url": "https://h/api/v1/orders", "baseurl": "https://h", "path": "/api/v1/orders"},
        ]},
        "asset_context": "", "extra": {}, "session_id": "c5", "iteration": 0,
        "project_id": "proj-c5",
    })

    assert out["export"].verdict == "success"  # production never dies with consumption
    assert captured["observations"] == []
    assert captured["assets"]                 # profiles still reach the curator


# --- C6: auth threads into the single exec (use_auth unchanged) ---------------

def test_C6_auth_threaded_into_the_single_exec():
    captured: dict = {}

    def exec_fn(cmd, sid, t):
        captured["cmd"] = cmd
        return ExecResult(stdout="", stderr="", returncode=0, duration_ms=5)

    g = pod.build_pod_graph(
        exec_fn=exec_fn, curate_fn=lambda a, o, p: (len(a), len(o), a, o),
        triage_fn=lambda er, a, j: [],
    )
    g.invoke({
        "job": JOBS["httpx_reprofile"],
        "input_asset": {"endpoints": [
            {"url": "https://h/api/v1/orders", "baseurl": "https://h", "path": "/api/v1/orders"},
        ]},
        "asset_context": "",
        "extra": {"auth_context": {"cookies": [{"name": "s", "value": "v"}]}},
        "session_id": "c6", "iteration": 0, "project_id": "proj-c6",
    })

    assert "-H 'Cookie: s=v'" in captured["cmd"]  # auth threaded into the single exec


# --- C7: the asset budget caps the probe SET, not the pod count ---------------

def test_C7_asset_budget_caps_the_probe_set_not_the_pod_count(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 5)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 2)
    pod_invoke = _make_recording_pod_invoke()
    agent = ja.build_job_agent(pod_invoke=pod_invoke, preprocess_fn=ja.default_preprocess_fn)

    assets = [
        {"url": f"https://h/p{i}", "baseurl": "https://h", "path": f"/p{i}"}
        for i in range(10)
    ]
    asyncio.run(ja.run_job(
        JOBS["httpx_reprofile"], assets, run_id="c7", phase=6, extra={}, agent=agent,
    ))

    assert len(pod_invoke.calls) == 1
    assert len(pod_invoke.calls[0]["input_asset"]["endpoints"]) == 2