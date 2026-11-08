"""The eval host exposure policy: SSH is the only internet-facing listener.

The plain stack services bind to `127.0.0.1`. The eval front and the target
ports must stay reachable from the Docker bridge subnets, so they are fenced
by a default-deny host firewall instead of a narrower bind. These tests pin
the generated rules; `--apply` is a thin executor over the same rule list.
"""
from __future__ import annotations

import host_firewall


def _argv(commands) -> list[str]:
    return [" ".join(command) for command in commands]


def test_input_chain_allows_only_ssh_from_the_internet() -> None:
    rules = host_firewall.input_rules("iptables")

    text = "\n".join(_argv(rules))
    assert "-m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT" in text
    assert "-i lo -j ACCEPT" in text
    assert "-p tcp --dport 22 -j ACCEPT" in text
    assert "-s 172.16.0.0/12 -j ACCEPT" in text
    assert text.rstrip().endswith("-j DROP")


def test_input_chain_keeps_the_dhcp_client_lease() -> None:
    """A host firewall must not stop the DHCP client that holds the address."""
    text = "\n".join(_argv(host_firewall.input_rules("iptables")))
    assert "-p udp --sport 67 --dport 68 -j ACCEPT" in text


def test_input_chain_drops_after_the_allowlist() -> None:
    rules = host_firewall.input_rules("iptables")
    allow_index = next(
        index for index, command in enumerate(rules) if "22" in command
    )
    drop_index = next(
        index for index, command in enumerate(rules) if command[-1] == "DROP"
    )
    assert allow_index < drop_index


def test_forward_chain_fences_docker_published_ports() -> None:
    rules = host_firewall.forward_rules("iptables")

    text = "\n".join(_argv(rules))
    assert "-m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT" in text
    assert "-i lo -j ACCEPT" in text
    assert "-s 172.16.0.0/12 -j ACCEPT"
    assert text.rstrip().endswith("-j DROP")


def test_ipv6_allows_loopback_and_ssh_only() -> None:
    rules = host_firewall.input_rules("ip6tables")

    text = "\n".join(_argv(rules))
    assert "-i lo -j ACCEPT" in text
    assert "-p tcp --dport 22 -j ACCEPT" in text
    assert text.rstrip().endswith("-j DROP")
    assert "172.16.0.0/12" not in text


def test_render_is_a_dry_run_without_touching_the_host(capsys) -> None:
    exit_code = host_firewall.main(["--dry-run"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "iptables" in out
    assert "ip6tables" in out
    assert "POLYMERHUS-INPUT" in out
    assert "POLYMERHUS-DOCKER-USER" in out


def test_apply_is_an_ordered_executor_over_the_same_rule_list(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return host_firewall.Completed(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(host_firewall, "run", fake_run)

    assert host_firewall.main(["--apply"]) == 0

    text = "\n".join(" ".join(call) for call in calls)
    assert "POLYMERHUS-INPUT" in text
    assert "-I INPUT 1 -j POLYMERHUS-INPUT" in text
    assert "-I DOCKER-USER 1 -j POLYMERHUS-DOCKER-USER" in text


def test_remove_takes_the_jumps_out_before_deleting_the_chains(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return host_firewall.Completed(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(host_firewall, "run", fake_run)

    assert host_firewall.main(["--remove"]) == 0

    text = "\n".join(" ".join(call) for call in calls)
    assert "-D INPUT -j POLYMERHUS-INPUT" in text
    assert "-D DOCKER-USER -j POLYMERHUS-DOCKER-USER" in text
