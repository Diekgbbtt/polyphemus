"""#238 follow-up, Task 10 - the FUNCTIONAL tier: rate-aware job admission.

This is the release gate for the whole feature. It drives an ordinary run
through the PUBLIC control plane and asserts what actually happened at the
target:

    control-plane launch -> auth gateway -> rate mapping -> v2 profile/policy
    -> deterministic admission -> materialized phases -> real pod -> MCP/Kali
    -> proxy/governor -> deterministic target -> persisted stats/output

What it must NEVER do (the whole point of the tier): script the orchestrator,
fake a runner, or call Kali's MCP surface directly. The model is the real
`ReconOrchestratorActor` on the real session machinery, answered by the
deterministic local provider
(`deterministic_llm_provider.py`); the pipeline, pod, MCP client, governor,
Vegeta/arjun/ffuf binaries and the target fixtures are all production.

Every scenario is parameterized over an ISOLATED target instance, resets its
generation first, and asserts the same nine things the design names (spec 16):
event order, posture and effective policy, evidence refs, final phase list,
invoked/non-invoked runners, target counters/inflight, persisted profile +
admission + pod stats, secret absence, and the warnings on every conservative
path.

The tier SKIPS - loudly, with the exact environmental cause - when the stack is
not up. A skip is never a pass: the release gate is the green run.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pytest

from tests.e2e import deterministic_llm_provider as provider
from tests.e2e.harness import driver

#: The intensive jobs the feature is about: they must appear in the materialized
#: phases exactly when the measured posture admits them.
INTENSIVE = ("arjun", "ffuf")

#: The subset the requested run reaches `arjun` and `ffuf` with.
FUNCTIONAL_JOBS = ["subfinder", "httpx", "katana", "ffuf", "arjun"]

#: The ordered trajectory the design requires (spec 12.2, 15).
TRAJECTORY = ["auth", "rate_mapping", "rate_profile_persisted",
              "admission_persisted", "pod_started", "target_observed",
              "run_finalized"]

_SECRET_SENTINELS = ("e2e-rate-secret", "e2e-smoke-cookie", "e2e-session")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_REF_RE = re.compile(r"^rate-artifact/v1:")


@dataclass(frozen=True)
class Scenario:
    """One row of the design's minimum E2E matrix (spec 16)."""

    name: str
    posture: str
    expected_outcome: str
    intensive_materialized: bool
    reason_codes: dict[str, str]
    note: str = ""
    #: The seed the run aims at. Defaults to the posture's own Compose service;
    #: the stage-error row aims at the alias the deterministic provider fails on.
    target_alias: str | None = None
    #: The expected `bypass_outcome`, asserted only when set (the named rows).
    expected_bypass: str | None = None
    #: Whether the target was actually reachable, so `target_observed` must
    #: appear. The stage-error row aims at an alias that never resolves: the
    #: trajectory must then be ABSENT of `target_observed` (a target that never
    #: answered was never observed).
    target_reachable: bool = True


SCENARIOS = (
    Scenario("no_limiter", "no_limiter", "no_limiter", True, {},
             "intensive runners start only when both gates pass"),
    Scenario("high_limit", "high_limit", "mapped", True, {},
             "a compatible limiter still admits the measured capacity"),
    Scenario("low_limit", "low_limit", "mapped", False,
             {"ffuf": "below_min_safe_rate"},
             "a low safe rate prunes the intensive runners"),
    Scenario("false_bypass", "false_bypass", "mapped", False,
             {"ffuf": "below_min_safe_rate"},
             "an unconfirmed bypass changes nothing",
             expected_bypass="no_bypass"),
    Scenario("burst_inconclusive", "burst_inconclusive", "inconclusive", False,
             {"ffuf": "profile_inconclusive"},
             "an inconclusive posture stays conservative"),
    Scenario("rate_stage_error", "no_limiter", "failed", False,
             # The unreachable seed also means the bounded jobs consume nothing,
             # so an intensive job may be pruned for `no_inputs` BEFORE the
             # posture gate is reached; the row asserts the WARNING below.
             {},
             "the actor's own failure path, no production fault flag",
             target_alias=provider.RATE_STAGE_ERROR_TARGET,
             target_reachable=False),
)


def _require_stack():
    reason = driver.stack_unavailable_reason()
    if reason:
        pytest.skip(reason)


# --- the shared assertions (spec 16) ---------------------------------------------


def assert_event_order(stats: dict, expected: list[str]) -> None:
    """The expected labels appear IN ORDER in the run's trajectory.

    `event_order` accumulates one entry per phase boundary (`admission_persisted`)
    and per run-level act, so the check is a subsequence check, not equality.
    """
    order = stats["traffic_admission"]["event_order"]
    position = 0
    for label in expected:
        while position < len(order) and order[position] != label:
            position += 1
        assert position < len(order), (
            f"trajectory lost {label!r}: {order}")
        position += 1


def assert_no_secrets(serialized: str, *extra_sentinels: str) -> None:
    for sentinel in (*_SECRET_SENTINELS, *extra_sentinels):
        assert sentinel not in serialized, (
            f"a stored secret leaked into the run's persisted state: {sentinel!r}")


