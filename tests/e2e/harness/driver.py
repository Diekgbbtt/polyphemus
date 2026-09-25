# The in-container driver for the pod e2e tier (#84, E5-E8). Runs INSIDE the
# sibling agent container (docker compose exec pod-e2e-agent python driver.py).
#
# It drives the pod exactly as the parent HuntingAgent would in production:
#   - the run is wrapped in `hunt_session(run_id, hunt_id)` so the pod's
#     D84-7 session binding resolves the real session/checkpointer stack
#     (the pod roles are session/high, registered in T1),
#   - `kb_retrieve` is the MOCKED seam: the symptom-technique KB workstream is
#     not merged, so the driver injects a canned SymptomTechniqueResult set
#     (POD_E2E_MOCK_KB=1) instead of a live KB call - the one mocked
#     collaborator, taints realism, acknowledged,
#   - the pod roles are wired to muse-spark by the compose overlay,
#   - the driver persists to /srv/tests/e2e/fixtures/runs/<POD_RUN_ID>/
#     the artifacts the NFR scorer reads: envelope.json (the IA-4 D5+D6), plus
#     the pod-memory notes (D84-32) for note-detail scoring.
#
# A single PASS is one spec through the pod: env POD_SPEC_PATH points at the
# YAML fixture (the worktree is mounted at /srv, so the path matches).
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ROOT = Path("/srv")
RUNS = ROOT / "tests" / "e2e" / "fixtures" / "runs"
RUN_ID = os.environ.get("POD_RUN_ID", "pod-unset")
SPEC_PATH = os.environ.get("POD_SPEC_PATH", "")
PROJECT_ID = os.environ.get("POD_PROJECT_ID", "pod-e2e")


def _load_spec() -> dict[str, Any]:
    if not SPEC_PATH:
        raise SystemExit("POD_SPEC_PATH unset")
    with open(SPEC_PATH, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    # The typed base the pod's verification ranges over: keep only the D4 keys
    # (the fixture carries extra name/comments).
    keep = {"target_identity", "verification_symptoms", "testing_pattern",
            "assumptions", "payload_vector_space", "rationale",
            "interpretation_guidance"}
    return {k: spec[k] for k in keep if k in spec}


def _mocked_kb(query: str, *, fault_id: str = "", technological_axis=()) -> dict:
    """The canned KB (POD_E2E_MOCK_KB=1): keyword-substring match against the
    mock-kb.yaml entries; a no-match returns the empty result (fail-open O13)."""
    kb_file = os.environ.get("POD_E2E_MOCK_KB_FILE",
                             "/srv/tests/e2e/fixtures/mock-kb.yaml")
    with open(kb_file, encoding="utf-8") as fh:
        kb = yaml.safe_load(fh).get("symptom_kb", {})
    q = (query or "").lower()
    for key, entry in kb.items():
        if key.lower() in q:
            return {"symptoms": entry.get("symptoms", []),
                    "techniques": entry.get("techniques", []),
                    "source": entry.get("source", "mock-kb")}
    return {"symptoms": [], "techniques": [], "source": "mock-kb"}


def _persist(name: str, data: Any) -> None:
    out = RUNS / RUN_ID
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(json.dumps(data, indent=2, default=str))


async def _run_pod(spec: dict) -> dict[str, Any]:
    """Wrap `arun_pod` in the hunt_session context - exactly the parent
    HuntingAgent's `_pod_loop` shape (IA-3/IA-4)."""
    from polymerhus.attack.hunting.llm import hunt_session
    from polymerhus.attack.hunting.pod import arun_pod

    run_id = f"pod-e2e-{RUN_ID}"
    try:
        from polymerhus.attack.hunting.pod.pod_memory import spec_identifier
        spec_id = spec_identifier(
            str(spec.get("fault") or "fault"), str(spec.get("strategy") or "strategy"))
        with hunt_session(run_id, f"hunt-{RUN_ID}"):
            return await arun_pod(spec, run_id=run_id, kb_fn=_mocked_kb,
                                  trace_fn=None, project_id=PROJECT_ID,
                                  spec_id=spec_id)
    except Exception as exc:  # noqa: BLE001 - the pod must never raise
        _persist("driver_error.json", {"error": str(exc)})
        return {"verdict": "unsuccessful", "evidence": {"error": str(exc)}}


def _read_notes(spec: dict) -> list[dict]:
    """Read the pod's run notes back from the per-project memory-store root the
    production lane wrote (D84-33 `data/<project_id>/test-executor-pod/` under
    the hunting module), keyed by the #164 spec id (`<fault>_<strategy>`) - the
    N3 note-detail evidence source.

    The `experiment_summary` is the TERMINAL RECORD of each variant's
    experiment-log slice (D84-35, T2) - NOT a notes.yaml record - so it is
    surfaced here from the variant files, shaped like the note records the NFR
    scorer expects; `kb_insight`/`freeform` come from notes.yaml."""
    try:
        from polymerhus.attack.hunting.pod.pod_memory import (
            PodMemoryStore,
            spec_identifier,
        )

        store = PodMemoryStore(project_id=PROJECT_ID)
        spec_id = spec_identifier(
            str(spec.get("fault") or "fault"), str(spec.get("strategy") or "strategy"))
        notes = [n for n in store.read_notes(spec_id)
                 if n.get("kind") != "experiment_summary"]
        for order in store.list_variant_orders(spec_id):
            body = store.read_experiment_log(spec_id, order).get("experiment_summary")
            if body:
                notes.append({"kind": "experiment_summary", "order": order,
                              "body": body})
        return notes
    except Exception:  # noqa: BLE001 - a missing store yields [], never a raise
        return []


def main() -> None:
    spec = _load_spec()
    _persist("spec.json", spec)
    out = asyncio.run(_run_pod(spec))
    _persist("envelope.json", out)
    _persist("notes.json", _read_notes(spec))
    print(json.dumps({"run_id": RUN_ID, "verdict": out.get("verdict"),
                      "terminal_reason": out.get("evidence", {}).get(
                          "terminal_reason")}, indent=2))


# --- the #238 follow-up control-plane harness (Task 9) ---------------------------
#
# Ruling 4 (plan pre-flight): the control-plane harness lives in THIS module,
# alongside (never replacing) the pod driver's `main()`. It drives runs the way
# an operator does - the PUBLIC HTTP API only - and touches PostgreSQL only to
# verify what the run PERSISTED, never to drive it. The target fixtures expose
# no host ports by design, so their control endpoints are read from inside
# their own container (the fixture API is unchanged either way).
#
# Why here: the pod driver above and this harness are the two halves of the same
# E2E tier, and a second module would need the same compose/env resolution.

#: The API the agent publishes on the host (`docker-compose.yml`: `8080:8080`).
API_BASE = os.environ.get("POLYPHEMUS_API_BASE", "http://localhost:8080").rstrip("/")

#: The #238 E2E stack: base + the E2E overlay (which routes the agent's two
#: model roles at the deterministic fixture).
E2E_COMPOSE = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "docker-compose.e2e.yml",
]
AGENT_CONTAINER_SERVICE = "agent"
PROVIDER_SERVICE = "rate-limit-llm"

