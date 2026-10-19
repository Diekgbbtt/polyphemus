"""The production runner can execute a spec's baseline replay (S5 8.5).

`provenance.baseline_ref` names one recorded artifact; the runner's `replay`
tool resolves it through the pod's replay seam. A replay is a probe execution:
it is recorded RAM as a `RawObservation` (G4) when the run's D6 log is bound,
so the critic sees the observed status like any other probe.
"""
from __future__ import annotations

import json

from polymerhus.attack.hunting.pod.agents import runner_react_tools
from polymerhus.attack.hunting.pod.context import ExperimentLog

BASELINE = "http_01J0000000000000000000000A"


def _tools(**kwargs):
    kwargs.setdefault("log", None)
    kwargs.setdefault("variant_ref", "v0")
    return {
        tool.name: tool
        for tool in runner_react_tools(
            exec_fn=lambda *a, **k: None,
            memory_store=None, spec_id="s", **kwargs,
        )
    }


def test_replay_tool_is_absent_without_the_seam():
    assert "replay" not in _tools()


def test_replay_tool_returns_the_status_of_the_new_artifact():
    seen = {}

    def replay_fn(project_id, artifact_id, overrides):
        seen["args"] = (project_id, artifact_id, overrides)
        return {"status": 200, "artifact_id": "http_NEW"}

    tools = _tools(replay_fn=replay_fn, project_id="proj-1")
    out = json.loads(tools["replay"].invoke(
        {"artifact_id": "http_OLD", "overrides": {"query": {"q": "x"}}}
    ))
    assert out["status"] == 200
    assert seen["args"] == ("proj-1", "http_OLD", {"query": {"q": "x"}})


def test_replay_tool_reports_a_missing_reference_as_null_status():
    tools = _tools(replay_fn=lambda *a: {"status": None}, project_id="proj-1")
    out = json.loads(tools["replay"].invoke({"artifact_id": "http_MISSING"}))
    assert out["status"] is None


def test_replay_records_the_observed_status_in_the_d6_log():
    log = ExperimentLog()

    def replay_fn(project_id, artifact_id, overrides):
        return {"status": 403, "artifact_id": "http_NEW"}

    tools = _tools(replay_fn=replay_fn, project_id="proj-1",
                   log=log, variant_ref="v0")
    json.loads(tools["replay"].invoke({"artifact_id": BASELINE}))

    assert len(log.raw_observations) == 1
    obs = log.raw_observations[0]
    assert obs.variant_ref == "v0"
    assert obs.status == 403
    assert obs.request["artifact_id"] == BASELINE
    assert obs.http_artifact_refs == ["http_NEW"]
    assert obs.probe_ref in log.executed


def test_a_missing_baseline_is_recorded_as_an_unobservable_response():
    log = ExperimentLog()
    tools = _tools(replay_fn=lambda *a: {"status": None}, project_id="proj-1",
                   log=log, variant_ref="v0")
    json.loads(tools["replay"].invoke({"artifact_id": "http_MISSING"}))
    assert log.raw_observations[0].status is None
    assert log.raw_observations[0].returncode == 1
