"""Unit tests for the `steel` CLI scaffold (#395).

The scaffold stands in for the pinned binary in the host unit and mocked-e2e
tiers. These assertions pin its fidelity to the envelopes
`skills/steel-browser/SKILL.md` documents, and to the clap variadic fold the
D19 boundary guards against.
"""
from __future__ import annotations

import json
import shlex
import subprocess

import pytest

from tests.support import steel_cli_scaffold as scaffold


def _run(text: str, *, code: int = 0) -> dict | list:
    result = subprocess.run(
        shlex.split(text), capture_output=True, text=True, timeout=30
    )
    assert result.returncode == code, (result.stdout, result.stderr)
    return json.loads(result.stdout)


@pytest.fixture()
def steel(tmp_path, monkeypatch):
    return scaffold.install(tmp_path, monkeypatch)


def test_version_names_the_pinned_cli(steel):
    result = subprocess.run(["steel", "--version"], capture_output=True, text=True)
    assert result.stdout.strip() == "steel 0.5.0-preview.6"


def test_catalogue_is_empty_before_a_start_and_lists_the_session_after(steel):
    assert _run("steel browser sessions --json") == {"data": [], "success": True}
    start = _run("steel browser start --session s1 --session-timeout 600000 --json")
    assert start["success"] is True
    data = start["data"]
    assert set(data) == {"connectUrl", "id", "inactivityTimeoutMs", "liveUrl",
                         "mode", "name", "remainingMs"}
    assert data["name"] == "s1" and data["remainingMs"] > 0
    listed = _run("steel browser sessions --json")["data"]
    assert [s["name"] for s in listed] == ["s1"]
    assert set(listed[0]) == {"id", "mode", "name", "status", "viewerUrl"}


def test_start_attaches_to_a_live_name(steel):
    first = _run("steel browser start --session s1 --json")["data"]
    second = _run("steel browser start --session s1 --json")["data"]
    assert first["id"] == second["id"]


def test_stop_clears_the_catalogue(steel):
    _run("steel browser start --session s1 --json")
    stopped = _run("steel browser stop --session s1 --json")
    assert stopped == {"data": {"stoppedSessions": ["s1"]}, "success": True}
    assert _run("steel browser sessions --json") == {"data": [], "success": True}


def test_an_operation_on_a_missing_session_is_a_typed_error(steel):
    result = subprocess.run(
        ["steel", "browser", "navigate", "https://example.com", "--session", "nope", "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["success"] is False and "nope" in payload["error"]


def test_navigate_sets_the_document(steel):
    _run("steel browser start --session s1 --json")
    nav = _run("steel browser navigate https://example.com --session s1 --json")
    assert nav == {"data": {"title": "Example Domain", "url": "https://example.com"},
                   "success": True}
    assert _run("steel browser get title --session s1 --json")["data"] == "Example Domain"
    assert _run("steel browser get url --session s1 --json")["data"] == "https://example.com"


def test_variadic_boundary_keeps_the_value_verbatim(steel):
    _run("steel browser start --session s1 --json")
    _run("steel browser fill --session s1 --json '#user' -- 'standard_user'")
    assert _run("steel browser get value '#user' --session s1 --json")["data"]["value"] == "standard_user"


def test_a_flag_after_the_selector_folds_into_the_value(steel):
    # The D19 defect: clap stops option parsing at the first positional, so a
    # trailing flag becomes part of the VALUE behind success:true.
    _run("steel browser start --session s1 --json")
    _run("steel browser fill --session s1 '#user' 'standard_user' --json")
    assert _run("steel browser get value '#user' --session s1 --json")["data"]["value"] == "standard_user --json"


def test_batch_inherits_the_session_and_returns_results(steel):
    _run("steel browser start --session s1 --json")
    batch = _run(
        "steel browser batch --session s1 --json -- 'snapshot -i' 'fill @e7 -- 42'"
    )
    results = batch["data"]["results"]
    assert batch["success"] is True
    assert [r["success"] for r in results] == [True, True]
    assert results[1]["data"] == {"filled": "@e7"}


def test_batch_op_failure_writes_results_then_an_error_line(steel):
    _run("steel browser start --session s1 --json")
    result = subprocess.run(
        ["steel", "browser", "batch", "--session", "s1", "--json", "--", "get title", "get nope"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    lines = result.stdout.strip().splitlines()
    assert "results" in json.loads(lines[0])["data"]
    assert json.loads(lines[1])["error"] == "One or more batch commands failed"


def test_scrape_and_profile_families_are_sessionless(steel):
    scrape = _run("steel scrape https://example.com --format markdown --json")
    assert scrape["data"]["metadata"]["title"] == "Example Domain"
    assert "Example Domain" in scrape["data"]["content"]["markdown"]
    assert _run("steel profile list --json") == {"data": [], "success": True}


def test_eval_reads_the_document(steel):
    _run("steel browser start --session s1 --json")
    _run("steel browser navigate https://example.com --session s1 --json")
    assert _run("steel browser eval 'document.title' --session s1 --json")["data"] == "Example Domain"
