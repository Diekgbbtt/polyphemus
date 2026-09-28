"""Synthetic-Host routing (ticket #269, D2).

Every `TargetRun` gets a unique synthetic Host (`t-<short>.target`), written
into the target front's `server_name` and aliased in that instance's kali
`/etc/hosts`. Distinct published ports were rejected because they break the
platform's bare-domain scope gate; the Host header is the discriminator.
"""
from __future__ import annotations

import pytest

from orchestrator import instances, routing, setup as setup_mod
from orchestrator.commands import CommandResult


def _paths(tmp_path, instance_id="arm-a"):
    run = setup_mod.TargetRun(
        target_id="t-1",
        target_config=setup_mod.TargetConfig(
            lifecycle="targetctl", params={"target": "jetlinks"}
        ),
    )
    instance = setup_mod.Instance(instance_id=instance_id, targets=(run,))
    return instances.instance_paths(
        instance, tmp_path / "instances", repo=tmp_path / "repo", branch="eval"
    )


def test_synthetic_host_is_deterministic_and_unique() -> None:
    a = routing.synthetic_host("arm-a/jetlinks-1")
    a_again = routing.synthetic_host("arm-a/jetlinks-1")
    b = routing.synthetic_host("arm-b/jetlinks-1")

    assert a == a_again
    assert a != b
    assert a.startswith("t-") and a.endswith(".target")
    assert a == a.lower()


def test_front_block_uses_server_name_and_proxies_to_the_port() -> None:
    block = routing.nginx_front_block("t-abcd1234.target", 32768)

    assert "server_name t-abcd1234.target;" in block
    assert "proxy_pass http://127.0.0.1:32768;" in block


def test_front_conf_path_is_per_host(tmp_path) -> None:
    a = routing.front_conf_path("/etc/nginx/conf.d", "t-aaaa.target")
    b = routing.front_conf_path("/etc/nginx/conf.d", "t-bbbb.target")

    assert a != b
    assert a.name == "eval-target-t-aaaa.target.conf"
    assert str(a).startswith("/etc/nginx/conf.d/")


def test_front_apply_carries_the_block_on_stdin() -> None:
    command = routing.plan_front_apply(
        "ubuntu@workshop", "/etc/nginx/conf.d/eval-target-t-aaaa.target.conf",
        "t-aaaa.target", 32768,
    )

    assert command.argv[0] == "ssh"
    assert "ubuntu@workshop" in command.argv
    assert "sudo tee /etc/nginx/conf.d/eval-target-t-aaaa.target.conf" in " ".join(
        command.argv
    )
    assert "server_name t-aaaa.target;" in command.stdin


def test_front_remove_deletes_the_per_host_conf() -> None:
    conf = "/etc/nginx/conf.d/eval-target-t-aaaa.target.conf"
    command = routing.plan_front_remove("ubuntu@workshop", conf)

    assert command.argv[0] == "ssh"
    assert f"sudo rm -f {conf}" in " ".join(command.argv)


def test_kali_alias_targets_the_instance_compose_project(tmp_path) -> None:
    paths = _paths(tmp_path)

    command = routing.kali_alias_command(paths, "t-aaaa.target", "10.0.0.5")
    script = command.argv[-1]

    assert command.argv[0] == "sh"
    assert command.cwd == str(paths.worktree)
    assert paths.compose_project in script
    assert "docker exec" in script
    assert "t-aaaa.target" in script
    assert "10.0.0.5" in script
    assert str(paths.worktree) not in script  # compose runs from the cwd instead


def test_kali_clear_removes_only_the_host(tmp_path) -> None:
    paths = _paths(tmp_path)

    command = routing.kali_clear_command(paths, "t-aaaa.target")
    script = command.argv[-1]

    assert "t-aaaa.target" in script
    assert paths.compose_project in script
    assert "10.0.0.5" not in script


def test_kali_hosts_command_reads_the_instance_hosts_file(tmp_path) -> None:
    paths = _paths(tmp_path)

    command = routing.kali_hosts_command(paths)
    script = command.argv[-1]

    assert "cat /etc/hosts" in script
    assert paths.compose_project in script
    assert command.cwd == str(paths.worktree)


def test_ssh_builder_is_the_shared_shape() -> None:
    command = routing.ssh_command("ubuntu@workshop", "echo hi", description="d")

    assert command.argv[0] == "ssh"
    assert all(opt in command.argv for opt in routing.SSH_OPTS)
    assert "ubuntu@workshop" in command.argv
    assert command.argv[-1] == "echo hi"


def test_is_numeric_address_distinguishes_ips_from_hosts() -> None:
    assert routing.is_numeric_address("172.17.0.1")
    assert not routing.is_numeric_address("host.docker.internal")
    assert not routing.is_numeric_address("")
    assert not routing.is_numeric_address("t-a.target")


def test_kali_alias_command_rejects_a_non_numeric_address(tmp_path) -> None:
    """SP1: the single write point refuses to put a hostname in /etc/hosts."""
    paths = _paths(tmp_path)

    with pytest.raises(routing.RoutingError, match="non-numeric"):
        routing.kali_alias_command(paths, "t-aaaa.target", "host.docker.internal")


def test_kali_alias_command_allows_a_plan_placeholder(tmp_path) -> None:
    paths = _paths(tmp_path)

    command = routing.kali_alias_command(paths, "t-aaaa.target", routing.PLAN_GATEWAY_IP)

    assert routing.PLAN_GATEWAY_IP in " ".join(command.argv)


def test_parse_gateway_address_takes_the_first_numeric_token() -> None:
    text = "fe80::1 host.docker.internal\n172.17.0.1 host.docker.internal\n"

    assert routing.parse_gateway_address(text) == "172.17.0.1"


def test_parse_gateway_address_fails_when_no_numeric_address() -> None:
    with pytest.raises(routing.RoutingError, match="numeric address"):
        routing.parse_gateway_address("host.docker.internal\n")


def test_resolve_gateway_runs_the_getent_command_through_the_runner(tmp_path) -> None:
    paths = _paths(tmp_path)
    seen: list = []

    def run(command):
        seen.append(command)
        return CommandResult(0, "172.17.0.1 host.docker.internal\n")

    assert routing.resolve_gateway(run, paths) == "172.17.0.1"
    assert "getent hosts host.docker.internal" in " ".join(seen[0].argv)


def test_resolve_gateway_failure_is_fatal(tmp_path) -> None:
    paths = _paths(tmp_path)

    def run(_command):
        return CommandResult(1, "", "Name or service not known")

    with pytest.raises(routing.RoutingError, match="host.docker.internal"):
        routing.resolve_gateway(run, paths)


def test_parse_synthetic_aliases_reads_only_synthetic_hosts() -> None:
    text = (
        "127.0.0.1 localhost\n"
        "10.0.0.5 t-aaaa.target\n"
        "10.0.0.6 t-bbbb.target other.example\n"
        "::1 ip6-localhost\n"
    )

    assert routing.parse_synthetic_aliases(text) == {
        "t-aaaa.target": "10.0.0.5",
        "t-bbbb.target": "10.0.0.6",
    }
