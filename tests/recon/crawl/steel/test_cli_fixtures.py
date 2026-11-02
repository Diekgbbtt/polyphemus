"""Seam under test: the fixture-pack loaders.

Every later steel-crawl ticket loads its inputs from this pack instead of
hand-writing JSON in each test. The loaders return typed records, so a
malformed fixture fails at load time with the file path in the message.
"""
from __future__ import annotations

import json

import pytest

from tests.recon.crawl.steel.fixtures import CliEnvelope, FixtureError, load_cli

CLI_VERBS = [
    "session",
    "catalogue",
    "navigate",
    "snapshot",
    "click",
    "fill",
    "select",
    "press",
    "eval",
    "stop",
]


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_cli_returns_a_typed_envelope():
    envelope = load_cli("session")

    assert isinstance(envelope, CliEnvelope)
    assert envelope.success is True
    assert envelope.data["name"] == "crawl-fixture"


@pytest.mark.parametrize("verb", CLI_VERBS)
def test_every_cli_verb_has_a_loadable_envelope(verb):
    envelope = load_cli(verb)

    assert isinstance(envelope, CliEnvelope)
    assert envelope.success is True


def test_missing_cli_fixture_fails_loudly():
    with pytest.raises(FixtureError, match="not found"):
        load_cli("does-not-exist")


def test_invalid_json_fails_loudly(tmp_path):
    _write(tmp_path / "cli" / "broken.json", "{not json")

    with pytest.raises(FixtureError, match="broken.json") as excinfo:
        load_cli("broken", root=tmp_path)

    assert "valid JSON" in str(excinfo.value)


def test_envelope_with_wrong_shape_fails_loudly(tmp_path):
    _write(tmp_path / "cli" / "wrong.json", json.dumps({"data": {}}))

    with pytest.raises(FixtureError, match="CliEnvelope") as excinfo:
        load_cli("wrong", root=tmp_path)

    assert "success" in str(excinfo.value)
