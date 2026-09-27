"""The four enforcement properties, certified from the TARGET's point of view.

#238 A10. These are NOT part of the posture matrix gate (`gate-once`): three of
them re-point the running agent at another Kali service, so they own the stack
for the duration of the test and restore it in a `finally`. They are driven by
`sh scripts/issue_238_e2e_stack.sh gate-properties [name]`.

What each one certifies, in the plan's terms:

1. **Shared bucket** - several jobs of ONE `(project_id, target_key)` share ONE
   governor bucket (`keys` has exactly one entry for the project), and the
   target's peak never exceeds the ceiling.
2. **Isolation** - two projects aiming at the SAME target keep two buckets, and
   neither exceeds its own ceiling.
3. **Failing governor ⇒ zero egress** - with an armed policy whose governor
   raises, the target observes **zero** requests: the proxy refuses locally.
4. **Capture-off** - capture disabled, rate and concurrency still applied.

The job subset deliberately omits `ffuf`: the properties under test are about
the ceiling and the bucket, and `arjun` already produces concurrent target
traffic through several leaks' worth of jobs. Dropping the 4,750-request fuzz
keeps each certification inside a few minutes without touching any admission
threshold or job cost.
"""
from __future__ import annotations

import os
import time

import pytest

from tests.e2e.harness import driver

#: Bounded, target-facing work: httpx mints the BaseURL, katana an Endpoint,
#: arjun probes it with its own concurrent pool. No ffuf (see module docstring).
LIGHT_JOBS = ["subfinder", "httpx", "katana", "arjun"]

POSTURE = "no_limiter"
TARGET_HOST = "no-limiter.e2e.local"


def _require_stack() -> None:
    reason = driver.stack_unavailable_reason()
    if reason:
        # In the gate, a SKIP is a silent failure: `gate-properties` sets
        # POLYPHEMUS_E2E_STRICT=1 so an unavailable stack is a red gate, not a
        # green one (CODING_STANDARD, "a SKIP is a silent failure").
        if os.environ.get("POLYPHEMUS_E2E_STRICT") == "1":
            pytest.fail(f"stack unavailable for the enforcement-property gate: {reason}")
        pytest.skip(reason)


def _start_run(name: str, *, jobs: list[str] | None = None) -> tuple[str, str, str, dict]:
    """Create a project for `name`, run `jobs`, return (project, run, generation, result)."""
    generation = driver.reset_target(POSTURE)
    project_id = driver.create_project(f"e2e-enforce-{name}")
    driver.configure_project(project_id, driver.e2e_recon_settings(TARGET_HOST))
    driver.store_auth(project_id, overview=driver.SMOKE_OVERVIEW,
                      accounts=driver.SMOKE_ACCOUNTS)
    run_id = driver.start_recon(project_id, jobs or LIGHT_JOBS)
    result = driver.wait_for_run(project_id, run_id, timeout_s=1500.0)
    return project_id, run_id, generation, result


