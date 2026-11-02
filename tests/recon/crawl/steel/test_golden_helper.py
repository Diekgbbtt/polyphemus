"""Seam under test: the golden-file comparison helper.

A later manifest writer or parser compares its value to a checked-in file and
gets a readable diff when the two disagree, instead of an opaque inequality.
"""
from __future__ import annotations

import json

import pytest

from tests.recon.crawl.steel.fixtures import GOLDEN_ROOT
from tests.recon.crawl.steel.support import assert_matches_golden

JSON_GOLDEN = GOLDEN_ROOT / "crawl_summary.json"
TEXT_GOLDEN = GOLDEN_ROOT / "crawl_summary.txt"


def test_json_value_matches_checked_in_golden():
    assert_matches_golden({"pages": 2, "actions": 4, "flows": 3}, JSON_GOLDEN)


def test_json_text_matches_checked_in_golden_ignoring_order_and_formatting():
    assert_matches_golden(json.dumps({"flows": 3, "actions": 4, "pages": 2}), JSON_GOLDEN)


def test_text_value_matches_checked_in_golden():
    assert_matches_golden("pages: 2\nactions: 4\nflows: 3", TEXT_GOLDEN)


def test_json_mismatch_shows_a_readable_diff():
    with pytest.raises(AssertionError) as excinfo:
        assert_matches_golden({"pages": 2, "actions": 5, "flows": 3}, JSON_GOLDEN)

    message = str(excinfo.value)
    assert "golden mismatch" in message
    assert '-  "actions": 4' in message
    assert '+  "actions": 5' in message


def test_text_mismatch_shows_a_readable_diff():
    with pytest.raises(AssertionError) as excinfo:
        assert_matches_golden("pages: 2\nactions: 5\nflows: 3", TEXT_GOLDEN)

    message = str(excinfo.value)
    assert "-actions: 4" in message
    assert "+actions: 5" in message


def test_missing_golden_file_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError, match="missing.json"):
        assert_matches_golden({"pages": 2}, tmp_path / "missing.json")
