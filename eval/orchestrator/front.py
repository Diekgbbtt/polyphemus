"""The host-level nginx front for local (`image`/`compose`) targets (SP2).

A local target publishes on a host port (e.g. 18080), but the platform's seed is
a bare domain and its scope gate probes the standard web port (80). A
port-bearing front URL would break the gate, so local targets get a real front:

  * one host-level nginx container (`ph-eval-front`) binds host :80;
  * one conf file per synthetic Host proxies `http://<host>/` to that target's
    published port over the Docker host gateway (`host.docker.internal:port`);
  * confs are added/removed per target, each with `nginx -t` + reload.

The front is multi-target safe: the one :80 binding is shared by every local
target and instance, and per-host conf files cannot overwrite each other. The
orchestrator creates the container before the first local target and removes it
after the last; a crash leaves only the idempotent (re-runnable) up command.
Kali reaches the front through the gateway address it resolves for the alias
(`routing.resolve_gateway`), so the whole path stays on port 80.
"""
from __future__ import annotations

import shlex
from pathlib import Path

from orchestrator import routing
from orchestrator.commands import Command

FRONT_CONTAINER = "ph-eval-front"
FRONT_IMAGE = "nginx:alpine"
FRONT_HOST_PORT = 80
FRONT_CONTAINER_PORT = 80
FRONT_CONF_DIR = "/etc/nginx/conf.d"


def plan_container_up() -> Command:
    """Start the shared front container, creating it on first use (idempotent).

    `docker start` is a no-op on a running container and succeeds on a stopped
    one; only an absent container reaches `docker run`. `--add-host
    host.docker.internal:host-gateway` lets the in-container nginx resolve the
    gateway in `proxy_pass`; the all-interfaces `:80` publish is what kali
    reaches through that gateway.
    """
    script = (
        f"docker start {FRONT_CONTAINER} >/dev/null 2>&1 "
        f"|| docker run -d --name {FRONT_CONTAINER} "
        f"--publish {FRONT_HOST_PORT}:{FRONT_CONTAINER_PORT} "
        f"--add-host {routing.HOST_GATEWAY}:host-gateway {FRONT_IMAGE}"
    )
    return Command(
        argv=("sh", "-c", script),
        description=f"ensure front container {FRONT_CONTAINER} on :{FRONT_HOST_PORT}",
    )


def plan_container_down() -> Command:
    """Remove the shared front container; absent is success (idempotent teardown)."""
    return Command(
        argv=(
            "sh",
            "-c",
            f"docker rm -f {FRONT_CONTAINER} >/dev/null 2>&1 || true",
        ),
        description=f"remove front container {FRONT_CONTAINER}",
    )


def front_conf(host: str) -> Path:
    """The in-container conf path for one synthetic Host."""
    return routing.front_conf_path(FRONT_CONF_DIR, host)


def plan_conf_apply(host: str, port: int | str) -> Command:
    """Write one synthetic Host's front block into the container and reload."""
    conf = shlex.quote(str(front_conf(host)))
    remote = f"cat > {conf} && nginx -t && nginx -s reload"
    return Command(
        argv=("docker", "exec", "-i", FRONT_CONTAINER, "sh", "-c", remote),
        stdin=routing.nginx_front_block(host, port, backend_host=routing.HOST_GATEWAY),
        description=f"front {host} -> {routing.HOST_GATEWAY}:{port}",
    )


def plan_conf_remove(host: str) -> Command:
    """Remove one synthetic Host's front block and reload; absent is success."""
    conf = shlex.quote(str(front_conf(host)))
    remote = f"rm -f {conf} && nginx -t && nginx -s reload"
    return Command(
        argv=("docker", "exec", FRONT_CONTAINER, "sh", "-c", remote),
        description=f"remove front {host}",
    )
