"""Unit tier: the external-bootstrap runner, part 2 - environment drivers.

`runner/env.py` is the environment seam: raw actuators (`up`, `down`) plus one
read-only observation (container facts from the docker engine, targetctl's own
URL, the URL's raw HTTP status). Interpretation is pure (`not_ready_reason`,
`leftovers`) and reuses the platform's own readiness rules.

Everything here runs against a recording fake executor: the exact commands the
drivers issue, the project-name mirror, the platform URL parser's reuse, and the
readiness interpretation. No docker, no ssh, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_path(rel: str) -> None:
    path = str(REPO_ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


_on_path("tools/bootstrap")
_on_path("eval")
_on_path("src")

from orchestrator.commands import Command, CommandResult  # noqa: E402

from runner.env import (  # noqa: E402
    COMPOSE_PROJECT_LABEL,
    COMPOSE_SERVICE_LABEL,
    NO_ANSWER,
    AttachEnv,
    ContainerFact,
    LocalEnv,
    Observation,
    SshServerEnv,
    containers_ready,
    driver_for,
    leftovers,
    not_ready_reason,
    parse_containers,
    project_name,
    url_hello,
)


class RecordingExecutor:
    """Records every `Command` and answers from a route map keyed by a substring."""

    def __init__(self, routes: dict[str, CommandResult] | None = None):
        self.routes = routes or {}
        self.calls: list[Command] = []
        self.default = CommandResult(0, "", "")

    def __call__(self, command: Command) -> CommandResult:
        self.calls.append(command)
        joined = " ".join(command.argv)
        for needle, result in self.routes.items():
            if needle in joined:
                return result
        return self.default


def _fact(state="running", health="", exit_code=0, service="app", name="web_shop-app-1"):
    return ContainerFact(
        name=name, service=service, state=state, health=health, exit_code=exit_code
    )


def _obs(url="http://203.0.113.5:8080/", status="200", containers=()):
    return Observation(
        target="shop",
        containers=tuple(containers),
        url=url,
        http_status=status,
        output="",
        returncode=0,
    )


# --- the project-name mirror ------------------------------------------------


def test_targetctl_project_name_mirrors_the_server_scaffold():
    """Pinned against `scripts/targetctl`'s documented naming rule and examples."""
    assert project_name("white-jotter") == "web_white_jotter"
    assert project_name("siyucms") == "web_siyucms"
    assert project_name("mogu-blog-v2") == "web_mogu_blog_v2"
    assert project_name("White-Jotter") == "web_white_jotter"
    assert project_name("youlai_mall") == "web_youlai_mall"


# --- readiness interpretation (platform rules, composite) -------------------


def test_containers_ready_uses_the_platform_rules():
    assert containers_ready((_fact(state="running", health="healthy"),))
    assert containers_ready((_fact(state="running", health=""),))
    assert containers_ready((_fact(state="exited", exit_code=0),))
    assert not containers_ready((_fact(state="running", health="starting"),))
    assert not containers_ready((_fact(state="running", health="unhealthy"),))
    assert not containers_ready((_fact(state="exited", exit_code=1),))
    assert not containers_ready((_fact(state="created", health=""),))
    assert not containers_ready(())


def test_not_ready_reason_is_none_only_when_every_signal_agrees():
    assert not_ready_reason(_obs(containers=(_fact(),))) is None
    assert "no containers" in not_ready_reason(_obs(containers=()))
    assert "not ready" in not_ready_reason(_obs(containers=(_fact(state="restarting"),)))
    assert "http" in not_ready_reason(_obs(status="502", containers=(_fact(),)))
    assert "url" in not_ready_reason(_obs(url=None, containers=(_fact(),)))
    assert not_ready_reason(_obs(status="503", containers=(_fact(),))) is not None
    assert not_ready_reason(_obs(status="", containers=(_fact(),))) is not None
    # 401/403/301 are live answers, so a login-walled target is ready.
    assert not_ready_reason(_obs(status="401", containers=(_fact(),))) is None


def test_leftovers_reports_every_container_after_teardown():
    containers = (_fact(name="web_shop-app-1"), _fact(name="web_shop-db-1", service="db"))
    assert leftovers(_obs(containers=containers)) == containers
    assert leftovers(_obs(containers=())) == ()


