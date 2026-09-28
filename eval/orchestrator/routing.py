"""Synthetic-Host routing (D2).

Every `TargetRun` gets a unique synthetic Host (`t-<short>.target`). It is
written into the target front's `server_name` (one nginx conf file per host,
so concurrent fronts cannot overwrite each other - the spec's 6.2 defect) and
aliased in that instance's kali `/etc/hosts`. Distinct published ports were
rejected because a port-bearing seed breaks the platform's bare-domain scope
gate; the HTTP `Host` is the discriminator.
"""
from __future__ import annotations

import shlex
from pathlib import Path

from orchestrator.commands import Command
from orchestrator.ids import short_id
from orchestrator.instances import InstancePaths

SYNTHETIC_SUFFIX = ".target"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")


def synthetic_host(identity: str) -> str:
    """`t-<short>.target` for a TargetRun identity (`<instance_id>/<target_id>`)."""
    return f"t-{short_id(identity)}{SYNTHETIC_SUFFIX}"


def nginx_front_block(host: str, port: int | str) -> str:
    """The remote nginx server block: `server_name <host>` -> the target port."""
    return (
        "server {\n"
        f"    server_name {host};\n"
        "    listen 80;\n"
        "    location / {\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
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


def _ssh(ssh_host: str, remote_command: str, *, stdin: str | None, description: str) -> Command:
    return Command(
        argv=("ssh", *SSH_OPTS, ssh_host, remote_command),
        stdin=stdin,
        description=description,
    )


def plan_front_apply(ssh_host: str, conf_path: str | Path, host: str, port: int | str) -> Command:
    """Write the per-host front block remotely and reload nginx."""
    remote = (
        f"sudo tee {conf_path} >/dev/null && sudo nginx -t && sudo systemctl reload nginx"
    )
    return _ssh(
        ssh_host,
        remote,
        stdin=nginx_front_block(host, port),
        description=f"front {host} -> 127.0.0.1:{port}",
    )


def plan_front_remove(ssh_host: str, conf_path: str | Path) -> Command:
    """Remove the per-host front block remotely and reload nginx."""
    remote = f"sudo rm -f {conf_path} && sudo nginx -t && sudo systemctl reload nginx"
    return _ssh(ssh_host, remote, stdin=None, description=f"remove front {conf_path}")


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


def _kali_exec_script(paths: InstancePaths, host: str, *, append: str | None) -> str:
    inner = _rewrite_hosts(host)
    if append:
        inner += f" && echo '{append}' >> /etc/hosts"
    return (
        f"cid=$({_compose_ps_kali(paths)}); "
        f"test -n \"$cid\" || {{ echo 'routing: no kali container for "
        f"{paths.compose_project}' >&2; exit 1; }}; "
        f"docker exec \"$cid\" sh -c {shlex.quote(inner)}"
    )


def kali_alias_command(paths: InstancePaths, host: str, ip: str) -> Command:
    """Alias the synthetic Host inside that instance's kali `/etc/hosts`."""
    script = _kali_exec_script(paths, host, append=f"{ip} {host}")
    return Command(
        argv=("sh", "-c", script),
        cwd=str(paths.worktree),
        description=f"alias {host} -> {ip} in {paths.compose_project} kali",
    )


def kali_clear_command(paths: InstancePaths, host: str) -> Command:
    """Remove every synthetic-Host alias line from that instance's kali."""
    script = _kali_exec_script(paths, host, append=None)
    return Command(
        argv=("sh", "-c", script),
        cwd=str(paths.worktree),
        description=f"clear {host} from {paths.compose_project} kali",
    )
