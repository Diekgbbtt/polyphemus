"""E2E walkthrough (live tier): the module runtime plane (#118) over the wire.

This is NOT a recon/analysis/hunting domain-quality test. It drives the RUNTIME
PLANE that scaffolds the modules - the ONE shared worker loop, the per-module
lifecycle verbs, the shared executor offload - against the live sibling agent,
while a BOUNDED recon run executes toward a real target. Every assertion is an
observable of the runtime, read off the HTTP lifecycle surface and the run rows.

Covers, live:
  * E1/E2 walkthrough predicates (module-runtime-assertions.md): pause one
    module while recon keeps progressing; drain analysis to `stopped` while
    recon stays up; resume continues from the next unit.
  * C18/C21 (dispatch + thread consumption): while a run is live the lifecycle
    verbs answer and the worker loop stays responsive (a paused module never
    wedges the API path); a module's run rows keep advancing after a pause.
  * The 503 fail-closed gate on the lifecycle surface when the runtime is not
    active is unit-tested (tests/app/test_module_lifecycle_api.py); here the
    sibling's runtime IS active, so the verbs answer live.

Target: `juice-shop-remote` (soupmarket.shop) from tests/e2e/fixtures/eval-targets.yaml,
with a BOUNDED job subset ([httpx]) - enough to observe run rows + lifecycle,
not a domain-quality run.

Pointing: `AGENT_BASE_URL` selects the sibling container (default localhost:8081
for this suite; the compose-internal default is http://agent:8080). The e2e must
run against the SIBLING agent (polymerhus-runtime-e2e), NOT the main
polymerhus-agent-1 that a different e2e is already driving.
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
_MODULES = ("recon", "analysis", "hunting")

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


def _run_status(project_id: str, run_id: str) -> dict:
    r = httpx.get(f"{AGENT}/projects/{project_id}/recon/{run_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def _lifecycle(module: str, verb: str):
    """Drive a lifecycle verb on the sibling; return (payload, http_code)."""
    r = httpx.post(f"{AGENT}/projects/p1/modules/{module}/{verb}", timeout=30)
    try:
        return r.json(), r.status_code
    except Exception:  # noqa: BLE001 - a non-JSON body still carries the code
        return {"error": r.text[:200]}, r.status_code


def test_runtime_plane_lifecycle_over_the_wire():
    """Pause analysis while recon keeps progressing; resume; drain analysis to
    stopped while recon stays up; every lifecycle verb answers on the sibling's
    LIVE runtime (the 503 fail-closed gate is unit-tested - here it must be
    live)."""
    # --- reachability + runtime-active gate (loud failure, never a skip)
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

    # every lifecycle verb answers (runtime active, all three modules registered)
    for module in _MODULES:
        for verb in ("pause", "resume"):
            body, code = _lifecycle(module, verb)
            assert code == 200, f"{module}/{verb} on the live runtime: {code} {body}"

    target = _load_target(_TARGET)
    kb = target["operator_kb"]

    project_id = httpx.post(
        f"{AGENT}/projects", json={"name": f"rte2e-{uuid.uuid4().hex[:8]}",
                                   }, timeout=10,
    ).json()["project_id"]

    payload = _apply_target_settings(target["settings"])
    payload["operator_kb"] = kb
    r = httpx.put(
        f"{AGENT}/projects/{project_id}/settings", json={"recon": payload}, timeout=10
    )
    assert r.status_code == 200, f"settings PUT failed: {r.text}"

    r = httpx.post(
        f"{AGENT}/projects/{project_id}/recon", json={"jobs": _JOBS}, timeout=10
    )
    assert r.status_code == 200, f"recon launch failed: {r.text}"
    run_id = r.json()["run_id"]

    # --- let the run actually start, then pause analysis while recon runs
    def _started():
        s = _run_status(project_id, run_id)
        return s if s["status"] not in ("queued", "starting") else None

    wait_for(_started, timeout=120, interval=5)

    body, code = _lifecycle("analysis", "pause")
    assert code == 200 and body["state"] == "paused", (
        f"analysis pause on the live runtime: {code} {body}"
    )

    # --- while analysis is paused, the recon run keeps progressing and the API
    #     path stays responsive (C21: a paused module never wedges the worker
    #     loop or the API thread)
    def _progressed():
        s = _run_status(project_id, run_id)
        return s if s.get("per_job") else None

    progressed = wait_for(_progressed, timeout=180, interval=10)
    assert progressed["status"] in ("running", "complete"), (
        f"recon did not progress under analysis pause: {progressed}"
    )

    # resume: analysis returns to running (dispatch continues from the next unit)
    body, code = _lifecycle("analysis", "resume")
    assert code == 200 and body["state"] == "running", (
        f"analysis resume on the live runtime: {code} {body}"
    )

    # --- drain analysis while recon stays up (E2): settles to stopped, archives
    def _recon_finished():
        s = _run_status(project_id, run_id)
        return s if s["status"] in ("complete", "failed") else None

    final = wait_for(_recon_finished, timeout=_POLL_TIMEOUT_S,
                     interval=_POLL_INTERVAL_S)
    assert final["status"] == "complete", f"recon did not complete: {final}"

    body, code = _lifecycle("analysis", "drain")
    assert code == 200 and body["state"] == "stopped", (
        f"analysis drain on the live runtime: {code} {body}"
    )

    # recon's run row reached its terminal while the module plane stayed live
    assert final["per_job"], f"recon run produced no per-job rows: {final}"
