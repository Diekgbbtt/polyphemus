"""#238 B1/B7 - the committed stack-lifecycle script contract."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "issue_238_e2e_stack.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_stack_script_exists_is_executable_and_pins_the_project_and_files():
    assert SCRIPT.exists(), "the stack lifecycle script must be committed"
    assert os.access(SCRIPT, os.X_OK), "the script must be executable"
    text = _text()
    assert "polyphemus-238-e2e" in text
    assert "docker-compose.yml" in text and "docker-compose.e2e.yml" in text
    assert "18080" in text
    # Never a global prune or a destructive remove beyond this project.
    for forbidden in ("docker system prune", "docker volume prune", "docker rm -f"):
        assert forbidden not in text, forbidden


def test_stack_script_refuses_unknown_verbs():
    assert "exit 64" in _text()


def test_stack_script_owns_the_twice_gate_and_drops_the_retired_selectors():
    text = _text()
    # The twice gate hard-resets between runs and asserts a clean state first.
    assert "gate_twice" in text and "run-a" in text and "run-b" in text
    assert text.count("assert_clean") >= 2
    # The functional gate is the LLM Configurator's live E2E.
    assert "test_llm_rate_aware_recon_configurator_e2e.py" in text
    # The deterministic-admission and recon-armed-governor selectors were
    # retired with the mechanisms they certified; a dangling selector or a
    # reference to a deleted gate file would be a script that lies about the
    # tier it runs.
    for retired in (
        "up-stale", "gate-stale", "gate-properties",
        "up_stale", "gate_stale", "gate_properties",
        "test_rate_limit_admission_e2e.py",
        "test_rate_limit_enforcement_properties_e2e.py",
    ):
        assert retired not in text, retired
