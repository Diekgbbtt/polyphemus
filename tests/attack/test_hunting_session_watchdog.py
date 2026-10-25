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
HUNT = "Service-u1__loop-1"
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
        likelihood="high", hunter_store=hunter, state=RunDispatchState(),
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
    assert export["terminal_reason"] == "budget-timeout"
    assert export["clean"] is False
