"""#238 Task 8 - live end-to-end evidence: map -> persist -> govern.

TIER (read this before citing the file): this is the LIVE **DIRECT-MCP**
measurement tier, not the functional release gate. It drives the real Kali MCP
surface directly and publishes the rate profile through a scripted orchestrator
double, which is exactly what `tests/e2e/test_rate_limit_admission_e2e.py` is
forbidden to do. It remains valuable - it is the fast, focused check of the
mapping/artefact/governor arithmetic - but it certifies the mapping, never the
production actor-to-target trajectory.

This is a LIVE gate (the #196 precedent): it drives the real Kali MCP surface,
the real proxy, the real governor and the real Vegeta runner against a
DETERMINISTIC LOCAL limiter fixture (`tests/e2e/rate_limit_e2e_target.py`,
service `rate-limit-e2e-target` in `docker-compose.e2e.yml`). No internet
target is ever involved, and every assertion is arithmetic - a known token
bucket, a stable 429 fingerprint, a route-normalization variant and
per-request counters.

What each test proves end to end:

* the mapping brackets the limiter WITHIN the operator budget, and the phases
  the spec names (baseline / steady / burst / recovery / concurrency) all ran;
* the published artifact's recomputed SHA-256 matches its manifest AND the
  evidence's `manifest_sha256`, with the replayed Authorization value redacted
  and absent from everything that leaves Kali;
* concurrent governed pods for ONE project+target share ONE aggregate bucket
  (the Review Focus pin), while a different project does not wait;
* a policy Kali cannot enforce is refused (returncode 78, no runner call, no
  traffic at the target);
* the route-normalization variant becomes a CONFIRMED finding only after an
  independent repetition, and is never applied to later traffic;
* the real `run_pipeline` orders auth -> rate -> persist -> phase 0 with the
  LIVE-measured profile and persists references only;
* a browser-only target runs ZERO Vegeta experiments and stays `inconclusive`.

The only non-production collaborator is the orchestrator actor used to drive
the pipeline ORDER (a scripted double that must be constructed anyway to
exercise both turns); the rate measurement it publishes is the one measured
live above. Deviations from the letter of the plan are recorded in the
tranche ledger.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastmcp import Client

from polymerhus.recon.control import pipeline
from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.control.orchestrator_agent import ReconOrchestratorActor
from polymerhus.recon.control.rate_limit_mapper import judge_bypass
from polymerhus.recon.control.rate_limit_runner import (
    RateLimitHarness,
    build_kali_execute,
)
from polymerhus.recon.domain.rate_limit import (
    ExperimentSpec,
    MutationSpec,
    PathMutation,
    RateLimitSafetyBudget,
    RateLoopVerdict,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_URL = os.environ.get("KALI_MCP_URL", "http://localhost:8000/mcp")
TARGET_BASE = os.environ.get("RATE_LIMIT_E2E_TARGET", "http://172.28.0.23").rstrip("/")
TARGET_HOST = urlsplit(TARGET_BASE).hostname or TARGET_BASE
AUTH_SECRET = "e2e-rate-secret"
ALLOW_SKIP = os.environ.get("KALI_HTTP_E2E_ALLOW_SKIP") == "1"
COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "docker-compose.e2e.yml",
]


async def _acall(tool: str, args: dict) -> dict:
    async with Client(MCP_URL) as client:
        result = await client.call_tool(tool, args)
        return result.data


def call(tool: str, args: dict) -> dict:
    return asyncio.run(_acall(tool, args))


def _unavailable(reason: str) -> None:
    if ALLOW_SKIP:
        pytest.skip(reason)
    pytest.fail(reason)


def _counters(*, reset: bool = False) -> dict:
    path = "/reset" if reset else "/counters"
    with urllib.request.urlopen(f"{TARGET_BASE}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _policy(*, rate_per_s: float, burst: int, project_key: str = TARGET_HOST) -> dict:
    return {
        "target_key": project_key,
        "host_patterns": [TARGET_HOST],
        "rate_per_s": rate_per_s,
        "burst": burst,
        "max_concurrency": 1,
        "min_delay_ms": 1000.0 / rate_per_s,
        "source": "e2e-live",
        # Kali enforces `traffic-policy/v2` (#238 Task 6/7): `max_concurrency` is
        # an enforced semantic, and the runtime refuses any other version with
        # returncode 78 and zero target calls. This helper drives the REAL Kali
        # surface, so it must speak the version Kali accepts.
        "version": "traffic-policy/v2",
    }


def _read_artifact_in_kali(ref: str) -> dict:
    """Read the published artifact from INSIDE the Kali container.

    The raw stream never crosses the MCP boundary (only its ref + hash do), so
    the integrity check has to run where the bytes live.
    """
    script = (
        "import gzip, hashlib, json, pathlib, sys\n"
        "ref = sys.argv[1]\n"
        "project, run, experiment = ref.split(':', 1)[1].split('/')\n"
        "directory = pathlib.Path('/data') / project / 'rate-limit' / run / experiment\n"
        "stream = (directory / 'results.jsonl.gz').read_bytes()\n"
        "manifest = json.loads((directory / 'manifest.json').read_text())\n"
        "lines = sum(1 for _ in gzip.open(directory / 'results.jsonl.gz'))\n"
        "print(json.dumps({\n"
        "  'manifest': manifest,\n"
        "  'recomputed_sha256': hashlib.sha256(stream).hexdigest(),\n"
        "  'lines': lines,\n"
        "}))\n"
    )
    proc = subprocess.run(
        COMPOSE + ["exec", "-T", "kali", "/opt/venv/bin/python", "-c", script, ref],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.fail(f"reading the artifact inside kali failed: {proc.stderr.strip()[:400]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def live_kali():
    parts = urlsplit(MCP_URL)
    try:
        with socket.create_connection((parts.hostname, parts.port or 80), timeout=1.0):
            pass
    except OSError as exc:
        _unavailable(f"kali MCP endpoint {MCP_URL} not listening: {exc}")
    try:
        status = call("proxy_status", {})
    except Exception as exc:  # noqa: BLE001 - this is the live gate
        _unavailable(f"kali MCP not reachable at {MCP_URL}: {exc}")
    if not status.get("proxy", {}).get("ok"):
        _unavailable(f"the recording/governing proxy is not healthy: {json.dumps(status)[:300]}")
    try:
        _counters(reset=True)
    except Exception as exc:  # noqa: BLE001
        _unavailable(
            f"rate-limit fixture {TARGET_BASE} not reachable from the host: {exc}"
        )
    # The fixture must ALSO be reachable from Kali, or every measurement below
    # would silently degrade into a failed experiment.
    probe = call(
        "execute_command",
        {
            "command": f"curl -sS -m 10 -o /dev/null -w '%{{http_code}}' {TARGET_BASE}/counters",
            "session_id": f"e2e-probe-{uuid.uuid4().hex[:6]}",
            "timeout_s": 30,
        },
    )
    if probe.get("returncode") != 0 or "200" not in str(probe.get("stdout")):
        _unavailable(f"rate-limit fixture {TARGET_BASE} not reachable from kali: {probe}")
    return status


@pytest.fixture(scope="module")
def mapped(live_kali):
    """ONE live mapping, shared by the assertions below (it is the expensive part)."""
    project_id = f"e2e-rate-{uuid.uuid4().hex[:10]}"
    run_id = f"e2e-rate-run-{uuid.uuid4().hex[:8]}"
    budget = RateLimitSafetyBudget(
        max_requests=200,
        max_duration_s=120.0,
        max_rate_per_s=5.0,
        max_concurrency=2,
        max_bypass_variants=2,
    )
    harness = RateLimitHarness(
        target_key=TARGET_HOST,
        url=f"{TARGET_BASE}/canonical",
        budget=budget,
        execute=build_kali_execute(
            project_id=project_id, run_id=run_id, mcp_url=MCP_URL
        ),
        project_id=project_id,
        run_id=run_id,
        headers={"Authorization": f"Bearer {AUTH_SECRET}"},
        host_patterns=[TARGET_HOST],
        profile_ttl_s=3600.0,
    )
    control = asyncio.run(harness.map())
    return {
        "harness": harness,
        "control": control,
        "budget": budget,
        "project_id": project_id,
        "run_id": run_id,
    }


# --- the mapping itself ---------------------------------------------------------


def test_the_mapping_brackets_the_limiter_within_the_operator_budget(mapped):
    control = mapped["control"]
    harness = mapped["harness"]
    budget = mapped["budget"]

    assert control.outcome == "mapped", (
        f"the fixture's token bucket must be measured, got {control.outcome} "
        f"({harness.failure_reason})"
    )
    assert control.threshold_low_per_s and control.threshold_high_per_s
    assert control.threshold_low_per_s < control.threshold_high_per_s
    assert "rate_limited" in {signal.value for signal in control.signals}

    # Every phase the plan names ran inside the SAME budget.
    phases = {evidence.phase for evidence in harness.evidence}
    assert {"baseline", "steady", "burst", "recovery", "concurrency"} <= phases

    usage = harness.ledger.usage
    assert usage.requests <= budget.max_requests
    assert usage.duration_s <= budget.max_duration_s
    assert usage.max_concurrency <= budget.max_concurrency
    # The budget bounds the OFFERED traffic the controller admitted. Vegeta's
    # own measured count differs by at most the in-flight workers per
    # experiment (it stops on the duration boundary), so the measured total is
    # bounded by the ceiling plus that bounded slack - never unbounded.
    for evidence in harness.evidence:
        offered = math.ceil(evidence.offered_rate_per_s * evidence.duration_s)
        assert evidence.requests <= offered + evidence.concurrent_workers
    assert sum(e.requests for e in harness.evidence) <= (
        budget.max_requests + len(harness.evidence) * budget.max_concurrency
    )
    assert all(
        e.offered_rate_per_s <= budget.max_rate_per_s + 1e-9
        for e in harness.evidence
    )
    assert all(e.outcome == "measured" for e in harness.evidence), [
        e.error for e in harness.evidence if e.outcome != "measured"
    ]

    # The enforced policy is the derived, conservative one - never infinity and
    # never above the operator ceiling.
    policy = control.traffic_policy
    assert policy is not None
    assert policy.version == "traffic-policy/v2"
    assert policy.target_key == TARGET_HOST
    assert 0 < policy.rate_per_s <= budget.max_rate_per_s
    assert policy.host_patterns == [TARGET_HOST]


def test_the_artifact_hash_matches_its_manifest_and_never_carries_the_secret(mapped):
    harness = mapped["harness"]
    measured = [
        e for e in harness.evidence if e.artifact_ref and e.manifest_sha256
    ]
    assert measured, "the mapping published no artifact"
    evidence = next((e for e in measured if e.rejection_ratio > 0), measured[0])

    stored = _read_artifact_in_kali(evidence.artifact_ref)
    manifest = stored["manifest"]

    assert manifest["ref"] == evidence.artifact_ref
    assert manifest["sha256"] == stored["recomputed_sha256"]
    assert manifest["sha256"] == evidence.manifest_sha256
    assert manifest["count"] == stored["lines"] > 0
    assert manifest["experiment_id"] == evidence.experiment_id
    assert manifest["project_id"] == mapped["project_id"]
    assert manifest["run_id"] == mapped["run_id"]

    # The authenticated context reached the child (the fixture answered, so the
    # replay carried it) and NEVER lands on disk or in the compact result.
    blob = json.dumps(manifest, sort_keys=True)
    assert AUTH_SECRET not in blob, "the replayed Authorization value leaked into the artifact"
    assert manifest["spec"]["headers"]["Authorization"] != f"Bearer {AUTH_SECRET}"

    # The reference that leaves Kali is a relative coordinate with a hash - not
    # a path and not raw evidence.
    assert evidence.artifact_ref.startswith("rate-artifact/v1:")
    assert "/data" not in evidence.artifact_ref


# --- governance ------------------------------------------------------------------


def test_concurrent_pods_share_one_aggregate_budget(live_kali):
    """The Review Focus pin, live: two (four) pods for one project+target spend
    ONE bucket, and a different project's traffic does not wait behind them."""
    _counters(reset=True)
    policy = _policy(rate_per_s=2.0, burst=1)
    session = uuid.uuid4().hex[:6]

    async def governed(index: int, *, project: str) -> dict:
        started = time.monotonic()
        result = await _acall(
            "execute_command",
            {
                "command": (
                    f"curl -sS -m 10 -o /dev/null -w '%{{http_code}}' {TARGET_BASE}/open"
                ),
                "session_id": f"e2e-conc-{session}-{index}",
                "timeout_s": 90,
                "project_id": project,
                "run_id": f"e2e-run-{session}",
                "spec_id": f"agg-{index}",
                "traffic_policy": policy,
            },
        )
        result["elapsed_s"] = time.monotonic() - started
        return result

    async def scenario():
        tasks = [governed(i, project="e2e-agg-proj") for i in range(4)]
        tasks.append(governed(99, project="e2e-other-proj"))
        return await asyncio.gather(*tasks)

    results = asyncio.run(scenario())
    shared, other = results[:4], results[4]

    assert all(r["returncode"] == 0 for r in results), [r.get("traffic_warning") for r in results]
    assert all(r.get("traffic_warning") is None for r in results)
    assert all("200" in str(r["stdout"]) for r in results)

    counters = _counters()
    assert counters["routes"].get("/open") == 5
    span = counters["last_at"] - counters["first_at"]
    # 4 requests at 1/2 s apart = 1.5 s of aggregate pacing; without a SHARED
    # bucket they land in ~0.1 s. Generous lower bound to stay non-flaky.
    assert span >= 0.9, f"the shared bucket did not pace the pods (span={span:.2f}s)"

    # A different project has its OWN bucket: its command never waited.
    assert other["elapsed_s"] < 0.8, other["elapsed_s"]


