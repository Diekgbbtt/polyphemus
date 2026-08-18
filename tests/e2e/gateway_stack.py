"""Host-side driver for the #100 gateway live tier (integration/e2e).

The litellm proxy lives INSIDE the agent container on 127.0.0.1:4000 - ADR D1:
intra-container, NOT published to the host, and NOT reachable from the
`tests` service container either (it binds the agent's loopback). Every
gateway-surface probe therefore runs INSIDE the agent container via
`docker compose exec`. This module shells the compose CLI from the host; the
test modules skip when the agent container is not up.

The gateway tier is host-side by construction (the catalogue's runner
decision): the tests service container cannot reach port 4000, so the live
tests cannot run as `docker compose --profile test run tests`. They run with
the repo venv on the host and `docker compose exec` into the agent.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]

# The compose files used for EVERY live run. The dev overlay is part of the
# picture: the agent bind-mounts the working tree, so an exec'd probe always
# runs the CURRENT source (the tier tests the edited tree, never the baked
# image layer - the same rule as the `tests` service).
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]

# The gateway surface inside the agent container (ADR D1 internal port).
GATEWAY_URL = "http://127.0.0.1:4000"

AGENT_SERVICE = "agent"


def _run(cmd: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a host-side command against the repo root; die loudly on non-zero."""
    return subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout,
    )


def compose_ps(service: str = AGENT_SERVICE) -> list[dict]:
    """`docker compose ps` rows for a service ([] when it has no container)."""
    result = _run(COMPOSE + ["ps", "--format", "json", service])
    if result.returncode != 0:
        return []
    rows = []
    for line in result.stdout.strip().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def agent_is_up() -> bool:
    """True when the agent container exists and is running."""
    for row in compose_ps():
        if row.get("State") == "running":
            return True
    return False


def agent_is_down() -> bool:
    """True when the agent container exists and is NOT running (stopped)."""
    for row in compose_ps():
        if row.get("State") != "running":
            return True
    return False


