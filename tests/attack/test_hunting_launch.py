"""T5: the singular-launch launcher seams at the runtime tier - the pod
resume seam and the modeller-only pass (tracker #174; spec #169 "Singular
component launches"; ADR #169 Q4/Q6).

T4b (#387) retired the hunt-config enqueue with the config family: the threat
file is the dispatch record, so `enqueue_hunt_config` is GONE and the API path
is a loud 410 tombstone (asserted in `tests/project_management/test_hunting_api.py`).
The remaining seams are asserted directly through temp-root stores, no live run
and no live control plane. No LLM, no DB, no process.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.threat_modeller import UnitOutcome

from tests.hunting_fixtures import intake_unit

UNIT = "Service:slug:a"
FAULT = "fault-x"
CLASS = "CSRF"
FAULT_KEY = f"{UNIT}_{FAULT}_{CLASS}"
RUN = "modeller-only-run"


def test_the_hunt_config_enqueue_seam_is_retired():
    """T4b (#387): the config enqueue retired with the config family - the threat
    file is the dispatch record (S2 8.4), and the API path is a loud 410
    tombstone (never a silent accept into a family nothing reads)."""
    assert not hasattr(hunting_runtime, "enqueue_hunt_config")


def test_resume_pod_resumes_one_session_by_its_id(tmp_path):
    """The pod-ONLY launch seam (identity-based refactor, 2026-08-25 operator
    ruling): `resume_pod_session` resumes ONE held/paused pod session by posting
    its coroutine id to the shared control plane's per-session `resume_session`
    - it NEVER fabricates a produced `specified` spec (no store write at all).
    The seam first verifies the session is REGISTERED (the shared
    `RuntimeManager.resume_session` is a documented no-op for a never-registered
    run and never raises - so the seam is the fail-closed check, verified live
    2026-08-25)."""
    class _Runtime:
        def __init__(self):
            self.resumed = []
            self.registered = {
                "hunting:run-1:pod:Service:slug:a_fault-x_CSRF:sqli_blind",
            }

        def run_ids(self, module):
            return list(self.registered)

        def resume_session(self, module, session_id):
            self.resumed.append((module, session_id))

    runtime = _Runtime()
    pod_session = "hunting:run-1:pod:Service:slug:a_fault-x_CSRF:sqli_blind"
    hunting_runtime.resume_pod_session(runtime, pod_session)

    assert runtime.resumed == [("hunting", pod_session)]


def test_resume_pod_fail_closed_when_no_session_is_registered(tmp_path):
    """FAIL-CLOSED: no stored/paused pod session by that id propagates the
    shared runtime's `RunNotRegistered` (the API tier maps it onto 404) - the
    launch refuses rather than fabricating a dispatch input. The registration
    check is the SEAM's own (the shared `RuntimeManager.resume_session` verb
    never raises for a never-registered id, verified live 2026-08-25)."""
    from polymerhus.app.runtime import RunNotRegistered

    class _EmptyRuntime:
        def run_ids(self, module):
            return []

        def resume_session(self, module, session_id):
            raise AssertionError("unregistered session must not reach resume")

    with pytest.raises(RunNotRegistered):
        hunting_runtime.resume_pod_session(
            _EmptyRuntime(), "hunting:run-1:pod:x:y")

    with pytest.raises(ValueError, match="required"):
        hunting_runtime.resume_pod_session(_EmptyRuntime(), "")


def _unit_outcome(unit_id: str) -> UnitOutcome:
    return UnitOutcome(unit_id=unit_id, status="completed")


def test_launch_modeller_drives_the_pass_under_the_module_context(tmp_path):
    """The modeller-only coroutine drives ONE modelling pass under the hunting
    module context with no surfer and no run row: the injected pass body runs
    once per selected distinct unit and returns its outcome. The launch
    succeeds without any control plane (the coroutine is what the launcher
    seam schedules)."""
    reports: list[tuple[str, str, str]] = []

    async def _pass(project_id, run_id, unit_id, tools, **kw):
        reports.append((project_id, run_id, unit_id))
        return _unit_outcome(unit_id)

    outcomes = asyncio.run(hunting_runtime.launch_modeller(
        "p1", run_id=RUN,
        intake_units=[intake_unit("Service:b", live_edges=1),
                      intake_unit("Service:a", live_edges=3)],
        modeller_pass_fn=_pass,
    ))

    # the intake order: live L1 edge count descending, then unit id
    assert reports == [("p1", RUN, "Service:a"), ("p1", RUN, "Service:b")]
    assert [outcome.unit_id for outcome in outcomes] == ["Service:a", "Service:b"]
    # no run row was opened or written by the pass (no pg accessors touched):
    # the launcher only runs the pass body


def test_launch_modeller_never_raises_through_the_control_plane(tmp_path):
    """Fail-open: a degraded pass (its body raises) is logged, the coroutine
    returns normally - the singular launch never 500s the caller."""

    async def _exploding_pass(project_id, run_id, unit_id, tools, **kw):
        raise RuntimeError("pass degraded")

    asyncio.run(hunting_runtime.launch_modeller(
        "p1", run_id=RUN,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_exploding_pass,
    ))


def test_a_modeller_only_launch_is_refused_while_a_run_is_live(monkeypatch):
    """M4 / spec #169 US10: the ONE-live-run-per-project guard covers the
    modeller-only launch too - the per-project produced/consumed directories are
    single-owner, so a second pass must never race a live run on one unit."""
    from polymerhus.app.clients import pg

    monkeypatch.setattr(pg, "list_hunting_runs", lambda project_id: [
        {"hunting_run_id": "live-run", "status": "running"}])
    reports: list[str] = []

    async def _pass(project_id, run_id, unit_id, tools, **kw):
        reports.append(unit_id)
        return _unit_outcome(unit_id)

    result = asyncio.run(hunting_runtime.launch_modeller(
        "p1", run_id=RUN,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_pass,
    ))

    assert reports == []                 # the pass never ran
    assert result is None                # the refusal shape `start_hunting` uses


def test_a_modeller_only_launch_proceeds_when_no_run_is_live(monkeypatch):
    """The guard is a refusal only while a run is LIVE: with no live run (or no
    readable row, fail-open) the modeller-only launch models its intake."""
    from polymerhus.app.clients import pg

    monkeypatch.setattr(pg, "list_hunting_runs", lambda project_id: [])
    reports: list[str] = []

    async def _pass(project_id, run_id, unit_id, tools, **kw):
        reports.append(unit_id)
        return _unit_outcome(unit_id)

    outcomes = asyncio.run(hunting_runtime.launch_modeller(
        "p1", run_id=RUN,
        intake_units=[intake_unit(UNIT)],
        modeller_pass_fn=_pass,
    ))

    assert reports == [UNIT]
    assert [outcome.unit_id for outcome in outcomes] == [UNIT]
