"""The per-dispatched-session watchdog.

A hunter or pod graph that does not finish inside its window is degraded, not
waited on. The hunter's drafts settle and the pod writes a degraded PodExport,
so the serial/batched cursor moves to the next entity.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting import surfer as surfer_mod
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    run_hunter_session,
    run_pod_session,
)

PROJECT = "proj-watchdog"
RUN = "run-watchdog"
HUNT = "Service-u1__threat-1"
SPEC_ID = "idor__report-id__signed-url"


def _draft() -> dict:
    return {
        "status": "hypothesised",
        "discriminators": [
            {"axis": "object", "value": "report-id"},
            {"axis": "delivery-route", "value": "signed-url"},
        ],
        "target_identity": {"url": "http://target/", "unit_id": "Service:u1"},
        "verification_symptoms": ["another tenant's report body is returned"],
        "provenance": {"run_id": RUN, "web_vulnerability_class": "idor"},
    }


def test_a_hunter_session_that_exceeds_its_window_settles_and_moves_on(
        tmp_path, monkeypatch):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunter.write_specs(PROJECT, HUNT, [_draft()])

    async def _noop_idle(**kw):
        return None

    monkeypatch.setattr(surfer_mod, "_run_hunter_idle", _noop_idle)

    async def _hang(payload):
        await asyncio.sleep(30)

    def _builder(*, run_id, project_id, hunter_store):
        return _hang, None

    asyncio.run(run_hunter_session(
        payload={}, project_id=PROJECT, run_id=RUN, hunt_key=HUNT,
        band="high", hunter_store=hunter, state=RunDispatchState(),
        gate=None, hunter_builder=_builder, session_timeout_s=0.01,
    ))

    body = hunter.read_spec(PROJECT, HUNT, SPEC_ID, side="produced")
    assert body["status"] == "dropped"
    assert hunter.read_terminal_set(PROJECT, HUNT) is not None


def test_a_pod_session_that_exceeds_its_window_writes_a_degraded_export(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    spec = {
        **_draft(),
        "status": "ratified",
    }

    async def _hang(*args, **kwargs):
        await asyncio.sleep(30)

    asyncio.run(run_pod_session(
        spec=spec, project_id=PROJECT, run_id=RUN, hunt_key=HUNT,
        spec_id=SPEC_ID, inbox=None, hunter_store=hunter, gate=None,
        pod_builder=_hang, pod_store=pod, state=RunDispatchState(),
        session_timeout_s=0.01,
    ))

    export = pod.read_pod_export(SPEC_ID, RUN)
    assert export is not None
    assert export["evidence"]["terminal_reason"] == "pod-watchdog-timeout"
    assert export["evidence"]["clean"] is False
    assert "watchdog" in export["evidence"]["error"]


def test_the_hunter_and_pod_watchdogs_have_separate_defaults():
    from polymerhus.attack.hunting.surfer import (
        DEFAULT_HUNTER_SESSION_TIMEOUT_S,
        DEFAULT_POD_SESSION_TIMEOUT_S,
        RunDispatchState,
    )

    state = RunDispatchState()
    assert DEFAULT_HUNTER_SESSION_TIMEOUT_S == 2700.0
    assert DEFAULT_POD_SESSION_TIMEOUT_S == 3600.0
    assert state.hunter_session_timeout_s == 2700.0
    assert state.pod_session_timeout_s == 3600.0


def test_a_cancelled_pod_session_writes_no_export_and_keeps_the_cursor(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    spec = {**_draft(), "status": "ratified"}

    async def _write_then_hang(*args, **kwargs):
        pod.write_resume(SPEC_ID, RUN, {
            "schema_version": 1,
            "last_order": 0,
            "current_variant_ref": "v0",
            "iteration": 1,
            "feedback": "",
            "executed": [],
        })
        await asyncio.sleep(30)

    async def _drive():
        task = asyncio.create_task(run_pod_session(
            spec=spec, project_id=PROJECT, run_id=RUN, hunt_key=HUNT,
            spec_id=SPEC_ID, inbox=None, hunter_store=hunter, gate=None,
            pod_builder=_write_then_hang, pod_store=pod,
            state=RunDispatchState(),
        ))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_drive())

    assert pod.read_pod_export(SPEC_ID, RUN) == {}
    assert pod.read_resume(SPEC_ID, RUN)["current_variant_ref"] == "v0"


def test_the_pod_timeout_hierarchy_is_progress_first():
    from polymerhus.attack.hunting.pod.config import PodTimeouts
    from polymerhus.attack.hunting.surfer import DEFAULT_POD_SESSION_TIMEOUT_S

    timeouts = PodTimeouts()
    assert timeouts.node_idle_s == 600.0
    assert timeouts.node_run_s is None
    assert timeouts.tool_idle_s == 300.0
    assert DEFAULT_POD_SESSION_TIMEOUT_S == 3600.0


def _seed_pod_trail(pod: PodMemoryStore) -> None:
    pod.write_variant(SPEC_ID, "v0", {
        "ref": "v0", "parent_ref": None, "declined_attribute": "",
        "spec": {"rationale": "seeded for the backstop"},
    })
    pod.write_experiment_log(SPEC_ID, 0, {
        "order": 0,
        "variant_ref": "v0",
        "raw_observations": [{
            "probe_ref": "sig-a", "variant_ref": "v0", "status": 200,
            "body": "observed",
        }],
        "kb_observations": [],
        "interpretations": [],
        "executed": ["sig-a"],
    })
    pod.write_resume(SPEC_ID, RUN, {
        "schema_version": 1,
        "last_order": 0,
        "current_variant_ref": "v0",
        "iteration": 1,
        "feedback": "",
        "executed": ["sig-a"],
    })


def test_the_watchdog_backstop_preserves_the_durable_trail(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    _seed_pod_trail(pod)
    spec = {**_draft(), "status": "ratified"}

    async def _hang(*args, **kwargs):
        await asyncio.sleep(30)

    asyncio.run(run_pod_session(
        spec=spec, project_id=PROJECT, run_id=RUN, hunt_key=HUNT,
        spec_id=SPEC_ID, inbox=None, hunter_store=hunter, gate=None,
        pod_builder=_hang, pod_store=pod, state=RunDispatchState(),
        session_timeout_s=0.01,
    ))

    export = pod.read_pod_export(SPEC_ID, RUN)
    evidence = export["evidence"]
    assert evidence["terminal_reason"] == "pod-watchdog-timeout"
    assert evidence["clean"] is False
    assert evidence["variant_specs"][0]["ref"] == "v0"
    assert evidence["raw_observations"][0]["probe_ref"] == "sig-a"
    assert pod.read_resume(SPEC_ID, RUN) == {}


def test_the_watchdog_backstop_does_not_overwrite_an_execution_terminal(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    existing = {
        "verdict": "successful",
        "evidence": {"terminal_reason": "symptom-confirmed", "clean": True},
    }
    pod.write_pod_export(SPEC_ID, RUN, existing)
    spec = {**_draft(), "status": "ratified"}

    async def _hang(*args, **kwargs):
        await asyncio.sleep(30)

    asyncio.run(run_pod_session(
        spec=spec, project_id=PROJECT, run_id=RUN, hunt_key=HUNT,
        spec_id=SPEC_ID, inbox=None, hunter_store=hunter, gate=None,
        pod_builder=_hang, pod_store=pod, state=RunDispatchState(),
        session_timeout_s=0.01,
    ))

    assert pod.read_pod_export(SPEC_ID, RUN) == existing
