"""Contract tests for the pinned local Steel deployment (#359, T3).

Parse the declared artifact, never the host's live state. These assertions are
the reviewable contract: a `latest` tag, a published UI/CDP port, or a missing
durable volume must fail here before it can ship.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "eval" / "deploy" / "steel" / "docker-compose.steel.yml"
ALLOWLIST = REPO_ROOT / "eval" / "deploy" / "steel" / "allowlist.sh"

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
