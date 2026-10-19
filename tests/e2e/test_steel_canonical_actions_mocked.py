"""Mocked e2e: the skill's canonical action scripts against the CLI scaffold.

The real `steel_exec` script path runs the unmodified reference scripts from
`skills/steel-browser/references/` with the scaffold on PATH, so the scripts'
command encodings, catalogue guards, batch envelopes, read-backs, and
trap-owned stop are exercised end to end with no docker, no browser, and no
cloud key. The scaffold models the skill's documented envelopes and the clap
variadic fold, so a mis-encoded command is observable.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import kali.mcp_server as m
from tests.support import steel_cli_scaffold as scaffold

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCES = REPO_ROOT / "skills" / "steel-browser" / "references"

STEEL_EXEC = m.steel_exec.fn


def _steel_exec(**kwargs):
    return asyncio.run(STEEL_EXEC(**kwargs))


@pytest.fixture()
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setenv("KALI_WORKDIR", str(root))
    return root


@pytest.fixture()
def steel(tmp_path, monkeypatch):
    return scaffold.install(tmp_path, monkeypatch)


def _script(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def test_session_lifecycle_reference_releases_its_session(workroot, steel):
    out = _steel_exec(
        script=_script("session-lifecycle.sh"), script_lang="sh", session_id="e2e-lifecycle"
    )
    assert out["returncode"] == 0, out
    assert "lifecycle complete" in out["stdout"]
    assert "released: True" in out["stdout"]
    assert scaffold.read_state(steel)["sessions"] == {}


def test_interact_batch_reference_lands_the_value_and_releases(workroot, steel):
    out = _steel_exec(
        script=_script("interact-batch.sh"), script_lang="sh", session_id="e2e-interact"
    )
    assert out["returncode"] == 0, out
    assert "batch success: True" in out["stdout"]
    assert "entry landed: True" in out["stdout"]
    assert "interaction complete" in out["stdout"]
    assert scaffold.read_state(steel)["sessions"] == {}


def test_catalogue_reference_reads_both_families(workroot, steel):
    out = _steel_exec(
        script=_script("catalogue.sh"), script_lang="sh", session_id="e2e-catalogue"
    )
    assert out["returncode"] == 0, out
    assert "live sessions: 0" in out["stdout"]
