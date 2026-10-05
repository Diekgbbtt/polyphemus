"""Integration tests for the eval compose overlays.

Render `docker compose config` against a synthetic env in a tmp copy (assert on
the render output, never on file text) for both overlays:

- `eval/docker-compose.eval.yml`: the env-drift guard;
- `eval/docker-compose.dashboard.yml`: the demo dashboard (synthetic store,
  read API, Vite dashboard) merged beside the normal stack.

Plus the non-eval control: the base render keeps its service set, and the
dashboard trio never appears without its overlay. Skip cleanly when docker is
absent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPLETE_ENV = {
    "NEO4J_URI": "bolt://neo4j:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "polymerhus",
    "POSTGRES_DSN": "postgresql://polymerhus:polymerhus@postgres:5432/polymerhus",
    "KALI_MCP_URL": "http://kali:8000/mcp",
    "LLM_CONFIGURATOR": "opencode:manual/test",
    "LLM_TRIAGER": "opencode:manual/test",
    "LLM_JOB_ORCHESTRATOR": "opencode:manual/test",
    "LLM_CRAWLER": "opencode:manual/test",
    "LLM_ANALYSER": "opencode:manual/test",
    "LLM_HUNTING_ORCHESTRATOR": "opencode:manual/test",
    "LLM_HUNTING_HUNTER": "opencode:manual/test",
    "LLM_POD_RUNNER": "opencode:manual/test",
    "LLM_POD_TRIAGER": "opencode:manual/test",
}

BASE_SERVICES = {"agent", "kali", "postgres", "neo4j", "lightrag"}

EVAL_OVERLAY = "eval/docker-compose.eval.yml"
DASHBOARD_OVERLAY = "eval/docker-compose.dashboard.yml"
REAL_OVERLAY = "eval/docker-compose.dashboard.real.yml"
# The demo trio the dashboard overlay adds; nothing else may appear with it.
DASHBOARD_SERVICES = {"eval-store", "eval-api", "eval-dashboard"}
# The real overlay adds only the read API and the dashboard.
REAL_SERVICES = {"eval-api", "eval-dashboard"}

docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI unavailable"
)


def stage(
    tmp_path: Path,
    env: dict[str, str] | None,
    with_overlay: bool = True,
    with_dashboard: bool = False,
    with_real: bool = False,
) -> Path:
    """A tmp compose project mirroring the instance layout (root files plus
    the eval overlay under `eval/`); the repo-root `.env` is never read."""
    shutil.copy(REPO_ROOT / "docker-compose.yml", tmp_path / "docker-compose.yml")
    shutil.copy(REPO_ROOT / "docker-compose.dev.yml", tmp_path / "docker-compose.dev.yml")
    (tmp_path / "eval").mkdir(exist_ok=True)
    if with_overlay:
        shutil.copy(REPO_ROOT / EVAL_OVERLAY, tmp_path / EVAL_OVERLAY)
    if with_dashboard:
        shutil.copy(REPO_ROOT / DASHBOARD_OVERLAY, tmp_path / DASHBOARD_OVERLAY)
    if with_real:
        shutil.copy(REPO_ROOT / REAL_OVERLAY, tmp_path / REAL_OVERLAY)
    if env is not None:
        (tmp_path / ".env").write_text(
            "".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8"
        )
    return tmp_path


def child_env(drop: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in COMPLETE_ENV and k not in drop
    }
    env.pop("COMPOSE_ENV_FILES", None)
    env.update(extra or {})
    return env


def render(
    project: Path,
    files: list[str],
    drop: tuple[str, ...] = (),
    extra: dict[str, str] | None = None,
):
    cmd = ["docker", "compose"]
    for f in files:
        cmd += ["-f", f]
    cmd += ["config"]
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=project, env=child_env(drop, extra)
    )


@docker
def test_eval_overlay_renders_with_complete_env(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV)

    rendered = render(
        project, ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"]
    )

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert BASE_SERVICES <= set(config["services"])
    assert "--reload" in rendered.stdout  # dev overlay still in the merge


@docker
def test_eval_overlay_fails_loud_on_missing_required_var(tmp_path: Path) -> None:
    env = {k: v for k, v in COMPLETE_ENV.items() if k != "LLM_TRIAGER"}
    project = stage(tmp_path, env)

    rendered = render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"],
        drop=("LLM_TRIAGER",),
    )

    assert rendered.returncode != 0
    assert "LLM_TRIAGER" in rendered.stderr


@docker
def test_eval_overlay_fails_loud_on_empty_required_var(tmp_path: Path) -> None:
    env = dict(COMPLETE_ENV, LLM_ANALYSER="")
    project = stage(tmp_path, env)

    rendered = render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"],
        drop=("LLM_ANALYSER",),
    )

    assert rendered.returncode != 0
    assert "LLM_ANALYSER" in rendered.stderr


@docker
def test_eval_overlay_requires_the_env_file(tmp_path: Path) -> None:
    project = stage(tmp_path, None)

    # Every required var is present in the process env, so only a missing
    # `.env` can fail the render - the overlay's `required: true`.
    rendered = render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"],
        extra=dict(COMPLETE_ENV),
    )

    assert rendered.returncode != 0
    assert ".env" in rendered.stderr


@docker
def test_base_compose_renders_unchanged_without_overlay(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_overlay=False)

    rendered = render(project, ["docker-compose.yml"], drop=tuple(COMPLETE_ENV))

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert set(config["services"]) == BASE_SERVICES


# --- the demo dashboard overlay -------------------------------------------------


def dashboard_render(project: Path, extra: dict[str, str] | None = None):
    return render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", DASHBOARD_OVERLAY],
        extra=extra,
    )


def published_port(config: dict, service: str, target: int) -> str:
    """The `<host_ip>:<published>` mapping for one service's container port."""
    for port in config["services"][service]["ports"]:
        if int(port["target"]) == target:
            return f"{port.get('host_ip', '0.0.0.0')}:{port['published']}"
    raise AssertionError(f"{service} does not publish {target}")


