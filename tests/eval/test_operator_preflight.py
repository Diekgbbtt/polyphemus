"""The host-side operator preflight (operator dashboard, Task 4).

Before the documented Compose startup, the operator runs
`python -m operator_api.preflight` with `EVAL_WEB_DIR_HOST_PATH` set. It checks
that the path is absolute and exists as a directory, and never creates it: a
typo must fail loudly rather than silently mounting an empty checkout.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from operator_api import preflight

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "eval"


def _run(cwd: Path, env: dict[str, str] | None) -> subprocess.CompletedProcess:
    child = {k: v for k, v in os.environ.items() if k != "EVAL_WEB_DIR_HOST_PATH"}
    child["PYTHONPATH"] = str(EVAL_DIR)
    child.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "operator_api.preflight"],
        cwd=cwd,
        env=child,
        capture_output=True,
        text=True,
    )


def test_existing_absolute_checkout_passes(tmp_path: Path) -> None:
    checkout = tmp_path / "WebExploitBench"
    checkout.mkdir()

    result = _run(tmp_path, {"EVAL_WEB_DIR_HOST_PATH": str(checkout)})

    assert result.returncode == 0, result.stderr


def test_missing_variable_fails(tmp_path: Path) -> None:
    result = _run(tmp_path, None)

    assert result.returncode != 0
    assert "EVAL_WEB_DIR_HOST_PATH" in result.stderr


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_variable_fails(value: str, tmp_path: Path) -> None:
    result = _run(tmp_path, {"EVAL_WEB_DIR_HOST_PATH": value})

    assert result.returncode != 0
    assert "EVAL_WEB_DIR_HOST_PATH" in result.stderr


def test_relative_path_fails_without_creating_it(tmp_path: Path) -> None:
    result = _run(tmp_path, {"EVAL_WEB_DIR_HOST_PATH": "WebExploitBench"})

    assert result.returncode != 0
    assert "EVAL_WEB_DIR_HOST_PATH" in result.stderr
    assert not (tmp_path / "WebExploitBench").exists()


def test_nonexistent_absolute_path_fails_without_creating_it(tmp_path: Path) -> None:
    absent = tmp_path / "absent" / "WebExploitBench"

    result = _run(tmp_path, {"EVAL_WEB_DIR_HOST_PATH": str(absent)})

    assert result.returncode != 0
    assert "EVAL_WEB_DIR_HOST_PATH" in result.stderr
    assert not absent.exists()
    assert not absent.parent.exists()


def test_a_file_instead_of_a_directory_fails(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "checkout.txt"
    not_a_dir.write_text("not a checkout", encoding="utf-8")

    result = _run(tmp_path, {"EVAL_WEB_DIR_HOST_PATH": str(not_a_dir)})

    assert result.returncode != 0
    assert "EVAL_WEB_DIR_HOST_PATH" in result.stderr


def test_main_reports_its_outcome_as_an_int(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVAL_WEB_DIR_HOST_PATH", raising=False)
    assert isinstance(preflight.main(), int)
    assert preflight.main() != 0

    checkout = tmp_path / "WebExploitBench"
    checkout.mkdir()
    monkeypatch.setenv("EVAL_WEB_DIR_HOST_PATH", str(checkout))
    assert preflight.main() == 0


def test_preflight_never_prints_the_host_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    absent = tmp_path / "absent-checkout"
    monkeypatch.setenv("EVAL_WEB_DIR_HOST_PATH", str(absent))

    assert preflight.main() != 0

    captured = capsys.readouterr()
    assert str(absent) not in captured.err + captured.out
