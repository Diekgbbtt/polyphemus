"""The eval host exposure policy.

Only the SSH daemon is reachable from the internet.
Every plain stack service binds to `127.0.0.1` in the compose file.
The eval front and the target ports must stay reachable from the Docker
bridge subnets, so this firewall allows loopback and `172.16.0.0/12` and
drops every other inbound connection.

The script is idempotent.
`--apply` installs two custom chains and a jump at the head of `INPUT` and
`DOCKER-USER`.
`--remove` takes the jumps out and deletes the chains.
`--dry-run` prints the exact commands and touches nothing.

Install the companion `eval/deploy/polymerhus-firewall.service` so the rules
survive a reboot.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import shlex
import subprocess
import sys

SSH_PORT = 22
LOOPBACK = "lo"
DOCKER_SUBNETS = ("172.16.0.0/12",)
INPUT_CHAIN = "POLYMERHUS-INPUT"
FORWARD_CHAIN = "POLYMERHUS-DOCKER-USER"
INPUT_PARENT = "INPUT"
FORWARD_PARENT = "DOCKER-USER"

__all__ = [
    "Completed",
    "FORWARD_CHAIN",
    "FORWARD_PARENT",
    "INPUT_CHAIN",
    "INPUT_PARENT",
    "forward_rules",
    "input_rules",
    "main",
    "render",
    "run",
]


@dataclass(frozen=True)
class Completed:
    """The subset of `subprocess.CompletedProcess` the executor reads."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


def run(argv: Sequence[str], **_kwargs) -> Completed:
    """Run one command and return its terminal without raising."""
    result = subprocess.run(
        list(argv), capture_output=True, text=True, check=False
    )
    return Completed(result.returncode, result.stdout, result.stderr)


def _allow_rules(binary: str) -> list[tuple[str, ...]]:
    """The allowlist shared by the host and the Docker forward path."""
    rules: list[tuple[str, ...]] = [
        ("-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"),
        ("-i", LOOPBACK, "-j", "ACCEPT"),
    ]
    if binary == "iptables":
        for subnet in DOCKER_SUBNETS:
            rules.append(("-s", subnet, "-j", "ACCEPT"))
    return rules


def input_rules(binary: str, *, ssh_port: int = SSH_PORT) -> list[tuple[str, ...]]:
    """The host `INPUT` chain: SSH from anywhere, everything else fenced."""
    rules = _allow_rules(binary)
    rules.append(("-p", "tcp", "--dport", str(ssh_port), "-j", "ACCEPT"))
    if binary == "iptables":
        # Keep the DHCP client lease. This is a client exchange, not a server.
        rules.append(("-p", "udp", "--sport", "67", "--dport", "68", "-j", "ACCEPT"))
    rules.append(("-j", "DROP"))
    return rules


def forward_rules(binary: str) -> list[tuple[str, ...]]:
    """The `DOCKER-USER` chain: only loopback and the Docker subnets pass."""
    rules = _allow_rules(binary)
    rules.append(("-j", "DROP"))
    return rules


def render(commands: Iterable[Sequence[str]]) -> str:
    return "\n".join(shlex.join(list(command)) for command in commands)


def _apply_family(binary: str) -> list[list[str]]:
    """Build the apply command list for one iptables family."""
    commands: list[list[str]] = []
    commands.append([binary, "-N", INPUT_CHAIN])
    commands.append([binary, "-F", INPUT_CHAIN])
    commands.extend(
        [binary, "-A", INPUT_CHAIN, *rule] for rule in input_rules(binary)
    )
    commands.append([binary, "-C", INPUT_PARENT, "-j", INPUT_CHAIN])
    commands.append([binary, "-I", INPUT_PARENT, "1", "-j", INPUT_CHAIN])

    commands.append([binary, "-N", FORWARD_CHAIN])
    commands.append([binary, "-F", FORWARD_CHAIN])
    commands.extend(
        [binary, "-A", FORWARD_CHAIN, *rule] for rule in forward_rules(binary)
    )
    # Docker creates DOCKER-USER at daemon start. The unit runs after Docker,
    # so a missing chain is a deployment order defect, not a silent skip.
    commands.append([binary, "-C", FORWARD_PARENT, "-j", FORWARD_CHAIN])
    commands.append([binary, "-I", FORWARD_PARENT, "1", "-j", FORWARD_CHAIN])
    return commands


def _remove_family(binary: str) -> list[list[str]]:
    commands: list[list[str]] = []
    commands.append([binary, "-D", INPUT_PARENT, "-j", INPUT_CHAIN])
    commands.append([binary, "-D", FORWARD_PARENT, "-j", FORWARD_CHAIN])
    commands.append([binary, "-F", INPUT_CHAIN])
    commands.append([binary, "-F", FORWARD_CHAIN])
    commands.append([binary, "-X", INPUT_CHAIN])
    commands.append([binary, "-X", FORWARD_CHAIN])
    return commands


# Commands whose non-zero exit is expected on a first apply or a second remove.
_TOLERATED = {
    "-N",
    "-C",
    "-D",
    "-X",
}


def _execute(commands: list[list[str]]) -> int:
    for command in commands:
        result = run(command)
        if result.returncode != 0 and command[1] not in _TOLERATED:
            print(
                f"host_firewall: command failed ({result.returncode}): "
                f"{shlex.join(command)}",
                file=sys.stderr,
            )
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
            return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = "--dry-run"
    for candidate in ("--apply", "--remove", "--dry-run"):
        if candidate in args:
            mode = candidate
            break
    if args and args[0] not in ("--apply", "--remove", "--dry-run"):
        print(
            "usage: host_firewall.py [--apply | --remove | --dry-run]",
            file=sys.stderr,
        )
        return 2

    families = ("iptables", "ip6tables")
    if mode == "--dry-run":
        for binary in families:
            print(render(_apply_family(binary)))
        return 0
    if mode == "--apply":
        for binary in families:
            code = _execute(_apply_family(binary))
            if code != 0:
                return code
        return 0
    for binary in families:
        code = _execute(_remove_family(binary))
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