def test_an_unenforceable_policy_is_refused_without_any_traffic(live_kali):
    _counters(reset=True)
    broken = dict(_policy(rate_per_s=1.0, burst=1))
    broken["version"] = "traffic-policy/v2"

    result = call(
        "execute_command",
        {
            "command": f"curl -sS -m 10 -o /dev/null -w '%{{http_code}}' {TARGET_BASE}/open",
            "session_id": f"e2e-refuse-{uuid.uuid4().hex[:6]}",
            "timeout_s": 30,
            "project_id": "e2e-refusal-proj",
            "run_id": "e2e-refusal-run",
            "traffic_policy": broken,
        },
    )

    assert result["returncode"] == 78
    assert result["stdout"] == ""
    assert result["traffic_warning"]
    assert "not enforceable" in result["traffic_warning"]
    assert _counters()["requests"] == 0, "a refused command must not reach the target"


# --- the bypass evidence gate ----------------------------------------------------


def _variant_spec(rate_per_s: float, experiment_id: str) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        phase="steady",
        url=f"{TARGET_BASE}/canonical/",  # the route-normalization variant
        rate_per_s=rate_per_s,
        duration_s=3.0,
        requests=max(1, round(rate_per_s * 3)),
        headers={"Authorization": f"Bearer {AUTH_SECRET}"},
    )


