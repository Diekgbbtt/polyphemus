"""#110: the three hunting seam endpoints (seam contract 3.3) - launch, stop,
status. No live PG / control plane: the gateway accessors, the marshalling
harness, and the runtime presence are faked. The 503 fail-closed launch is the
real surface while `polymerhus.app.runtime` has not landed."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from polymerhus.app.clients import pg
from polymerhus.app.main import app

client = TestClient(app)

RUN_ID = "rt-hunt-0001"


def _row(status: str = "running"):
    return {
        "hunting_run_id": RUN_ID, "project_id": "p1", "status": status,
        "started_at": None, "finished_at": None,
    }


class _FakeRuntime:
    """The stand-in for `polymerhus.app.runtime` once the control plane lands."""

    def __init__(self):
        self.scheduled: list[str] = []
        self.cancelled: list[str] = []

    def schedule(self, module: str, coro, *, name: str) -> object:
        self.scheduled.append(name)
        # consume the coroutine so pytest never reports it as un-awaited
        asyncio.create_task(coro)
        return coro

    def cancel_run(self, module: str, run_id: str) -> None:
        self.cancelled.append(run_id)


def _patch_control_plane(monkeypatch, runtime=None):
    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: runtime)
    return hunting_runtime


# --- POST /projects/{pid}/hunting ----------------------------------------------

def test_launch_returns_the_surrogate_id_and_schedules(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)

    recorded: list[tuple] = []

    def fake_start(project_id, *, run_id=None, candidates=None, **kw):
        recorded.append((project_id, run_id, candidates))

        async def _finish():
            return run_id

        return _finish()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)

    resp = client.post("/projects/p1/hunting", json={"candidates": [
        {"unit_id": "Service:slug:a", "fault_class": "fault-x"},
    ]})

    assert resp.status_code == 201
    assert resp.json() == {"hunting_run_id": RUN_ID}
    assert fake_runtime.scheduled == [f"hunting:{RUN_ID}"]
    # the row opens SYNCHRONOUSLY before scheduling, and the launch carries the
    # candidate batch into the scheduled entry point
    (pid, rid, candidates) = recorded[0]
    assert pid == "p1" and rid == RUN_ID
    assert [c.unit_id for c in candidates] == ["Service:slug:a"]
    assert [c.fault_class for c in candidates] == ["fault-x"]


def test_launch_empty_batch_is_an_empty_pass_scheduled(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: RUN_ID)
    fake_runtime = _FakeRuntime()
    hunting_runtime = _patch_control_plane(monkeypatch, fake_runtime)
    recorded: list[tuple] = []

    def fake_start(project_id, *, run_id=None, candidates=None, **kw):
        recorded.append((candidates,))

        async def _finish():
            return run_id

        return _finish()

    monkeypatch.setattr(hunting_runtime, "start_hunting", fake_start)

    resp = client.post("/projects/p1/hunting", json={})

    assert resp.status_code == 201
    assert recorded[0] == ([],)  # an empty batch launches an O1 empty pass


def test_launch_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post("/projects/nope/hunting", json={})

    assert resp.status_code == 404
    assert fake_runtime.scheduled == []  # never scheduled


def test_launch_fails_closed_503_until_the_control_plane_lands(monkeypatch):
    """THE fail-closed surface: a real orchestration pass must never ride the
    uvicorn request loop through the in-process fallback, so the launch is a 503
    while `polymerhus.app.runtime` has not landed (as in this worktree)."""
    from polymerhus.attack.hunting import runtime as hunting_runtime
    monkeypatch.setattr(hunting_runtime, "_app_runtime", lambda: None)
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    opened = []
    monkeypatch.setattr(pg, "create_hunting_run", lambda pid: opened.append(pid) or RUN_ID)

    resp = client.post("/projects/p1/hunting", json={})

    assert resp.status_code == 503
    assert opened == []  # no run opened behind the gate


# --- POST /projects/{pid}/hunting/{rid}/stop -----------------------------------

def test_stop_acknowledges_and_reaches_the_cancel_seam(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row())
    recorded_statuses = []
    monkeypatch.setattr(pg, "set_hunting_run_status",
                        lambda rid, status: recorded_statuses.append((rid, status)))
    fake_runtime = _FakeRuntime()
    _patch_control_plane(monkeypatch, fake_runtime)

    resp = client.post(f"/projects/p1/hunting/{RUN_ID}/stop")

    assert resp.status_code == 200
    assert resp.json() == {"hunting_run_id": RUN_ID, "stopping": True}
    assert fake_runtime.cancelled == [RUN_ID]  # the hard-cancel reached the loop
    assert recorded_statuses == [(RUN_ID, "stopped")]


def test_stop_unknown_run_404(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: None)

    resp = client.post(f"/projects/p1/hunting/{RUN_ID}/stop")

    assert resp.status_code == 404


# --- GET /projects/{pid}/hunting/{rid} -----------------------------------------

def test_status_returns_the_status_row(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: _row(status="complete"))

    resp = client.get(f"/projects/p1/hunting/{RUN_ID}")

    assert resp.status_code == 200
    assert resp.json()["hunting_run_id"] == RUN_ID
    assert resp.json()["status"] == "complete"


def test_status_unknown_run_404(monkeypatch):
    monkeypatch.setattr(pg, "get_hunting_run", lambda rid: None)

    resp = client.get(f"/projects/p1/hunting/{RUN_ID}")

    assert resp.status_code == 404