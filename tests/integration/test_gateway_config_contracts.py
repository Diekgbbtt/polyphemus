"""C1-C4: the gateway's DEPLOYMENT configuration contracts (#100, T1 #104).

The catalogue (`docs/design/llm-gateway-100-assertions.md`) splits the static
surface: C2 (the YAML's own shape) is already pinned by the unit tier
(`tests/test_gateway_config.py` - model_list empty, store_model_in_db, the D8
cache rules, no secrets) and is NOT duplicated here. This module pins the
remaining deployment contracts against the repo tree:

- C1: the compose `agent` service env (`DATABASE_URL` on the same postgres
  INSTANCE as `POSTGRES_DSN` but in the dedicated `polymerhus_gateway`
  database, `LITELLM_MASTER_KEY`), the published/unpublished ports, and the
  Dockerfile entrypoint wiring (`CONFIG_FILE_PATH`, `CMD python -m
  polymerhus.app.gateway_entrypoint`).
- C3: `requirements-gateway.txt` pins `litellm[proxy]==1.96.0`,
  `fastapi==0.140.6`, `httpx==0.28.1` exactly.
- C4: the dev overlay keeps the two ASGI processes' reload policies
  INDEPENDENT (ADR D1): the agent gains `--reload`, the proxy command NEVER
  carries `--reload`.

Static by construction: pure file parses, no live stack, no network. These
run in the integration tier because they pin the DEPLOYMENT surface (the
unit tier already owns the entrypoint's branch logic).
"""

from pathlib import Path

import pytest
import yaml

from polymerhus.app.gateway_entrypoint import PROXY_PORT, _proxy_command

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPOSE_BASE = REPO_ROOT / "docker-compose.yml"
COMPOSE_DEV = REPO_ROOT / "docker-compose.dev.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
REQUIREMENTS_GATEWAY = REPO_ROOT / "requirements-gateway.txt"


@pytest.fixture(scope="module")
def base_compose() -> dict:
    if not COMPOSE_BASE.exists():
        pytest.fail("docker-compose.yml missing - required by C1")
    return yaml.safe_load(COMPOSE_BASE.read_text())


@pytest.fixture(scope="module")
def dev_compose() -> dict:
    if not COMPOSE_DEV.exists():
        pytest.fail("docker-compose.dev.yml missing - required by C4")
    return yaml.safe_load(COMPOSE_DEV.read_text())


# ---------------------------------------------------------------------------
# C1 - compose agent env + ports, Dockerfile entrypoint (D10 env contract) --
# ---------------------------------------------------------------------------

def test_c1_agent_env_carries_gateway_contract(base_compose):
    services = base_compose.get("services", {})
    agent = services.get("agent")
    assert isinstance(agent, dict), "compose must declare the agent service"
    env = agent.get("environment", {})
    assert isinstance(env, dict)
    # DATABASE_URL is litellm's own DB pointer: the SAME postgres INSTANCE as
    # the agent's POSTGRES_DSN (ADR D1) but a DEDICATED database - litellm's
    # prisma schema machinery owns its target database and destroys or refuses
    # shared ones (P3005 / destructive db push, verified 2026-08-17). The
    # database is created by db/postgres/init.sql.
    from urllib.parse import urlsplit
    agent_dsn = urlsplit(env.get("DATABASE_URL", ""))
    pg_dsn = urlsplit(env.get("POSTGRES_DSN", ""))
    assert (agent_dsn.hostname, agent_dsn.port) == (pg_dsn.hostname, pg_dsn.port), (
        "DATABASE_URL must share the postgres INSTANCE with POSTGRES_DSN (ADR D1)")
    assert agent_dsn.path == "/polymerhus_gateway", (
        "DATABASE_URL must point at the gateway's DEDICATED database")
    assert pg_dsn.path == "/polymerhus"
    assert agent_dsn.path != pg_dsn.path, (
        "a shared DATABASE would put litellm's schema machinery against the "
        "agent's tables (P3005 / destructive db push - verified 2026-08-17)")
    # The dev default master key ships in-repo so a clean clone runs; the
    # operator's .env overrides it (ADR D10 - never a production key).
    assert env.get("LITELLM_MASTER_KEY") == "sk-polymerhus-dev-gateway", (
        "the compose default LITELLM_MASTER_KEY is the documented dev value")
    # The proxy port is INTRA-CONTAINER ONLY (D1): 8080 published, 4000 not.
    ports = agent.get("ports", [])
    assert ports == ["8080:8080"], (
        f"agent publishes ONLY 8080; the proxy port {PROXY_PORT} must stay "
        f"internal (got {ports})")


