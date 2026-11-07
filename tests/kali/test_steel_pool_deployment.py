"""#359 W10 deployment shape: in-stack pool, thin overlay, entrypoint lane.

The browser pool is part of the instance compose project. One `steel-worker`
service is replicated by Compose; the browser MCP runs in Kali and owns the
reverse proxy that maps a loopback public port per replica. There is no SSH
tunnel, no forwarded Docker socket, and no worker-port relay.
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


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_browser_mcp_is_off_without_the_pool_socket():
    script = _entrypoint()

    assert "STEEL_POOL_DOCKER_SOCKET:-" in script
    assert "STEEL_POOL_DOCKER_SOCKET is unset; browser MCP not started" in script


def test_browser_mcp_waits_for_the_docker_socket():
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


def test_entrypoint_has_no_worker_forward():
    script = _entrypoint()

    assert "start_browser_forwards" not in script
    assert "STEEL_POOL_FORWARD" not in script
    assert "forward.py" not in script
    assert "FORWARD_PID" not in script


def test_compose_exposes_the_pool_configuration():
    env = _compose("docker-compose.yml")["services"]["kali"]["environment"]

    assert env["STEEL_POOL_DOCKER_SOCKET"] == "/var/run/docker.sock"
    assert "STEEL_POOL_SIZE" not in env
    assert "STEEL_POOL_LABEL" not in env
    assert "STEEL_WORKER_HOST" not in env
    assert "STEEL_POOL_FORWARD_PORTS" not in env
    assert "STEEL_CLI_TIMEOUT_S" not in env


def test_compose_mounts_the_session_store_and_the_docker_socket():
    rendered = _compose("docker-compose.yml")
    kali = rendered["services"]["kali"]
    mounts = {
        mount["target"]: mount["source"]
        for mount in kali["volumes"]
        if isinstance(mount, dict)
    }

    assert mounts["/var/lib/steel/sessions"] == "steel-sessions"
    assert mounts["/var/run/docker.sock"] == "/var/run/docker.sock"
    assert "steel-sessions" in rendered["volumes"]


def test_compose_keeps_the_browser_mcp_off_the_host():
    rendered = _compose("docker-compose.yml")
    kali = rendered["services"]["kali"]
    published = {int(port["target"]) for port in kali.get("ports", [])}

    assert 8000 in published
    assert 8003 not in published


def test_compose_gives_the_end_path_time_to_finish():
    kali = _compose("docker-compose.yml")["services"]["kali"]

    # CLI timeout 300 s + API 10 s + settle 5 s; the end path runs on SIGTERM.
    # Compose normalizes 330 s to 5m30s.
    assert kali["stop_grace_period"] == "5m30s"


def test_steel_worker_is_one_replicated_service():
    rendered = _compose("docker-compose.yml")
    worker = rendered["services"]["steel-worker"]

    assert worker["image"] == "steel-browser-api:v0.5.5-beta"
    assert worker["command"] == ["--no-nginx"]
    assert worker["environment"]["DOMAIN"] == "localhost:3000"
    assert worker["environment"]["CDP_DOMAIN"] == "localhost:3000"
    assert worker["environment"]["ENABLE_COMMANDS_API"] == "false"
    assert worker["labels"]["polymerhus.steel-pool"] == "true"
    assert worker["deploy"]["replicas"] == 2
    assert "polymerhus-net" in worker["networks"]
    assert not worker.get("ports")


def test_steel_worker_has_no_published_port():
    rendered = _compose("docker-compose.yml")
    worker = rendered["services"]["steel-worker"]

    assert "ports" not in worker
    assert "expose" not in worker


def test_thin_overlay_scales_the_pool_to_zero():
    thin = _yaml("docker-compose.thin.yml")

    assert thin["services"]["steel-worker"]["deploy"]["replicas"] == 0
    assert thin["services"]["kali"]["environment"]["STEEL_POOL_DOCKER_SOCKET"] == ""
    assert thin["services"]["agent"]["environment"]["KALI_BROWSER_MCP_URL"] == ""


def test_eval_overlay_points_the_agent_at_the_browser_mcp():
    overlay = _yaml("eval/docker-compose.eval.yml")

    assert overlay["services"]["agent"]["environment"]["KALI_BROWSER_MCP_URL"] == (
        "http://kali:8003/mcp"
    )


def test_dev_overlay_points_the_agent_at_the_browser_mcp():
    overlay = _yaml("docker-compose.dev.yml")

    assert overlay["services"]["agent"]["environment"]["KALI_BROWSER_MCP_URL"] == (
        "${KALI_BROWSER_MCP_URL:-http://kali:8003/mcp}"
    )


def test_runbook_describes_the_in_stack_pool():
    runbook = (ROOT / "eval" / "deploy" / "steel" / "POOL-RUNBOOK.md").read_text(
        encoding="utf-8"
    )

    for fragment in (
        "steel-worker",
        "deploy.replicas",
        "docker compose",
        "KALI_BROWSER_MCP_URL",
        "3100",
        "localhost:3000",
        "arm64",
        "chromium",
        "pool.discovered",
    ):
        assert fragment in runbook, fragment

    for retired in (
        "-L 127.0.0.1:3100:127.0.0.1:3100",
        "ssh -N",
        "/run/steel-pool/docker.sock",
        "docker-compose.steel-pool.yml",
    ):
        assert retired not in runbook, retired


def test_compose_renders_the_thin_stack():
    rendered = _compose("docker-compose.yml", "docker-compose.thin.yml")
    worker = rendered["services"]["steel-worker"]
    kali = rendered["services"]["kali"]

    assert worker["deploy"]["replicas"] == 0
    assert kali["environment"]["STEEL_POOL_DOCKER_SOCKET"] == ""
    assert rendered["services"]["agent"]["environment"]["KALI_BROWSER_MCP_URL"] == ""