def test_the_known_variant_confirms_only_after_independent_repetition(mapped):
    harness = mapped["harness"]
    control = mapped["control"]
    canonical = next(
        e for e in harness.evidence
        if e.phase in ("steady", "refine") and e.rejection_ratio > 0
    )
    execute = build_kali_execute(
        project_id=mapped["project_id"], run_id=mapped["run_id"], mcp_url=MCP_URL
    )
    rate = canonical.offered_rate_per_s
    variant = asyncio.run(execute(_variant_spec(rate, "e2e-variant-0")))
    repeat = asyncio.run(execute(_variant_spec(rate, "e2e-variant-1")))

    assert variant.outcome == "measured" and repeat.outcome == "measured"
    assert variant.rejection_ratio == 0.0, "the normalized route must not be limited"
    assert variant.body_fingerprint and repeat.body_fingerprint

    mutation = MutationSpec(
        variant_id="route-normalization",
        family="endpoint-shape",
        description="trailing-slash normalization the limiter's key does not cover",
        payload=PathMutation(mutation_id="route-normalization", suffix="/"),
    )
    finding = judge_bypass(canonical, variant, repeat, mutation=mutation)
    assert finding.outcome == "confirmed"
    assert finding.gates.all_passed
    assert finding.gates.material_state_change and finding.gates.reproduced

    # Gate 4 is load-bearing: the SAME variant without an independent repeat is
    # never promoted to a confirmed finding.
    unrepeated = judge_bypass(canonical, variant, canonical, mutation=mutation)
    assert unrepeated.outcome != "confirmed"
    assert unrepeated.gates.reproduced is False

    # The number that governs traffic is the MEASURED one, and the confirmed
    # bypass stays a finding: it never enters the enforced policy.
    assert control.traffic_policy.source.startswith("measured")
    enforced = json.dumps(control.traffic_policy.model_dump(mode="json"))
    assert "route-normalization" not in enforced
    assert "bypass" not in enforced

    # ... and nothing downstream re-sends the normalized route.
    before = _counters()
    call(
        "execute_command",
        {
            "command": f"curl -sS -m 10 -o /dev/null -w '%{{http_code}}' {TARGET_BASE}/canonical",
            "session_id": f"e2e-nobypass-{uuid.uuid4().hex[:6]}",
            "timeout_s": 30,
            "project_id": mapped["project_id"],
            "run_id": mapped["run_id"],
            "traffic_policy": control.traffic_policy.model_dump(mode="json"),
        },
    )
    after = _counters()
    assert after["routes"].get("/canonical/", 0) == before["routes"].get("/canonical/", 0), (
        "a confirmed bypass must never be applied automatically to later traffic"
    )