def test_c1_dockerfile_entrypoint_contract():
    if not DOCKERFILE.exists():
        pytest.fail("Dockerfile missing - required by C1")
    text = DOCKERFILE.read_text()
    assert 'ENV CONFIG_FILE_PATH="/srv/gateway/litellm_config.yaml"' in text, (
        "the Dockerfile must bake the gateway config path (CONFIG_FILE_PATH)")
    assert 'CMD ["python", "-m", "polymerhus.app.gateway_entrypoint"]' in text, (
        "the container CMD must be the gateway entrypoint module")


# ---------------------------------------------------------------------------
# C3 - requirements-gateway.txt pinning (D10 one-file review) ---------------
# ---------------------------------------------------------------------------

def test_c3_gateway_requirements_are_pinned():
    if not REQUIREMENTS_GATEWAY.exists():
        pytest.fail("requirements-gateway.txt missing - required by C3")
    pinned: dict[str, str] = {}
    for line in REQUIREMENTS_GATEWAY.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            package, _, version = line.partition("==")
            pinned[package.strip()] = version.strip()
    assert pinned.get("litellm[proxy]") == "1.96.0", (
        "litellm[proxy] must stay pinned at 1.96.0 (ADR D10 ratifies the "
        "version; a bump is a one-file review)")
    assert pinned.get("fastapi") == "0.140.6", (
        "fastapi pinned at 0.140.6 (0.140.7 removed get_flat_dependant, "
        "breaking the 1.96.0 proxy at boot)")
    assert pinned.get("httpx") == "0.28.1", (
        "httpx pinned at 0.28.1 (the sync's models.dev fetch surface)")


# ---------------------------------------------------------------------------
# C4 - independent reload policies (ADR D1) ---------------------------------
# ---------------------------------------------------------------------------

def test_c4_dev_overlay_reloads_only_the_agent(dev_compose, base_compose):
    services = dev_compose.get("services", {})
    agent = services.get("agent")
    assert isinstance(agent, dict), "the dev overlay must extend the agent service"
    env = agent.get("environment", {})
    assert isinstance(env, dict)
    args = env.get("AGENT_UVICORN_ARGS", "")
    assert "--reload" in args, (
        "the dev overlay must give the AGENT uvicorn --reload (live edits)")
    assert "--reload-dir /srv/src" in args
    # The dev overlay bind-mounts the gateway config (live-edit without rebuild).
    volumes = agent.get("volumes", [])
    assert "./gateway:/srv/gateway" in volumes, (
        "the dev overlay must bind-mount ./gateway at /srv/gateway")


def test_c4_proxy_command_never_reloads():
    """ADR D1: the two ASGI processes keep INDEPENDENT reload policies. The
    proxy's launcher command is fixed - it must NEVER carry --reload (the
    proxy is the routing substrate, not the live-edited surface)."""
    for config_path in (None, "/srv/gateway/litellm_config.yaml"):
        cmd = _proxy_command(config_path)
        assert "--reload" not in cmd, (
            f"the proxy command must never reload (got {cmd})")
        assert cmd[cmd.index("--port") + 1] == str(PROXY_PORT), (
            f"the proxy must bind the internal port {PROXY_PORT} (got {cmd})")
