"""Steel CLI eager delivery pins (ticket 03, #221 stream).

Seams under assertion (both static/structural, no live cloud needed):
- kali/postrun.sh file content (pinned release facts, wiring shape).
- docker-compose.yml kali service config (credential env wiring).

Expected values below are independent literals from the ticket brief
(GitHub release tag v0.4.4, verified live 2026-09-11), never recomputed
the way the stanza computes them.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

STEEL_VERSION = "0.4.4"
SHA_X86_64 = "358ccca0f5250dcb64b8870e2148e83d4d75c1e0c4eaef2c2d4a0a427aaa32ef"
SHA_AARCH64 = "0cec104b3c0da0c232a5f4fe5feaa8098dfc9581fb76029f621d55cc023feb7a"


def _postrun_text() -> str:
    return (REPO_ROOT / "kali" / "postrun.sh").read_text()


def _compose() -> dict:
    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())


def test_postrun_pins_steel_version():
    assert STEEL_VERSION in _postrun_text()


def test_postrun_arch_selects_pinned_tarball():
    text = _postrun_text()
    # Independent literals: the release tarball shape per arch.
    assert "steel-cli-" in text
    assert "unknown-linux-gnu.tar.gz" in text
    assert "x86_64" in text
    assert "aarch64" in text
    # Vendor release path literal; the tag itself is pinned via _SVER above.
    assert "steel-dev/cli/releases/download" in text


def test_postrun_checksum_verifies_both_arches():
    text = _postrun_text()
    assert SHA_X86_64 in text
    assert SHA_AARCH64 in text
    assert "sha256sum" in text


def test_postrun_stanza_is_idempotent_and_best_effort():
    text = _postrun_text()
    # Idempotent: skip when the pinned version is already present.
    assert "steel --version" in text
    assert "0.4.4" in text
    # Best-effort: never abort boot (no active `set -e` command line -
    # the header only names it in a comment; script always exits 0).
    assert not [
        line for line in text.splitlines()
        if line.strip().startswith("set -")
    ]
    assert text.rstrip().endswith("exit 0")
    # Installs into the persisted binary dir like the other gap-fills.
    assert "/opt/localbin" in text


def test_compose_kali_wires_steel_key_only():
    config = _compose()
    kali_env = config["services"]["kali"].get("environment", {})
    if isinstance(kali_env, list):
        kali_env = dict(
            item.split("=", 1) for item in kali_env if "=" in item
        )
    assert "STEEL_API_KEY" in kali_env
    # Wired via .env interpolation, never a real key value in the repo.
    assert kali_env["STEEL_API_KEY"] == "${STEEL_API_KEY:-}"
    # Nothing else new: the agent service gains no steel wiring.
    agent_env = config["services"]["agent"].get("environment", {})
    assert "STEEL_API_KEY" not in agent_env