def test_the_production_variant_probe_never_fakes_a_confirmation(mapped):
    """The harness's own `run_variant` replays the CANONICAL url (the mutation
    transport is not wired in this tranche), so it must read `no_bypass` - a
    gate that coerced that into a confirmation would be the bug this pins."""
    harness = mapped["harness"]
    mutation = MutationSpec(
        variant_id="route-normalization-untransported",
        family="endpoint-shape",
        description="no transport applies this mutation to the wire yet",
        payload=PathMutation(mutation_id="route-normalization-untransported", suffix="/"),
    )
    finding = asyncio.run(harness.judge_variant(mutation))
    assert finding.outcome != "confirmed"
    assert finding.gates.material_state_change is False


# --- the pipeline: order, persistence, browser-only -------------------------------


class _ScriptedOrchestrator:
    """Drives the REAL pipeline through both turns with the LIVE-measured profile."""

    def __init__(self, *, events: list, profile, verdict: GatewayVerdict):
        self._events = events
        self._profile = profile
        self._verdict = verdict
        self.rate_kwargs: dict = {}

    async def run_gateway(self, **kwargs):
        self._events.append("gateway")
        return self._verdict

    async def run_rate_limit(self, **kwargs):
        self._events.append("rate")
        self.rate_kwargs = dict(kwargs)
        return self._profile

    async def stop(self):
        self._events.append("stop")


