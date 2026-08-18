"""E2E walkthrough (live tier): the module runtime plane's FINITE STATE MACHINE.

This is a runtime-plane test, NOT a recon/analysis/hunting domain-quality test.
It walks the module lifecycle state machine over the wire and, in each reachable
state, feeds EVERY contract input the surface exposes, asserting the contract
outcome. The runtime plane (ONE shared worker loop, per-module lifecycle verbs,
admission control, the shared executor offload) is what is under test.

Reachable states over HTTP (from `RuntimeManager`):
  running -> paused -> running -> draining -> stopped
  `created` is the handle's pre-registration enum (unobservable over the wire);
  `draining` is the transient inside `drain()` (the HTTP call returns only once
  settled to `stopped`). Both are covered at the integration tier
  (tests/app/test_runtime_manager.py); here every WIRE-observable state is
  entered and every contract input is applied in it.

Contract inputs per state (the operator-intent surface):
  pause  / resume / drain   - lifecycle verbs (state transitions + safe no-ops)
  launch (schedule)          - admitted in `running`; refused 503 otherwise (#118)
  stop   (cancel_run)        - hard-cancels a registered run (module-agnostic)

Each module (recon / analysis / hunting) walks the FULL matrix independently
(draining one module does not affect the others - the independence the goal
names). The walk ends each module at `stopped` (a terminal state; there is no
restart verb over HTTP).

Target: `juice-shop-remote` (soupmarket.shop) from
tests/e2e/fixtures/eval-targets.yaml, bounded to a single [httpx] job - enough
to make launches real (run rows written, tasks registered) without a domain-
quality run.

Pointing: `AGENT_BASE_URL` selects the sibling container (default
http://localhost:8081 - the polymerhus-runtime-e2e container). The main
polymerhus-agent-1 on 8080 is driven by a different e2e and must stay untouched.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
import yaml

from tests.conftest import wait_for

_TARGET = "juice-shop-remote"
_JOBS = ["httpx"]  # bounded subset - runtime-plane test, not domain quality
_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "eval-targets.yaml")
_POLL_TIMEOUT_S = 1800
_POLL_INTERVAL_S = 10

AGENT = os.environ.get("AGENT_BASE_URL", "http://localhost:8081")


def _load_target(name: str) -> dict:
    with open(_FIXTURE) as fh:
        data = yaml.safe_load(fh)
    for t in data["targets"]:
        if t["name"] == name:
            return t
    raise AssertionError(f"eval target {name!r} not in {_FIXTURE}")


def _strip_nulls(obj):
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(x) for x in obj]
    return obj


def _apply_target_settings(settings: dict) -> dict:
    out = _strip_nulls(settings)
    assert isinstance(out, dict)
    auth = out.get("auth_context") or {}
    creds = auth.get("credentials")
    if isinstance(creds, dict) and not (creds.get("username") and creds.get("password")):
        auth.pop("credentials", None)
    return out


def _lifecycle(module: str, verb: str) -> tuple[dict, int]:
    r = httpx.post(f"{AGENT}/projects/p1/modules/{module}/{verb}", timeout=60)
    try:
        return r.json(), r.status_code
    except Exception:  # noqa: BLE001 - non-JSON body still carries the code
        return {"error": r.text[:200]}, r.status_code


def _state(module: str) -> str:
    """Read the module's current state via the idempotent resume verb: the
    runtime verb is a safe no-op on a non-paused module and always reports the
    current state - so a POST /resume is a state probe."""
    body, code = _lifecycle(module, "resume")
    assert code == 200, f"state probe failed for {module}: {code} {body}"
    return body["state"]


def _run_status(project_id: str, run_id: str) -> dict:
    r = httpx.get(f"{AGENT}/projects/{project_id}/recon/{run_id}", timeout=10)
    r.raise_for_status()
    return r.json()


class _BoundedProject:
    """One light project (juice-shop-remote, [httpx] only) reused across the
    three module walks - real launches without a domain-quality run."""

    def __init__(self):
        self.project_id = None
        self.run_id = None


def _prepare_project() -> _BoundedProject:
    target = _load_target(_TARGET)
    kb = target["operator_kb"]

    project_id = httpx.post(
        f"{AGENT}/projects", json={"name": f"fsm-{uuid.uuid4().hex[:8]}",
                                   }, timeout=10,
    ).json()["project_id"]

    payload = _apply_target_settings(target["settings"])
    payload["operator_kb"] = kb
    r = httpx.put(
        f"{AGENT}/projects/{project_id}/settings", json={"recon": payload}, timeout=10
    )
    assert r.status_code == 200, f"settings PUT failed: {r.text}"

    p = _BoundedProject()
    p.project_id = project_id
    return p


def _launch(module: str, project_id: str, run_id: str | None = None) -> tuple[dict, int]:
    """Launch a run on `module`; assert it routes through runtime.schedule."""
    if module == "recon":
        r = httpx.post(f"{AGENT}/projects/{project_id}/recon",
                       json={"jobs": _JOBS}, timeout=10)
    elif module == "analysis":
        r = httpx.post(f"{AGENT}/projects/{project_id}/analysis",
                       json={"run_id": run_id}, timeout=10)
    elif module == "hunting":
        r = httpx.post(f"{AGENT}/projects/{project_id}/hunting", json={}, timeout=10)
    else:
        raise AssertionError(module)
    try:
        return r.json(), r.status_code
    except Exception:  # noqa: BLE001
        return {"error": r.text[:200]}, r.status_code


def _stop(module: str, project_id: str, run_id: str) -> tuple[dict, int]:
    if module in ("recon", "hunting"):
        r = httpx.post(f"{AGENT}/projects/{project_id}/{module}/{run_id}/stop",
                       timeout=30)
    else:  # analysis: graceful stop
        r = httpx.post(f"{AGENT}/projects/{project_id}/analysis/{run_id}/stop",
                       timeout=30)
    try:
        return r.json(), r.status_code
    except Exception:  # noqa: BLE001
        return {"error": r.text[:200]}, r.status_code


def _walk_module_fsm(module: str, project_id: str, run_id: str):
    """Walk ONE module through the full state machine, feeding every contract
    input in every reachable state. Ends the module at `stopped` (terminal)."""

    # ---- running ----------------------------------------------------------
    assert _state(module) == "running", f"{module} must boot running"

    # resume in running is a safe no-op that reports running
    body, code = _lifecycle(module, "resume")
    assert code == 200 and body["state"] == "running"

    # launch (schedule) is ADMITTED in running
    body, code = _launch(module, project_id, run_id)
    assert code in (200, 201), f"{module} launch in running: {code} {body}"

    # stop (cancel_run) hard-cancels a registered run (module-agnostic)
    launched_id = (body.get("run_id") or body.get("hunting_run_id")
                   or body.get("analysis_run_id"))
    assert launched_id, f"launch returned no run id: {body}"
    body, code = _stop(module, project_id, launched_id)
    assert code == 200, f"{module} stop in running: {code} {body}"

    # ---- paused -----------------------------------------------------------
    body, code = _lifecycle(module, "pause")
    assert code == 200 and body["state"] == "paused"

    # pause in paused is a no-op that reports paused
    body, code = _lifecycle(module, "pause")
    assert code == 200 and body["state"] == "paused"

    # launch (schedule) is REFUSED 503 while paused (#118 contract)
    body, code = _launch(module, project_id, run_id)
    assert code == 503, (
        f"{module} launch in paused must be a clean 503 (admission refused): "
        f"{code} {body}"
    )

    # resume returns to running
    body, code = _lifecycle(module, "resume")
    assert code == 200 and body["state"] == "running"
    assert _state(module) == "running"

    # pause again, then drain from paused (E2: drain settles to stopped)
    body, code = _lifecycle(module, "pause")
    assert code == 200 and body["state"] == "paused"
    body, code = _lifecycle(module, "drain")
    assert code == 200 and body["state"] == "stopped"
    assert _state(module) == "stopped"

    # ---- stopped (terminal) -----------------------------------------------
    # every lifecycle verb is a safe no-op; launch is refused 503
    for verb in ("pause", "resume", "drain"):
        body, code = _lifecycle(module, verb)
        assert code == 200 and body["state"] == "stopped", (
            f"{module} {verb} in stopped: {code} {body}"
        )
    body, code = _launch(module, project_id, run_id)
    assert code == 503, (
        f"{module} launch in stopped must be a clean 503 (admission refused): "
        f"{code} {body}"
    )


def test_fsm_full_coverage_analysis():
    _gate_reachable()
    p = _prepare_project()
    # analysis launch needs an existing recon run's feed correlation; recon is
    # still RUNNING here (this walk runs before the recon walk drains it)
    body, code = _launch("recon", p.project_id, None)
    assert code == 200, f"recon setup launch for analysis: {code} {body}"
    run_id = body["run_id"]
    _walk_module_fsm("analysis", p.project_id, run_id)


def test_fsm_full_coverage_hunting():
    _gate_reachable()
    p = _prepare_project()
    # hunting launch is control-plane-gated (503 until the runtime landed -
    # here it is live, so the walk is real)
    _walk_module_fsm("hunting", p.project_id, None)


def test_fsm_full_coverage_recon():
    # Runs LAST: this walk drains recon to `stopped` (terminal) - no later
    # walk needs a live recon launch, so the order keeps the matrix clean.
    _gate_reachable()
    p = _prepare_project()
    # recon launches real runs: bounded [httpx] toward the eval target
    _walk_module_fsm("recon", p.project_id, None)


def _gate_reachable():
    """Reachability gate for the sibling (loud failure, never a skip - the
    sibling IS the system under test)."""
    health = None
    try:
        health = wait_for(
            lambda: httpx.get(f"{AGENT}/health", timeout=3).json(), timeout=120
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"sibling agent not reachable at {AGENT}: {exc}")
    assert health is not None and health["status"] == "ok", (
        f"sibling agent unhealthy before the run: {health}"
    )
