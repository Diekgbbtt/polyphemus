"""Contract test for the shipped systemd unit and its configuration surface.

The unit and the env template are the daemon's deploy artifacts. This pins the
two things that silently break a deploy: the ExecStart must invoke the daemon
module from a working directory where `advance` is importable, and every
environment variable `load_config_from_env` reads must be documented in the
template.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from advance import daemon

SYSTEMD_DIR = Path(__file__).resolve().parents[2] / "eval" / "advance" / "systemd"


def test_service_invokes_the_daemon_module_and_loads_the_env_file() -> None:
    service = (SYSTEMD_DIR / "eval-advance.service").read_text(encoding="utf-8")

    assert "ExecStart=" in service and "-m advance.daemon run" in service
    assert "WorkingDirectory=" in service
    assert "EnvironmentFile=" in service
    assert "Restart=" in service


def test_env_template_documents_every_configuration_variable() -> None:
    template = (SYSTEMD_DIR / "eval-advance.env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"EVAL_ADVANCE_[A-Z_]+", template))

    # S8: derive the expected set from the code, not a hand-maintained literal,
    # so a new variable read by the loader cannot ship undocumented.
    expected = set(
        re.findall(r"EVAL_ADVANCE_[A-Z_]+", inspect.getsource(daemon.load_config_from_env))
    )
    assert expected, "no EVAL_ADVANCE_* variables found in load_config_from_env"
    assert expected <= documented


def test_install_note_documents_the_operator_rewind() -> None:
    readme = (SYSTEMD_DIR / "README.md").read_text(encoding="utf-8")

    assert "rewind" in readme
    assert "--confirm" in readme
    assert "last-known-good" in readme.lower()