def assert_all_evidence_refs_relative_and_hashed(rate_limit: dict) -> None:
    # #238 A2: the typed evidence lives under `rate_limit["evidence"]`
    # (`{ref, sha256, experiment_id, count}`); `artifact_refs` is the legacy
    # `list[str]` coordinate list.
    evidence = rate_limit.get("evidence") or []
    for item in evidence:
        assert _ARTIFACT_REF_RE.match(item["ref"]), (
            f"an artifact reference must be RELATIVE, got {item['ref']!r}")
        assert not str(item["ref"]).startswith("/"), item
        assert _SHA256_RE.match(item["sha256"]), (
            f"an artifact reference must be pinned by a lowercase sha256, got "
            f"{item['sha256']!r}")
    for ref in rate_limit.get("artifact_refs") or []:
        # The legacy coordinate list is plain strings, never objects.
        assert isinstance(ref, str), ref


def _materialized(stats: dict) -> set[str]:
    return {
        job
        for phase in stats["traffic_admission"]["materialized_phases"]
        for job in phase
    }


def _decisions(stats: dict, decision: str) -> dict[str, str]:
    return {
        row["job"]: row["reason_code"]
        for row in stats["traffic_admission"]["decisions"]
        if row["decision"] == decision
    }


def _invoked_runners(per_job: list[dict]) -> set[str]:
    return {
        row["job"]
        for row in per_job
        if row.get("status") in ("success", "degraded", "failed")
    }


#: The routes the BOUNDED jobs (`httpx`, `katana`) touch on the fixture: the
#: index and the canonical link/form target. Any OTHER route is ffuf's wordlist
#: fuzzing (`ffuf -u <base>/FUZZ -w common.txt`).
_BOUNDED_ROUTES = frozenset({"/", "/canonical", "/canonical/"})


def _intensive_target_traffic(counters: dict) -> dict[str, int]:
    """Attribute the fixture's own request events to the intensive jobs.

    * ffuf fuzzes `<base>/FUZZ` over the 4,750-line wordlist, so it is the only
      job that produces MANY DISTINCT routes outside the bounded surface (a
      single `/robots.txt` from katana is not ffuf);
    * arjun probes the BaseURL with its own parameter names, so a root request
      carrying a query key OTHER than katana's `seed` is arjun.

    Deliberately conservative: it never claims traffic when the evidence is not
    attributable.
    """
    attributed: dict[str, int] = {}
    routes = counters.get("routes") or {}
    fuzz_routes = [route for route in routes if route not in _BOUNDED_ROUTES]
    if len(fuzz_routes) >= 20:
        attributed["ffuf"] = len(fuzz_routes)
    root_queries = (counters.get("query_names") or {}).get("/") or {}
    arjun_hits = sum(
        count for name, count in root_queries.items() if name != "seed"
    )
    if arjun_hits:
        attributed["arjun"] = arjun_hits
    return attributed


# --- the scenario driver ---------------------------------------------------------


