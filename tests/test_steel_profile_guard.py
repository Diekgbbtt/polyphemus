"""The profile-mount reference refuses a runtime without a profile store (#395).

Seam under test: `skills/steel-browser/references/profile-mount.sh`. The local
OSS API has no `/v1/profiles`, and a create with `profileId` silently succeeds
without mounting anything. The script probes the route and must refuse instead
of reporting a false mount.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "internal" / "tools" / "steel-browser" / "references" / "profile-mount.sh"


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def test_profile_mount_refuses_a_runtime_with_no_profile_store(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir / "curl", "printf 404\n")
    calls = tmp_path / "steel-calls.log"
    _stub(bindir / "steel", f'printf "%s\\n" "$*" >> "{calls}"\n')

    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "STEEL_BROWSER_API_URL": "http://steel.test:3000/v1",
        "STEEL_API_KEY": "dummy",
        "PROFILE": "ph-test",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "no profile store" in result.stderr
    assert "sessionContext" in result.stderr
    assert not calls.exists() or calls.read_text() == ""
