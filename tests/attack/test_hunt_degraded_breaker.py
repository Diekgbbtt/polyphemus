"""Part 2 (#280): the consecutive-degradation circuit breaker in the hunt pass.

The coupled gap to the parsing-error fix: when phase turns keep returning a
no-decision (None) outcome, the pass driver used to fail-open each pair and move
on at full speed, so a poisoned actor thread became a hot loop at ~4s per pair.
The breaker counts CONSECUTIVE no-decision turn outcomes across the phase's
pairs (reset on any real decision), applies a bounded exponential backoff, and
aborts the pass with a typed, operator-visible failure after K - without ever
silently pruning a pair below the threshold (D67-11).
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting.hunt_orchestrator import (
    DegradedTurnBreaker,
    DeliveredCandidate,
    EnvisionedDirection,
    GateDecision,
    HuntOrchestrationDegradedError,
    NoteDecision,
    NoteRecord,
    OrchestratorTools,
    RatifyDecision,
    ReadOnlyGraphView,
    Witness,
    revival_key,
    run_orchestration,
)


class _MemoryStore:
    def __init__(self):
        self._configs: list[dict] = []
        self._notes: list[dict] = []

    def write_config(self, project_id, config):
        data = config.model_dump() if not isinstance(config, dict) else dict(config)
        self._configs.append(data)
        return f"{data.get('unit_id')}::{data.get('fault_class')}::{data.get('vulnerability_class')}"

    def update_config(self, project_id, config):
        self._configs.append(
            config.model_dump() if not isinstance(config, dict) else dict(config))
        return "k"

    def append_note(self, project_id, key, note):
        self._notes.append({"revival_key": key, "note": note})
        return {"note_id": f"n{len(self._notes)}", "revival_key": key, "note": note}

    def read_configs_by_key(self, project_id, key):
        return []

    def read_notes(self, project_id, key=None):
        return []

    def read_hunter_specs(self, project_id, key):
        return []

    def read_hunter_notes(self, project_id, key):
        return []


def _candidate(unit_id: str) -> DeliveredCandidate:
    return DeliveredCandidate(
        unit_id=unit_id, fault_class="fault-x",
        applies_witnesses=Witness(deterministic=None, llm="witness"),
        match_verdict="applies",
    )


def _carry(candidate: DeliveredCandidate) -> EnvisionedDirection:
    return EnvisionedDirection(unit_id=candidate.unit_id,
                               fault_class=candidate.fault_class, carried=True,
                               rationale="r")


def _ratify(inp) -> RatifyDecision:
    configs = []
    for draft in inp.configs:
        amended = draft.model_copy(deep=True)
        amended.status = "ratified"
        configs.append(amended)
    return RatifyDecision(configs=configs)


def _note(inp) -> NoteDecision:
    return NoteDecision(notes=[NoteRecord(
        key=revival_key(inp.pair.unit_id, inp.pair.fault_class), note="n")])


def _run(candidates, *, hypothesise, ratify=_ratify, note=_note):
    return run_orchestration(
        project_id="p", run_id="r", candidates=candidates,
        tools=OrchestratorTools(
            store_reads=_MemoryStore(),
            graph_view=ReadOnlyGraphView("p", read_fn=lambda cy, p: [])),
        hypothesise_fn=hypothesise, ratify_fn=ratify, note_fn=note,
    )


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

    async def _run():
        breaker = DegradedTurnBreaker(backoff_base_s=1.0, backoff_max_s=3.0,
                                      warn_streak=2, abort_streak=9,
                                      sleep=fake_sleep)
        for _ in range(5):
            breaker.record_outcome("hypothesise", None)
            await breaker.before_turn("hypothesise")

    asyncio.run(_run())
    # Below the warn threshold there is no sleep; then 1s, 2s, capped at 3s.
    assert slept == [1.0, 2.0, 3.0, 3.0]


def test_breaker_resets_on_a_real_decision():
    breaker = DegradedTurnBreaker(backoff_base_s=0.0, backoff_max_s=1.0,
                                  warn_streak=1, abort_streak=3)
    breaker.record_outcome("h", None)
    breaker.record_outcome("h", None)
    breaker.record_outcome("h", GateDecision())   # a real decision resets
    breaker.record_outcome("h", None)
    breaker.record_outcome("h", None)
    assert breaker.streak == 2  # no abort: the counter was reset


def test_breaker_aborts_at_the_threshold():
    breaker = DegradedTurnBreaker(backoff_base_s=0.0, backoff_max_s=1.0,
                                  warn_streak=1, abort_streak=2)
    breaker.record_outcome("hypothesise", None)
    with pytest.raises(HuntOrchestrationDegradedError) as exc:
        breaker.record_outcome("hypothesise", None)
    assert exc.value.streak == 2
    assert exc.value.phase == "hypothesise"


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
    with pytest.raises(HuntOrchestrationDegradedError) as exc:
        breaker.record_outcome("hypothesise", None, cause=_rate_limit())
    assert exc.value.provider_cause is True


def test_breaker_marks_a_generic_abort_as_not_provider_caused():
    breaker = DegradedTurnBreaker(backoff_base_s=0.0, backoff_max_s=1.0,
                                  warn_streak=1, abort_streak=1)
    with pytest.raises(HuntOrchestrationDegradedError) as exc:
        breaker.record_outcome("hypothesise", None, cause=ValueError("parse failure"))
    assert exc.value.provider_cause is False


def test_pass_abort_from_a_raising_provider_seam_is_provider_caused(monkeypatch):
    """A phase seam that raises a 429 degrades that turn and marks the abort
    provider-caused, so the runtime can pause the run instead of failing it."""
    _set_breaker_env(monkeypatch, abort=2, warn=1, base=0.0)
    candidates = [_candidate(f"Service:slug:{c}") for c in "ab"]

    def hypothesise(inp):
        raise _rate_limit()

    with pytest.raises(HuntOrchestrationDegradedError) as exc:
        _run(candidates, hypothesise=hypothesise)
    assert exc.value.provider_cause is True


# --- the pass ----------------------------------------------------------------

def test_pass_aborts_after_k_consecutive_no_decision_turns(monkeypatch):
    _set_breaker_env(monkeypatch, abort=3, warn=1, base=0.0)
    candidates = [_candidate(f"Service:slug:{c}") for c in "abcdef"]
    with pytest.raises(HuntOrchestrationDegradedError) as exc:
        _run(candidates, hypothesise=lambda inp: None)
    assert exc.value.streak == 3


def test_pass_a_real_decision_resets_consecutive_failures(monkeypatch):
    _set_breaker_env(monkeypatch, abort=2, warn=1, base=0.0)
    candidates = [_candidate(f"Service:slug:{c}") for c in "abc"]
    calls = {"n": 0}

    def hypothesise(inp):
        calls["n"] += 1
        if calls["n"] == 2:
            return GateDecision(directions=[_carry(inp.candidates[0])])
        return None

    # Sequence None, real, None: with reset pair 3 is streak 1 (no abort).
    report = _run(candidates, hypothesise=hypothesise)
    assert report.pairs_processed == 3


def test_per_pair_fail_open_below_the_threshold_is_unchanged(monkeypatch):
    _set_breaker_env(monkeypatch, abort=5, warn=2, base=0.0)
    candidates = [_candidate(f"Service:slug:{c}") for c in "ab"]
    calls = {"n": 0}

    def hypothesise(inp):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # one degraded pair, still below the threshold
        return GateDecision(directions=[_carry(c) for c in inp.candidates])

    report = _run(candidates, hypothesise=hypothesise)
    assert report.pairs_processed == 2
    assert report.ledger.units_skipped == 1


def test_breaker_backoff_sleeps_between_degraded_turns(monkeypatch):
    _set_breaker_env(monkeypatch, abort=9, warn=1, base=0.01, cap=1.0)
    candidates = [_candidate(f"Service:slug:{c}") for c in "abcd"]
    slept: list[float] = []
    real_sleep = asyncio.sleep

    async def recording_sleep(delay):
        slept.append(delay)
        await real_sleep(0)

    import polymerhus.attack.hunting.hunt_orchestrator as H
    monkeypatch.setattr(H.asyncio, "sleep", recording_sleep)
    _run(candidates, hypothesise=lambda inp: None)
    assert slept and all(d >= 0 for d in slept)
    assert slept[-1] > slept[0]
