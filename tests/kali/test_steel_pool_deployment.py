"""#359 W6 deployment shape: entrypoint lane, compose wiring, operator overlay.

The browser MCP is an optional second process in the Kali container. These
tests pin the configuration that makes it startable without taking the exec
plane down, and the operator overlay that carries the tunnel inputs.
"""
from __future__ import annotations

from pathlib import Path
import os
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _entrypoint() -> str:
    return (ROOT / "kali" / "entrypoint.sh").read_text(encoding="utf-8")


def _browser_function() -> str:
    script = _entrypoint()
    start = script.index("start_browser_mcp() {")
    end = script.index("\n}\n", start)
    return script[start:end]


def _compose(*files: str, env: dict | None = None) -> dict:
    command = ["docker", "compose"]
    for name in files:
        command += ["-f", name]
    command.append("config")
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"docker compose config unavailable: {proc.stderr.strip()[:200]}")
    return yaml.safe_load(proc.stdout)


def _compose_failure(*files: str, env: dict) -> str:
    command = ["docker", "compose"]
    for name in files:
        command += ["-f", name]
    command.append("config")
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
        check=False,
    )
    if proc.returncode == 0:
        pytest.fail("the overlay rendered without the forwarded agent")
    return proc.stderr


def test_browser_mcp_is_off_without_the_pool_socket():
    script = _entrypoint()

    assert "STEEL_POOL_DOCKER_SOCKET:-" in script
    assert "STEEL_POOL_DOCKER_SOCKET is unset; browser MCP not started" in script


def test_browser_mcp_waits_for_the_tunnel_socket():
    """The operator cannot create the in-container socket before the container
    exists, so the entrypoint must wait instead of racing the tunnel."""
    body = _browser_function()

    assert '[ -S "$STEEL_POOL_DOCKER_SOCKET" ]' in body
    assert "BROWSER_SOCKET_WAIT_S" in body
    assert "is absent after" in body


def test_browser_mcp_probes_the_loopback_listener():
    body = _browser_function()

    assert "/dev/tcp/127.0.0.1/$BROWSER_PORT" in body
    assert "browser MCP ready" in body


def test_browser_mcp_log_is_a_file_beside_the_proxy_log():
    script = _entrypoint()

    assert "/var/log/kali-browser-mcp.log" in script
    assert '>>"$BROWSER_LOG" 2>&1 &' in script


def test_browser_mcp_starts_after_the_exec_server():
    """The exec server is the container's primary lane: it must be running
    before the optional lane blocks on its bounded socket wait."""
    script = _entrypoint()

    exec_start = script.index('/opt/kali/mcp_server.py &')
    browser_start = script.index("start_browser_mcp\n")
    assert exec_start < browser_start
    assert script.rstrip().endswith('wait "$MCP_PID"')


def test_browser_mcp_never_aborts_the_entrypoint():
    body = _browser_function()

    assert "return 1" not in body
    assert body.count("return 0") >= 5


def test_browser_mcp_is_killed_by_the_shutdown_trap():
    script = _entrypoint()

    trap = script[script.index("shutdown() {") : script.index("trap shutdown")]
    assert '[ -n "$BROWSER_PID" ] && kill "$BROWSER_PID"' in trap


def test_compose_exposes_the_pool_configuration():
    env = _compose("docker-compose.yml")["services"]["kali"]["environment"]

    assert env["STEEL_MCP_PORT"] == "8003"
    assert env["STEEL_SESSION_STORE"] == "/var/lib/steel/sessions"
    assert env["STEEL_CLI"] == "/opt/localbin/.steel/steel"
    assert env["STEEL_GUARD"] == "/opt/kali/steel_guard.py"
    assert env["STEEL_WORKER_API_SUFFIX"] == "/v1"
    assert env["STEEL_POOL_LABEL"] == "polymerhus.steel-pool=true"
    assert env["STEEL_POOL_SIZE"] == "4"
    assert env["STEEL_POOL_WAIT_S"] == "30"
    assert env["STEEL_POOL_HEALTH_S"] == "30"
    assert env["STEEL_HEARTBEAT_S"] == "120"
    assert env["STEEL_LEASE_TTL_S"] == "600"
    # Empty means the feature is off; the operator overlay sets the path.
    assert not env.get("STEEL_POOL_DOCKER_SOCKET")


