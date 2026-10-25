"""Part 2 (#280): the consecutive-degradation circuit breaker in the modeller
pass (retired from the planner in T2b, #386).

The coupled gap to the parsing-error fix: when turns keep returning a
no-decision outcome, the pass used to fail-open each state and move on at full
speed, so a poisoned actor thread became a hot threat. The breaker counts
CONSECUTIVE no-decision turn outcomes (reset on any real gate write), applies a
bounded exponential backoff, and aborts the pass with a typed,
operator-visible failure after K - without ever fabricating a model below the
threshold.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import (
    DegradedTurnBreaker,
    ThreatModellerDegradedError,
    arun_modeller_pass,
)
from polymerhus.attack.hunting.threat_modeller_tools import ModellerTools

from tests.hunting_fixtures import modeller_gate_payloads

PROJECT = "p"
RUN = "r"
UNIT = "Service:slug:a"


def _tools(tmp_path, **kwargs) -> ModellerTools:
    return ModellerTools(threat_store=ThreatModelStore(root_dir=tmp_path),
                         project_id=PROJECT, run_id=RUN, **kwargs)


def _gate_writer(turn, store):
    """The turn seam's real-decision action: the BOUND store tool's gate write.

    The well-formedness pseudo-phase writes its exit note and the COMPLETED
    gate, so a seam that writes every turn never re-enters the phase."""
    tool = next(t for t in turn.tools if t.name == "hunts_store")
    if turn.phase == "WELLFORMEDNESS":
        notes = next(t for t in turn.tools if t.name == "notes")
        notes.invoke({
            "cmd": "write", "option": "append",
            "note_name": "wellformedness", "kind": "wellformedness",
            "body": "every threat checked",
        })
        from polymerhus.attack.hunting.threat_model import ModelState
        return tool.invoke({
            "cmd": "write", "state": ModelState.COMPLETED.value,
            "sections": modeller_gate_payloads()[ModelState.COMPLETED],
        })
    return tool.invoke({
        "cmd": "write", "state": turn.state.value,
        "sections": modeller_gate_payloads()[turn.state],
    })


def _run(tmp_path, turns):
    return asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT, _tools(tmp_path), turn_fn=turns))


def _set_breaker_env(monkeypatch, *, abort, warn=1, base=0.0, cap=30.0):
    monkeypatch.setenv("HUNT_TURN_DEGRADED_STREAK_ABORT", str(abort))
    monkeypatch.setenv("HUNT_TURN_DEGRADED_STREAK_WARN", str(warn))
    monkeypatch.setenv("HUNT_TURN_DEGRADED_BACKOFF_BASE_S", str(base))
    monkeypatch.setenv("HUNT_TURN_DEGRADED_BACKOFF_MAX_S", str(cap))


# --- the breaker unit --------------------------------------------------------

def test_breaker_backoff_is_exponential_and_bounded():
    slept: list[float] = []

    async def fake_sleep(delay):
        slept.append(delay)

    async def _run_breaker():
        breaker = DegradedTurnBreaker(backoff_base_s=1.0, backoff_max_s=3.0,
                                      warn_streak=2, abort_streak=9,
                                      sleep=fake_sleep)
        for _ in range(5):
            breaker.record_outcome("UNIT_TECHNICAL_SHARP", None)
            await breaker.before_turn("UNIT_TECHNICAL_SHARP")

    asyncio.run(_run_breaker())
    # Below the warn threshold there is no sleep; then 1s, 2s, capped at 3s.
    assert slept == [1.0, 2.0, 3.0, 3.0]


def test_breaker_resets_on_a_real_decision():
    breaker = DegradedTurnBreaker(backoff_base_s=0.0, backoff_max_s=1.0,
                                  warn_streak=1, abort_streak=3)
    breaker.record_outcome("h", None)
    breaker.record_outcome("h", None)
    breaker.record_outcome("h", True)   # a real gate write resets
    breaker.record_outcome("h", None)
    breaker.record_outcome("h", None)
    assert breaker.streak == 2  # no abort: the counter was reset


def test_breaker_aborts_at_the_threshold():
    breaker = DegradedTurnBreaker(backoff_base_s=0.0, backoff_max_s=1.0,
                                  warn_streak=1, abort_streak=2)
    breaker.record_outcome("TRUST_MODELLED", None)
    with pytest.raises(ThreatModellerDegradedError) as exc:
        breaker.record_outcome("TRUST_MODELLED", None)
    assert exc.value.streak == 2
    assert exc.value.state == "TRUST_MODELLED"


# --- #329: the abort carries the provider cause -------------------------------

def _rate_limit():
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.example.test/v1")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError("Rate limit exceeded", response=response, body=None)


def test_breaker_marks_a_provider_caused_abort():
    breaker = DegradedTurnBreaker(backoff_base_s=0.0, backoff_max_s=1.0,
                                  warn_streak=1, abort_streak=1)
    with pytest.raises(ThreatModellerDegradedError) as exc:
        breaker.record_outcome("TRUST_MODELLED", None, cause=_rate_limit())
    assert exc.value.provider_cause is True
    # #331: the typed error rides the abort, so the runtime can record the
    # status/quota class on the interrupted run (not just a boolean).
    assert exc.value.provider_error is not None
    assert exc.value.provider_error.status_code == 429


def test_breaker_marks_a_generic_abort_as_not_provider_caused():
    breaker = DegradedTurnBreaker(backoff_base_s=0.0, backoff_max_s=1.0,
                                  warn_streak=1, abort_streak=1)
    with pytest.raises(ThreatModellerDegradedError) as exc:
        breaker.record_outcome("TRUST_MODELLED", None,
                               cause=ValueError("parse failure"))
    assert exc.value.provider_cause is False
    assert exc.value.provider_error is None


# --- the pass ----------------------------------------------------------------

def test_pass_abort_from_a_raising_provider_seam_is_provider_caused(
        tmp_path, monkeypatch):
    """A turn seam that raises a 429 degrades that turn and marks the abort
    provider-caused, so the runtime can pause the run instead of failing it."""
    _set_breaker_env(monkeypatch, abort=2, warn=1, base=0.0)

    def turns(turn):
        raise _rate_limit()

    with pytest.raises(ThreatModellerDegradedError) as exc:
        _run(tmp_path, turns)
    assert exc.value.provider_cause is True


def test_pass_aborts_after_k_consecutive_no_decision_turns(tmp_path, monkeypatch):
    _set_breaker_env(monkeypatch, abort=3, warn=1, base=0.0)

    with pytest.raises(ThreatModellerDegradedError) as exc:
        _run(tmp_path, lambda turn: None)
    assert exc.value.streak == 3


def test_pass_a_real_decision_resets_consecutive_failures(tmp_path, monkeypatch):
    """None, gate, None, None, None: the gate write resets the counter, so with
    abort=4 the two later no-decisions stay below the threshold and the pass
    returns instead of aborting."""
    _set_breaker_env(monkeypatch, abort=4, warn=1, base=0.0)
    store = ThreatModelStore(root_dir=tmp_path)
    seen: list[ModelState] = []

    def turns(turn):
        seen.append(turn.state)
        if turn.state == ModelState.TRUST_MODELLED:
            _gate_writer(turn, store)
        return None

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT,
        ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN),
        turn_fn=turns))

    assert len(seen) == len(ModelState)     # every state was asked
    assert outcome.status == "degraded"     # never fabricated a completion


def test_per_state_fail_open_below_the_threshold_is_unchanged(tmp_path,
                                                              monkeypatch):
    """One degraded state below the threshold: the pass keeps going and the
    later gates still land. The skipped sharpening gate leaves the model
    incomplete, so the completion check reports it - never a fabricated
    completion and never an abort."""
    _set_breaker_env(monkeypatch, abort=5, warn=2, base=0.0)
    store = ThreatModelStore(root_dir=tmp_path)

    def turns(turn):
        if turn.state == ModelState.UNIT_TECHNICAL_SHARP:
            return None                      # one degraded state
        _gate_writer(turn, store)
        return None

    outcome = asyncio.run(arun_modeller_pass(
        PROJECT, RUN, UNIT,
        ModellerTools(threat_store=store, project_id=PROJECT, run_id=RUN),
        turn_fn=turns))

    assert outcome.status == "degraded"
    assert outcome.state == ModelState.COMPLETED.value
    assert "technical_sharpening" in outcome.reason


def test_breaker_backoff_sleeps_between_degraded_turns(tmp_path, monkeypatch):
    _set_breaker_env(monkeypatch, abort=9, warn=1, base=0.01, cap=1.0)
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay):
        slept.append(delay)
        await real_sleep(0)

    import polymerhus.attack.hunting.threat_modeller as tm
    monkeypatch.setattr(tm.asyncio, "sleep", recording_sleep)
    _run(tmp_path, lambda turn: None)
    assert slept and all(d >= 0 for d in slept)
    assert slept[-1] > slept[0]
