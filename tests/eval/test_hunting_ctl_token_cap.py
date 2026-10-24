"""The eval client's token-cap stopper (the 7M trial budget guard).

`hunting_ctl monitor --token-cap` polls the project's cumulative `capped_tokens`
- the same budget axis `eval/orchestrator/trial.py` enforces - and issues the
API stop when the cap is reached. The predicate is pure so the boundary rows
are testable without a live app.
"""
from __future__ import annotations

import hunting_ctl


def test_token_cap_is_not_reached_below_the_cap() -> None:
    assert hunting_ctl.token_cap_reached(6_999_999, 0, 7_000_000) is False


def test_token_cap_is_reached_at_the_cap() -> None:
    assert hunting_ctl.token_cap_reached(7_000_000, 0, 7_000_000) is True


def test_token_cap_is_reached_above_the_cap() -> None:
    assert hunting_ctl.token_cap_reached(7_000_001, 0, 7_000_000) is True


def test_token_cap_uses_the_baseline_as_a_delta() -> None:
    assert hunting_ctl.token_cap_reached(3_400_000, 3_000_000, 500_000) is False
    assert hunting_ctl.token_cap_reached(3_500_000, 3_000_000, 500_000) is True


def test_an_unreachable_usage_read_never_stops() -> None:
    """A transport or parse failure is not an exhausted budget."""
    assert hunting_ctl.token_cap_reached(None, 0, 7_000_000) is False


def test_a_disabled_cap_never_stops() -> None:
    assert hunting_ctl.token_cap_reached(99_000_000, 0, 0) is False
    assert hunting_ctl.token_cap_reached(99_000_000, 0, None) is False


def test_the_hunting_terminal_set_matches_the_api_vocabulary() -> None:
    assert set(hunting_ctl.HUNTING_TERMINAL) == {
        "complete", "stopped", "failed", "interrupted"}
