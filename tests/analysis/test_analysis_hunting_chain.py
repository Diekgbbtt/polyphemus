"""The drained-analysis -> hunting chain trigger (app side).

An analysis consumer that genuinely drains (`drained`, never `withheld`/`stopped`)
and whose project has the chain ON (opt-in; `settings.recon.hunt_after_analysis`)
chains ONE hunting run
through the SAME operator-intent launch seam the REST
`POST /projects/{id}/hunting` rides. The trigger is fail-open loudly: a missing
control plane or a refused launch is logged, never raised into the supervisor.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from polymerhus.analysis import lifecycle
from polymerhus.analysis.feed import resolve_hunt_after_analysis


def _run(coro):
    return asyncio.run(coro)


def test_the_chain_flag_defaults_off_and_can_be_opted_in():
    # The chain is opt-in: an absent/None/`false` value is OFF; an explicit
    # `true` enables it.
    assert resolve_hunt_after_analysis(None) is False
    assert resolve_hunt_after_analysis({}) is False
    assert resolve_hunt_after_analysis({"hunt_after_analysis": False}) is False
    assert resolve_hunt_after_analysis({"hunt_after_analysis": True}) is True


class _Recorder:
    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, project_id, body):
        self.calls.append((project_id, body))
        return {"hunting_run_id": "h1"}


def _patch(monkeypatch, *, available=True, recorder=None, error=None):
    import polymerhus.attack.hunting.runtime as hunting_runtime
    import polymerhus.project_management.api as pm_api

    monkeypatch.setattr(
        hunting_runtime, "hunting_control_plane_available", lambda: available
    )
    if error is not None:
        async def _launch(project_id, body):
            raise error

        monkeypatch.setattr(pm_api, "launch_hunting", _launch)
    else:
        async def _launch(project_id, body):
            await recorder(project_id, body)

        monkeypatch.setattr(pm_api, "launch_hunting", _launch)


def test_a_drained_analysis_launches_hunting(monkeypatch):
    recorder = _Recorder()
    _patch(monkeypatch, recorder=recorder)

    _run(lifecycle._chain_hunting_on_drained("p1", "r1", "drained", enabled=True))

    assert [project for project, _ in recorder.calls] == ["p1"]


def test_an_unenabled_project_does_not_launch(monkeypatch):
    recorder = _Recorder()
    _patch(monkeypatch, recorder=recorder)

    _run(lifecycle._chain_hunting_on_drained("p1", "r1", "drained", enabled=False))

    assert recorder.calls == []


@pytest.mark.parametrize("status", ["withheld", "stopped", "interrupted", "failed"])
def test_a_non_drained_terminal_does_not_launch(monkeypatch, status):
    recorder = _Recorder()
    _patch(monkeypatch, recorder=recorder)

    _run(lifecycle._chain_hunting_on_drained("p1", "r1", status, enabled=True))

    assert recorder.calls == []


def test_a_missing_control_plane_does_not_launch(monkeypatch):
    recorder = _Recorder()
    _patch(monkeypatch, available=False, recorder=recorder)

    _run(lifecycle._chain_hunting_on_drained("p1", "r1", "drained", enabled=True))

    assert recorder.calls == []


def test_a_refused_launch_fails_open(monkeypatch):
    # The one-live-run-per-project guard refuses a relaunch with 409; the
    # trigger must swallow it and never crash the analysis supervisor.
    _patch(monkeypatch, error=HTTPException(status_code=409, detail="live run"))

    _run(lifecycle._chain_hunting_on_drained("p1", "r1", "drained", enabled=True))