#: `polymerhus.app.clients.pg._TERMINAL_RUN_STATUSES` - mirrored (not imported)
#: so this module stays importable inside the pod container, where the host's
#: `polymerhus` package is not the one under test.
TERMINAL_RUN_STATUSES = frozenset({"complete", "failed"})

#: The five isolated target postures (`docker-compose.e2e.yml`).
TARGET_SERVICES = {
    "no_limiter": "rate-matrix-no-limiter",
    "high_limit": "rate-matrix-high-limit",
    "low_limit": "rate-matrix-low-limit",
    "false_bypass": "rate-matrix-false-bypass",
    "burst_inconclusive": "rate-matrix-burst-inconclusive",
}


class HarnessError(RuntimeError):
    """A control-plane step failed: the run itself, the API, or the fixture."""


def _compose(args: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess:
    from pathlib import Path  # noqa: PLC0415

    root = Path(__file__).resolve().parents[3]
    return subprocess.run(E2E_COMPOSE + args, cwd=root, capture_output=True,
                          text=True, timeout=timeout)


def service_state(service: str) -> str | None:
    """The service's container state, or None when it has no container."""
    result = _compose(["ps", "--format", "json", service], timeout=60)
    if result.returncode != 0:
        return None
    for line in result.stdout.strip().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        return row.get("State")
    return None


def stack_up() -> bool:
    """The agent API and the deterministic provider must both be serving."""
    if service_state(AGENT_CONTAINER_SERVICE) != "running":
        return False
    try:
        return provider_counters()["status"] == "ok"
    except Exception:  # noqa: BLE001 - the stack gate is best-effort
        return False


def stack_unavailable_reason() -> str | None:
    """Why the live tier must skip, or None when it can run."""
    state = service_state(AGENT_CONTAINER_SERVICE)
    if state != "running":
        return (
            f"the agent container is {state or 'absent'} - bring the #238 stack "
            "up (`docker compose -f docker-compose.yml -f docker-compose.e2e.yml "
            "up -d postgres neo4j kali agent rate-limit-llm`) before the "
            "functional E2E"
        )
    try:
        provider_counters()
    except Exception as exc:  # noqa: BLE001
        return f"the deterministic model provider is not serving: {exc}"
    try:
        _http("GET", "/health", timeout=10)
    except Exception as exc:  # noqa: BLE001
        return f"the control-plane API at {API_BASE} is not answering: {exc}"
    return None


def _http(method: str, path: str, body: dict | None = None, *,
          timeout: float = 60.0) -> dict:
    """One public-API call; raises `HarnessError` with the API's own detail."""
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise HarnessError(f"{method} {path} -> HTTP {exc.code}: {detail[:400]}") from exc
    except OSError as exc:
        raise HarnessError(f"{method} {path} -> {exc}") from exc
    try:
        return json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        return {"_raw": payload}


# --- the public control-plane API -------------------------------------------------


def create_project(name: str) -> str:
    """`POST /projects` - a fresh project id."""
    return _http("POST", "/projects", {"name": name})["project_id"]


def configure_project(project_id: str, recon: dict) -> dict:
    """`PUT /projects/{id}/settings` - the operator's recon settings blob."""
    return _http("PUT", f"/projects/{project_id}/settings", {"recon": recon})


def store_auth(project_id: str, *, overview: Any = None, accounts: Any = None) -> dict:
    """`PUT /projects/{id}/auth` - the operator's auth seed (D220-12)."""
    payload: dict = {}
    if overview is not None:
        payload["overview"] = overview
    if accounts is not None:
        payload["accounts"] = accounts
    return _http("PUT", f"/projects/{project_id}/auth", payload)


def start_recon(project_id: str, jobs: list[str] | None = None, *,
                with_analysis: bool = False) -> str:
    """`POST /projects/{id}/recon` - launch a real run; returns its run id.

    `with_analysis=False` is the recon-only dispatch: the analysis consumer is a
    separate subsystem and would only add unrelated work to the gate.
    """
    body: dict = {"with_analysis": with_analysis}
    if jobs is not None:
        body["jobs"] = jobs
    return _http("POST", f"/projects/{project_id}/recon", body)["run_id"]


def read_run(project_id: str, run_id: str) -> dict:
    """`GET /projects/{id}/recon/{run_id}` - status, stats and per-job rows."""
    return _http("GET", f"/projects/{project_id}/recon/{run_id}")


def read_run_stats(project_id: str, run_id: str) -> dict:
    """The run's persisted `stats` blob (the trajectory record)."""
    return read_run(project_id, run_id).get("stats") or {}


def wait_for_run(project_id: str, run_id: str, *, timeout_s: float = 900.0,
                 poll_s: float = 2.0) -> dict:
    """Poll until the run reaches a terminal status; return its status payload.

    A timeout reports the last status, the provider counters and the last job
    rows - the diagnostics an operator needs to see WHERE it stalled.
    """
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        last = read_run(project_id, run_id)
        if last.get("status") in TERMINAL_RUN_STATUSES:
            return last
        time.sleep(poll_s)
    detail = {
        "project_id": project_id,
        "run_id": run_id,
        "last_status": last.get("status"),
        "current_phase": last.get("current_phase"),
        "provider": _safe_provider_counters(),
        "per_job": last.get("per_job"),
    }
    raise HarnessError(
        f"run {run_id} did not reach a terminal status within {timeout_s:.0f}s: "
        f"{json.dumps(detail, default=str)[:1500]}"
    )


# --- the deterministic provider ---------------------------------------------------


def _in_container_get(service: str, url: str, *, timeout: int = 60) -> dict:
    """`GET url` from INSIDE `service` (compose DNS + no published ports)."""
    script = (
        "import json, urllib.request\n"
        f"print(urllib.request.urlopen({url!r}, timeout=15).read().decode())\n"
    )
    result = _compose(["exec", "-T", service, "python", "-c", script],
                      timeout=timeout)
    if result.returncode != 0:
        raise HarnessError(
            f"in-container GET {url} on {service} failed: "
            f"{(result.stderr or result.stdout).strip()[:400]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def provider_counters() -> dict:
    """The fixture's own request counters - the proof the REAL model client
    reached it, and per production turn."""
    return _in_container_get(PROVIDER_SERVICE, "http://127.0.0.1:8080/health")


def agent_env(name: str) -> str | None:
    """A variable from the RUNNING agent container's environment.

    The scenario knobs that belong to the stack (`RATE_LIMIT_PROFILE_TTL_S`,
    the threshold bounds) are container environment, not test knobs: a scenario
    that needs one reads it here and SKIPS loudly when the stack was not brought
    up with it, rather than quietly asserting a weaker property.
    """
    result = _compose(
        ["exec", "-T", AGENT_CONTAINER_SERVICE, "printenv", name], timeout=60)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _safe_provider_counters() -> dict:
    try:
        return provider_counters()
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        return {"unavailable": str(exc)[:200]}


# --- the deterministic target fixtures --------------------------------------------


def reset_target(posture: str) -> str:
    """`POST /reset` on the posture's fixture; returns the new generation id."""
    service = _target_service(posture)
    script = (
        "import json, urllib.request\n"
        "req = urllib.request.Request('http://127.0.0.1:80/reset', data=b'', method='POST')\n"
        "print(urllib.request.urlopen(req, timeout=15).read().decode())\n"
    )
    result = _compose(["exec", "-T", service, "python", "-c", script], timeout=60)
    if result.returncode != 0:
        raise HarnessError(
            f"POST /reset on {service} failed: "
            f"{(result.stderr or result.stdout).strip()[:400]}")
    return json.loads(result.stdout.strip().splitlines()[-1])["generation"]


def read_target_counters(posture: str, generation: str) -> dict:
    """`GET /counters?generation=<id>` - a STALE generation is a 409, never a
    silent read of another scenario's state."""
    return _in_container_get(
        _target_service(posture),
        f"http://127.0.0.1:80/counters?generation={generation}")


def read_target_events(posture: str, generation: str) -> dict:
    """`GET /events?generation=<id>` - the ordered, timestamped request log."""
    return _in_container_get(
        _target_service(posture),
        f"http://127.0.0.1:80/events?generation={generation}")


def _target_service(posture: str) -> str:
    try:
        return TARGET_SERVICES[posture]
    except KeyError:
        raise HarnessError(
            f"unknown posture {posture!r}; known: {sorted(TARGET_SERVICES)}") from None


# --- the public-API smoke trajectory (Task 9 Step 5) ------------------------------

#: The auth seed the smoke trajectory stores. The gateway turn needs a usable
#: account AND a declared replayability fact, or the production gate skips the
#: loop (`no_auth_surface`) or asks the fixture for the generation branch.
#: #238 A1: the shape is the PUBLIC contract (`validate_overview` /
#: `validate_account`) - no `target`/`auth-surface` pseudo-fields, and the
#: account map is the mapping the API expects (never `{"accounts": ...}` - the
#: `store_auth` wrapper already adds that key).
SMOKE_OVERVIEW = {
    "http-client-replayability": True,
    "required_headers": ["X-E2E-Correlation"],
    "notes": "Disposable issue 238 fixture.",
}
SMOKE_ACCOUNTS = {
    "smoke-account": {
        "origin": "operator",
        "status": "valid",
        "snapshot": {
            "headers": {"X-E2E-Correlation": "issue-238-smoke"},
            "cookies": [{"name": "session", "value": "e2e-smoke-cookie"}],
        },
    }
}

#: #238 B5: the transport scheme every #238 project declares. The fixtures
#: listen on plain HTTP/80; the scheme is EXPLICIT (never inferred from a DNS
#: name) so the mapping replays over the transport the target speaks.
E2E_TARGET_SCHEME = "http"


def smoke_rate_trajectory(*, posture: str = "no_limiter") -> dict:
    """Launch ONE real run through the public API and return its evidence.

    The run is the smallest one that reaches BOTH orchestrator turns: an auth
    gateway turn (a stored, usable account) and a rate-limit turn (the target's
    canonical URL). Nothing here scripts the orchestrator: if the production
    actor loop does not call the deterministic provider, the provider counters
    stay empty and the caller fails.
    """
    project_id = create_project(f"e2e-smoke-{posture}")
    configure_project(project_id, {
        "target_seed": _target_service(posture),
        "settings": {"scan_mode": "safe"},
    })
    store_auth(project_id, overview=SMOKE_OVERVIEW, accounts=SMOKE_ACCOUNTS)
    before = provider_counters()
    run_id = start_recon(project_id, ["subfinder"])
    result = wait_for_run(project_id, run_id)
    after = provider_counters()
    return {
        "project_id": project_id,
        "run_id": run_id,
        "status": result.get("status"),
        "stats": result.get("stats") or {},
        "provider": after,
        "provider_before": before,
    }


if __name__ == "__main__":
    main()
