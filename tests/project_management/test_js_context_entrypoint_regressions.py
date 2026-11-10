"""Public JS admission runs before claiming or scheduling hunting work."""

import asyncio

import pytest
from fastapi import HTTPException

from polymerhus.app.clients import pg
import polymerhus.app.data_root as data_root
from polymerhus.project_management import api
from polymerhus.attack.hunting.js_context_admission import current_js_context_selection
from tests.attack.test_js_context_entrypoint_regressions import published_selection
from tests.attack.test_js_context_hunting_admission import _summary
from tests.project_management.test_hunting_api import (
    RUN_ID, _ResumeRows, _FakeRuntime, _patch_resume, _patch_control_plane,
)


@pytest.fixture(autouse=True)
def no_evolver(monkeypatch):
    monkeypatch.setattr("polymerhus.project_management.api._ensure_project_evolver", lambda _: None)
    async def inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


@pytest.mark.parametrize("damage", ["missing", "malformed", "auth"])
def test_api_resume_refuses_invalid_original_binding_before_claim(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(data_root, "DATA_ROOT", tmp_path)
    selected = published_selection(tmp_path, project_id="p1")
    producer = {"run_id": "run-1", "project_id": "p1", "status": "complete",
                "stats": {"js_context_application": _summary(selected)}}
    value = selected.as_dict()
    if damage == "missing":
        (tmp_path / "p1/js-client-side" / selected.context_id / "run-1.yml").unlink()
    elif damage == "auth":
        value = {**value, "auth_ref": "foreign-account"}
    else:
        value = {"invalid": True}
    rows = _ResumeRows(stats={"js_context_selection": value})
    fake = _FakeRuntime()
    _patch_resume(monkeypatch, rows, fake)
    monkeypatch.setattr(pg, "get_run", lambda _: producer)
    monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: ["run-2"])
    with pytest.raises(HTTPException) as refusal:
        asyncio.run(api.resume_hunting_run("p1", RUN_ID))
    assert refusal.value.status_code == 409
    assert refusal.value.detail["code"]
    assert rows.rows[RUN_ID]["status"] == "stopped"
    assert rows.claims == []
    assert fake.scheduled == []


@pytest.mark.parametrize("status", ["pending", "settled_success", "settled_gap", "legacy"])
def test_api_modeller_checks_and_propagates_the_same_admission(tmp_path, monkeypatch, status):
    monkeypatch.setattr(data_root, "DATA_ROOT", tmp_path)
    selected = published_selection(tmp_path, project_id="p1")
    producer = {"run_id": "run-1", "project_id": "p1", "status": "complete",
                "stats": {"js_context_application": _summary(selected, status)}}
    monkeypatch.setattr(pg, "project_exists", lambda _: True)
    monkeypatch.setattr(pg, "list_hunting_runs", lambda _: [])
    monkeypatch.setattr(pg, "get_run", lambda _: producer)
    monkeypatch.setattr(pg, "list_active_js_context_producers", lambda _: [] if status == "legacy" else ["run-1"])
    fake = _FakeRuntime()
    runtime = _patch_control_plane(monkeypatch, fake)
    observed = []
    coroutines = []

    def schedule(module, coro, *, name):
        fake.scheduled.append(name)
        coroutines.append(coro)

    fake.schedule = schedule

    async def consume(*args, **kwargs):
        observed.append(current_js_context_selection())
        return [], None

    monkeypatch.setattr(runtime, "_run_intake", consume)
    monkeypatch.setattr(runtime, "_default_modeller_tools", lambda *a, **k: object())
    if status == "pending":
        try:
            with pytest.raises(HTTPException) as refusal:
                asyncio.run(api.launch_modeller_only("p1", api.HuntingModellerLaunch()))
            assert refusal.value.status_code == 409
            assert refusal.value.detail["code"] == "js_context_not_ready"
        finally:
            for coro in coroutines:
                coro.close()
        assert fake.scheduled == []
        assert observed == []
    else:
        response = asyncio.run(api.launch_modeller_only("p1", api.HuntingModellerLaunch()))
        for coro in coroutines:
            asyncio.run(coro)
        assert response["dispatched_asynchronously"] is True
        assert observed == [None if status == "legacy" else selected]