def mounts(service: dict) -> dict[str, dict]:
    return {mount["target"]: mount for mount in service["volumes"]}


@docker
def test_dashboard_overlay_adds_the_demo_trio_beside_the_stack(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_dashboard=True)

    rendered = dashboard_render(project)

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    # The normal stack is untouched, and the trio is exactly what is added.
    assert BASE_SERVICES <= set(config["services"])
    assert set(config["services"]) == BASE_SERVICES | DASHBOARD_SERVICES
    assert "--reload" in rendered.stdout  # the dev overlay survives the merge


@docker
def test_dashboard_overlay_publishes_loopback_only_ports_that_are_configurable(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_dashboard=True)

    default = yaml.safe_load(dashboard_render(project).stdout)
    assert published_port(default, "eval-api", 8090) == "127.0.0.1:8090"
    assert published_port(default, "eval-dashboard", 5173) == "127.0.0.1:5173"

    overridden = yaml.safe_load(
        dashboard_render(project, extra={"EVAL_API_PORT": "18090", "EVAL_DASHBOARD_PORT": "15173"}).stdout
    )
    assert published_port(overridden, "eval-api", 8090) == "127.0.0.1:18090"
    assert published_port(overridden, "eval-dashboard", 5173) == "127.0.0.1:15173"


@docker
def test_dashboard_api_reads_a_dedicated_demo_store_read_only(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_dashboard=True)

    config = yaml.safe_load(dashboard_render(project).stdout)
    api = config["services"]["eval-api"]
    api_mounts = mounts(api)

    # The store is the demo's own named volume, never a host path or the real store.
    assert api_mounts["/srv/eval-store"]["source"] == "eval-dashboard-store"
    assert api_mounts["/srv/eval-store"]["read_only"] is True
    assert api_mounts["/srv/eval"]["read_only"] is True
    assert api["environment"]["EVAL_ARTIFACT_STORE"] == "/srv/eval-store"
    assert api["environment"]["PYTHONPATH"] == "/srv/eval"
    assert api["image"] == "polymerhus-agent:latest"
    assert api["healthcheck"]

    # The one-shot generator writes that same volume, and the API waits for it.
    store = config["services"]["eval-store"]
    assert mounts(store)["/srv/eval-store"]["source"] == "eval-dashboard-store"
    assert store["command"][-1] == "/srv/eval-store"
    assert api["depends_on"]["eval-store"]["condition"] == "service_completed_successfully"


@docker
def test_dashboard_frontend_proxies_to_the_api_and_waits_for_it(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_dashboard=True)

    config = yaml.safe_load(dashboard_render(project).stdout)
    dashboard = config["services"]["eval-dashboard"]

    assert dashboard["environment"] == {
        "VITE_EVAL_API_BASE_URL": "/eval-api",
        "EVAL_PROXY_TARGET": "http://eval-api:8090",
        "AGENT_PROXY_TARGET": "http://agent:8080",
    }
    assert dashboard["depends_on"]["eval-api"]["condition"] == "service_healthy"
    # Bind-mounted source, dependencies kept out of the working tree.
    # The bind mount is relative to the compose project (here, the staged copy).
    assert mounts(dashboard)["/srv/frontend"]["source"] == str(project / "frontend")
    assert mounts(dashboard)["/srv/frontend/node_modules"]["source"] == (
        "eval-dashboard-node-modules"
    )
    assert "0.0.0.0" in " ".join(dashboard["command"])
    assert dashboard["healthcheck"]


@docker
def test_normal_startup_is_unchanged_without_the_dashboard_overlay(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_overlay=False, with_dashboard=True)

    rendered = render(project, ["docker-compose.yml", "docker-compose.dev.yml"])

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert not (DASHBOARD_SERVICES & set(config["services"]))
    assert BASE_SERVICES <= set(config["services"])