def _run_scenario(scenario: Scenario) -> dict:
    """One real run against the scenario's isolated target instance."""
    generation = driver.reset_target(scenario.posture)
    project_id = driver.create_project(f"e2e-admission-{scenario.name}")
    driver.configure_project(project_id, driver.e2e_recon_settings(
        scenario.target_alias or driver.TARGET_SEEDS[scenario.posture],
    ))
    driver.store_auth(project_id,
                      overview=driver.SMOKE_OVERVIEW,
                      accounts=driver.SMOKE_ACCOUNTS)
    run_id = driver.start_recon(project_id, FUNCTIONAL_JOBS)
    result = driver.wait_for_run(project_id, run_id)
    return {
        "scenario": scenario,
        "project_id": project_id,
        "run_id": run_id,
        "generation": generation,
        "status": result.get("status"),
        "stats": result.get("stats") or {},
        "per_job": result.get("per_job") or [],
        "target": driver.read_target_counters(scenario.posture, generation),
    }


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_rate_aware_admission_over_the_posture_matrix(scenario):
    """The whole feature, per posture, through the production trajectory."""
    _require_stack()
    observed = _run_scenario(scenario)
    stats = observed["stats"]

    # 1. the run reached its terminal state through the whole trajectory
    assert observed["status"] == "complete", (
        f"{scenario.name}: the run did not complete ({observed['status']})")
    if scenario.target_reachable:
        assert_event_order(stats, TRAJECTORY)
    else:
        # The target never answered: every other step happened, but
        # `target_observed` must NOT be claimed.
        assert_event_order(
            stats,
            ["auth", "rate_mapping", "rate_profile_persisted",
             "admission_persisted", "run_finalized"],
        )
        assert "target_observed" not in stats["traffic_admission"]["event_order"], (
            f"{scenario.name}: the trajectory claimed the unreachable target was "
            "observed")

    # 2. the posture was measured and the policy is the v2 contract
    rate_limit = stats["rate_limit"]
    assert rate_limit["version"] == "rate-profile/v2"
    assert rate_limit["outcome"] == scenario.expected_outcome, (
        f"{scenario.name}: measured {rate_limit['outcome']}, expected "
        f"{scenario.expected_outcome}")
    policy = rate_limit["traffic_policy"]
    assert policy["version"] == "traffic-policy/v2"
    if scenario.expected_bypass is not None:
        assert rate_limit["bypass_outcome"] == scenario.expected_bypass, (
            f"{scenario.name}: bypass outcome {rate_limit['bypass_outcome']!r}")

    # 3. the admission envelope is present and internally consistent
    admission = stats["traffic_admission"]
    assert admission["version"] == "traffic-admission/v1"
    assert admission["profile_version"] == "rate-profile/v2"
    assert admission["effective_policy"]["version"] == "traffic-policy/v2"

    # 4/5. the final phase list decides who runs
    materialized = _materialized(stats)
    invoked = _invoked_runners(observed["per_job"])
    for job in INTENSIVE:
        if scenario.intensive_materialized:
            assert job in materialized, f"{scenario.name}: {job} was pruned"
            assert job in invoked, f"{scenario.name}: {job} never ran"
        else:
            assert job not in materialized, (
                f"{scenario.name}: {job} materialized under a posture that "
                "must prune it")
            assert job not in invoked, (
                f"{scenario.name}: {job} was invoked even though it was pruned")
            reasons = _decisions(stats, "excluded")
            assert reasons.get(job), (
                f"{scenario.name}: {job} was pruned without a structured reason")
            if job in scenario.reason_codes:
                assert reasons[job] == scenario.reason_codes[job], (
                    f"{scenario.name}: {job} pruned for {reasons[job]!r}")

    # 6. the target saw what the phase list implies
    # `read_target_counters` returns the fixture's `/counters` snapshot itself.
    counters = observed["target"]
    intensive_traffic = _intensive_target_traffic(observed["target"])
    if scenario.intensive_materialized:
        assert intensive_traffic, (
            f"{scenario.name}: the intensive runners were admitted but no "
            "tool-attributable target traffic was recorded")
    else:
        assert not intensive_traffic, (
            f"{scenario.name}: target traffic arrived for a pruned runner: "
            f"{intensive_traffic}")

    # 7/8. persistence and secret safety
    assert_all_evidence_refs_relative_and_hashed(rate_limit)
    if scenario.expected_outcome in ("mapped", "no_limiter"):
        assert rate_limit.get("evidence"), (
            f"{scenario.name}: a measured profile must publish at least one "
            "evidence reference")
    assert_no_secrets(json.dumps(stats))
    assert_no_secrets(json.dumps(observed["target"]))

    # 9. every conservative posture persists a structured warning
    if scenario.expected_outcome in ("failed", "inconclusive"):
        warnings = stats["traffic_admission"].get("warnings") or []
        assert any(
            w.startswith(f"rate_profile_{scenario.expected_outcome}:")
            for w in warnings
        ), f"{scenario.name}: no structured warning on a conservative path: {warnings}"


def test_the_functional_module_never_scripts_the_production_seams():
    """A structural guard: the functional tier must not grow a scripted
    orchestrator, a fake runner, or a direct MCP call."""
    with open(__file__, encoding="utf-8") as fh:
        text = fh.read()
    # Assembled so this guard does not match its own token list.
    forbidden_terms = ["_Scripted" + "Orchestrator", "fake_run" + "_job",
                       "fast" + "mcp", "call_" + "tool("]
    for forbidden in forbidden_terms:
        assert forbidden not in text, (
            f"the functional gate must not use {forbidden!r}: it would certify "
            "a path the operator never runs")


def test_a_stale_profile_never_re_admits_an_intensive_runner():
    """Stale is the fail-closed case: a profile that expires before the next
    observation prunes the intensive jobs and keeps only bounded work.

    Driving it needs the stack brought up with a short `RATE_LIMIT_PROFILE_TTL_S`
    (an agent-environment knob, not a test knob), so the scenario refuses to
    run - loudly - instead of pretending the gate passed.
    """
    _require_stack()
    ttl = driver.agent_env("RATE_LIMIT_PROFILE_TTL_S")
    if not ttl or float(ttl) > 5:
        pytest.skip(
            "bring the #238 stack up with a short RATE_LIMIT_PROFILE_TTL_S "
            "(<= 5s) to exercise the stale-profile gate; the TTL is an "
            f"agent-environment knob (saw {ttl!r})")

    scenario = Scenario("stale", "low_limit", "mapped", False,
                        {"ffuf": "profile_stale"})
    observed = _run_scenario(scenario)
    stats = observed["stats"]
    assert_event_order(stats, TRAJECTORY)
    assert "profile_stale" in json.dumps(stats["traffic_admission"]), (
        "a stale profile must be recorded as a refusal, not silently ignored")
    for job in INTENSIVE:
        assert job not in _materialized(stats)
        assert job not in _invoked_runners(observed["per_job"])
