"""Live functional E2E for the LLM rate-aware recon Configurator."""
from __future__ import annotations

import json

import pytest

from tests.e2e.harness import driver as harness


def _require_stack() -> None:
    reason = harness.stack_unavailable_reason()
    if reason:
        pytest.skip(reason)


def _run(posture: str) -> dict:
    _require_stack()
    project_id = harness.create_project(f"llm-configurator-{posture}")
    harness.configure_project(
        project_id,
        harness.e2e_recon_settings(harness.TARGET_SEEDS[posture]),
    )
    harness.store_auth(
        project_id,
        overview=harness.SMOKE_OVERVIEW,
        accounts=harness.SMOKE_ACCOUNTS,
    )
    generation = harness.reset_target(posture)
    before = harness.provider_counters()
    run_id = harness.start_recon(project_id, ["httpx", "ffuf"])
    result = harness.wait_for_run(project_id, run_id, timeout_s=1200)
    after = harness.provider_counters()
    return {
        "project_id": project_id,
        "run_id": run_id,
        "status": result.get("status"),
        "stats": result.get("stats") or {},
        "per_job": result.get("per_job") or [],
        "provider_before": before,
        "provider_after": after,
        "generation": generation,
    }


def _posture_yaml(project_id: str, target_key: str) -> dict:
    script = (
        "import json, sys\n"
        "from polymerhus.app.rate_limit.store import RateLimitPostureStore\n"
        "record = RateLimitPostureStore().read(sys.argv[1], sys.argv[2])\n"
        "print(json.dumps(record.profile.model_dump(mode='json') if record else None))\n"
    )
    result = harness._compose(
        ["exec", "-T", "agent", "python", "-c", script, project_id, target_key],
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _jobs_by_name(result: dict) -> dict:
    return {row.get("job"): row for row in result["per_job"]}


def _seed_unreadable_posture(project_id: str) -> None:
    """Plant a corrupt YAML in the project's rate-limit bucket.

    This is the only way to reach the `unreadable` branch from the PUBLIC
    control plane: the run writes ITS OWN target's file freshly (valid), so the
    reader trips over a SIBLING file the run never owns. Production has no
    fault flag for this - a corrupt file is a real operational state, and the
    design forbids treating it as absent.
    """
    script = (
        "import sys\n"
        "from polymerhus.app.data_root import project_dir\n"
        "directory = project_dir(sys.argv[1], 'rate-limit')\n"
        "directory.mkdir(parents=True, exist_ok=True)\n"
        "(directory / 'aaa-corrupt.yaml').write_text("
        "'safe_rate_per_s: [not a mapping', encoding='utf-8')\n"
    )
    result = harness._compose(
        ["exec", "-T", "agent", "python", "-c", script, project_id],
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_high_and_low_posture_change_the_configurator_plan_and_commands():
    high = _run("high_limit")
    low = _run("low_limit")

    assert high["status"] == low["status"] == "complete"
    assert "traffic_admission" not in high["stats"]
    assert "traffic_admission" not in low["stats"]

    high_jobs = _jobs_by_name(high)
    low_jobs = _jobs_by_name(low)
    assert "httpx" in high_jobs and "httpx" in low_jobs
    assert "ffuf" in high_jobs, "the high-rate fixture must admit the intensive job"
    assert "ffuf" not in low_jobs, "the low-rate fixture must not materialize ffuf"

    high_commands = json.dumps(high_jobs["httpx"].get("stats") or {})
    low_commands = json.dumps(low_jobs["httpx"].get("stats") or {})
    assert high_commands != low_commands, "posture must drive different tool parameters"

    turns_high = high["provider_after"]["by_turn"]
    turns_low = low["provider_after"]["by_turn"]
    for turns in (turns_high, turns_low):
        assert turns.get("gateway", 0) >= 1
        assert turns.get("configurator", 0) >= 1
        assert turns.get("triager", 0) >= 1


def test_stats_and_yaml_are_the_same_measured_posture():
    run = _run("high_limit")
    stored = run["stats"]["rate_limit"]
    target_key = stored["target_key"]
    yaml_profile = _posture_yaml(run["project_id"], target_key)

    assert yaml_profile == stored
    assert yaml_profile["version"] == "rate-profile/v2"
    assert yaml_profile["traffic_policy"]["version"] == "traffic-policy/v2"


def test_an_unreadable_posture_omits_every_target_facing_pod():
    _require_stack()
    project_id = harness.create_project("llm-configurator-unreadable")
    harness.configure_project(
        project_id,
        harness.e2e_recon_settings(harness.TARGET_SEEDS["high_limit"]),
    )
    harness.store_auth(
        project_id,
        overview=harness.SMOKE_OVERVIEW,
        accounts=harness.SMOKE_ACCOUNTS,
    )
    generation = harness.reset_target("high_limit")
    _seed_unreadable_posture(project_id)

    run_id = harness.start_recon(project_id, ["httpx", "ffuf"])
    result = harness.wait_for_run(project_id, run_id, timeout_s=1200)

    assert result["status"] == "complete"
    # The posture was still MEASURED and persisted: the run fails closed only on
    # the pods, never on the measurement itself.
    stored = (result.get("stats") or {}).get("rate_limit")
    assert stored, "the mapping still ran"
    # An unreadable posture is never 'absent': the Configurator must omit every
    # target-facing pod rather than fall back to the conservative default.
    assert (result.get("per_job") or []) == [], (
        "an unreadable posture must omit every target-facing pod, "
        f"got {result.get('per_job')!r}"
    )
    # The ONLY traffic a pod-less run may leave is the mapper's OWN bounded
    # measurement. Asserting exact equality (not "small") is what makes a
    # single escaped pod fatal: the mapper's count is self-derived from the
    # run's persisted stats, and any extra request is unaccounted for.
    counters = harness.read_target_counters("high_limit", generation)
    assert counters["requests"] == stored["usage"]["requests"], (
        "the target saw traffic beyond the bounded rate mapping: a pod escaped"
    )
