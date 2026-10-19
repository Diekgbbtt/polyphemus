"""Contract tests for the pinned local Steel deployment (#359, T3).

Parse the declared artifact, never the host's live state. These assertions are
the reviewable contract: a `latest` tag, a published UI/CDP port, or a missing
durable volume must fail here before it can ship.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "eval" / "deploy" / "steel" / "docker-compose.steel.yml"
ALLOWLIST = REPO_ROOT / "eval" / "deploy" / "steel" / "allowlist.sh"
OPERATOR = REPO_ROOT / "eval" / "OPERATOR.md"

IMAGE_DIGEST = (
    "ghcr.io/steel-dev/steel-browser-api@"
    "sha256:eb8567bac2221d2856923184cf693a08df9a488680431ebded73cab63aa181eb"
)

docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI unavailable"
)


def _service() -> dict:
    config = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return config["services"]["steel-api"]


def test_image_is_pinned_by_digest_and_latest_appears_nowhere():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "latest" not in text
    assert _service()["image"] == IMAGE_DIGEST
    assert "@sha256:" in _service()["image"]


def test_only_port_3000_is_published():
    ports = [str(p) for p in _service()["ports"]]
    assert ports == ["3000:3000"]
    assert not any("5173" in p or "9223" in p for p in ports)


def test_the_service_restarts_unless_stopped():
    assert _service()["restart"] == "unless-stopped"


def test_the_service_restarts_unless_stopped():
    assert _service()["restart"] == "unless-stopped"


def test_the_cache_volume_is_durable_and_mounted():
    service = _service()
    mounts = [str(v) for v in service["volumes"]]
    assert any(m.endswith(":/app/.cache") for m in mounts)
    named = [m.split(":", 1)[0] for m in mounts if not m.startswith(("/", "."))]
    assert named, "the .cache mount must be a named (durable) volume"
    declared = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")).get("volumes") or {}
    assert all(name in declared for name in named)


def test_domain_is_required():
    assert ":?" in _service()["environment"]["DOMAIN"]


def test_the_target_alias_is_configurable_and_inert_by_default():
    hosts = _service()["extra_hosts"]
    assert len(hosts) == 1
    alias = hosts[0]
    assert "STEEL_TARGET_HOST" in alias and "STEEL_TARGET_IP" in alias
    # The fallback pair must route nowhere real.
    assert "steel-target.invalid" in alias
    assert "127.0.0.1" in alias


@docker
def test_compose_resolves_with_a_domain_and_fails_without_one():
    env = {k: v for k, v in os.environ.items() if k != "STEEL_DOMAIN"}
    missing = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert missing.returncode != 0
    assert "STEEL_DOMAIN" in missing.stderr

    env["STEEL_DOMAIN"] = "192.0.2.10:3000"
    present = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert present.returncode == 0, present.stderr
    assert "192.0.2.10:3000" in present.stdout
    # Never publish the debug port or the UI.
    assert "9223" not in present.stdout
    assert "5173" not in present.stdout


def test_allowlist_script_is_executable_and_valid_bash():
    assert ALLOWLIST.exists()
    assert os.access(ALLOWLIST, os.X_OK)
    check = subprocess.run(
        ["bash", "-n", str(ALLOWLIST)], capture_output=True, text=True
    )
    assert check.returncode == 0, check.stderr


def test_allowlist_requires_a_source_and_names_both_families():
    text = ALLOWLIST.read_text(encoding="utf-8")
    assert "iptables" in text
    assert "ip6tables" in text
    assert "DOCKER-USER" in text
    assert "at least one allowed source is required" in text
    # Idempotence comes from flushing the dedicated chain, never from appending.
    assert "-F" in text
    assert "--remove" in text


# A stateful iptables/ip6tables stub: it models chain existence, append, insert,
# check, delete, flush, and drop. The allowlist script is run twice against it,
# so the assertion is real idempotence, not text matching.
IPTABLES_STUB = r'''#!/usr/bin/env python3
import json
import os
import sys

name = os.path.basename(sys.argv[0])
state_path = os.path.join(os.environ["STUB_DIR"], name + ".json")
state = {"DOCKER-USER": [], "POLYMERHUS-STEEL": []}
if os.path.exists(state_path):
    with open(state_path) as fh:
        state = json.load(fh)
args = []
i = 0
while i < len(sys.argv[1:]):
    if sys.argv[1:][i] == "-w":
        i += 2
        continue
    args.append(sys.argv[1:][i])
    i += 1
op, chain, rest = args[0], args[1], args[2:]
if op == "-S":
    if chain not in state:
        sys.exit(1)
    print("-N " + chain)
    for rule in state[chain]:
        print("-A " + chain + " " + " ".join(rule))
elif op == "-N":
    state[chain] = []
elif op == "-F":
    state[chain] = []
elif op == "-X":
    state.pop(chain, None)
elif op == "-A":
    state[chain].append(rest)
elif op == "-I":
    state[chain].insert(0, rest[1:])
elif op == "-C":
    sys.exit(0 if rest in state[chain] else 1)
elif op == "-D":
    if rest not in state[chain]:
        sys.exit(1)
    state[chain].remove(rest)
else:
    sys.exit(2)
with open(state_path, "w") as fh:
    json.dump(state, fh)
'''


def _stub_bin(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("iptables", "ip6tables", "id"):
        path = bindir / tool
        path.write_text(IPTABLES_STUB if tool != "id" else "#!/bin/sh\necho 0\n", encoding="utf-8")
        path.chmod(0o755)
    return bindir


def test_allowlist_is_idempotent_and_ipv4_ipv6_aware(tmp_path):
    bindir = _stub_bin(tmp_path)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "STUB_DIR": str(tmp_path)}
    argv = [str(ALLOWLIST), "192.0.2.10", "2001:db8::1"]

    for _ in range(2):
        run = subprocess.run(argv, capture_output=True, text=True, env=env)
        assert run.returncode == 0, run.stderr

    v4 = json.loads((tmp_path / "iptables.json").read_text())
    v6 = json.loads((tmp_path / "ip6tables.json").read_text())
    assert v4["DOCKER-USER"] == [["-j", "POLYMERHUS-STEEL"]]
    assert v6["DOCKER-USER"] == [["-j", "POLYMERHUS-STEEL"]]
    assert len(v4["POLYMERHUS-STEEL"]) == 2  # one accept, one drop
    assert len(v6["POLYMERHUS-STEEL"]) == 2
    assert ["-s", "192.0.2.10", "-j", "ACCEPT"] in [
        rule[-4:] for rule in v4["POLYMERHUS-STEEL"]
    ]
    assert ["-s", "2001:db8::1", "-j", "ACCEPT"] in [
        rule[-4:] for rule in v6["POLYMERHUS-STEEL"]
    ]
    assert v4["POLYMERHUS-STEEL"][-1][-1] == "DROP"
    assert v6["POLYMERHUS-STEEL"][-1][-1] == "DROP"

    removed = subprocess.run([str(ALLOWLIST), "--remove"], capture_output=True, text=True, env=env)
    assert removed.returncode == 0, removed.stderr
    v4 = json.loads((tmp_path / "iptables.json").read_text())
    v6 = json.loads((tmp_path / "ip6tables.json").read_text())
    assert "POLYMERHUS-STEEL" not in v4 and v4["DOCKER-USER"] == []
    assert "POLYMERHUS-STEEL" not in v6 and v6["DOCKER-USER"] == []


def test_operator_guide_covers_deploy_allowlist_teardown_move_and_boundary():
    text = OPERATOR.read_text(encoding="utf-8")
    for heading in (
        "#### Deploy",
        "#### Allowlist",
        "#### Teardown",
        "#### Moving the stack to another host",
        "#### The #245 portability boundary",
    ):
        assert heading in text
    for capability in (
        "residential proxies",
        "Dedicated IPs",
        "CAPTCHA",
        "Credentials API",
        "Files API",
        "Concurrency: 1",
        "build-time injection",
    ):
        assert capability in text