def real_render(project: Path, extra: dict[str, str] | None = None):
    return render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", REAL_OVERLAY],
        extra=extra,
    )


@docker
def test_real_overlay_adds_only_the_api_and_dashboard(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    rendered = real_render(project)

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    # The normal stack survives; the real overlay adds exactly two services and
    # never the demo generator.
    assert set(config["services"]) == BASE_SERVICES | REAL_SERVICES
    assert "eval-store" not in config["services"]
    assert "eval-dashboard-store" not in config.get("volumes", {})


@docker
def test_real_dashboard_services_restart_after_daemon_restart(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    rendered = real_render(project)

    assert rendered.returncode == 0, rendered.stderr
    services = yaml.safe_load(rendered.stdout)["services"]
    assert services["eval-api"]["restart"] == "unless-stopped"
    assert services["eval-dashboard"]["restart"] == "unless-stopped"


@docker
def test_real_overlay_binds_the_real_store_read_only(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    config = yaml.safe_load(real_render(project).stdout)
    api = config["services"]["eval-api"]
    api_mounts = mounts(api)

    assert set(api_mounts) == {"/srv/eval", "/srv/eval-artifacts", "/srv/eval-project-data"}
    assert api_mounts["/srv/eval-artifacts"]["source"] == "/srv/eval-artifacts"
    assert api_mounts["/srv/eval-artifacts"]["read_only"] is True
    assert api_mounts["/srv/eval"]["read_only"] is True
    # The resolved workspace sources are wired read-only too.
    assert api_mounts["/srv/eval-project-data"]["read_only"] is True
    assert api["environment"]["EVAL_ARTIFACT_STORE"] == "/srv/eval-artifacts"
    assert api["environment"]["EVAL_PROJECT_DATA_ROOT"] == "/srv/eval-project-data"
    assert api["environment"]["EVAL_AGENT_BASE_URL"] == "http://agent:8080"
    assert api["environment"]["EVAL_INSTANCE_ID"] == "eval-server-1"
    assert api["environment"]["PYTHONPATH"] == "/srv/eval"
    assert api["image"] == "polymerhus-agent:latest"
    assert api["healthcheck"]

    # The host path is configurable; the container path stays fixed.
    overridden = yaml.safe_load(
        real_render(
            project,
            extra={
                "EVAL_ARTIFACT_STORE_HOST_PATH": "/tmp/real-eval-store",
                "EVAL_PROJECT_DATA_ROOT_HOST_PATH": "/tmp/real-project-data",
            },
        ).stdout
    )
    assert mounts(overridden["services"]["eval-api"])["/srv/eval-artifacts"]["source"] == (
        "/tmp/real-eval-store"
    )
    assert mounts(overridden["services"]["eval-api"])["/srv/eval-project-data"][
        "source"
    ] == "/tmp/real-project-data"


@docker
def test_real_overlay_mounts_the_project_data_read_only_and_never_live(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    config = yaml.safe_load(real_render(project).stdout)

    for service in REAL_SERVICES:
        for mount in config["services"][service]["volumes"]:
            source = mount["source"]
            # The raw `live/` mirror is never read as history, and every mount
            # of the instance data root is read-only.
            assert "live" not in source.split("/")
            if source.endswith("/data"):
                assert mount["read_only"] is True


@docker
def test_real_overlay_ports_and_proxy_are_loopback(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    config = yaml.safe_load(real_render(project).stdout)

    assert published_port(config, "eval-api", 8090) == "127.0.0.1:8090"
    assert published_port(config, "eval-dashboard", 5173) == "127.0.0.1:5173"
    dashboard = config["services"]["eval-dashboard"]
    assert dashboard["environment"]["EVAL_PROXY_TARGET"] == "http://eval-api:8090"
    assert dashboard["environment"]["VITE_EVAL_API_BASE_URL"] == "/eval-api"
    assert dashboard["depends_on"]["eval-api"]["condition"] == "service_healthy"
    assert dashboard["healthcheck"]


@docker
def test_real_overlay_ports_are_configurable(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    config = yaml.safe_load(
        real_render(
            project, extra={"EVAL_API_PORT": "18090", "EVAL_DASHBOARD_PORT": "15173"}
        ).stdout
    )

    assert published_port(config, "eval-api", 8090) == "127.0.0.1:18090"
    assert published_port(config, "eval-dashboard", 5173) == "127.0.0.1:15173"


@docker
def test_demo_overlay_still_uses_its_dedicated_named_volume(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_dashboard=True)

    config = yaml.safe_load(dashboard_render(project).stdout)

    assert mounts(config["services"]["eval-api"])["/srv/eval-store"]["source"] == (
        "eval-dashboard-store"
    )
    assert mounts(config["services"]["eval-store"])["/srv/eval-store"]["source"] == (
        "eval-dashboard-store"
    )
