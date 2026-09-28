"""Structural validation of the delivery workflow (`.github/workflows/deploy-eval.yml`).

PyYAML is available in the repo venv (it is used by `test_eval_overlay.py`), so
this parses the workflow rather than scraping text for everything except the
secret interpolations, which are easiest to assert literally.

Asserts the ticket #268 acceptance surface: the triggers (push on `dev` plus
`workflow_dispatch`), the three required secrets, `permissions: contents: read`,
and the absence of any `eval` branch reference (the workflow may only ever
touch `dev`).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-eval.yml"

REQUIRED_SECRETS = ("EVAL_SSH_KEY", "EVAL_HOST", "EVAL_SSH_KNOWN_HOSTS")


def load() -> tuple[dict, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    # PyYAML resolves the bare `on:` key to boolean True (YAML 1.1). Keep the
    # raw mapping so assertions are on the document, not on a coincidence.
    return yaml.safe_load(text), text


def triggers(doc: dict) -> dict:
    on = doc.get("on", doc.get(True))
    assert isinstance(on, dict), f"workflow has no mapping triggers: {on!r}"
    return on


def test_triggers_on_push_to_dev_and_manual_dispatch() -> None:
    doc, _ = load()
    on = triggers(doc)

    assert "workflow_dispatch" in on
    push = on["push"]
    branches = push["branches"]
    assert "dev" in branches
    assert branches == ["dev"], branches


def test_permissions_are_read_only() -> None:
    doc, _ = load()
    assert doc["permissions"] == {"contents": "read"}


def test_references_the_three_required_secrets() -> None:
    _, text = load()
    for name in REQUIRED_SECRETS:
        assert f"secrets.{name}" in text, f"{name} is not referenced"


def test_never_references_the_eval_branch() -> None:
    doc, text = load()

    # Git-ref syntax that would reach the `eval` branch. Natural-language
    # mentions of the eval server are fine; a branch REF is not.
    forbidden = (
        r"refs/heads/eval\b",
        r"\borigin/eval\b",
        r"--branch[= ]eval\b",
        r"\bgit\b[^\n]*\beval\b",
        r"\bcheckout\b[^\n]*\beval\b",
        r"branches:\s*[^\n]*\beval\b",
    )
    for pattern in forbidden:
        assert not re.search(pattern, text), f"workflow references eval: /{pattern}/"

    # No branch list anywhere in the document may name `eval`.
    on = triggers(doc)
    for event in on.values():
        if isinstance(event, dict) and "branches" in event:
            assert "eval" not in event["branches"]


def test_invokes_the_script_over_ssh_with_host_key_verification() -> None:
    _, text = load()

    assert "eval/deploy/ff_dev.sh" in text
    assert "BatchMode=yes" in text
    assert "StrictHostKeyChecking=yes" in text
    assert "EVAL_SSH_KNOWN_HOSTS" in text
