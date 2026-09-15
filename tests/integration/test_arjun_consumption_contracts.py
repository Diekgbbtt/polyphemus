"""Contract predicates (integration tier) for #37 - arjun consumption set.

Mechanises the #37 assertion catalogue at the COMPILED dispatch seam -
`run_job` (the real compiled job-agent graph + real `default_preprocess_fn`,
injected recording pod_invoke). They touch NO Neo4j (the endpoint population
enters as a plain list); expected values come from the grilling record, never
recomputed from the code.

These gate the verifier and are NOT selected by the tdd unit red/green loop
(the unit tier drives the same mechanics during the loop; this tier is the
gate's copy of the contract, at the compiled seam).

- C1 - cluster dispatch: arjun pods == distinct route clusters, NOT endpoints.
- C2 - junk exclusion: concat-fragment paths never reach a pod.
- C3 - empty population -> zero pods (job would be "skipped").
- C4 - restapi-first ordering at the compiled seam (ordering, never exclusion).
- C5 - auth threading: every pod's extra carries the auth context (P5).
- C6 - fail-open: a derivation error degrades to capped raw pods, never raises.
"""
import asyncio
import logging

from polymerhus.recon.control import batching as batching_module
from polymerhus.recon.control import job_agent as ja
from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.types import PodExport


def _make_recording_pod_invoke():
    calls: list[dict] = []

    def pod_invoke(pod_input, job, run_id, phase):
        calls.append(pod_input)
        return PodExport(input_asset=pod_input["input_asset"], verdict="success")

    pod_invoke.calls = calls
    return pod_invoke


def _run_arjun(pod_invoke, assets, extra=None):
    agent = ja.build_job_agent(pod_invoke=pod_invoke,
                               preprocess_fn=ja.default_preprocess_fn)
    asyncio.run(ja.run_job(
        JOBS["arjun"], assets, run_id="arjun-c", phase=7,
        extra=extra or {}, agent=agent,
    ))


def _ep(path, **kw):
    base = {"url": f"https://h{path}", "baseurl": "https://h", "path": path,
            "method": "GET"}
    base.update(kw)
    return base


# --- C1: pods == distinct route clusters --------------------------------------

def test_C1_arjun_pods_equal_route_clusters_not_endpoints(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 20)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    pod_invoke = _make_recording_pod_invoke()
    _run_arjun(pod_invoke, [
        _ep("/users/1"), _ep("/users/2"), _ep("/users/3"),
        _ep("/api/orders", profile="restapi"),
    ])
    assert sorted(pi["input_asset"]["path"] for pi in pod_invoke.calls) == [
        "/api/orders", "/users/1"]


# --- C2: junk paths never reach a pod ------------------------------------------

def test_C2_concat_fragment_junk_never_reaches_a_pod(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 20)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    pod_invoke = _make_recording_pod_invoke()
    _run_arjun(pod_invoke, [_ep("/api/users"), _ep("/'+_(i[8])+'")])
    assert [pi["input_asset"]["path"] for pi in pod_invoke.calls] == ["/api/users"]


# --- C3: empty population -> zero pods -----------------------------------------

def test_C3_empty_set_dispatches_zero_pods(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 20)
    pod_invoke = _make_recording_pod_invoke()
    _run_arjun(pod_invoke, [])
    assert pod_invoke.calls == []


# --- C4: restapi-first ordering (ordering, never exclusion) --------------------

def test_C4_restapi_orders_first_without_excluding(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 20)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    pod_invoke = _make_recording_pod_invoke()
    _run_arjun(pod_invoke, [
        _ep("/page", profile="webapp"),
        _ep("/api/a", profile="restapi"),
        _ep("/plain"),
    ])
    # The Send fan-out completes pods concurrently, so arrival order is not
    # dispatch order: assert the ordering property on the preprocess seam
    # (unit tier pins the exact sequence) plus full-set survival here.
    assert sorted(pi["input_asset"]["path"] for pi in pod_invoke.calls) == [
        "/api/a", "/page", "/plain"]
    ordered = ja.default_preprocess_fn(
        [_ep("/page", profile="webapp"),
         _ep("/api/a", profile="restapi"),
         _ep("/plain")], JOBS["arjun"], {}, "")
    assert [pi["input_asset"]["path"] for pi in ordered] == [
        "/api/a", "/page", "/plain"]


# --- C5: auth threading preserved (P5) ------------------------------------------

def test_C5_every_pod_carries_the_auth_context(monkeypatch):
    monkeypatch.setattr(ja, "MAX_PODS", 20)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    pod_invoke = _make_recording_pod_invoke()
    auth = {"cookies": "session=abc", "headers": {"X-T": "1"}}
    _run_arjun(pod_invoke, [_ep("/a"), _ep("/b")], extra={"auth_context": auth})
    assert len(pod_invoke.calls) == 2
    assert all(pi["extra"]["auth_context"] == auth for pi in pod_invoke.calls)


# --- C6: fail-open degradation (P6) ----------------------------------------------

def test_C6_derivation_error_degrades_to_capped_raw_pods(monkeypatch, caplog):
    def _boom(*args, **kwargs):
        raise RuntimeError("dedup exploded")

    monkeypatch.setattr(batching_module, "derive_consumption_set", _boom)
    monkeypatch.setattr(ja, "MAX_PODS", 20)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 2)
    pod_invoke = _make_recording_pod_invoke()
    with caplog.at_level(logging.WARNING,
                         logger="polymerhus.recon.control.job_agent"):
        _run_arjun(pod_invoke, [_ep("/a"), _ep("/b"), _ep("/c")])
    assert sorted(pi["input_asset"]["path"] for pi in pod_invoke.calls) == [
        "/a", "/b"]
    assert "derive_consumption_set failed" in caplog.text