def test_url_hello_scrapes_the_last_http_status():
    assert url_hello("curl: (7) failed\n000\n") == "000"
    assert url_hello("200\n") == "200"
    assert url_hello("") == ""


def test_parse_containers_reads_the_engine_facts():
    text = json.dumps(
        [
            {
                "Name": "/web_shop-app-1",
                "State": {"Status": "running", "Health": {"Status": "healthy"}, "ExitCode": 0},
                "Config": {"Labels": {COMPOSE_SERVICE_LABEL: "app"}},
            },
            {
                "Name": "/web_shop-db-1",
                "State": {"Status": "exited", "ExitCode": 0},
                "Config": {"Labels": {COMPOSE_SERVICE_LABEL: "db"}},
            },
        ]
    )
    facts = parse_containers(text)
    assert [(f.name, f.service, f.state, f.health, f.exit_code) for f in facts] == [
        ("web_shop-app-1", "app", "running", "healthy", 0),
        ("web_shop-db-1", "db", "exited", "", 0),
    ]


def test_parse_containers_tolerates_garbage():
    assert parse_containers("") == ()
    assert parse_containers("not json") == ()
    assert parse_containers("[{}]") == ()
    assert parse_containers('{"Health": "healthy"}') == ()


# --- ssh driver -------------------------------------------------------------


def test_ssh_env_issues_every_lifecycle_command_over_the_configured_ssh():
    ex = RecordingExecutor()
    env = SshServerEnv(ssh="eval-server-polyphemus", targetctl="/root/wb", executor=ex)
    up = env.up("shop")
    down = env.down("shop")
    assert ex.calls[0].argv[-1] == "/root/wb up shop"
    assert ex.calls[1].argv[-1] == "/root/wb down shop"
    assert ex.calls[0].argv[:2] == ("ssh", "-o")
    assert "eval-server-polyphemus" in ex.calls[0].argv
    assert up.returncode == 0 and down.returncode == 0


def test_ssh_env_never_prunes_and_only_addresses_the_target_project():
    ex = RecordingExecutor()
    env = SshServerEnv(ssh="srv", targetctl="/root/wb", executor=ex)
    env.up("shop")
    env.down("shop")
    env.observe("shop")
    rendered = "\n".join(" ".join(c.argv) for c in ex.calls)
    assert "prune" not in rendered
    assert "rm -f" not in rendered
    assert f"label={COMPOSE_PROJECT_LABEL}=web_shop" in rendered
    assert "label=com.docker.compose.project=web_shop" in rendered


def test_ssh_env_observation_reads_url_containers_and_http_status():
    ex = RecordingExecutor(
        {
            "/root/wb ps shop": CommandResult(0, "UI: http://0.0.0.0:48287/\n", ""),
            "docker ps": CommandResult(0, "abc123\n", ""),
            "docker inspect": CommandResult(
                0,
                json.dumps(
                    [
                        {
                            "Name": "/web_shop-app-1",
                            "State": {
                                "Status": "running",
                                "Health": {"Status": "healthy"},
                                "ExitCode": 0,
                            },
                            "Config": {"Labels": {COMPOSE_SERVICE_LABEL: "app"}},
                        }
                    ]
                ),
                "",
            ),
            "curl": CommandResult(0, "200", ""),
        }
    )
    env = SshServerEnv(ssh="srv", executor=ex)
    obs = env.observe("shop")
    assert obs.url == "http://0.0.0.0:48287/"
    assert obs.http_status == "200"
    assert [f.service for f in obs.containers] == ["app"]
    assert obs.returncode == 0
    joined = "\n".join(" ".join(c.argv) for c in ex.calls)
    # The docker and curl probes run on the server, beside the containers.
    assert joined.count("ssh -o BatchMode=yes srv") == 4


def test_ssh_env_observation_without_a_url_reports_no_answer():
    ex = RecordingExecutor({"/root/wb ps shop": CommandResult(1, "", "no such target")})
    env = SshServerEnv(ssh="srv", executor=ex)
    obs = env.observe("shop")
    assert obs.url is None
    assert obs.http_status == NO_ANSWER
    assert not containers_ready(obs.containers)
    assert "no containers" in not_ready_reason(obs)


