"""The worktree e2e stack for the unit threat model walkthroughs.

Topology (the `docker-compose.e2e.yml` contract):

- The shared base services (`neo4j`, `postgres`, `kali`, `lightrag`) come from
  the MAIN tree's `docker-compose.yml` + `docker-compose.dev.yml`, so the
  worktree joins the same `polymerhus_polymerhus-net` service DNS the agent
  uses in production.
- The `agent` is built FROM THIS WORKTREE (`polymerhus-agent-e2e:latest`) and
  mounts this worktree's `src`, `data`, `lightrag`, `db`, `skills`, `gateway`.
  The dev source mount means the tier tests the edited tree, not the baked
  image layer; the image is rebuilt only when it is missing.
- The `http-e2e-target` fixture is recreated so the current
  `tests/e2e/http_e2e_target.py` (white-jotter-001 sign-in surface) is loaded.
- The main tree `.env` supplies the provider keys; the overlay supplies the
  `LLM_HUNTING_THREAT_MODELLER` role (the main `.env` still carries the old
  pre-T10 key).

The stack is idempotent: `ensure_stack()` starts what is missing and waits for
the agent's `/health` (postgres, neo4j, kali_mcp). A daemon that is absent or a
stack that cannot come up returns a precise skip reason, never a silent pass.
"""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_TREE = Path(os.environ.get("POLYPHEMUS_MAIN_TREE", "/Users/diekgbbtt/polymerhus"))
MAIN_ENV = Path(os.environ.get(
    "POLYPHEMUS_MAIN_ENV", str(MAIN_TREE / ".env")))
AGENT_URL = os.environ.get("UNIT_THREAT_MODEL_AGENT_URL", "http://localhost:8081")

BASE_COMPOSE = [
    "docker", "compose",
    "-f", str(MAIN_TREE / "docker-compose.yml"),
    "-f", str(MAIN_TREE / "docker-compose.dev.yml"),
]
E2E_COMPOSE = ["docker", "compose", "-f", "docker-compose.e2e.yml"]
E2E_IMAGE = "polymerhus-agent-e2e:latest"


def _run(cmd: list[str], *, timeout: int = 900,
         input_text: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["POLYPHEMUS_MAIN_ENV"] = str(MAIN_ENV)
    return subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout,
        env=env, input=input_text,
    )


