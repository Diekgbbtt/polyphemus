"""Unit tier: the hunting module's LLM bootstrap + role wiring (`attack/hunting/llm.py`, #94).

The hunting roles (`hunting_orchestrator`, `hunting_hunter`) are validated at the
HUNTING bootstrap, never app boot (operator ruling 2026-08-06); and the
orchestrator's `reason_fn`/`rematch_fn` and the hunting agent's `author`/`judge`
seams bind to a model through `invoke_role` on those roles. These tests exercise
that at the public seam with a FAKE `invoke_role` - the unit tier touches no live
model (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import pytest

from polymerhus.app.llm import providers as P
from polymerhus.attack.hunting import llm as HL
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    GateDecision,
    GateInput,
    MatchVerdict,
    Witness,
)
from polymerhus.recon.control.targeted import TargetedReconResult


# --- the off-app-boot bootstrap validation -----------------------------------

def test_validate_hunting_llm_config_demands_hunting_vars(monkeypatch):
    """`validate_hunting_llm_config()` is the hunting module's OWN fail-fast: with
    the hunting model vars absent it raises (unlike app boot, which never demands
    them), and with them present it passes."""
    for r in P.HUNTING_ROLES:
        monkeypatch.delenv(r.model_key, raising=False)
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    with pytest.raises(P.LLMConfigError) as e:
        HL.validate_hunting_llm_config()
    assert "HUNTING" in str(e.value)

    for r in P.HUNTING_ROLES:
        monkeypatch.setenv(r.model_key, "swissai:x")
    HL.validate_hunting_llm_config()  # now configured: no raise


# --- the gate reasoning seam (hunting_orchestrator) ---------------------------

def _gate_input() -> GateInput:
    return GateInput(
        candidates=[DeliveredCandidate(
            unit_id="u1", fault_class="idor",
            applies_witnesses=Witness(deterministic="d", llm="looks addressable"),
            match_verdict="applies",
        )],
        kb_degraded=False, kb_evidences={}, surface=[],
    )


def test_gate_reason_fn_invokes_hunting_orchestrator_with_gatedecision_schema(monkeypatch):
    seen = {}

    def fake_invoke_role(role, messages, *, schema=None, **kw):
        seen["role"] = role
        seen["schema"] = schema
        return GateDecision(directions=[])

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    out = HL.build_gate_reason_fn()(_gate_input())
    assert seen["role"] == "hunting_orchestrator"
    assert seen["schema"] is GateDecision
    assert isinstance(out, GateDecision)


def test_gate_reason_fn_degrades_none_to_empty_decision(monkeypatch):
    """A None/unparseable structured result surfaces as an empty GateDecision, which
    `run_orchestration` treats identically to a gate that carried nothing (fail-open
    is the orchestrator's job, never a raise here)."""
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role",
                        lambda *a, **k: None)
    out = HL.build_gate_reason_fn()(_gate_input())
    assert isinstance(out, GateDecision)
    assert out.directions == []


# --- the re-match seam (hunting_orchestrator) ---------------------------------

def _result() -> TargetedReconResult:
    return TargetedReconResult(correlation_id="c", requester_id="r",
                               origin="hunting", status="success")


def test_rematch_fn_invokes_hunting_orchestrator_with_matchverdict_schema(monkeypatch):
    seen = {}

    def fake_invoke_role(role, messages, *, schema=None, **kw):
        seen["role"] = role
        seen["schema"] = schema
        return MatchVerdict(unit_id="u1", fault_class="idor", verdict="applies")

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    out = HL.build_rematch_fn()("u1", "idor", _result())
    assert seen["role"] == "hunting_orchestrator"
    assert seen["schema"] is MatchVerdict
    assert out.verdict == "applies"


def test_rematch_fn_degrades_none_to_insufficient_evidence(monkeypatch):
    """A None result never fabricates an 'applies': it degrades to
    insufficient-evidence, which the orchestrator's depth-1 cap lands as unresolved."""
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", lambda *a, **k: None)
    out = HL.build_rematch_fn()("u1", "idor", _result())
    assert out.unit_id == "u1" and out.fault_class == "idor"
    assert out.verdict == "insufficient-evidence"