def agent_exec(args: list[str], *, env: dict | None = None,
               timeout: int = 600) -> subprocess.CompletedProcess:
    """`docker compose exec -T [-e K=V ...] agent <args>`; returns the result.

    `env` merges `-e K=V` flags onto the exec'd process (the service env is
    inherited; an explicit `-e` overrides). Stdout/stderr are captured; the
    caller reads `.returncode`, `.stdout`, `.stderr`."""
    cmd = list(COMPOSE) + ["exec", "-T"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [AGENT_SERVICE] + list(args)
    return _run(cmd, timeout=timeout)


def agent_python(code: str, *, env: dict | None = None,
                 timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a Python snippet inside the agent container, returning the result."""
    return agent_exec(
        ["python", "-c", code],
        env={**({"PYTHONUNBUFFERED": "1"} if env is None else {}), **(env or {})},
        timeout=timeout,
    )


def agent_http_get(path: str, *, key: str | None = None) -> tuple[int, dict]:
    """In-container GET against the gateway surface; returns (status, body).

    With no explicit key the snippet resolves `LITELLM_MASTER_KEY` from the
    container's own env (the gateway surface requires a valid proxy key; the
    stack's admin key only exists inside the service env, ADR D1 prevents the
    host from reaching port 4000)."""
    code = (
        "import httpx, json, os\n"
        f"url = {GATEWAY_URL!r} + {path!r}\n"
        f"key = {key!r} or os.environ.get(\"LITELLM_MASTER_KEY\")\n"
        "headers = {}\n"
        "if key:\n"
        "    headers['Authorization'] = f'Bearer {key}'\n"
        "r = httpx.get(url, headers=headers, timeout=15)\n"
        "print(r.status_code)\n"
        "print(r.text)\n"
    )
    result = agent_python(code)
    if result.returncode != 0:
        raise RuntimeError(f"in-container GET {path} failed: {result.stderr}")
    lines = result.stdout.strip().splitlines()
    status = int(lines[0])
    body_text = "\n".join(lines[1:])
    try:
        body = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        body = {"_raw": body_text}
    return status, body


def gateway_logs(service: str = AGENT_SERVICE) -> str:
    """`docker compose logs` for the service (all lines, no tail bound)."""
    result = _run(COMPOSE + ["logs", "--no-color", service], timeout=120)
    return result.stdout + result.stderr


def model_info() -> list[dict]:
    """The live registered set: `GET /model/info` (auth LITELLM_MASTER_KEY,
    inherited from the service env) parsed to the `data` list."""
    status, body = agent_http_get("/model/info", key=None)
    if status != 200:
        raise RuntimeError(f"/model/info answered HTTP {status}: {body}")
    data = body.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"/model/info returned no 'data' list: {body}")
    return data


# --- The raw-source oracle (catalogue C8) ------------------------------------
#
# The registered set's expectation is derived from the TWO raw sources - the
# live models.dev catalog and the provider /v1/models - through the spec's
# join rules (D5/D9), NEVER from the sync's output. The join is executed with
# the pure mapping functions (`polymerhus.app.llm.sync.build_desired`): they
# are the spec rules in code form, unit-pinned, I/O-free; what the oracle adds
# is the LIVE fetch of the sources themselves.

DEFAULT_REGISTRY_URL = "https://models.dev/catalog.json"

# Provider selection mirrors the sync's `API_KEY_{PROVIDER}` convention; the
# .env file is read directly so the host environment cannot leak in.

ENV_FILE = REPO_ROOT / ".env"


def env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def configured_api_keys() -> dict[str, str]:
    """{provider: api_key} for every `API_KEY_<PROVIDER>` present in .env.

    The provider id is recovered by inverting the app's `_key_env`
    normalization (providers.py): `API_KEY_OPENCODE_GO` -> the provider id
    `opencode-go` (hyphens in a provider id round-trip as underscores in the
    env var name). Without this inversion a hyphenated provider would be
    misread as `opencode_go` and silently dropped from the oracle."""
    values = env_file_values()
    result: dict[str, str] = {}
    for key, value in values.items():
        if not (key.startswith("API_KEY_") and value and not value.startswith("#")):
            continue
        provider = key[len("API_KEY_"):].lower().replace("_", "-")
        result[provider] = value
    return result


def fetch_catalog() -> dict:
    """The live models.dev registry (the raw source; cached per run)."""
    with httpx.Client(timeout=60.0) as client:
        response = client.get(DEFAULT_REGISTRY_URL)
        response.raise_for_status()
        return response.json()


def fetch_provider_ids(provider: str, api_key: str) -> set[str]:
    """The provider's live `/v1/models` id set (existence-only source)."""
    from polymerhus.app.llm.providers import PROVIDERS

    url = f"{PROVIDERS[provider]}/models"
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        response.raise_for_status()
        data = response.json()
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise RuntimeError(f"{url} returned no 'data' list")
    return {item["id"] for item in entries if isinstance(item, dict)
            and isinstance(item.get("id"), str)}


def oracle_desired(*, synced_at: str = "2026-08-17T00:00:00+00:00") -> list:
    """The spec-derived desired set for the configured providers, live sources.

    Returns `build_desired(...)` output - the join of live /v1/models ids with
    the live catalog per the D5/D9 rules. The catalog fetch is cached per
    process (one fetch serves every assertion in a run)."""
    from polymerhus.app.llm.providers import PROVIDERS
    from polymerhus.app.llm.sync import build_desired

    catalog = fetch_catalog()
    provider_ids: dict[str, set[str]] = {}
    api_keys = configured_api_keys()
    for provider, key in api_keys.items():
        if provider not in PROVIDERS:
            continue
        provider_ids[provider] = fetch_provider_ids(provider, key)
    return build_desired(provider_ids, catalog, base_urls=PROVIDERS,
                         api_keys=api_keys, synced_at=synced_at)


def skip_reason() -> str | None:
    """The reason the gateway live tier must skip, or None to run."""
    if not agent_is_up():
        return ("the agent container is not running - bring the stack up "
                "(`docker compose -f docker-compose.yml -f "
                "docker-compose.dev.yml up -d agent`) before the gateway live "
                "tier")
    return None