def _wait_for_admission(project_id: str, run_id: str, *, timeout_s: float = 600.0) -> None:
    """Block until the admission envelope is persisted.

    `pipeline` persists it AFTER the rate-mapping turn and BEFORE the first phase
    runner: the target traffic observed at that instant is the mapping's own, and
    everything after it belongs to the materialized jobs.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        stats = driver.read_run_stats(project_id, run_id)
        if (stats or {}).get("traffic_admission"):
            return
        time.sleep(2)
    raise AssertionError(
        f"run {run_id} never persisted an admission envelope within {timeout_s}s"
    )


def _ceiling_of(result: dict) -> int:
    policy = ((result.get("stats") or {}).get("rate_limit") or {}).get(
        "traffic_policy"
    ) or {}
    return int(policy.get("max_concurrency") or 0)


def _keys_for(runtime: dict | None, project_id: str) -> list[str]:
    governor = ((runtime or {}).get("governor") or {})
    return [key for key in (governor.get("keys") or []) if key.startswith(f"{project_id}/")]


def test_several_jobs_of_one_project_share_one_governor_bucket():
    _require_stack()
    project_id, _run_id, generation, result = _start_run("shared")
    counters = driver.read_target_counters(POSTURE, generation)
    runtime = driver.kali_governor_runtime()
    ceiling = _ceiling_of(result)

    assert result.get("status") == "complete", result.get("status")
    assert counters.get("requests"), (
        "the target saw no traffic - the ceiling assertion would be vacuous"
    )
    assert ceiling >= 1
    assert counters["max_in_flight"] <= ceiling, (
        f"target peak {counters['max_in_flight']} exceeded the ceiling {ceiling}"
    )
    keys = _keys_for(runtime, project_id)
    assert keys == [f"{project_id}/{TARGET_HOST}"], (
        "several jobs of one (project_id, target_key) must share ONE bucket, "
        f"not one per lease/source_ip: {keys}"
    )
    assert runtime["governor"]["admitted"] > 0, "nothing was governed"


def test_two_projects_on_the_same_target_keep_their_own_bucket():
    _require_stack()
    project_a, _run_a, _generation_a, result_a = _start_run("isolation-a")
    project_b, _run_b, generation_b, result_b = _start_run("isolation-b")
    # `reset_target` per project mints a NEW generation: only the last one is
    # current (a stale read is a 409, never another scenario's state).
    counters = driver.read_target_counters(POSTURE, generation_b)
    runtime = driver.kali_governor_runtime()

    keys_a = _keys_for(runtime, project_a)
    keys_b = _keys_for(runtime, project_b)
    assert keys_a == [f"{project_a}/{TARGET_HOST}"], keys_a
    assert keys_b == [f"{project_b}/{TARGET_HOST}"], keys_b
    assert keys_a != keys_b, "the same target under two projects must not share state"
    assert counters.get("requests")
    for result in (result_a, result_b):
        ceiling = _ceiling_of(result)
        assert counters["max_in_flight"] <= ceiling, (
            f"target peak {counters['max_in_flight']} exceeded a ceiling {ceiling}"
        )


def test_a_failing_governor_yields_zero_target_egress():
    """An armed policy whose governor RAISES must not become free egress: the
    proxy refuses every flow locally (503) and the target sees NOTHING."""
    _require_stack()
    generation = driver.reset_target(POSTURE)
    driver.point_agent_at_kali("http://kali-failing-governor:8000/mcp")
    try:
        project_id = driver.create_project("e2e-enforce-failing-governor")
        driver.configure_project(project_id, driver.e2e_recon_settings(TARGET_HOST))
        driver.store_auth(project_id, overview=driver.SMOKE_OVERVIEW,
                          accounts=driver.SMOKE_ACCOUNTS)
        run_id = driver.start_recon(project_id, ["httpx", "katana", "arjun"])
        # The mapping turn is a CAPTURE-ONLY lease (it MEASURES the policy), so
        # its own hits are expected and are not "egress through a broken
        # governor". The boundary is the admission envelope: read the target
        # right after it, then require that NOTHING else arrived.
        _wait_for_admission(project_id, run_id)
        baseline = int(driver.read_target_counters(POSTURE, generation)["requests"])
        result = driver.wait_for_run(project_id, run_id, timeout_s=900.0)
        counters = driver.read_target_counters(POSTURE, generation)
        runtime = driver.kali_governor_runtime("kali-failing-governor")
    finally:
        driver.point_agent_at_kali(None)

    assert baseline > 0, (
        "the mapping turn produced no target traffic - the assertion below "
        "would be vacuous"
    )
    # A few mapping hits may still have been in flight at the boundary; a job's
    # traffic is orders of magnitude larger (arjun alone is ~500 requests).
    stragglers = counters["requests"] - baseline
    assert stragglers <= 5, (
        "enforcement was broken yet "
        f"{stragglers} post-admission requests reached the target"
    )
    assert (runtime or {}).get("governor", {}).get("admitted", 0) == 0
    assert (runtime or {}).get("addon", {}).get("governor_refusals", 0) > 0, (
        "the proxy did not refuse locally - the failure was silent"
    )
    assert result.get("status") in ("complete", "failed"), result.get("status")


def test_capture_off_still_applies_rate_and_concurrency():
    """Capture and governance are separate switches: turning capture off must
    NOT disarm an armed policy - and it must stop recording."""
    _require_stack()
    driver.point_agent_at_kali("http://kali-capture-off:8000/mcp")
    try:
        project_id, _run_id, generation, result = _start_run("capture-off")
        counters = driver.read_target_counters(POSTURE, generation)
        runtime = driver.kali_governor_runtime("kali-capture-off")
        ceiling = _ceiling_of(result)
    finally:
        driver.point_agent_at_kali(None)

    addon = (runtime or {}).get("addon") or {}
    governor = (runtime or {}).get("governor") or {}
    assert addon.get("enabled") is False, "capture was supposed to be OFF"
    assert addon.get("recorded", 0) == 0, "the capture-off proxy recorded flows"
    assert governor.get("admitted", 0) > 0, "the armed policy was not applied"
    assert counters.get("requests"), "the target saw no traffic"
    assert counters["max_in_flight"] <= ceiling, (
        f"target peak {counters['max_in_flight']} exceeded the ceiling {ceiling}"
    )
