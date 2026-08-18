"""E2E walkthrough (live tier) for the #74 payload FIFO - the recon/analysis
decoupling quality contract, asserted over the run record of a REAL bounded
recon+analysis run against the `juice-shop-remote` eval target.

The target is applied mechanically per the eval-targets.yaml contract
(docs/agents/domain.md + the fixture's own header): create project -> PUT
/settings (the target's `settings` plus `operator_kb`) -> POST /bootstrap ->
POST /recon with a BOUNDED job subset -> poll -> assert.

Since #75 the queue contract is read from the ANALYSIS run's own status row
(GET /analysis/{run_id}), not the recon run: recon reaches `complete` the instant
its jobs finish and NEVER waits on analysis (D3), while the analysis run settles
independently. The FeedStats contract (analysis/feed.py), on the analysis run:
  * status == "drained"       - the analysis run reached its terminal drained state
  * mode == "queued"          - the decoupling mode, not the inline rollback
  * analysis_drained == True  - the terminal marker was consumed LAST and no
                                chunk is outstanding (the at-least-once hold)
  * dispatches_entered > 0    - non-vacuity: a pass actually entered dispatches
  * passes == advanced + 1    - exactly-once: every pushed chunk consumed once,
                                plus the terminal marker (which is NOT a push)
  * l0_assets_read == recon's produced_assets - exactness: the analyser read
                                exactly what curate merged (curate's count and
                                list increment together, curator.py)
  * advance_blocked_s_max near zero - the decoupling itself (AST-DEC-09): push
                                is a put_nowait and never waits on the LLM
And the recon run must NOT carry `analysis_drained` (the coupling is gone).

Gating: the agent must be reachable and the LLM provider configuration sound.
Both are part of what is under test (the `opencode` provider wiring), so once
the agent answers /health the run's own diagnostics fail loudly instead of a
skip - skips are reserved for an unreachable agent.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
import yaml

from tests.conftest import wait_for

_TARGET = "juice-shop-remote"
_JOBS = ["httpx", "katana"]  # bounded subset (operator choice, 2026-08-03)
_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "eval-targets.yaml")
_POLL_TIMEOUT_S = 2700
_POLL_INTERVAL_S = 10


def _agent_base() -> str:
    """Mirror `neo4j_target()`'s in-network/host split: the compose `tests`
    service runs with NEO4J_URI=bolt://neo4j:7687 and reaches the agent by
    service DNS; a host run uses the published port."""
    if os.environ.get("AGENT_BASE_URL"):
        return os.environ["AGENT_BASE_URL"]
    in_network = (os.environ.get("NEO4J_URI") or "").startswith("bolt://neo4j")
    return "http://agent:8080" if in_network else "http://localhost:8080"


AGENT = _agent_base()


def _load_target(name: str) -> dict:
    with open(_FIXTURE) as fh:
        data = yaml.safe_load(fh)
    for t in data["targets"]:
        if t["name"] == name:
            return t
    raise AssertionError(f"eval target {name!r} not in {_FIXTURE}")


def _strip_nulls(obj):
    """The eval-targets contract: a `null` attribute means "not supplied" and
    the driving agent omits it rather than PUTting it (a null username would
    fail auth_context validation with a misleading 400)."""
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
        # juice-shop-remote's credentials are all-null: agentic login is not
        # supplied, so drop the block and use the cookies/header path instead.
        auth.pop("credentials", None)
    return out


def _run_status(project_id: str, run_id: str) -> dict:
    r = httpx.get(f"{AGENT}/projects/{project_id}/recon/{run_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def _analysis_status(project_id: str, run_id: str) -> dict | None:
    """The analysis run's OWN status row (#75), independent of the recon run.
    404 until the consumer has created its row - treated as 'not yet'."""
    r = httpx.get(f"{AGENT}/projects/{project_id}/analysis/{run_id}", timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def test_payload_fifo_queue_decoupling_quality_against_eval_target():
    # --- reachability gate. The provider/LLM wiring is UNDER TEST, so an
    #     unhealthy agent is a loud failure below, never a skip here.
    health = None
    try:
        health = wait_for(
            lambda: httpx.get(f"{AGENT}/health", timeout=3).json(), timeout=120
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"agent not reachable at {AGENT}: {exc}")
    assert health is not None and health["status"] == "ok", (
        f"agent unhealthy before the run: {health}"
    )

    target = _load_target(_TARGET)
    kb = target["operator_kb"]

    project_id = httpx.post(
        f"{AGENT}/projects", json={"name": f"pff-e2e-{uuid.uuid4().hex[:8]}"},
        timeout=10,
    ).json()["project_id"]

    # --- mechanical application of the eval target
    payload = _apply_target_settings(target["settings"])
    payload["operator_kb"] = kb
    r = httpx.put(
        f"{AGENT}/projects/{project_id}/settings", json={"recon": payload}, timeout=10
    )
    assert r.status_code == 200, f"settings PUT failed: {r.text}"

    r = httpx.post(
        f"{AGENT}/projects/{project_id}/bootstrap",
        json={"operator_kb": kb}, timeout=600,
    )
    assert r.status_code == 200, f"bootstrap failed: {r.text}"

    r = httpx.post(
        f"{AGENT}/projects/{project_id}/recon", json={"jobs": _JOBS}, timeout=10
    )
    assert r.status_code == 200, f"recon launch failed: {r.text}"
    run_id = r.json()["run_id"]

    # --- RECON completes INDEPENDENTLY of analysis (#75 D3): poll the recon run
    #     to complete first; it must NOT wait on the analyser.
    def _recon_terminal_or_none():
        s = _run_status(project_id, run_id)
        return s if s["status"] in ("complete", "failed") else None

    status = wait_for(_recon_terminal_or_none, timeout=_POLL_TIMEOUT_S,
                      interval=_POLL_INTERVAL_S)
    assert status["status"] == "complete", f"recon did not complete: {status}"
    per_job = {j["job"]: j for j in status["per_job"]}

    # #75: the recon run no longer carries the analysis queue contract - that moved
    # to the analysis run. The recon stats must NOT claim drained-ness.
    assert "analysis_drained" not in (status.get("stats") or {}), (
        f"recon run still carries analysis stats (coupling not removed): {status['stats']}"
    )

    # --- ANALYSIS is its OWN run: poll it to its own terminal status.
    def _analysis_terminal_or_none():
        a = _analysis_status(project_id, run_id)
        if a is None:
            return None
        return a if a["status"] in ("drained", "withheld", "stopped", "interrupted") else None

    analysis = wait_for(_analysis_terminal_or_none, timeout=_POLL_TIMEOUT_S,
                        interval=_POLL_INTERVAL_S)
    stats = analysis["stats"]

    # --- the queue contract, now read from the ANALYSIS run's stats
    assert analysis["status"] == "drained", f"analysis not drained: {analysis}"
    assert stats.get("mode") == "queued", f"feed not in queued mode: {stats}"
    assert stats.get("analysis_drained") is True, f"analysis_drained False: {stats}"
    assert stats.get("dispatches_entered", 0) > 0, (
        f"no pass entered dispatches (vacuity): {stats}"
    )

    advanced = stats.get("advanced", 0)
    passes = stats.get("passes", 0)
    assert advanced >= 1, f"no chunk was pushed (no surface?): {stats} {per_job}"
    # #75: the terminal marker is NOT a push, so passes == advanced (chunks) + 1 (marker).
    assert passes == advanced + 1, (
        f"exactly-once violated: passes {passes} != advanced + 1 = {advanced + 1}: {stats}"
    )

    # Exactness is asserted over ASSETS ONLY: `l0_assets_read` counts len(chunk.assets)
    # (analysis/supervisor.py, `l0_assets_read=len(assets)`), and the chunk's
    # observations ride a SEPARATE field the counter does not tally. Summing
    # produced_observations in here compared an assets-only counter against
    # assets+observations, which no run carrying observations could ever satisfy.
    produced_assets = sum(
        (j["stats"] or {}).get("produced_assets", 0) for j in status["per_job"]
    )
    assert produced_assets >= 1, f"recon produced no assets at all: {per_job}"
    assert stats.get("l0_assets_read", 0) == produced_assets, (
        f"exactness violated: feed read {stats.get('l0_assets_read')} assets, "
        f"recon curated {produced_assets}: {stats} {per_job}"
    )

    # --- the decoupling itself (AST-DEC-09): push never waits on the LLM
    blocked = stats.get("advance_blocked_s_max", 0.0)
    assert blocked < 5.0, f"push blocked the recon loop for {blocked}s: {stats}"