class _RecordingRegistry:
    def __init__(self, events: list):
        self._events = events
        self.run_stats: dict = {}

    def create_run(self, *args, **kwargs):
        self._events.append("create_run")

    def set_run_status(self, *args, **kwargs):
        self._events.append("set_run_status")

    def upsert_job(self, *args, **kwargs):
        pass

    def set_run_stats(self, run_id, stats):
        self._events.append("set_run_stats")
        self.run_stats.update(stats)


def _drive_pipeline(monkeypatch, *, profile, verdict, job_subset=None):
    events: list[str] = []
    registry = _RecordingRegistry(events)
    seen: dict[str, dict] = {}
    orchestrator = _ScriptedOrchestrator(
        events=events, profile=profile, verdict=verdict
    )

    async def fake_run_job(job, input_assets, *, run_id, phase, extra, prepared_pod_inputs=None):
        events.append(f"job:{job.tool}")
        seen[job.tool] = {"extra": dict(extra)}
        return []

    def fake_read_assets(node_type, project_id, where=None, *, driver=None):
        if node_type == "Subdomain":
            return [{"name": TARGET_HOST}]
        if node_type == "BaseURL":
            return [{"url": TARGET_BASE}]
        return []

    monkeypatch.setattr(pipeline, "_touch_heartbeat", lambda run_id: None)

    async def scenario():
        await pipeline.run_pipeline(
            "e2e-rate-proj",
            run_id=f"e2e-rate-{uuid.uuid4().hex[:6]}",
            # `subfinder` is deliberately NOT used: it is a discovery job and is
            # pruned for a bare-IP seed (D14 host mode). `naabu` is a non-HTTP
            # job that does run, which is what the policy-scope assertion needs.
            job_subset=job_subset or ["naabu", "httpx"],
            run_job=fake_run_job,
            load_settings=lambda pid: {"target_domain": TARGET_HOST},
            registry=registry,
            read_assets=fake_read_assets,
            orchestrator_factory=lambda run_id: orchestrator,
            feed_mode="queued",
            with_analysis=False,
        )

    asyncio.run(scenario())
    return registry, seen, orchestrator