def test_ssh_env_parses_the_port_bearing_url_when_there_is_no_ui_line():
    ex = RecordingExecutor(
        {"/root/wb ps shop": CommandResult(0, "Accessible at http://0.0.0.0:9999/\n", "")}
    )
    env = SshServerEnv(ssh="srv", executor=ex)
    assert env.observe("shop").url == "http://0.0.0.0:9999/"


def test_ssh_env_lifecycle_hints_name_the_remote_commands():
    env = SshServerEnv(ssh="srv", targetctl="/root/wb")
    hints = env.lifecycle_hints("shop")
    assert "ssh srv /root/wb ps shop" in hints
    assert all("/root/wb" in hint for hint in hints)


# --- local driver -----------------------------------------------------------


def test_local_env_uses_an_explicit_bash_and_the_amd64_platform():
    ex = RecordingExecutor()
    env = LocalEnv(
        local_dir=Path("/Users/x/WebExploitBench"),
        bash="/opt/homebrew/bin/bash",
        executor=ex,
    )
    env.up("shop")
    call = ex.calls[0]
    assert call.argv == (
        "/opt/homebrew/bin/bash",
        "/Users/x/WebExploitBench/scripts/targetctl",
        "up",
        "shop",
    )
    assert call.env["DOCKER_DEFAULT_PLATFORM"] == "linux/amd64"
    assert call.cwd == "/Users/x/WebExploitBench"


def test_local_env_down_and_ps_use_the_same_scaffold():
    ex = RecordingExecutor()
    env = LocalEnv(local_dir=Path("/wt"), executor=ex)
    env.down("shop")
    env.ps("shop")
    assert ex.calls[0].argv == ("/wt/scripts/targetctl", "down", "shop")
    assert ex.calls[1].argv == ("/wt/scripts/targetctl", "ps", "shop")


def test_local_env_observation_runs_the_engine_commands_locally():
    ex = RecordingExecutor(
        {
            "targetctl ps shop": CommandResult(0, "UI: http://0.0.0.0:48287/\n", ""),
            "docker inspect": CommandResult(0, "[]", ""),
            "curl": CommandResult(0, "404", ""),
        }
    )
    env = LocalEnv(local_dir=Path("/wt"), executor=ex)
    obs = env.observe("shop")
    assert obs.url == "http://0.0.0.0:48287/"
    assert obs.http_status == "404"
    assert obs.containers == ()
    joined = "\n".join(" ".join(c.argv) for c in ex.calls)
    assert "ssh" not in joined


# --- attach driver ----------------------------------------------------------


def test_attach_env_lifecycle_is_a_no_op_and_base_url_comes_from_config():
    ex = RecordingExecutor()
    env = AttachEnv(base_url="http://203.0.113.9:8080/", executor=ex)
    assert env.up("shop").returncode == 0
    assert env.down("shop").returncode == 0
    assert ex.calls == []
    url, command = env.url_command("shop")
    assert url == "http://203.0.113.9:8080/"
    assert command is None
    assert env.supported_containers() is False


def test_attach_env_probes_the_configured_url_and_reports_no_containers():
    ex = RecordingExecutor({"curl": CommandResult(0, "200", "")})
    env = AttachEnv(base_url="http://203.0.113.9:8080/", executor=ex)
    obs = env.observe("shop")
    assert obs.url == "http://203.0.113.9:8080/"
    assert obs.http_status == "200"
    assert obs.containers == ()
    assert "curl" in " ".join(ex.calls[0].argv)


# --- the driver factory -----------------------------------------------------


def test_driver_for_builds_each_configured_driver(tmp_path):
    ex = RecordingExecutor()
    assert isinstance(driver_for("ssh", ssh="srv", executor=ex), SshServerEnv)
    assert isinstance(driver_for("local", local_dir=tmp_path, executor=ex), LocalEnv)
    assert isinstance(
        driver_for("attach", base_url="http://x/", executor=ex), AttachEnv
    )


def test_driver_for_fails_loudly_on_an_incomplete_description():
    with pytest.raises(ValueError):
        driver_for("ssh")
    with pytest.raises(ValueError):
        driver_for("attach")
    with pytest.raises(ValueError):
        driver_for("wat", ssh="srv")
