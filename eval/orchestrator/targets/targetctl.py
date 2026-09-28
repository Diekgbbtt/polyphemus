"""The `targetctl` strategy: WebExploitBench on the REMOTE workshop host.

Deployment is issued over ssh (operator directive) and fronted by that host's
nginx on the synthetic Host: `targetctl` publishes on a random host port, so
nginx is both the stable bare-domain face and the TLS-capable front. One conf
file per synthetic Host means concurrent instances never overwrite each other's
front. The inner-kali alias makes resolution deterministic for the recon fleet.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from orchestrator import routing
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.targets.base import (
    Sleep,
    TargetContext,
    TargetError,
    TargetNotReadyError,
    TargetUpResult,
    wait_ready,
)

DEFAULT_SSH_HOST = "ubuntu@dj-viscon-workshop-1.vsos.ethz.ch"
DEFAULT_REMOTE_DIR = "~/WebExploitBench"
DEFAULT_REPO_URL = "https://github.com/AgentCyberRange/WebExploitBench.git"
DEFAULT_NGINX_CONF_DIR = "/etc/nginx/conf.d"
DEFAULT_READY_RETRIES = 60
DEFAULT_READY_INTERVAL_S = 5.0
PLAN_PORT = "<published-port>"
PLAN_IP = "<target-ip>"

_UI_URL_RE = re.compile(r"UI:\s*(https?://\S+)")
_ANY_URL_RE = re.compile(r"https?://\S+")
_LOOPBACK_HOSTS = ("0.0.0.0", "127.0.0.1", "localhost")


class TargetctlError(TargetError):
    """A targetctl deployment command failed or its output could not be parsed."""


def parse_targetctl_url(output: str) -> str:
    """Pick the accessible URL from `targetctl up` output.

    Prefer an explicit `UI:` line; otherwise the first URL with no path (a bare
    host:port), matching the shape `targetctl` prints.
    """
    match = _UI_URL_RE.search(output)
    if match:
        return match.group(1)
    for candidate in _ANY_URL_RE.finditer(output):
        url = candidate.group(0)
        parsed = urlparse(url)
        if parsed.path in ("", "/"):
            return url
    raise TargetctlError("targetctl output carries no accessible URL")


def rewrite_public_host(url: str, public_host: str) -> str:
    """Rewrite a loopback/bind-all host in `url` to the workshop public host."""
    for loopback in _LOOPBACK_HOSTS:
        url = url.replace(f"http://{loopback}:", f"http://{public_host}:")
    return url


def url_port(url: str) -> str:
    port = urlparse(url).port
    if port is None:
        raise TargetctlError(f"targetctl URL carries no port: {url!r}")
    return str(port)


class TargetctlStrategy:
    """One WebExploitBench target run on the remote workshop host."""

    def __init__(
        self,
        context: TargetContext,
        *,
        env: Mapping[str, str] | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        params = context.run.target_config.params
        environment = os.environ if env is None else env
        self.context = context
        self.host = context.host
        self.paths = context.paths
        self._sleep = sleep or time.sleep
        self.target = str(params["target"])
        self.ssh_host = str(
            params.get("ssh_host") or environment.get("EVAL_SSH_HOST") or DEFAULT_SSH_HOST
        )
        self.remote_dir = str(
            params.get("remote_dir")
            or environment.get("EVAL_REMOTE_DIR")
            or DEFAULT_REMOTE_DIR
        )
        self.repo_url = str(params.get("repo_url") or DEFAULT_REPO_URL)
        self.nginx_conf_dir = str(
            params.get("nginx_conf_dir")
            or environment.get("EVAL_NGINX_CONF_DIR")
            or DEFAULT_NGINX_CONF_DIR
        )
        self.ready_retries = int(
            params.get("ready_retries")
            or environment.get("EVAL_READY_RETRIES")
            or DEFAULT_READY_RETRIES
        )
        self.ready_interval_s = float(
            params.get("ready_interval_s")
            or environment.get("EVAL_READY_INTERVAL_S")
            or DEFAULT_READY_INTERVAL_S
        )

    @property
    def public_host(self) -> str:
        return self.ssh_host.rsplit("@", 1)[-1]

    @property
    def front_conf(self) -> Path:
        return routing.front_conf_path(self.nginx_conf_dir, self.host)

    @property
    def front_url(self) -> str:
        return f"http://{self.host}/"

    # --- command builders (shared by plan and execute) ------------------------

    def _ssh(self, remote_command: str, *, description: str) -> Command:
        return Command(
            argv=("ssh", *routing.SSH_OPTS, self.ssh_host, remote_command),
            description=description,
        )

    def _checkout_cmd(self) -> Command:
        remote = (
            f"test -d {self.remote_dir}/.git || "
            f"(git clone --depth 1 {self.repo_url} {self.remote_dir})"
        )
        return self._ssh(remote, description=f"ensure {self.remote_dir}")

    def _targetctl(self, *args: str) -> Command:
        remote = f"cd {self.remote_dir} && scripts/targetctl {' '.join(args)}"
        return self._ssh(remote, description=f"targetctl {' '.join(args)}")

    def _ip_cmd(self) -> Command:
        return self._ssh("hostname -I | awk '{print $1}'", description="target ip")

    def _probe_cmd(self, port: int | str) -> Command:
        remote = (
            "curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "
            f"-H 'Host: {self.host}' http://127.0.0.1:{port}/"
        )
        return self._ssh(remote, description=f"probe {self.host}")

    # --- lifecycle ------------------------------------------------------------

    def plan_up(self) -> list[Command]:
        return [
            self._checkout_cmd(),
            self._targetctl("build", self.target),
            self._targetctl("up", self.target),
            routing.plan_front_apply(self.ssh_host, self.front_conf, self.host, PLAN_PORT),
            self._probe_cmd(PLAN_PORT),
            self._ip_cmd(),
            routing.kali_alias_command(self.paths, self.host, PLAN_IP),
        ]

    def up(self, run: CommandRunner) -> TargetUpResult:
        checkout = self._checkout_cmd()
        require_ok(run(checkout), checkout, error=TargetctlError)
        build = self._targetctl("build", self.target)
        require_ok(run(build), build, error=TargetctlError)

        up_cmd = self._targetctl("up", self.target)
        output = require_ok(run(up_cmd), up_cmd, error=TargetctlError).stdout
        backend = rewrite_public_host(parse_targetctl_url(output), self.public_host)
        port = url_port(backend)

        front = routing.plan_front_apply(self.ssh_host, self.front_conf, self.host, port)
        require_ok(run(front), front, error=TargetctlError)

        ready = wait_ready(
            run,
            self._probe_cmd(port),
            retries=self.ready_retries,
            interval_s=self.ready_interval_s,
            sleep=self._sleep,
        )
        if not ready:
            raise TargetNotReadyError(
                f"target {self.target!r} did not answer at {self.front_url} "
                f"after {self.ready_retries} probes"
            )

        alias = routing.kali_alias_command(self.paths, self.host, self._resolve_ip(run))
        require_ok(run(alias), alias, error=TargetctlError)
        return TargetUpResult(
            host=self.host, front_url=self.front_url, backend=backend, ready=True
        )

    def _resolve_ip(self, run: CommandRunner) -> str:
        ip_cmd = self._ip_cmd()
        result = run(ip_cmd)
        remote_ip = result.stdout.strip().split()[0] if result.stdout.strip() else ""
        return remote_ip or self.public_host

    def plan_down(self) -> list[Command]:
        return [
            self._targetctl("down", self.target),
            routing.plan_front_remove(self.ssh_host, self.front_conf),
            routing.kali_clear_command(self.paths, self.host),
        ]

    def down(self, run: CommandRunner) -> None:
        # The target process is best-effort (it may already be gone); the front
        # and the alias are always removed so teardown leaves nothing behind.
        down_cmd = self._targetctl("down", self.target)
        down_result = run(down_cmd)
        front = routing.plan_front_remove(self.ssh_host, self.front_conf)
        require_ok(run(front), front, error=TargetctlError)
        clear = routing.kali_clear_command(self.paths, self.host)
        require_ok(run(clear), clear, error=TargetctlError)
        if down_result.returncode != 0:
            detail = down_result.stderr.strip() or down_result.stdout.strip()
            raise TargetctlError(
                f"targetctl down failed ({down_result.returncode}): {detail}"
            )

    def plan_status(self) -> list[Command]:
        return [self._targetctl("ps", self.target)]

    def status(self, run: CommandRunner) -> str:
        command = self._targetctl("ps", self.target)
        return require_ok(run(command), command, error=TargetctlError).stdout