def test_the_pipeline_runs_auth_then_mapping_then_phase_zero_with_the_live_profile(
    mapped, monkeypatch
):
    profile = mapped["harness"].build_profile(
        RateLoopVerdict(outcome="mapped", rationale="e2e: deterministic controller truth")
    )
    assert profile.outcome == "mapped"
    assert profile.artifact_refs, "the live mapping produced no artifact references"

    registry, seen, orchestrator = _drive_pipeline(
        monkeypatch,
        profile=profile,
        verdict=GatewayVerdict(
            outcome="authenticated", account="alice", branch="request", rationale="e2e"
        ),
    )

    events = registry._events
    order = {name: events.index(name) for name in ("create_run", "gateway", "rate", "set_run_stats")}
    assert order["create_run"] < order["gateway"] < order["rate"] < order["set_run_stats"]
    assert order["set_run_stats"] < min(
        index for index, event in enumerate(events) if event.startswith("job:")
    )

    stored = registry.run_stats["rate_limit"]
    assert stored["outcome"] == "mapped"
    assert stored["artifact_refs"] == profile.artifact_refs
    assert all(ref.startswith("rate-artifact/v1:") for ref in stored["artifact_refs"])
    assert AUTH_SECRET not in json.dumps(stored)
    # References, never raw evidence: no body and no absolute path.
    assert "/data/" not in json.dumps(stored)

    # The measured policy is what the request job actually carries.
    assert seen["httpx"]["extra"]["traffic_policy"]["target_key"] == TARGET_HOST
    assert (
        seen["httpx"]["extra"]["traffic_policy"]["version"] == "traffic-policy/v2"
    )
    assert "naabu" in seen, "the non-HTTP job still runs"
    assert "traffic_policy" not in seen["naabu"]["extra"]


def test_a_browser_only_target_maps_nothing_and_stays_inconclusive(live_kali):
    _counters(reset=True)
    actor = ReconOrchestratorActor("e2e-browser-only", project_id="e2e-browser")
    profile = asyncio.run(
        actor.run_rate_limit(target_key=TARGET_HOST, url=f"{TARGET_BASE}/", browser_only=True)
    )

    assert profile.outcome == "inconclusive"
    assert profile.bypass_outcome == "inconclusive"
    assert profile.artifact_refs == []
    # Conservative pacing: at most one request per second, burst 1.
    assert profile.traffic_policy.rate_per_s <= 1.0
    assert profile.traffic_policy.burst == 1
    counters = _counters()
    assert counters["requests"] == 0, (
        "a browser-only target must cost ZERO Vegeta executions"
    )