# --- the hunting agent's author / judge seams (hunting_hunter) ----------------

def test_author_fn_invokes_hunter_and_parses_json(monkeypatch):
    seen = {}

    def fake_invoke_role(role, messages, *, schema=None, **kw):
        seen["role"] = role
        seen["schema"] = schema
        return '{"target_identity": "u1", "rationale": "r"}'

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    spec = HL.build_author_fn()("compose the D4 spec ...")
    assert seen["role"] == "hunting_hunter"
    assert seen["schema"] is None            # free-text, not a pydantic schema
    assert spec == {"target_identity": "u1", "rationale": "r"}


def test_author_fn_parses_fenced_json_block(monkeypatch):
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role",
                        lambda *a, **k: '```json\n{"a": 1}\n```')
    assert HL.build_author_fn()("x") == {"a": 1}


def test_judge_fn_returns_none_on_unparseable_reply(monkeypatch):
    """A non-JSON reply degrades to None - the hunting agent already treats that as
    a no-meaningful-insight / degraded judgment (fail-open), never a crash."""
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role",
                        lambda *a, **k: "I could not decide.")
    assert HL.build_judge_fn()("x") is None


def test_author_and_judge_share_ONE_per_hunt_thread_when_session_bound(monkeypatch):
    """Bound to a hunt session, the hunter's turns run STATEFUL on ONE thread per hunt:
    the author and the judge of the SAME hunt resume the SAME thread (so the judge sees
    the author's reasoning), while a different hunt gets a distinct thread (no collision)."""
    import polymerhus.app.llm.session as S

    seen = []

    def fake_stateful_turn(role, thread, messages, *, checkpointer, schema=None, **kw):
        seen.append((role, getattr(thread, "thread_id", thread)))
        return '{"ok": true}'

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    with HL.hunt_session("run1", "hunt-A"):
        assert HL.build_author_fn()("author prompt") == {"ok": True}
        assert HL.build_judge_fn()("judge prompt") == {"ok": True}
    with HL.hunt_session("run1", "hunt-B"):
        HL.build_author_fn()("x")

    assert seen[0] == ("hunting_hunter", "run1:hunt-A:hunting_hunter")
    assert seen[1] == ("hunting_hunter", "run1:hunt-A:hunting_hunter")  # SAME thread -> shared memory
    assert seen[2] == ("hunting_hunter", "run1:hunt-B:hunting_hunter")  # other hunt -> distinct thread


# --- _parse_json_object: free-text D4/D5 replies -------------------------------


def test_parse_json_object_extracts_fenced_block_after_prose():
    """A live D4 reply may open with prose and THEN carry a ```json fence (the
    model's free-text answer before the spec); the parser must recover it."""
    reply = (
        "The LightRAG retrieval returned a fallback, so I ground the spec in "
        "the rationale.\n\n"
        '```json\n{"target_identity": {"unit": "a"}, "rationale": "spec"}\n```\n'
    )
    assert HL._parse_json_object(reply) == {
        "target_identity": {"unit": "a"},
        "rationale": "spec",
    }


def test_parse_json_object_keeps_leading_fence_support():
    reply = '```json\n{"meaningful_insight": false, "next_step": "end"}\n```'
    assert HL._parse_json_object(reply) == {
        "meaningful_insight": False,
        "next_step": "end",
    }


def test_parse_json_object_rejects_unfenced_prose_with_inline_json():
    # No code fence: prose-plus-json stays unparseable (fail-open), so the
    # harness treats the turn as degraded instead of guessing.
    assert HL._parse_json_object('Here is the answer {"ok": true}.') is None


def test_parse_json_object_passthrough_and_empty():
    assert HL._parse_json_object({"ok": True}) == {"ok": True}
    assert HL._parse_json_object("") is None
    assert HL._parse_json_object(None) is None
