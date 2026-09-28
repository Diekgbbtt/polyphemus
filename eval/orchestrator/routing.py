"""Synthetic-Host routing (D2).

Every `TargetRun` gets a unique synthetic Host (`t-<short>.target`). It is
written into the target front's `server_name` (one nginx conf file per host,
so concurrent fronts cannot overwrite each other - the spec's 6.2 defect) and
aliased in that instance's kali `/etc/hosts`. Distinct published ports were
rejected because a port-bearing seed breaks the platform's bare-domain scope
gate; the HTTP `Host` is the discriminator.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

from orchestrator.commands import Command, CommandRunner
from orchestrator.ids import short_id
from orchestrator.instances import InstancePaths

SYNTHETIC_SUFFIX = ".target"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")

# Single-sourced (S1/S2): the host loopback the host-side readiness probes use,
# and the Docker host gateway kali reaches host-published ports through. Kali is
# not on the host network, so `127.0.0.1` inside kali is kali itself.
LOOPBACK = "127.0.0.1"
HOST_GATEWAY = "host.docker.internal"
# Plan-mode placeholder for the gateway address resolved at run time (SP1).
PLAN_GATEWAY_IP = "<gateway-ip>"

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


class RoutingError(RuntimeError):
    """A remote routing command failed or an address could not be resolved."""


def is_numeric_address(value: str) -> bool:
    """True when `value` is a numeric IPv4 address, not a hostname.

    `/etc/hosts` has no resolver in its address column, so every value written
    as an alias target must be numeric (SP1).
    """
    return bool(_IPV4_RE.match(value))


def is_plan_placeholder(ip: str) -> bool:
    """True for a plan-mode placeholder such as `<gateway-ip>` (never executed)."""
    return ip.startswith("<") and ip.endswith(">")


def synthetic_host(identity: str) -> str:
    """`t-<short>.target` for a TargetRun identity (`<instance_id>/<target_id>`)."""
    return f"t-{short_id(identity)}{SYNTHETIC_SUFFIX}"


def nginx_front_block(host: str, port: int | str, *, backend_host: str = LOOPBACK) -> str:
    """The nginx server block: `server_name <host>` -> `backend_host:port`.

    `backend_host` defaults to loopback (the remote workshop host, where nginx
    and the target share a network namespace) and is the Docker host gateway
    for the local front container, which reaches host-published ports that way.
    """
    return (
        "server {\n"
        f"    server_name {host};\n"
        "    listen 80;\n"
        "    location / {\n"
        f"        proxy_pass http://{backend_host}:{port};\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }\n"
        "}\n"
    )


def front_conf_path(conf_dir: str | Path, host: str) -> Path:
    """One conf file per synthetic Host, so concurrent fronts never collide."""
    return Path(conf_dir) / f"eval-target-{host}.conf"


def ssh_command(
    ssh_host: str,
    remote_command: str,
    *,
    stdin: str | None = None,
    description: str = "",
) -> Command:
    """The one ssh command builder shared by `routing` and `targetctl` (S2)."""
    return Command(
        argv=("ssh", *SSH_OPTS, ssh_host, remote_command),
        stdin=stdin,
        description=description,
    )


def plan_front_apply(ssh_host: str, conf_path: str | Path, host: str, port: int | str) -> Command:
    """Write the per-host front block remotely and reload nginx."""
    quoted = shlex.quote(str(conf_path))
    remote = (
        f"sudo tee {quoted} >/dev/null && sudo nginx -t && sudo systemctl reload nginx"
    )
    return ssh_command(
        ssh_host,
        remote,
        stdin=nginx_front_block(host, port),
        description=f"front {host} -> {LOOPBACK}:{port}",
    )


def plan_front_remove(ssh_host: str, conf_path: str | Path) -> Command:
    """Remove the per-host front block remotely and reload nginx."""
    quoted = shlex.quote(str(conf_path))
    remote = f"sudo rm -f {quoted} && sudo nginx -t && sudo systemctl reload nginx"
    return ssh_command(
        ssh_host, remote, stdin=None, description=f"remove front {conf_path}"
    )


def _compose_ps_kali(paths: InstancePaths) -> str:
    files = " ".join(f"-f {compose_file}" for compose_file in paths.compose_files)
    return f"docker compose -p {paths.compose_project} {files} ps -q kali"


def _rewrite_hosts(host: str) -> str:
    # /etc/hosts is a docker bind mount: sed -i cannot rename it, so rewrite
    # through a temp file and truncate-write back (the hosts.sh technique).
    return (
        f"awk '!/[[:space:]]{host}$/' /etc/hosts > /tmp/hosts.tmp "
        "&& cat /tmp/hosts.tmp > /etc/hosts"
    )


def _kali_exec_command(
    paths: InstancePaths, inner: str, *, description: str
) -> Command:
    script = (
        f"cid=$({_compose_ps_kali(paths)}); "
        f"test -n \"$cid\" || {{ echo 'routing: no kali container for "
        f"{paths.compose_project}' >&2; exit 1; }}; "
        f"docker exec \"$cid\" sh -c {shlex.quote(inner)}"
    )
    return Command(
        argv=("sh", "-c", script),
        cwd=str(paths.worktree),
        description=description,
    )


def kali_alias_command(paths: InstancePaths, host: str, ip: str) -> Command:
    """Alias the synthetic Host inside that instance's kali `/etc/hosts`.

    `ip` must be a NUMERIC address (SP1): `/etc/hosts` does not resolve a
    hostname in its address column, so an unresolved `host.docker.internal`
    line would silently point nowhere. This is the single write point, so it
    enforces the guarantee for every caller; a plan-mode placeholder (never
    executed) is the only non-numeric value allowed. Local strategies resolve
    the gateway first with `resolve_gateway`.
    """
    if not (is_numeric_address(ip) or is_plan_placeholder(ip)):
        raise RoutingError(
            f"refusing to alias {host} to non-numeric address {ip!r}: "
            "/etc/hosts does not resolve a hostname in its address column"
        )
    inner = _rewrite_hosts(host) + f" && echo '{ip} {host}' >> /etc/hosts"
    return _kali_exec_command(
        paths, inner, description=f"alias {host} -> {ip} in {paths.compose_project} kali"
    )


def plan_gateway_resolve(paths: InstancePaths) -> Command:
    """Read the Docker host gateway address as seen INSIDE that instance's kali.

    `host.docker.internal` may be absent in a container that lacks the
    `host-gateway` mapping, so the resolution is explicit and its failure fatal.
    """
    return _kali_exec_command(
        paths,
        f"getent hosts {HOST_GATEWAY}",
        description=f"resolve {HOST_GATEWAY} in {paths.compose_project} kali",
    )


def parse_gateway_address(text: str) -> str:
    """The first numeric address in `getent hosts` output (SP1)."""
    for token in text.split():
        if is_numeric_address(token):
            return token
    raise RoutingError(
        f"no numeric address for {HOST_GATEWAY} in getent output: {text!r}"
    )


def resolve_gateway(run: CommandRunner, paths: InstancePaths) -> str:
    """Resolve the host gateway inside kali, failing loudly (SP1)."""
    command = plan_gateway_resolve(paths)
    result = run(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RoutingError(
            f"resolving {HOST_GATEWAY} inside {paths.compose_project} kali failed "
            f"(exit {result.returncode}): {detail or 'no output'}"
        )
    return parse_gateway_address(result.stdout)


def kali_clear_command(paths: InstancePaths, host: str) -> Command:
    """Remove every synthetic-Host alias line from that instance's kali."""
    return _kali_exec_command(
        paths,
        _rewrite_hosts(host),
        description=f"clear {host} from {paths.compose_project} kali",
    )


def kali_hosts_command(paths: InstancePaths) -> Command:
    """Read that instance's kali `/etc/hosts` (the live alias surface)."""
    return _kali_exec_command(
        paths,
        "cat /etc/hosts",
        description=f"read {paths.compose_project} kali /etc/hosts",
    )


def parse_synthetic_aliases(hosts_text: str) -> dict[str, str]:
    """The synthetic-Host aliases present in an `/etc/hosts` body: host -> ip."""
    aliases: dict[str, str] = {}
    for line in hosts_text.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        ip = fields[0]
        for name in fields[1:]:
            if name.endswith(SYNTHETIC_SUFFIX):
                aliases[name] = ip
    return aliases