def docker_available() -> bool:
    try:
        return _run(["docker", "info"], timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _image_present() -> bool:
    try:
        return _run(["docker", "image", "inspect", E2E_IMAGE], timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _health_ok(timeout: float = 10.0) -> bool:
    try:
        with urllib.request.urlopen(f"{AGENT_URL}/health", timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def ensure_stack(timeout: int = 360) -> str | None:
    """Bring the worktree stack up; return None when ready, else a skip reason."""
    if not docker_available():
        return (
            "unit-threat-model e2e blocked: the Docker daemon is not running "
            "(start Docker Desktop and rerun)")
    if not MAIN_ENV.exists():
        return (
            "unit-threat-model e2e blocked: the main .env is absent at "
            f"{MAIN_ENV}")
    base = _run(BASE_COMPOSE + ["up", "-d", "neo4j", "postgres", "kali", "lightrag"])
    if base.returncode != 0:
        return (
            "unit-threat-model e2e blocked: the shared base services did not "
            f"start: {base.stderr.strip()[-400:]}")
    if not _image_present():
        build = _run(E2E_COMPOSE + ["build", "agent"], timeout=1800)
        if build.returncode != 0:
            return (
                "unit-threat-model e2e blocked: the worktree agent image did "
                f"not build: {build.stderr.strip()[-400:]}")
    up = _run(E2E_COMPOSE + ["up", "-d", "--force-recreate", "agent", "http-e2e-target"])
    if up.returncode != 0:
        return (
            "unit-threat-model e2e blocked: the worktree e2e services did not "
            f"start: {up.stderr.strip()[-400:]}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health_ok():
            return None
        time.sleep(3)
    return (
        f"unit-threat-model e2e blocked: {AGENT_URL}/health never became "
        f"healthy within {timeout}s")


def _agent_container() -> str | None:
    result = _run(E2E_COMPOSE + ["ps", "-q", "agent"], timeout=30)
    return result.stdout.strip() or None


_FORCE_KEY_SCRIPT = r"""
import json, os
from polymerhus.app.llm.providers import gateway_virtual_key
from polymerhus.app.llm.sync import GatewayClient

gateway_url = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000")
master = os.environ.get("LITELLM_MASTER_KEY", "")
key = os.environ.get("API_KEY_OPENCODE_GO", "")
if not key:
    raise SystemExit("API_KEY_OPENCODE_GO is absent in the agent env")
client = GatewayClient(gateway_url, master)
scoped = []
for entry in client.list_models():
    name = entry.get("model_name", "")
    if not name.startswith("opencode-go/"):
        continue
    params = dict(entry.get("litellm_params") or {})
    params["api_key"] = key
    info = dict(entry.get("model_info") or {})
    row_id = info.get("id") or entry.get("id")
    client.update_model(row_id, name, params, info)
    scoped.append(name)
client.ensure_virtual_key(gateway_virtual_key("opencode-go", key), scoped)
print(json.dumps({"updated": len(scoped), "virtual_key": gateway_virtual_key("opencode-go", key)[:12]}))
"""

_PREFLIGHT_SCRIPT = r"""
import json, os, uuid, urllib.error, urllib.request
from polymerhus.app.llm.providers import gateway_virtual_key

gateway_url = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000")
key = os.environ.get("API_KEY_OPENCODE_GO", "")
virtual = gateway_virtual_key("opencode-go", key)
body = json.dumps({
    "model": "opencode-go/deepseek-v4.1-flash",
    "messages": [{"role": "user", "content": "Reply with OK"}],
    "max_tokens": 8,
}).encode()
request = urllib.request.Request(
    f"{gateway_url}/chat/completions", data=body,
    headers={
        "Authorization": f"Bearer {virtual}",
        "Content-Type": "application/json",
        "x-opencode-session": uuid.uuid4().hex,
        "x-opencode-client": "polymerhus-e2e",
    },
)
try:
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
        print("OK", payload.get("choices", [{}])[0].get("message", {}).get("content"))
except urllib.error.HTTPError as exc:
    print("HTTP", exc.code, exc.read().decode("utf-8", "replace")[:500])
except Exception as exc:  # noqa: BLE001
    print("ERR", repr(exc)[:400])
"""


def _force_gateway_credentials() -> str | None:
    """Overwrite the shared gateway's stored OpenCode key and virtual key.

    The gateway's provider key lives in the shared `polymerhus_gateway`
    Postgres store, not in the container env; the startup sync intentionally
    keeps the last-known-good records when the provider catalog fetch fails
    (D9). A stale stored key therefore survives a container recreate. This
    force writes the current main-.env key into every `opencode-go/*`
    deployment and re-provisions the app-minted virtual key, then the
    preflight proves the routing.
    """
    container = _agent_container()
    if not container:
        return "unit-threat-model e2e blocked: the worktree e2e agent container is absent"
    result = _run(
        ["docker", "exec", "-i", container, "python3", "-"],
        input_text=_FORCE_KEY_SCRIPT, timeout=300,
    )
    if result.returncode != 0:
        return (
            "unit-threat-model e2e blocked: forcing the gateway provider key "
            f"failed: {(result.stderr or result.stdout).strip()[-500:]}")
    return None


def _preflight_llm() -> tuple[bool, str]:
    container = _agent_container()
    if not container:
        return False, "the worktree e2e agent container is absent"
    result = _run(
        ["docker", "exec", "-i", container, "python3", "-"],
        input_text=_PREFLIGHT_SCRIPT, timeout=180,
    )
    output = (result.stdout or result.stderr).strip()
    return result.returncode == 0 and output.startswith("OK"), output[-500:]


def ensure_llm() -> str | None:
    """The live-model bootstrap: force the shared gateway key, then route a
    real OpenCode Go completion. Returns a skip reason when the LLM edge is
    not usable; the LLM-free walkthroughs call `ensure_stack` alone."""
    forced = _force_gateway_credentials()
    if forced:
        return forced
    ok, detail = _preflight_llm()
    if not ok:
        return (
            "unit-threat-model e2e blocked: the gateway rejected the live "
            f"OpenCode Go route ({detail})")
    return None


def http_client():
    import httpx
    return httpx.Client(base_url=AGENT_URL, timeout=60.0)


def create_project(client, prefix: str = "utm-e2e") -> str:
    name = f"{prefix}-{uuid.uuid4().hex[:8]}"
    resp = client.post("/projects", json={"name": name}, timeout=60)
    assert resp.status_code == 200, f"create project failed: {resp.status_code} {resp.text}"
    return resp.json()["project_id"]


def seed_white_jotter_l1(project_id: str) -> dict:
    """Seed the white-jotter-001 L1 into the shared Neo4j (host connection)."""
    from neo4j import GraphDatabase
    from tests.conftest import neo4j_target
    from tests.e2e.white_jotter_fixture import load_white_jotter_l1

    uri, auth = neo4j_target()
    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session() as session:
            return load_white_jotter_l1(project_id, session)
    finally:
        driver.close()


def run_rows(project_id: str) -> list[dict]:
    from tests.integration.hunting_wiring_stack import hunting_run_rows
    return hunting_run_rows(project_id)


def wait_terminal(client, project_id: str, run_id: str, *,
                  timeout: float = 1500, interval: float = 5) -> dict:
    """Poll the LIVE run row through the agent API (the same store the run
    writes), not a host-side PG DSN that the test process may not carry."""
    terminal = {"complete", "failed", "stopped", "interrupted"}
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/projects/{project_id}/hunting/{run_id}", timeout=30)
        if resp.status_code == 200:
            last = resp.json()
            if last.get("status") in terminal:
                return last
        time.sleep(interval)
    raise AssertionError(
        f"run {run_id} did not reach a terminal within {timeout}s "
        f"(last observed: {last})")


def threat_model(project_id: str):
    from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
    return ThreatModelStore()


def read_model(project_id: str, unit_id: str):
    return threat_model(project_id).read_model(project_id, unit_id)


def read_loop_files(project_id: str, unit_id: str) -> list[dict]:
    return threat_model(project_id).read_loop_files(project_id, unit_id)


def read_completed_units(project_id: str) -> list[str]:
    return threat_model(project_id).read_completed_units(project_id)


def spec_files(project_id: str, hunt_key: str) -> tuple[list[str], list[str]]:
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
    store = HunterMemoryStore()
    return (
        store.produced_spec_files(project_id, hunt_key),
        store.consumed_spec_files(project_id, hunt_key),
    )


def pod_export_entries(project_id: str, spec_id: str) -> list[tuple[str, dict]]:
    from tests.integration.hunting_wiring_stack import pod_export_entries as _read
    return _read(project_id, spec_id)
