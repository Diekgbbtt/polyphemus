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
LEGACY_OVERLAY = "eval/docker-compose.dashboard.legacy.yml"
OPERATOR_OVERLAY = "eval/docker-compose.dashboard.operator.yml"
# The demo trio the dashboard overlay adds; nothing else may appear with it.
DASHBOARD_SERVICES = {"eval-store", "eval-api", "eval-dashboard"}
# The real overlay adds only the read API and the dashboard.
REAL_SERVICES = {"eval-api", "eval-dashboard"}
# The operator overlay adds one isolated service on its own network.
OPERATOR_SERVICES = {"eval-operator-api"}
OPERATOR_NETWORK = "eval-operator-net"
# The standalone storage-compatibility demo: its own project, network and
# volumes, never merged with the base stack.
STORAGE_DEMO = "docker-compose.storage-compat-demo.yml"
STORAGE_DEMO_SERVICES = {"eval-corpus", "eval-api", "eval-dashboard"}

docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI unavailable"
)


def stage(
    tmp_path: Path,
    env: dict[str, str] | None,
    with_overlay: bool = True,
    with_dashboard: bool = False,
    with_real: bool = False,
    with_operator: bool = False,
    with_legacy: bool = False,
    with_storage_demo: bool = False,
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
    if with_legacy:
        shutil.copy(REPO_ROOT / LEGACY_OVERLAY, tmp_path / LEGACY_OVERLAY)
    if with_operator:
        shutil.copy(REPO_ROOT / OPERATOR_OVERLAY, tmp_path / OPERATOR_OVERLAY)
    if with_storage_demo:
        shutil.copy(REPO_ROOT / STORAGE_DEMO, tmp_path / STORAGE_DEMO)
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
def test_real_overlay_never_creates_a_missing_host_path(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    config = yaml.safe_load(real_render(project).stdout)
    api_mounts = mounts(config["services"]["eval-api"])

    # Every source is an explicit, read-only bind that must already exist: a
    # missing root fails loudly instead of becoming an empty directory.
    for target, mount in api_mounts.items():
        assert mount["type"] == "bind", target
        assert mount["read_only"] is True, target
        # A default bind renders `create_host_path: true`; ours must not.
        assert mount["bind"].get("create_host_path") is not True, target


@docker
def test_real_overlay_defaults_the_raw_root_to_the_instance_data_root(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    config = yaml.safe_load(real_render(project).stdout)

    assert mounts(config["services"]["eval-api"])["/srv/eval-project-data"][
        "source"
    ] == "/opt/polymerhus-dev/eval/instances/data/eval-server-1"


def legacy_render(project: Path, extra: dict[str, str] | None = None):
    return render(
        project,
        [
            "docker-compose.yml",
            "docker-compose.dev.yml",
            REAL_OVERLAY,
            LEGACY_OVERLAY,
        ],
        extra=extra,
    )


@docker
def test_legacy_overlay_adds_the_historical_runs_root_read_only(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_legacy=True)

    rendered = legacy_render(project)

    assert rendered.returncode == 0, rendered.stderr
    api = yaml.safe_load(rendered.stdout)["services"]["eval-api"]
    api_mounts = mounts(api)
    assert set(api_mounts) == {
        "/srv/eval",
        "/srv/eval-artifacts",
        "/srv/eval-project-data",
        "/srv/eval-runs",
        "/srv/eval-runs-legacy",
    }
    legacy = api_mounts["/srv/eval-runs-legacy"]
    assert legacy["source"] == "/opt/eval-platform-model/eval/runs"
    assert legacy["read_only"] is True
    assert legacy["bind"].get("create_host_path") is not True
    assert api["environment"]["EVAL_RUNS_LEGACY_ROOT"] == "/srv/eval-runs-legacy"
    # The primary root keeps its own mount and variable.
    assert api_mounts["/srv/eval-runs"]["read_only"] is True
    assert api["environment"]["EVAL_RUNS_ROOT"] == "/srv/eval-runs"


@docker
def test_legacy_overlay_host_path_is_overridable(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_legacy=True)

    config = yaml.safe_load(
        legacy_render(
            project, extra={"EVAL_RUNS_LEGACY_ROOT_HOST_PATH": "/tmp/legacy-runs"}
        ).stdout
    )

    assert mounts(config["services"]["eval-api"])["/srv/eval-runs-legacy"][
        "source"
    ] == "/tmp/legacy-runs"


@docker
def test_the_real_overlay_alone_configures_no_legacy_root(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    api = yaml.safe_load(real_render(project).stdout)["services"]["eval-api"]

    assert "/srv/eval-runs-legacy" not in mounts(api)
    assert api["environment"].get("EVAL_RUNS_LEGACY_ROOT") in (None, "")


@docker
def test_real_overlay_binds_the_real_store_read_only(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True)

    config = yaml.safe_load(real_render(project).stdout)
    api = config["services"]["eval-api"]
    api_mounts = mounts(api)

    assert set(api_mounts) == {
        "/srv/eval",
        "/srv/eval-artifacts",
        "/srv/eval-project-data",
        "/srv/eval-runs",
    }
    assert api_mounts["/srv/eval-artifacts"]["source"] == "/srv/eval-artifacts"
    assert api_mounts["/srv/eval-artifacts"]["read_only"] is True
    assert api_mounts["/srv/eval"]["read_only"] is True
    # The resolved workspace sources are wired read-only too.
    assert api_mounts["/srv/eval-project-data"]["read_only"] is True
    # The harness runs root (the recorded-spend source) is read-only as well.
    assert api_mounts["/srv/eval-runs"]["read_only"] is True
    assert api["environment"]["EVAL_ARTIFACT_STORE"] == "/srv/eval-artifacts"
    assert api["environment"]["EVAL_PROJECT_DATA_ROOT"] == "/srv/eval-project-data"
    assert api["environment"]["EVAL_AGENT_BASE_URL"] == "http://agent:8080"
    assert api["environment"]["EVAL_INSTANCE_ID"] == "eval-server-1"
    assert api["environment"]["EVAL_RUNS_ROOT"] == "/srv/eval-runs"
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
                "EVAL_RUNS_ROOT_HOST_PATH": "/tmp/real-runs",
            },
        ).stdout
    )
    assert mounts(overridden["services"]["eval-api"])["/srv/eval-artifacts"]["source"] == (
        "/tmp/real-eval-store"
    )
    assert mounts(overridden["services"]["eval-api"])["/srv/eval-project-data"][
        "source"
    ] == "/tmp/real-project-data"
    assert mounts(overridden["services"]["eval-api"])["/srv/eval-runs"]["source"] == (
        "/tmp/real-runs"
    )


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


# --- the operator ground-truth overlay -----------------------------------------


def operator_render(project: Path, extra: dict[str, str] | None = None):
    return render(
        project,
        [
            "docker-compose.yml",
            "docker-compose.dev.yml",
            REAL_OVERLAY,
            OPERATOR_OVERLAY,
        ],
        extra=extra,
    )


def service_networks(config: dict, service: str) -> set[str]:
    return set(config["services"][service].get("networks") or {})


@docker
def test_operator_overlay_adds_only_one_isolated_service(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_operator=True)

    rendered = operator_render(
        project, extra={"EVAL_WEB_DIR_HOST_PATH": "/tmp/webench-fixture"}
    )

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert set(config["services"]) == BASE_SERVICES | REAL_SERVICES | OPERATOR_SERVICES

    # The operator service is alone on its own bridge; no service the discovery
    # agent shares a network with may reach it.
    assert service_networks(config, "eval-operator-api") == {OPERATOR_NETWORK}
    for service in config["services"]:
        if service != "eval-operator-api":
            assert OPERATOR_NETWORK not in service_networks(config, service)
    # And the operator service never joins the shared bridge.
    assert "polymerhus-net" not in service_networks(config, "eval-operator-api")


@docker
def test_operator_overlay_is_absent_without_its_overlay(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_operator=True)

    rendered = render(
        project, ["docker-compose.yml", "docker-compose.dev.yml", REAL_OVERLAY]
    )

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert not (OPERATOR_SERVICES & set(config["services"]))
    assert OPERATOR_NETWORK not in config.get("networks", {})


@docker
def test_operator_overlay_publishes_loopback_only_and_restarts_unless_stopped(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_operator=True)

    default = yaml.safe_load(
        operator_render(project, extra={"EVAL_WEB_DIR_HOST_PATH": "/tmp/webench"}).stdout
    )
    operator = default["services"]["eval-operator-api"]
    assert published_port(default, "eval-operator-api", 8091) == "127.0.0.1:8091"
    assert operator["restart"] == "unless-stopped"
    assert operator["image"] == "polymerhus-agent:latest"
    assert operator["working_dir"] == "/srv/eval"
    assert operator["environment"]["PYTHONPATH"] == "/srv/eval"
    assert operator["environment"]["EVAL_OPERATOR_BENCHMARK_ROOT"] == "/srv/webexploitbench"
    assert operator["environment"]["EVAL_OPERATOR_SETUP_ROOT"] == "/srv/eval/setups"
    assert operator["environment"]["EVAL_OPERATOR_SETUP_FILES"] == (
        "first.yaml,webexploitbench-chain.yaml"
    )
    assert operator["environment"]["EVAL_OPERATOR_FRONTEND_ORIGIN"] == (
        "http://localhost:15173"
    )
    assert "operator_api.app:app" in " ".join(operator["command"])
    assert "8091" in operator["command"]
    assert operator["healthcheck"]

    overridden = yaml.safe_load(
        operator_render(
            project,
            extra={
                "EVAL_WEB_DIR_HOST_PATH": "/tmp/webench",
                "EVAL_OPERATOR_PORT": "18091",
                "EVAL_OPERATOR_FRONTEND_ORIGIN": "http://localhost:15173",
            },
        ).stdout
    )
    assert published_port(overridden, "eval-operator-api", 8091) == "127.0.0.1:18091"


@docker
def test_operator_overlay_binds_its_sources_read_only(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_operator=True)

    config = yaml.safe_load(
        operator_render(
            project, extra={"EVAL_WEB_DIR_HOST_PATH": "/tmp/webench-host"}
        ).stdout
    )
    operator_mounts = mounts(config["services"]["eval-operator-api"])

    assert set(operator_mounts) == {"/srv/eval", "/srv/webexploitbench"}
    assert operator_mounts["/srv/eval"]["read_only"] is True
    assert operator_mounts["/srv/webexploitbench"]["read_only"] is True
    assert operator_mounts["/srv/webexploitbench"]["source"] == "/tmp/webench-host"
    # A default bind renders `create_host_path: true`; this one must not, so a
    # typo can never be replaced by an empty, silently-created directory.
    assert operator_mounts["/srv/webexploitbench"]["bind"].get("create_host_path") is not True


@docker
def test_operator_overlay_requires_the_benchmark_host_path(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_operator=True)

    rendered = operator_render(project, extra={})

    assert rendered.returncode != 0
    assert "EVAL_WEB_DIR_HOST_PATH" in rendered.stderr


@docker
def test_operator_overlay_adds_no_socket_or_shared_configuration(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_real=True, with_operator=True)

    rendered = operator_render(
        project, extra={"EVAL_WEB_DIR_HOST_PATH": "/tmp/webench-host"}
    )

    assert rendered.returncode == 0, rendered.stderr
    assert "/var/run/docker.sock" not in rendered.stdout
    config = yaml.safe_load(rendered.stdout)
    for service, definition in config["services"].items():
        if service == "eval-operator-api":
            continue
        for key in (definition.get("environment") or {}):
            assert not key.startswith("EVAL_OPERATOR_")
        # The benchmark reference is mounted only into the operator service.
        for mount in definition.get("volumes") or []:
            assert mount["target"] != "/srv/webexploitbench"


# --- the standalone storage-compatibility demo ---------------------------------


def storage_demo_render(project: Path, extra: dict[str, str] | None = None):
    """Render the standalone demo file on its own - never merged with base."""
    return render(project, [STORAGE_DEMO], drop=tuple(COMPLETE_ENV), extra=extra)


@docker
def test_storage_demo_is_a_standalone_project_with_only_three_services(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_storage_demo=True)

    rendered = storage_demo_render(project)

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    # The demo is exactly the generator, the read API and the frontend: the base
    # stack (agent, Neo4j, Postgres, Kali) is never part of it.
    assert set(config["services"]) == STORAGE_DEMO_SERVICES
    assert not (BASE_SERVICES & set(config["services"]))
    assert config["name"] == "polyphemus-storage-compat-demo"
    # Its own dedicated network, never the real `polymerhus-net`.
    assert set(config["networks"]) == {"storage-compat-net"}


@docker
def test_storage_demo_publishes_loopback_only_ports_that_are_configurable(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_storage_demo=True)

    default = yaml.safe_load(storage_demo_render(project).stdout)
    assert published_port(default, "eval-api", 8090) == "127.0.0.1:28090"
    assert published_port(default, "eval-dashboard", 5173) == "127.0.0.1:25173"

    overridden = yaml.safe_load(
        storage_demo_render(
            project,
            extra={
                "STORAGE_COMPAT_API_PORT": "38090",
                "STORAGE_COMPAT_DASHBOARD_PORT": "35173",
            },
        ).stdout
    )
    assert published_port(overridden, "eval-api", 8090) == "127.0.0.1:38090"
    assert published_port(overridden, "eval-dashboard", 5173) == "127.0.0.1:35173"


@docker
def test_storage_demo_api_reads_the_four_roots_from_a_dedicated_volume(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_storage_demo=True)

    config = yaml.safe_load(storage_demo_render(project).stdout)
    api = config["services"]["eval-api"]
    api_mounts = mounts(api)

    # The corpus is the demo's OWN named volume, read-only - never the operator's
    # real store, raw data, runs roots or benchmark ground truth.
    assert api_mounts["/srv/corpus"]["type"] == "volume"
    assert api_mounts["/srv/corpus"]["source"] == "storage-compat-corpus"
    assert api_mounts["/srv/corpus"]["read_only"] is True
    assert api_mounts["/srv/eval"]["read_only"] is True
    # The read API's four sources all point inside that one synthetic volume.
    assert api["environment"]["EVAL_ARTIFACT_STORE"] == "/srv/corpus/store"
    assert api["environment"]["EVAL_PROJECT_DATA_ROOT"] == "/srv/corpus/raw"
    assert api["environment"]["EVAL_RUNS_ROOT"] == "/srv/corpus/runs"
    assert api["environment"]["EVAL_RUNS_LEGACY_ROOT"] == "/srv/corpus/runs-legacy"
    assert api["environment"]["EVAL_DATASET_ID"] == "storage-compatibility"
    assert api["environment"]["EVAL_INSTANCE_ID"] == "demo-instance-1"
    assert api["image"] == "polymerhus-agent:latest"
    assert api["healthcheck"]
    # Nothing in the demo binds a real host path.
    for mount in api_mounts.values():
        assert mount["type"] != "bind" or mount["source"] == str(project / "eval")


@docker
def test_storage_demo_generator_writes_the_corpus_volume_and_gates_the_api(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_storage_demo=True)

    config = yaml.safe_load(storage_demo_render(project).stdout)
    generator = config["services"]["eval-corpus"]
    api = config["services"]["eval-api"]

    # The generator writes the same volume the API reads read-only, with a
    # command that targets the new storage-compatibility corpus.
    assert mounts(generator)["/srv/corpus"]["source"] == "storage-compat-corpus"
    assert mounts(generator)["/srv/corpus"].get("read_only") is not True
    assert "read_api.storage_compat_corpus" in generator["command"]
    assert generator["command"][-2:] == ["--root", "/srv/corpus"]
    assert generator["restart"] == "no"
    # The API waits for the one-shot generation, never racing an empty store.
    assert api["depends_on"]["eval-corpus"]["condition"] == (
        "service_completed_successfully"
    )


@docker
def test_storage_demo_frontend_proxies_to_the_api_and_waits_for_it(
    tmp_path: Path,
) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_storage_demo=True)

    config = yaml.safe_load(storage_demo_render(project).stdout)
    dashboard = config["services"]["eval-dashboard"]

    assert dashboard["environment"] == {
        "VITE_EVAL_API_BASE_URL": "/eval-api",
        "EVAL_PROXY_TARGET": "http://eval-api:8090",
    }
    assert dashboard["depends_on"]["eval-api"]["condition"] == "service_healthy"
    assert mounts(dashboard)["/srv/frontend"]["source"] == str(project / "frontend")
    assert mounts(dashboard)["/srv/frontend/node_modules"]["source"] == (
        "storage-compat-node-modules"
    )
    assert "0.0.0.0" in " ".join(dashboard["command"])


@docker
def test_storage_demo_references_no_real_paths_or_agent(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_storage_demo=True)

    rendered = storage_demo_render(project)

    assert rendered.returncode == 0, rendered.stderr
    # No real store/raw/runs/Neo4j/ground-truth host path leaks into the demo.
    for host_path in (
        "/srv/eval-artifacts",
        "/opt/polymerhus-dev",
        "/opt/eval-platform-model",
        "/root/WebExploitBench",
        "/var/run/docker.sock",
    ):
        assert host_path not in rendered.stdout
    # No agent/Neo4j/Postgres service or URL is reachable from the demo.
    assert "EVAL_AGENT_BASE_URL" not in rendered.stdout
    assert "agent:8080" not in rendered.stdout