def test_compose_mounts_the_session_store_volume():
    rendered = _compose("docker-compose.yml")
    kali = rendered["services"]["kali"]
    mounts = {
        mount["target"]: mount["source"]
        for mount in kali["volumes"]
        if isinstance(mount, dict)
    }

    assert mounts["/var/lib/steel/sessions"] == "steel-sessions"
    assert "steel-sessions" in rendered["volumes"]


def test_compose_keeps_the_browser_mcp_off_the_host():
    rendered = _compose("docker-compose.yml")
    kali = rendered["services"]["kali"]
    published = {int(port["target"]) for port in kali.get("ports", [])}

    assert 8000 in published
    assert 8003 not in published


def test_compose_gives_the_end_path_time_to_finish():
    kali = _compose("docker-compose.yml")["services"]["kali"]

    # CLI timeout 180 s + API 10 s + settle 5 s; the end path runs on SIGTERM.
    assert kali["stop_grace_period"] == "3m30s"


def test_operator_overlay_carries_the_agent_and_the_socket():
    env = {**os.environ, "SSH_AUTH_SOCK": "/tmp/operator-agent.sock"}
    rendered = _compose(
        "docker-compose.yml", "docker-compose.pool-overlay.yml", env=env
    )
    kali = rendered["services"]["kali"]

    assert kali["environment"]["SSH_AUTH_SOCK"] == "/run/ssh-agent.sock"
    assert kali["environment"]["STEEL_POOL_DOCKER_SOCKET"] == (
        "/run/steel-pool/docker.sock"
    )
    mounts = {
        mount["target"]: mount["source"]
        for mount in kali["volumes"]
        if isinstance(mount, dict)
    }
    assert mounts["/run/ssh-agent.sock"] == "/tmp/operator-agent.sock"
    agent = rendered["services"]["agent"]
    assert agent["environment"]["KALI_BROWSER_MCP_URL"] == "http://kali:8003/mcp"


def test_operator_overlay_fails_without_the_agent():
    env = {key: value for key, value in os.environ.items() if key != "SSH_AUTH_SOCK"}

    stderr = _compose_failure(
        "docker-compose.yml", "docker-compose.pool-overlay.yml", env=env
    )

    assert "SSH_AUTH_SOCK" in stderr


def test_pool_compose_publishes_loopback_only():
    rendered = _compose("eval/deploy/steel/docker-compose.steel-pool.yml")
    ports = []
    for service in rendered["services"].values():
        for port in service.get("ports", []):
            ports.append((port["host_ip"], int(port["published"]), int(port["target"])))
            assert service["labels"]["polymerhus.steel-pool"] == "true"
            assert service["command"] == ["--no-nginx"]

    assert sorted(ports) == [
        ("127.0.0.1", 3100, 3000),
        ("127.0.0.1", 3101, 3000),
    ]


def test_runbook_pins_the_tunnel_and_the_checks():
    runbook = (ROOT / "eval/deploy/steel/POOL-RUNBOOK.md").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "-L 127.0.0.1:3100:127.0.0.1:3100",
        "-L [::1]:3100:127.0.0.1:3100",
        "-L 127.0.0.1:3101:127.0.0.1:3101",
        "-L [::1]:3101:127.0.0.1:3101",
        "-L /run/steel-pool/docker.sock:/var/run/docker.sock",
        "--unix-socket /run/steel-pool/docker.sock",
        "/var/log/kali-browser-mcp.log",
        "pool.warning",
        "STEEL_POOL_SIZE=2",
    ):
        assert fragment in runbook, fragment
